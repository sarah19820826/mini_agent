"""Todo tool - in-memory task list for plan-driven execution.

Plan as a tool: instead of switching between ReAct and Plan modes,
todo is just another tool call. Simple tasks use zero overhead;
complex tasks get full planning capability.
"""
import json
from typing import Any, Dict, List, Optional


VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class TodoStore:
    """Session-level in-memory task list. Each agent instance owns one."""

    def __init__(self):
        self._items: List[Dict[str, str]] = []

    def read(self) -> List[Dict[str, str]]:
        return list(self._items)

    def write(self, todos: List[Dict[str, Any]], merge: bool = False) -> List[Dict[str, str]]:
        """Write task list. Returns full list after write."""
        if not merge:
            # Replace mode: overwrite entire list
            self._items = [self._validate(t) for t in self._dedupe_by_id(todos)]
        else:
            # Merge mode: update existing items by id, append new ones
            existing = {item["id"]: item for item in self._items}
            for raw_todo in self._dedupe_by_id(todos):
                item_id = str(raw_todo.get("id", "")).strip()
                if not item_id:
                    continue
                if item_id in existing:
                    if "content" in raw_todo and raw_todo["content"]:
                        existing[item_id]["content"] = str(raw_todo["content"]).strip()
                    if "status" in raw_todo and raw_todo["status"]:
                        status = str(raw_todo["status"]).strip().lower()
                        if status in VALID_STATUSES:
                            existing[item_id]["status"] = status
                else:
                    validated = self._validate(raw_todo)
                    existing[validated["id"]] = validated
                    self._items.append(validated)
            # Rebuild list preserving order
            seen: set = set()
            rebuilt: List[Dict[str, str]] = []
            for item in self._items:
                current = existing.get(item["id"], item)
                if current["id"] not in seen:
                    rebuilt.append(current)
                    seen.add(current["id"])
            self._items = rebuilt
        return self.read()

    def has_items(self) -> bool:
        return len(self._items) > 0

    def format_for_injection(self) -> Optional[str]:
        """Render task list for context compression recovery.

        Only outputs pending and in_progress items — completed/cancelled
        would cause the LLM to redo work after compression.
        """
        if not self._items:
            return None
        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
            "cancelled": "[~]",
        }
        active_items = [
            item for item in self._items
            if item["status"] in ("pending", "in_progress")
        ]
        if not active_items:
            return None
        lines = ["[Your active task list was preserved across context compression]"]
        for item in active_items:
            marker = markers.get(item["status"], "[?]")
            lines.append(f"- {marker} {item['id']}. {item['content']} ({item['status']})")
        return "\n".join(lines)

    @staticmethod
    def _dedupe_by_id(todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate by id within the same batch, keeping last occurrence."""
        last_index: Dict[str, int] = {}
        for i, item in enumerate(todos):
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = i
        return [todos[i] for i in sorted(last_index.values())]

    @staticmethod
    def _validate(item: Dict[str, Any]) -> Dict[str, str]:
        """Validate and normalize a task item."""
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip() or "(no description)"
        status = str(item.get("status", "pending")).strip().lower()
        if status not in VALID_STATUSES:
            status = "pending"
        return {"id": item_id, "content": content, "status": status}


# ── Tool schema ──

TODO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "todo",
        "description": (
            "Manage your task list for the current session. "
            "Use for complex tasks with 3+ steps or when the user "
            "provides multiple tasks. "
            "Call with no parameters to read the current list.\n\n"
            "Writing:\n"
            "- Provide 'todos' array to create/update items\n"
            "- merge=false (default): replace the entire list\n"
            "- merge=true: update existing items by id, add new ones\n\n"
            "Each item: {id, content, status: pending|in_progress|completed|cancelled}\n"
            "List order is priority. Only ONE item in_progress at a time.\n"
            "Mark items completed immediately when done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Task items to write. Omit to read current list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                },
                "merge": {
                    "type": "boolean",
                    "description": "true: update by id. false (default): replace all.",
                    "default": False,
                },
            },
        },
    },
}


def todo_tool(todos: list = None, merge: bool = False, store: TodoStore = None) -> str:
    """Todo tool handler. store is injected by ToolDispatcher at runtime."""
    if store is None:
        return json.dumps({"error": "TodoStore not initialized"})
    if todos is not None:
        current = store.write(todos, merge=merge)
    else:
        current = store.read()
    summary = {
        "total": len(current),
        "pending": sum(1 for t in current if t["status"] == "pending"),
        "in_progress": sum(1 for t in current if t["status"] == "in_progress"),
        "completed": sum(1 for t in current if t["status"] == "completed"),
    }
    return json.dumps({"todos": current, "summary": summary})
