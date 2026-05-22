"""IdleAgent - top-level agent that orchestrates the loop.

Builds the system prompt, registers tools, manages sessions,
and provides run() / run_sync() entry points.
"""
import logging
from typing import Any, Dict, List, Optional

from agent.loop import AgentLoop
from agent.delegate import DelegateManager, create_delegate_tool_schema, DELEGATE_BLOCKED_TOOLSETS
from config.settings import MAX_ITERATIONS, SKILLS_DIRS
from context_compressor import ContextCompressor
from memory.memory_manager import MemoryManager, create_memory_tool_schema
from skill.skills_loader import SkillsLoader
from skill.skill_service import SkillService
from tools.tool_dispatcher import ToolDispatcher
from tools.tool_registry import ToolRegistry, get_registry
from tools.todo_tool import TodoStore, TODO_SCHEMA, todo_tool

logger = logging.getLogger(__name__)


def build_system_prompt(custom_identity: str = "",
                        skill_advertise: str = "",
                        disabled_tools: Optional[List[str]] = None) -> str:
    """Build the system prompt for the agent."""
    disabled_tools = disabled_tools or []

    base = (
        "You are a helpful AI assistant. You can use tools to complete tasks.\n"
        "Think step by step. When you need to use a tool, call it. "
        "When you have the final answer, provide it directly.\n\n"
    )

    if custom_identity:
        base = custom_identity + "\n\n" + base

    if skill_advertise:
        base += skill_advertise + "\n\n"

    if disabled_tools:
        base += f"Note: The following tools are unavailable: {', '.join(disabled_tools)}\n"

    return base


class IdleAgent:
    """Main agent instance. Owns tools, memory, skills, and the loop."""

    def __init__(self, llm, max_iterations: int = MAX_ITERATIONS,
                 custom_identity: str = "",
                 system_prompt: str = "",
                 enabled_toolsets: Optional[List[str]] = None,
                 disabled_toolsets: Optional[List[str]] = None,
                 disabled_tools: Optional[List[str]] = None,
                 enable_delegate: bool = True,
                 skills_dirs: Optional[List[str]] = None,
                 memory_dir: str = "data",
                 session_id: str = "default"):
        self.llm = llm
        self.max_iterations = max_iterations
        self.session_id = session_id
        self.custom_identity = custom_identity

        self.enabled_toolsets = enabled_toolsets or []
        self.disabled_toolsets = disabled_toolsets or []
        self.disabled_tools = disabled_tools or []

        # Initialize subsystems
        self.registry = ToolRegistry()
        self.todo_store = TodoStore()
        self.memory_manager = MemoryManager(
            memory_file=f"{memory_dir}/memory_{session_id}.md",
            user_file=f"{memory_dir}/user_{session_id}.md",
        )

        # Skills
        skills_dirs = skills_dirs or SKILLS_DIRS
        self.skills_loader = SkillsLoader(skills_dirs)
        self.skill_service = SkillService(
            loader=self.skills_loader,
            registry=self.registry,
        )

        # Delegate manager (must be before _register_builtin_tools)
        self.delegate_manager = DelegateManager() if enable_delegate else None

        # Register tools
        self._register_builtin_tools(enable_delegate)

        # Dispatcher
        self.dispatcher = ToolDispatcher(
            registry=self.registry,
            todo_store=self.todo_store,
            skill_service=self.skill_service,
        )

        # Compressor
        self.compressor = ContextCompressor(llm=llm)

        # System prompt
        self.system_prompt = system_prompt or build_system_prompt(
            custom_identity=custom_identity,
            skill_advertise=self.skills_loader.get_advertise_prompt(),
            disabled_tools=self.disabled_tools,
        )

        # Messages (persistent across turns)
        self.messages: List[Dict] = [
            {"role": "system", "content": self.system_prompt}
        ]

    def _register_builtin_tools(self, enable_delegate: bool):
        """Register all built-in tools."""
        reg = self.registry

        # Todo tool
        reg.register(
            name="todo",
            schema=TODO_SCHEMA,
            handler=todo_tool,
            description="Manage task list for planning",
        )

        # Memory tool
        def _handle_memory(**kwargs):
            return self.memory_manager.handle_tool_call("memory", kwargs)

        reg.register(
            name="memory",
            schema=create_memory_tool_schema(),
            handler=_handle_memory,
            description="Save persistent memory",
        )

        # Delegate tool
        if enable_delegate and self.delegate_manager:
            def _handle_delegate(**kwargs):
                return self.delegate_manager.delegate_task(
                    goal=kwargs.get("goal", ""),
                    context=kwargs.get("context", ""),
                    role=kwargs.get("role", "leaf"),
                    parent_llm=self.llm,
                    parent_enabled_toolsets=self.enabled_toolsets,
                    parent_disabled_toolsets=self.disabled_toolsets,
                    max_iterations=min(self.max_iterations, 50),
                    agent_factory=lambda **kw: IdleAgent(**kw),
                ).final_answer

            reg.register(
                name="delegate_task",
                schema=create_delegate_tool_schema(),
                handler=_handle_delegate,
                toolset="delegate",
                description="Delegate tasks to sub-agents",
            )

    def get_tools(self) -> List[Dict]:
        """Get tool schemas for LLM, filtered by toolsets and disabled tools."""
        exclude_ts = []
        if not any(True for _ in []):  # always check disabled_toolsets
            pass
        return self.registry.get_schemas(
            exclude_toolsets=self.disabled_toolsets,
            exclude_names=self.disabled_tools,
        )

    def run(self, user_input: str) -> Dict[str, Any]:
        """Run one turn, returning events generator results."""
        self.messages.append({"role": "user", "content": user_input})

        loop = AgentLoop(
            llm=self.llm,
            max_iterations=self.max_iterations,
            system_prompt=self.system_prompt,
            memory_manager=self.memory_manager,
            dispatcher=self.dispatcher,
            compressor=self.compressor,
            todo_store=self.todo_store,
        )

        tools = self.get_tools()

        final_answer = ""
        metrics = {
            "total_iterations": 0,
            "tool_call_count": 0,
            "total_tokens": 0,
        }

        for event in loop.run(self.messages, tools):
            etype = event.get("type")
            if etype == "final_answer":
                final_answer = event.get("content", "")
            elif etype == "budget_exhausted":
                final_answer = event.get("summary", "Budget exhausted")
            elif etype == "error":
                logger.error("[Agent] Error: %s", event.get("message"))

        return {
            "success": bool(final_answer),
            "final_answer": final_answer,
            "metrics": metrics,
        }

    def run_sync(self, user_input: str) -> Dict[str, Any]:
        """Synchronous wrapper for run()."""
        return self.run(user_input)

    def shutdown(self):
        """Clean up resources."""
        if self.delegate_manager:
            self.delegate_manager.shutdown()
