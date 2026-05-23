"""Tool dispatcher - execute tool calls with name/argument repair and progress preview.

Handles:
- Tool name repair (case normalization, camel→snake, fuzzy matching)
- Argument JSON repair (surrogate chars, missing braces, trailing commas)
- Permission checks and progress preview
- TodoStore injection for the todo tool
- Skill MCP tool injection
"""
import difflib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from tools.tool_registry import get_registry
from tools.todo_tool import TodoStore

logger = logging.getLogger(__name__)
SKILLS_TOOLSET = "skills"


class ToolDispatcher:
    """Dispatch tool calls to registered handlers with repair and safety."""

    def __init__(self, registry=None, todo_store: TodoStore = None,
                 skill_service=None):
        self._registry = registry or get_registry()
        self._todo_store = todo_store or TodoStore()
        self._skill_service = skill_service
        self._callback = None

    def set_progress_callback(self, callback):
        """Set a callback(tool_name, preview_text) for progress updates."""
        self._callback = callback

    def execute_tool_calls(self, tool_calls: List[Dict], messages: List[Dict]) -> None:
        """Execute tool calls and append results to messages in place."""
        for tc in tool_calls:
            tool_name = tc.get("function", {}).get("name", "")
            raw_args = tc.get("function", {}).get("arguments", "{}")
            tool_call_id = tc.get("id", "")

            # Parse arguments with repair
            arguments = repair_tool_arguments(raw_args) if isinstance(raw_args, str) else (raw_args or {})

            # Build preview
            preview = self._build_tool_preview(tool_name, arguments)
            if self._callback:
                self._callback(tool_name, preview)

            # Dispatch
            result = self._dispatch(tool_name, arguments)

            # Append result to messages
            msg = {
                "role": "tool",
                "content": result,
                "tool_call_id": tool_call_id,
            }
            messages.append(msg)
            logger.info(
                "[ToolDispatcher] '%s' result_len=%d preview='%s...'",
                tool_name, len(result), result[:200],
            )

    def _dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Route to the correct handler, repairing name if needed."""
        tool_entry = self._registry.get_tool(tool_name)

        if tool_entry is None:
            # Try to repair tool name
            repaired = self._repair_tool_name(tool_name)
            if repaired:
                logger.info("[ToolDispatcher] Name repaired: '%s' → '%s'", tool_name, repaired)
                tool_entry = self._registry.get_tool(repaired)
                tool_name = repaired

        if tool_entry is None:
            available = ", ".join(self._registry.list_tools())
            return f"Tool '{tool_name}' not found. Available: {available}"

        try:
            # Inject TodoStore for todo tool
            if tool_name == "todo":
                execution_args = {**arguments, "store": self._todo_store}
            else:
                execution_args = arguments

            result = tool_entry.handler(**execution_args)
            result_str = str(result) if result is not None else "Tool executed (no output)"
            return result_str
        except Exception as tool_err:
            error_msg = f"Tool '{tool_name}' execution failed: {type(tool_err).__name__}: {tool_err}"
            logger.error("[ToolDispatcher] %s", error_msg)
            return error_msg

    def inject_skill_mcp_tools(self, skill_name: str, tools: List[Dict]) -> None:
        """Inject MCP tool schemas for a skill into the tools list."""
        if not self._skill_service:
            return
        try:
            mcp_defs = self._skill_service.get_mcp_tool_definitions_for_skill(skill_name)
            if not mcp_defs:
                return
            existing = {t.get("function", {}).get("name", "") for t in tools}
            injected = []
            for td in mcp_defs:
                name = td.get("function", {}).get("name", "")
                if name and name not in existing:
                    tools.append(td)
                    injected.append(name)
            if injected:
                logger.info("Injected MCP tools for skill '%s': %s", skill_name, injected)
        except Exception as exc:
            logger.warning("Failed to inject MCP tools for skill '%s': %s", skill_name, exc)

    def hydrate_todo_store(self, messages: List[Dict]) -> None:
        """Recover TodoStore state from conversation history."""
        if self._todo_store.has_items():
            return
        for message in reversed(messages):
            if message.get("role") != "tool":
                continue
            content = message.get("content", "")
            if '"todos"' not in content:
                continue
            try:
                data = json.loads(content)
                todos = data.get("todos")
                if isinstance(todos, list):
                    self._todo_store.write(todos, merge=False)
                    return
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

    # ── Tool name repair ──

    def _repair_tool_name(self, tool_name: str) -> Optional[str]:
        """Try multiple transformations to repair a misspelled tool name."""
        valid_names = self._registry.list_tools()

        def normalize(name):
            return name.lower().replace("-", "_").replace(" ", "_")

        def camel_to_snake(name):
            return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

        def strip_tool_suffix(name):
            lower = name.lower()
            for suffix in ("_tool", "-tool", "tool"):
                if lower.endswith(suffix):
                    return name[:-len(suffix)].rstrip("_-")
            return None

        # Strategy 1: exact lowercase
        lowered = tool_name.lower()
        if lowered in valid_names:
            return lowered

        # Strategy 2: normalize
        normalized = normalize(tool_name)
        if normalized in valid_names:
            return normalized

        # Strategy 3: candidate expansion
        candidates = {tool_name, lowered, normalized, camel_to_snake(tool_name)}
        for _ in range(2):
            extra = set()
            for c in candidates:
                stripped = strip_tool_suffix(c)
                if stripped:
                    extra.add(stripped)
                    extra.add(normalize(stripped))
                    extra.add(camel_to_snake(stripped))
            candidates |= extra
        for c in candidates:
            if c and c in valid_names:
                return c

        # Strategy 4: fuzzy match
        matches = difflib.get_close_matches(lowered, valid_names, n=1, cutoff=0.7)
        return matches[0] if matches else None

    # ── Progress preview ──

    def _build_tool_preview(self, tool_name: str, arguments: Dict) -> str:
        """Build human-readable progress preview text."""
        if tool_name == "delegate_task":
            goal = arguments.get("goal", "")[:40]
            return f"Delegating to sub-agent — {goal}"
        if tool_name == "memory":
            action_desc = {"add": "Writing", "replace": "Updating"}.get(
                arguments.get("action", ""), "Operating")
            return f"{action_desc} memory {arguments.get('target', '')}"
        if tool_name == "todo":
            todos = arguments.get("todos")
            return f"Updating {len(todos)} tasks" if todos else "Reading task list"

        search_tools = {
            "searchDocChunk": ("query", "Searching documents"),
            "web_search": ("query", "Searching web"),
        }
        if tool_name in search_tools:
            key, desc = search_tools[tool_name]
            value = str(arguments.get(key, ""))[:30]
            return f"{desc} — {value}" if value else desc

        return f"Calling {tool_name}"


# ── Argument JSON repair (module-level) ──

def repair_tool_arguments(raw_arguments: str) -> dict:
    """Repair JSON arguments returned by LLM."""
    if not raw_arguments or not raw_arguments.strip():
        return {}

    # Strategy 1: clean surrogate characters
    cleaned = raw_arguments.encode("utf-8", errors="replace").decode("utf-8")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 2: complete missing closing braces
    stripped = cleaned.strip()
    open_braces = stripped.count("{") - stripped.count("}")
    open_brackets = stripped.count("[") - stripped.count("]")
    if open_braces > 0:
        stripped += "}" * open_braces
    if open_brackets > 0:
        stripped += "]" * open_brackets
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strategy 3: remove trailing comma before closing brace
    last_comma = stripped.rfind(",")
    if last_comma > 0:
        candidate = stripped[:last_comma]
        open_b = candidate.count("{") - candidate.count("}")
        if open_b > 0:
            candidate += "}" * open_b
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Fallback
    return {"raw_input": raw_arguments}
