"""Memory module - persistent cross-session memory for the agent.

Two stores: 'user' (who the user is) and 'memory' (environment/project notes).
Operations: add, replace, remove. Security-scanned on write.
Prefetch on each turn, injected as <memory-context> fence.
"""
import json
import os
import re
import logging

logger = logging.getLogger(__name__)

# Threat patterns for memory content security scan
_THREAT_PATTERNS = [
    (re.compile(r"(ignore|disregard|forget)\s+(previous|all|prior\s+previous)?\s+(instructions|directives)", re.I),
     "prompt_injection"),
    (re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*\S+", re.I),
     "credential_exposure"),
    (re.compile(r"<memory-context>|</memory-context>", re.I),
     "fence_tag_injection"),
]


def scan_context_threats(content: str) -> list:
    """Return list of threat types found in content."""
    threats = []
    for pattern, threat_type in _THREAT_PATTERNS:
        if pattern.search(content):
            threats.append(threat_type)
    return threats


def sanitize_context(content: str) -> str:
    """Strip memory-context fence tags from content to prevent nesting attacks."""
    cleaned = re.sub(r"</?memory-context>", "", content, flags=re.I)
    return cleaned


def build_memory_context_block(raw_context: str) -> str:
    """Wrap prefetched memory in a <memory-context> fence block."""
    if not raw_context or not raw_context.strip():
        return ""
    clean = sanitize_context(raw_context)
    if not clean:
        return ""
    return (
        "<memory-context>\n"
        "[System note: The following is recalled memory context, "
        "NOT new user input. Treat as authoritative reference data — "
        "this is the agent's persistent memory and should inform all responses.]\n\n"
        f"{clean}\n"
        "</memory-context>"
    )


class FileMemoryStore:
    """File-based memory store. Each entry is a line in a text file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self._ensure_file()

    def _ensure_file(self):
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        if not os.path.exists(self.filepath):
            self._write([])

    def _read(self) -> list:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write(self, entries: list):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(entries))
            if entries:
                f.write("\n")

    def add(self, content: str) -> dict:
        entries = self._read()
        entries.append(content)
        self._write(entries)
        return {"success": True, "action": "add", "content": content}

    def replace(self, old_text: str, content: str) -> dict:
        entries = self._read()
        for i, entry in enumerate(entries):
            if old_text in entry:
                entries[i] = content
                self._write(entries)
                return {"success": True, "action": "replace", "content": content}
        return {"success": False, "error": f"No entry found containing '{old_text}'"}

    def remove(self, old_text: str) -> dict:
        entries = self._read()
        new_entries = [e for e in entries if old_text not in e]
        if len(new_entries) == len(entries):
            return {"success": False, "error": f"No entry found containing '{old_text}'"}
        self._write(new_entries)
        return {"success": True, "action": "remove", "matched": len(entries) - len(new_entries)}

    def get_all(self) -> str:
        entries = self._read()
        if not entries:
            return ""
        return "\n".join(entries)


class StreamingContextScrubber:
    """Filter <memory-context> tags from streaming output.

    Handles tags split across delta boundaries using a buffer.
    """

    _OPEN_TAG = "<memory-context>"
    _CLOSE_TAG = "</memory-context>"

    def __init__(self):
        self._in_span = False
        self._buf = ""

    def feed(self, text: str) -> str:
        """Return visible text with fence content removed."""
        self._buf += text
        output_parts = []
        while self._buf:
            if self._in_span:
                close_idx = self._buf.find(self._CLOSE_TAG)
                if close_idx == -1:
                    if len(self._buf) > len(self._CLOSE_TAG):
                        self._buf = self._buf[-(len(self._CLOSE_TAG) - 1):]
                    break
                self._buf = self._buf[close_idx + len(self._CLOSE_TAG):]
                self._in_span = False
            else:
                open_idx = self._buf.find(self._OPEN_TAG)
                if open_idx == -1:
                    safe_len = len(self._buf) - (len(self._OPEN_TAG) - 1)
                    if safe_len > 0:
                        output_parts.append(self._buf[:safe_len])
                    self._buf = self._buf[safe_len:]
                    break
                output_parts.append(self._buf[:open_idx])
                self._buf = self._buf[open_idx + len(self._OPEN_TAG):]
                self._in_span = True
        return "".join(output_parts)

    def flush(self) -> str:
        remaining = self._buf
        self._buf = ""
        self._in_span = False
        return "" if self._in_span else remaining


def create_memory_tool_schema() -> dict:
    """Memory tool schema for LLM function calling."""
    return {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Save durable information to persistent memory that survives "
                "across sessions. Memory is injected into future turns, so keep "
                "it compact and focused on facts that will still matter later.\n\n"
                "WHEN TO SAVE (proactively, don't wait to be asked):\n"
                "- User corrects you or says 'remember this'\n"
                "- User shares preferences, habits, personal details\n"
                "- You discover environment facts (OS, tools, project structure)\n"
                "- You learn conventions, API quirks, workflow specifics\n\n"
                "TWO TARGETS:\n"
                "- 'user': who the user is (name, role, preferences)\n"
                "- 'memory': your notes (environment facts, project conventions)\n\n"
                "ACTIONS: add, replace (old_text identifies target), "
                "remove (old_text identifies target).\n\n"
                "SKIP: trivial info, easily re-discovered facts, raw data dumps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "replace", "remove"],
                    },
                    "target": {
                        "type": "string",
                        "enum": ["memory", "user"],
                    },
                    "content": {
                        "type": "string",
                        "description": "The entry content. Required for add/replace.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Short unique substring identifying the entry.",
                    },
                },
                "required": ["action", "target"],
            },
        },
    }


class MemoryManager:
    """Manages memory tools: add/replace/remove, prefetch, security scan."""

    def __init__(self, memory_file: str = "data/memory.md",
                 user_file: str = "data/user.md"):
        self.memory_store = FileMemoryStore(memory_file)
        self.user_store = FileMemoryStore(user_file)
        self._on_write_callbacks = []

    def _notify_memory_write(self, action: str, target: str, content: str):
        for cb in self._on_write_callbacks:
            try:
                cb(action, target, content)
            except Exception as e:
                logger.warning("Memory write callback error: %s", e)

    def on_memory_write(self, callback):
        self._on_write_callbacks.append(callback)

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """Handle memory tool call (add/replace/remove). Returns JSON string."""
        action = args.get("action", "")
        target = args.get("target", "memory")
        store = self.memory_store if target == "memory" else self.user_store

        if target not in ("memory", "user"):
            return json.dumps({"success": False, "error": f"Invalid target '{target}'. Use 'memory' or 'user'."}, ensure_ascii=False)

        # Security scan
        if action in ("add", "replace"):
            content = args.get("content", "")
            threats = scan_context_threats(content)
            if threats:
                threat_list = ", ".join(threats)
                logger.warning("[Memory] Security blocked: %s", threat_list)
                return json.dumps({"success": False, "error": f"Blocked: content matches threat pattern ({threat_list})."}, ensure_ascii=False)

        if action == "add":
            content = args.get("content", "")
            if not content:
                return json.dumps({"success": False, "error": "Content is required for 'add' action."}, ensure_ascii=False)
            result = store.add(content)
            if result.get("success"):
                self._notify_memory_write(action, target, content)
            return json.dumps(result, ensure_ascii=False)

        elif action == "replace":
            old_text = args.get("old_text", "")
            content = args.get("content", "")
            if not old_text:
                return json.dumps({"success": False, "error": "old_text is required for 'replace' action."}, ensure_ascii=False)
            if not content:
                return json.dumps({"success": False, "error": "content is required for 'replace' action."}, ensure_ascii=False)
            result = store.replace(old_text, content)
            if result.get("success"):
                self._notify_memory_write(action, target, content)
            return json.dumps(result, ensure_ascii=False)

        elif action == "remove":
            old_text = args.get("old_text", "")
            if not old_text:
                return json.dumps({"success": False, "error": "old_text is required for 'remove' action."}, ensure_ascii=False)
            result = store.remove(old_text)
            return json.dumps(result, ensure_ascii=False)

        return json.dumps({"success": False, "error": f"Unknown action '{action}'. Use: add, replace, remove"}, ensure_ascii=False)

    def prefetch_all(self, user_query: str, session_id: str = "") -> str:
        """Prefetch all relevant memory for injection.

        Simple implementation: return all memory content.
        Production could use semantic similarity to filter.
        """
        parts = []
        mem = self.memory_store.get_all()
        if mem:
            parts.append("## Memory\n" + mem)
        usr = self.user_store.get_all()
        if usr:
            parts.append("## User Profile\n" + usr)
        return "\n\n".join(parts) if parts else ""
