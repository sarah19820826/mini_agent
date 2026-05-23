"""Skill service - conditionally register skill tools, dispatch tool calls.

Only registers read_skill_resource when skills have resources,
and run_skill_script when skills have scripts. This keeps the LLM
tool list lean.
"""
import logging
from typing import Dict, List, Optional

from skill.skills_loader import SkillsLoader
from tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
SKILLS_TOOLSET = "skills"


class SkillService:
    """Bridge between SkillsLoader and ToolRegistry."""

    def __init__(self, loader: SkillsLoader, registry: Optional[ToolRegistry] = None,
                 mcp_service=None):
        self.loader = loader
        self.registry = registry
        self.mcp_service = mcp_service
        self._skill_mcp_tools: Dict[str, List[dict]] = {}
        self._skill_tool_to_client: Dict[str, tuple] = {}

    # ── Tool registration ──

    def register_tools_to_registry(self) -> None:
        """Register skill tools to the registry. Conditional on skill content."""
        reg = self.registry

        # load_skill - always register
        def _handle_load_skill(skill_name: str = "") -> str:
            return self.loader.load_skill(skill_name)

        reg.register(
            name="load_skill",
            schema={
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "Load the full instructions of a skill. Use this when the user's "
                        "request matches a skill's description from the available skills list."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "The name of the skill to load",
                            }
                        },
                        "required": ["skill_name"],
                    },
                },
            },
            handler=_handle_load_skill,
            toolset=SKILLS_TOOLSET,
            description="Load full instructions of a skill",
        )

        # read_skill_resource - only when skills have resources
        has_resources = any(
            self.loader.has_resources(name) for name in self.loader.skills
        )
        if has_resources:
            def _handle_read_resource(skill_name: str = "", resource_path: str = "") -> str:
                return self.loader.read_skill_resource(skill_name, resource_path)

            reg.register(
                name="read_skill_resource",
                schema={
                    "type": "function",
                    "function": {
                        "name": "read_skill_resource",
                        "description": "Read a resource file from the specified skill.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_name": {"type": "string"},
                                "resource_path": {"type": "string"},
                            },
                            "required": ["skill_name", "resource_path"],
                        },
                    },
                },
                handler=_handle_read_resource,
                toolset=SKILLS_TOOLSET,
            )

        # run_skill_script - only when skills have scripts
        has_scripts = any(
            self.loader.has_scripts(name) for name in self.loader.skills
        )
        if has_scripts:
            def _handle_run_script(skill_name: str = "", script_path: str = "",
                                   args: list = None) -> str:
                return self.loader.run_skill_script(skill_name, script_path, args)

            reg.register(
                name="run_skill_script",
                schema={
                    "type": "function",
                    "function": {
                        "name": "run_skill_script",
                        "description": "Run a Python script from the specified skill.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_name": {"type": "string"},
                                "script_path": {"type": "string"},
                                "args": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["skill_name", "script_path"],
                        },
                    },
                },
                handler=_handle_run_script,
                toolset=SKILLS_TOOLSET,
            )

    # ── Tool dispatch ──

    def dispatch_tool_call(self, skill_name: str, tool_name: str,
                           arguments: dict) -> str:
        """Route tool call to correct backend, priority order."""
        # Priority 1: scoped native - run_script
        if tool_name == "run_script":
            return self.loader.run_skill_script(
                skill_name, arguments.get("script_path", ""),
                arguments.get("args"),
            )
        # Priority 2: scoped native - read_resource
        if tool_name == "read_resource":
            return self.loader.read_skill_resource(
                skill_name, arguments.get("resource_path", ""),
            )
        # Priority 3: skill-exclusive MCP tools
        if tool_name in self._skill_tool_to_client:
            owner_skill, client = self._skill_tool_to_client[tool_name]
            if owner_skill == skill_name:
                from utils.async_bridge import run_async
                return run_async(client.call_tool(tool_name, arguments))
        # Priority 4: global MCP tools (fallback)
        if self.mcp_service:
            return self.mcp_service.call_tool(tool_name, arguments)

        return f"No handler for tool '{tool_name}' in skill '{skill_name}'"

    # ── MCP tool definitions ──

    def get_mcp_tool_definitions_for_skill(self, skill_name: str) -> List[dict]:
        """Get MCP tool schemas declared in SKILL.md tools field."""
        skill = self.loader.skills.get(skill_name)
        if not skill:
            return []
        tool_names = skill.metadata.get("tools", [])
        if not tool_names or self.mcp_service is None:
            return []
        return self.mcp_service.get_tool_definitions(tool_names)

    def get_all_tools_for_skill(self, skill_name: str) -> List[dict]:
        """Build complete tool list for a skill (4 sources)."""
        tools = []

        # Source 1: scoped run_script
        if self.loader.has_scripts(skill_name):
            scripts = self.loader.list_scripts(skill_name)
            scripts_desc = ", ".join(scripts) if scripts else "Python scripts in scripts/"
            tools.append({
                "type": "function",
                "function": {
                    "name": "run_script",
                    "description": f"Run a Python script in the current skill. Available: {scripts_desc}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "script_path": {"type": "string"},
                            "args": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["script_path"],
                    },
                },
            })

        # Source 2: scoped read_resource
        if self.loader.has_resources(skill_name):
            resources = self.loader.list_resources(skill_name)
            resources_desc = ", ".join(resources) if resources else "Files in references/"
            tools.append({
                "type": "function",
                "function": {
                    "name": "read_resource",
                    "description": f"Read a reference file. Available: {resources_desc}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "resource_path": {"type": "string"},
                        },
                        "required": ["resource_path"],
                    },
                },
            })

        # Source 3: global MCP tools
        global_mcp = self.get_mcp_tool_definitions_for_skill(skill_name)
        tools.extend(global_mcp)

        # Source 4: skill-exclusive MCP tools
        tools.extend(self._skill_mcp_tools.get(skill_name, []))

        return tools
