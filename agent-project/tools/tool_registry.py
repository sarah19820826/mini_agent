"""Tool registry - register and lookup tools by name.

Thread-safe. Tracks a generation counter that increments on each change,
allowing consumers to detect stale caches.
"""
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolEntry:
    """A registered tool."""
    name: str
    schema: Dict[str, Any]
    handler: Callable
    check_fn: Optional[Callable[[], bool]] = None
    is_async: bool = False
    toolset: str = ""
    description: str = ""


class ToolRegistry:
    """Global tool registry. Singleton pattern."""

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._generation = 0
        self._lock = threading.Lock()

    def register(self, name: str, schema: Dict[str, Any], handler: Callable, *,
                 check_fn: Optional[Callable[[], bool]] = None,
                 is_async: bool = False, toolset: str = "",
                 description: str = "") -> None:
        """Register a tool."""
        with self._lock:
            if name in self._tools:
                print(f"[Registry] Overriding existing tool: {name}")
            self._tools[name] = ToolEntry(
                name=name, schema=schema, handler=handler,
                check_fn=check_fn, is_async=is_async,
                toolset=toolset, description=description,
            )
            self._generation += 1
            print(f"[Registry] Registered tool: {name} (generation={self._generation})")

    def get_tool(self, name: str) -> Optional[ToolEntry]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_schemas(self, exclude_toolsets: Optional[List[str]] = None,
                    exclude_names: Optional[List[str]] = None) -> List[Dict]:
        """Get tool schemas for LLM, filtered by toolset and name."""
        exclude_toolsets = exclude_toolsets or []
        exclude_names = exclude_names or []
        schemas = []
        for entry in self._tools.values():
            if entry.toolset in exclude_toolsets:
                continue
            if entry.name in exclude_names:
                continue
            if entry.check_fn is not None and not entry.check_fn():
                continue
            schemas.append(entry.schema)
        return schemas

    @property
    def generation(self) -> int:
        return self._generation


# Global singleton
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _registry


# Module-level convenience functions
def register(**kwargs):
    _registry.register(**kwargs)


def get_tool(name: str) -> Optional[ToolEntry]:
    return _registry.get_tool(name)


def list_tools() -> List[str]:
    return _registry.list_tools()
