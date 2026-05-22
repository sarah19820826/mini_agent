"""Context compressor - 3-step compression with fallback and debounce.

Triggers at 75% context window. Steps:
1. Protect head (system + first turns) and tail (last N messages)
2. Prune tool outputs in the middle zone
3. LLM-driven structured summary of pruned middle

Fallback chain: reduce tail → delete old tool results → emergency truncate.
Debounce: skip compression if recent savings < 10%.
"""
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Defaults from config
DEFAULT_PROTECT_FIRST_N = 3
DEFAULT_PROTECT_LAST_N = 6
DEFAULT_COMPRESSION_THRESHOLD = 0.75
MIN_SUMMARY_TOKENS = 200
SUMMARY_TOKENS_CEILING = 2000
SUMMARY_RATIO = 0.3
COMPRESSION_DEBOUNCE_THRESHOLD = 0.1
TOOL_RESULT_MAX_CHARS = 200


def _estimate_message_tokens(msg: Dict) -> int:
    """Rough token estimate: ~4 chars per token."""
    content = msg.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            item.get("text", "") for item in content
            if isinstance(item, dict)
        )
    return max(1, len(str(content)) // 4)


def _summarize_tool_result(tool_name: str, tool_args: str,
                           tool_content: str) -> str:
    """Generate a single-line summary for a tool output."""
    import re
    try:
        args = json.loads(tool_args) if tool_args else {}
    except (json.JSONDecodeError, TypeError):
        args = {}
    content = tool_content or ""
    content_len = len(content)
    line_count = content.count("\n") + 1 if content.strip() else 0

    if tool_name == "terminal":
        cmd = args.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        exit_match = re.search(r'"exit_code"\s*:\s*(-?\d+)', content)
        exit_code = exit_match.group(1) if exit_match else "?"
        return f"[terminal] ran `{cmd}` -> exit {exit_code}, {line_count} lines output"

    if tool_name == "read_file":
        path = args.get("path", "?")
        offset = args.get("offset", 1)
        return f"[read_file] read {path} from line {offset} ({content_len:,} chars)"

    if tool_name == "write_file":
        path = args.get("path", "?")
        written = args.get("content", "")
        wl = written.count("\n") + 1 if written else "?"
        return f"[write_file] wrote to {path} ({wl} lines)"

    if tool_name == "search_files":
        pattern = args.get("pattern", "?")
        path = args.get("path", ".")
        target = args.get("target", "content")
        mc = re.search(r'"total_count"\s*:\s*(\d+)', content)
        count = mc.group(1) if mc else "?"
        return f"[search_files] {target} search for '{pattern}' in {path} -> {count} matches"

    if len(content) <= TOOL_RESULT_MAX_CHARS:
        return content

    preview = content[:150].replace("\n", " ")
    return f"[{tool_name}] {preview}... (truncated, original {len(content)} chars)"


# Structured summary template (13 fields)
_SUMMARY_TEMPLATE = """
Generate a structured summary with these sections:

## Active Task - The user's most recent unfinished request (verbatim)
## Goal - The user's overall objective
## Completed Actions - List of completed operations (tool name + result)
## Active State - Current working state (directory/branch/file)
## In Progress - Work currently being done
## Blocked - Blocking items and errors
## Key Decisions - Important technical decisions and why
## Remaining Work - What's left to do
## Critical Context - Key context that must not be lost (no secrets)
## User Feedback - Corrections or preferences expressed by user
## Error History - Errors encountered and how they were handled
## File Changes - Files created/modified/deleted
## Next Steps - The very next action to take

Keep the summary compact and information-dense. Target {budget} tokens.
"""


class ContextCompressor:
    """Compress conversation history when token count exceeds threshold."""

    def __init__(self, llm=None, context_window: int = 128_000,
                 protect_first_n: int = DEFAULT_PROTECT_FIRST_N,
                 protect_last_n: int = DEFAULT_PROTECT_LAST_N,
                 threshold_ratio: float = DEFAULT_COMPRESSION_THRESHOLD):
        self.llm = llm
        self.context_window = context_window
        self.threshold_tokens = int(context_window * threshold_ratio)
        self.protect_first_n = protect_first_n
        self.protect_last_n = protect_last_n
        self._recent_savings: List[float] = []

    def compress(self, messages: List[Dict],
                 previous_summary: str = "",
                 focus_topic: str = "") -> List[Dict]:
        """Compress messages using 3-step strategy."""
        before_tokens = sum(_estimate_message_tokens(m) for m in messages)

        # Debounce check
        if self._recent_savings:
            avg_saving = sum(self._recent_savings) / len(self._recent_savings)
            if avg_saving < COMPRESSION_DEBOUNCE_THRESHOLD:
                return messages

        # Step 1: partition
        head = messages[:self.protect_first_n]
        tail = messages[-self.protect_last_n:] if len(messages) > self.protect_first_n + self.protect_last_n else []
        middle = messages[self.protect_first_n:len(messages) - len(tail)]

        if not middle:
            return messages

        # Step 2: prune tool outputs in middle
        pruned_middle = []
        for msg in middle:
            if msg.get("role") == "tool":
                tool_name = msg.get("name", msg.get("tool_call_id", "unknown"))
                tool_args = msg.get("_tool_args", "")
                summary = _summarize_tool_result(tool_name, tool_args, msg.get("content", ""))
                pruned_middle.append({**msg, "content": summary})
            elif "tool_calls" in msg:
                # Truncate large arguments in assistant tool_calls
                pruned = dict(msg)
                for tc in msg.get("tool_calls", []):
                    args = tc.get("function", {}).get("arguments", "")
                    if isinstance(args, str) and len(args) > 200:
                        new_tc = dict(tc)
                        new_tc["function"] = dict(tc["function"])
                        new_tc["function"]["arguments"] = args[:200] + "...[truncated]"
                        pruned["tool_calls"] = [pruned.get("tool_calls", [])[0] if pruned.get("tool_calls") else new_tc]
                pruned_middle.append(pruned)
            else:
                pruned_middle.append(msg)

        # Step 3: LLM summary
        if self.llm and pruned_middle:
            summary_text = self._generate_llm_summary(pruned_middle, previous_summary, focus_topic)
        else:
            summary_text = self._build_structured_summary(pruned_middle)

        summary_msg = {
            "role": "user",
            "content": f"[Compressed conversation summary]\n{summary_text}",
            "_is_compressed": True,
        }

        result = head + [summary_msg] + tail
        after_tokens = sum(_estimate_message_tokens(m) for m in result)
        if before_tokens > 0:
            saving_ratio = (before_tokens - after_tokens) / before_tokens
            self._recent_savings.append(saving_ratio)
            if len(self._recent_savings) > 5:
                self._recent_savings.pop(0)

        return result

    def compress_with_fallback(self, messages: List[Dict],
                               todo_store=None,
                               previous_summary: str = "",
                               focus_topic: str = "") -> List[Dict]:
        """Compress with fallback chain to guarantee token reduction."""
        result = self.compress(messages, previous_summary, focus_topic)
        result_tokens = sum(_estimate_message_tokens(m) for m in result)

        if result_tokens < self.threshold_tokens:
            return self._inject_todo_state(result, todo_store)

        # Fallback 1: reduce tail protection
        original_tail = self.protect_last_n
        self.protect_last_n = min(3, self.protect_last_n)
        result = self.compress(messages, previous_summary, focus_topic)
        self.protect_last_n = original_tail
        result_tokens = sum(_estimate_message_tokens(m) for m in result)
        if result_tokens < self.threshold_tokens:
            return self._inject_todo_state(result, todo_store)

        # Fallback 2: delete oldest 10 tool results
        filtered = []
        removed = 0
        for msg in result:
            if msg.get("role") == "tool" and removed < 10:
                removed += 1
                continue
            filtered.append(msg)
        result = filtered
        result_tokens = sum(_estimate_message_tokens(m) for m in result)
        if result_tokens < self.threshold_tokens:
            return self._inject_todo_state(result, todo_store)

        # Fallback 3: emergency truncate
        system_msgs = [m for m in messages if m.get("role") == "system"]
        recent = messages[-6:]
        overflow_notice = {
            "role": "assistant",
            "content": (
                "[Context overflow] The conversation exceeded the context window. "
                "Most earlier history has been discarded. "
                "Only the system prompt and the last 3 turns are preserved."
            ),
        }
        result = system_msgs + [overflow_notice] + recent
        return self._inject_todo_state(result, todo_store)

    def _generate_llm_summary(self, pruned_middle: List[Dict],
                              previous_summary: str,
                              focus_topic: str) -> str:
        """Use LLM to generate structured summary."""
        system_instruction = (
            "You are a summarization agent creating a context checkpoint. "
            "Treat the conversation turns below as source material for a "
            "compact record of prior work. "
            "Write the summary in the same language the user was using. "
            "NEVER include API keys, tokens, passwords — replace with [REDACTED]."
        )

        conversation_lines = []
        total_chars = 0
        max_chars = 15000
        for msg in pruned_middle:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    item.get("text", "") for item in content
                    if isinstance(item, dict)
                )
            if content:
                line = f"[{role}]: {content[:500]}"
                if total_chars + len(line) > max_chars:
                    conversation_lines.append("[...remaining messages omitted]")
                    break
                conversation_lines.append(line)
                total_chars += len(line)

        content_tokens = sum(_estimate_message_tokens(m) for m in pruned_middle)
        budget = max(MIN_SUMMARY_TOKENS,
                     min(int(content_tokens * SUMMARY_RATIO), SUMMARY_TOKENS_CEILING))

        summarizer_msgs = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": "\n\n".join([
                f"[Previous context summary]\n{previous_summary}" if previous_summary else "",
                f"[Focus topic: {focus_topic}]" if focus_topic else "",
                "[Conversation history]\n" + "\n".join(conversation_lines),
                _SUMMARY_TEMPLATE.format(budget=budget),
            ])},
        ]
        try:
            response = self.llm.chat(summarizer_msgs, tools=None)
            return response.get("content", "").strip()
        except Exception:
            return self._build_structured_summary(pruned_middle)

    def _build_structured_summary(self, messages: List[Dict],
                                  previous_summary: str = "") -> str:
        """Rule-based fallback summary when LLM is unavailable."""
        actions = []
        recent_user = ""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = str(content)
            if role == "user" and content:
                recent_user = content[:200]
            if "tool_calls" in msg:
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "?")
                    args = fn.get("arguments", "")
                    actions.append(f"- Called {name}({str(args)[:100]})")
            if role == "tool" and content:
                summary = content[:150] if len(content) > 150 else content
                actions.append(f"- Result: {summary}")

        lines = [
            "## Compressed Summary (rule-based fallback)",
            f"## Actions ({len(actions)} operations):",
        ]
        for a in actions[-20:]:  # last 20
            lines.append(a)
        if recent_user:
            lines.append(f"## Recent User Input: {recent_user}")
        return "\n".join(lines)

    def _inject_todo_state(self, messages: List[Dict],
                           todo_store) -> List[Dict]:
        """Inject incomplete todo state after compression."""
        if todo_store is None:
            return messages
        injection = todo_store.format_for_injection()
        if injection:
            injection_msg = {"role": "user", "content": injection}
            system_count = sum(1 for m in messages if m.get("role") == "system")
            insert_pos = max(system_count, len(messages) - self.protect_last_n)
            messages.insert(insert_pos, injection_msg)
        return messages
