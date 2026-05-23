"""Sub-agent delegation - parallel task execution with resource control.

Orchestrator-Worker pattern: main agent decomposes complex tasks,
delegates to independent child agents running in ThreadPoolExecutor.

Safety: depth limit, concurrency limit, permission isolation, timeout.
"""
import enum
import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Constants
DELEGATE_BLOCKED_TOOLSETS: List[str] = ["delegate"]
DELEGATE_BLOCKED_TOOLS: List[str] = ["memory", "clarify"]
DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_TIMEOUT = 300  # seconds

# Execution discipline injected into child agent identity
DELEGATE_EXECUTION_DISCIPLINE = """
## Execution Discipline
- Focus only on the assigned task. Don't scope creep.
- Use tools efficiently. Avoid redundant searches or reads.
- If you can't complete the task, explain why and provide partial results.
- Report findings concisely.
"""

DELEGATE_WORK_BOUNDARIES = """
## Work Boundaries
- You cannot interact directly with the user.
- You cannot modify persistent memory.
- You cannot delegate to other sub-agents (leaf mode).
- Complete the task and return results.
"""

DELEGATE_RESULT_FORMAT = """
## Result Format
Return a clear, structured answer that the parent agent can use directly.
Include:
1. What you did (brief)
2. Key findings or results
3. Any issues encountered
"""


class DelegateRole(enum.Enum):
    LEAF = "leaf"  # cannot delegate further
    ORCHESTRATOR = "orchestrator"  # may delegate (if depth allows)


@dataclass
class DelegateResult:
    """Structured result from a delegated sub-agent."""
    goal: str
    success: bool
    final_answer: str = ""
    error: Optional[str] = None
    tool_calls_count: int = 0
    iterations_used: int = 0
    tokens_used: int = 0
    duration_seconds: float = 0.0


def create_delegate_tool_schema() -> Dict[str, Any]:
    """Schema for the delegate_task tool."""
    return {
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": (
                "Delegate a sub-task to an independent sub-agent. "
                "Use for parallelizable, independent sub-tasks. "
                "Sub-agents have independent iteration budgets and tool sets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Clear, specific goal for the sub-task",
                    },
                    "context": {
                        "type": "string",
                        "description": "Context information for the sub-agent",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["leaf", "orchestrator"],
                        "description": "leaf cannot delegate further, orchestrator can",
                        "default": "leaf",
                    },
                },
                "required": ["goal", "context"],
            },
        },
    }


class DelegateManager:
    """Manage sub-agent delegation with resource controls."""

    def __init__(self, max_depth: int = DEFAULT_MAX_DEPTH,
                 max_concurrent: int = DEFAULT_MAX_CONCURRENT,
                 timeout: int = DEFAULT_TIMEOUT):
        self._max_depth = max_depth
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._active_count = 0
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)

    def delegate_task(self, goal: str, context: str, role: str = "leaf",
                      current_depth: int = 0,
                      parent_llm=None, parent_enabled_toolsets: List[str] = None,
                      parent_disabled_toolsets: List[str] = None,
                      max_iterations: int = 50,
                      agent_factory: Optional[Callable] = None) -> DelegateResult:
        """Delegate a task to a child agent.

        Args:
            goal: Task description for the child agent.
            context: Background information.
            role: "leaf" (no further delegation) or "orchestrator".
            current_depth: Current delegation depth.
            parent_llm: LLM client to inherit.
            parent_enabled_toolsets: Toolset whitelist from parent.
            parent_disabled_toolsets: Toolset blacklist from parent.
            max_iterations: Iteration budget for child agent.
            agent_factory: Callable(llm, **kwargs) -> IdleAgent instance.
        """
        # Depth check
        if current_depth >= self._max_depth:
            logger.warning("[Delegate] Depth limit reached (%d), downgrading to leaf", current_depth)
            role = "leaf"

        # Concurrency check
        with self._lock:
            if self._active_count >= self._max_concurrent:
                # Wait briefly for a slot
                time.sleep(1)

        def _run():
            try:
                return self._run_child_agent(
                    goal=goal, context=context,
                    parent_llm=parent_llm, role=role,
                    enabled_toolsets=parent_enabled_toolsets or [],
                    disabled_toolsets=parent_disabled_toolsets or [],
                    max_iterations=max_iterations,
                    current_depth=current_depth,
                    agent_factory=agent_factory,
                )
            finally:
                with self._lock:
                    self._active_count -= 1

        with self._lock:
            self._active_count += 1

        future = self._executor.submit(_run)
        try:
            return future.result(timeout=self._timeout)
        except FuturesTimeout:
            return DelegateResult(
                goal=goal, success=False,
                error=f"Sub-agent timed out after {self._timeout}s",
            )
        except Exception as e:
            return DelegateResult(
                goal=goal, success=False,
                error=f"Sub-agent failed: {type(e).__name__}: {e}",
            )

    def _run_child_agent(self, goal, context, parent_llm, role,
                         enabled_toolsets, disabled_toolsets,
                         max_iterations, current_depth,
                         agent_factory) -> DelegateResult:
        """Create and run a child agent."""
        import time as _time
        start = _time.time()

        # Build child disabled toolsets
        child_disabled = list(DELEGATE_BLOCKED_TOOLSETS)
        for ts in disabled_toolsets:
            if ts not in child_disabled:
                child_disabled.append(ts)

        # Build blocked tools list
        blocked_tools = list(DELEGATE_BLOCKED_TOOLS)
        if role == "leaf":
            blocked_tools.append("delegate_task")

        # Build child identity
        child_identity = (
            f"You are a sub-agent responsible for completing a specific task.\n\n"
            f"{DELEGATE_EXECUTION_DISCIPLINE}\n\n"
            f"## Task Goal\n{goal}\n\n"
            f"## Context\n{context}\n\n"
            f"{DELEGATE_WORK_BOUNDARIES}\n\n"
            f"{DELEGATE_RESULT_FORMAT}\n\n"
            f"## Technical Constraints\n"
            f"- Role: {role}\n"
            f"- Max iterations: {max_iterations}\n"
            f"- Blocked tools: {', '.join(blocked_tools)}\n"
            f"- Return final answer immediately when done\n"
        )

        # Create child agent
        factory = agent_factory or self._default_agent_factory
        child_agent = factory(
            llm=parent_llm,
            max_iterations=max_iterations,
            custom_identity=child_identity,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=child_disabled,
            enable_delegate=(role == "orchestrator" and
                             current_depth < self._max_depth - 1),
        )

        # Run synchronously
        result_data = child_agent.run_sync(goal)
        duration = _time.time() - start

        metrics = result_data.get("metrics", {})
        return DelegateResult(
            goal=goal,
            success=result_data.get("success", False),
            final_answer=result_data.get("final_answer", ""),
            error=result_data.get("error"),
            tool_calls_count=metrics.get("tool_call_count", 0),
            iterations_used=metrics.get("total_iterations", 0),
            tokens_used=metrics.get("total_tokens", 0),
            duration_seconds=round(duration, 2),
        )

    def _default_agent_factory(self, **kwargs):
        """Default factory — imports IdleAgent lazily to avoid circular deps."""
        from agent.agent import IdleAgent
        return IdleAgent(**kwargs)

    def shutdown(self):
        self._executor.shutdown(wait=True)
