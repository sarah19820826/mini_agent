"""Agent loop - ReAct main loop with six safeguards.

The core execution loop: THINK → ACT → DONE.
Safeguards: budget, interrupt, compression, retry, empty response, tool repair.
"""
import time
import logging
from typing import Any, Dict, Generator, List, Optional

from context_compressor import ContextCompressor
from memory.memory_manager import build_memory_context_block
from tools.tool_dispatcher import ToolDispatcher
from tools.todo_tool import TodoStore
from utils.error_classifier import classify_error, jittered_backoff

logger = logging.getLogger(__name__)

# Defaults
RETRY_BASE_DELAY = 5.0
RETRY_MAX_DELAY = 120.0
MAX_EMPTY_RESPONSES = 2


class IterationBudget:
    """Track remaining iterations."""

    def __init__(self, max_iterations: int):
        self.max = max_iterations
        self.current = 0

    def consume(self) -> bool:
        if self.current >= self.max:
            return False
        self.current += 1
        return True

    @property
    def remaining(self) -> int:
        return max(0, self.max - self.current)


class AgentLoop:
    """ReAct loop: THINK → ACT → DONE with safeguards."""

    def __init__(self, llm, max_iterations: int = 200,
                 system_prompt: str = "",
                 memory_manager=None,
                 dispatcher: Optional[ToolDispatcher] = None,
                 compressor: Optional[ContextCompressor] = None,
                 todo_store: Optional[TodoStore] = None,
                 stream_callback=None):
        self._llm = llm
        self._max_iterations = max_iterations
        self._system_prompt = system_prompt
        self._memory = memory_manager
        self._dispatcher = dispatcher or ToolDispatcher(todo_store=todo_store)
        self._compressor = compressor or ContextCompressor(llm=llm)
        self._todo_store = todo_store or TodoStore()
        self._interrupt_requested = False
        self._stream = type("_Stream", (), {"has_callback": stream_callback is not None,
                                             "feed": stream_callback or (lambda x: None)})()

    def run(self, messages: List[Dict], tools: List[Dict]) -> Generator[Dict, None, None]:
        """Execute the ReAct loop. Yields events for each step."""
        budget = IterationBudget(self._max_iterations)
        consecutive_empty = 0
        current_error_streak = 0

        while budget.consume():
            # Safeguard 2: interrupt check
            if self._interrupt_requested:
                yield {"type": "interrupted"}
                return

            # Safeguard 3: context compression check
            messages = self._check_and_compress(messages)

            # Memory prefetch
            messages = self._inject_memory(messages, messages)

            # THINK: call LLM (safeguard 4: error classification + retry)
            response = yield from self._api_call_with_retry(
                messages, tools, current_error_streak,
            )
            if response is None:
                continue  # retry triggered

            current_error_streak = 0

            # Safeguard 5: empty response protection
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])
            if not content and not tool_calls:
                consecutive_empty += 1
                if consecutive_empty >= MAX_EMPTY_RESPONSES:
                    yield {"type": "error", "message": "LLM repeatedly returned empty responses"}
                    return
                continue
            consecutive_empty = 0

            # Append assistant response
            asst_msg = {"role": "assistant", "content": content}
            if tool_calls:
                asst_msg["tool_calls"] = tool_calls
            messages.append(asst_msg)

            # Branch: tool calls?
            if tool_calls:
                # ACT: execute tool calls (safeguard 6: name/argument repair)
                yield from self._execute_tools(tool_calls, messages, tools)
                continue

            # DONE: final answer
            yield {"type": "final_answer", "content": content}
            return

        # Budget exhausted
        yield {"type": "budget_exhausted",
               "summary": self._build_summary(messages)}

    def request_interrupt(self):
        self._interrupt_requested = True

    def _check_and_compress(self, messages: List[Dict]) -> List[Dict]:
        """Compress if token count exceeds threshold."""
        total = sum(len(str(m.get("content", ""))) for m in messages)
        threshold_chars = int(self._compressor.context_window * 0.25)  # ~4 chars/token
        if total >= threshold_chars:
            logger.info("[Loop] Compressing %d chars (%d messages)", total, len(messages))
            messages = self._compressor.compress_with_fallback(
                messages, todo_store=self._todo_store,
            )
        return messages

    def _inject_memory(self, messages: List[Dict],
                       original_messages: List[Dict]) -> List[Dict]:
        """Prefetch and inject memory context."""
        if not self._memory:
            return messages

        # Remove previous fence
        messages = [m for m in messages if not m.get("_is_memory_fence")]

        # Extract latest user query
        user_query = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_query = content
                break

        if user_query:
            prefetch = self._memory.prefetch_all(user_query)
            block = build_memory_context_block(prefetch)
            if block:
                messages.append({
                    "role": "user",
                    "content": block,
                    "_is_memory_fence": True,
                })
        return messages

    def _api_call_with_retry(self, messages: List[Dict], tools: List[Dict],
                             current_error_streak: int) -> Generator[Dict, None, Optional[Dict]]:
        """Call LLM with error classification and retry."""
        try:
            if self._stream.has_callback:
                response = self._llm.chat_stream(
                    messages=messages,
                    callback=self._stream.feed,
                    tools=tools,
                )
            else:
                response = self._llm.chat(messages=messages, tools=tools)
            return response
        except Exception as api_error:
            classified = classify_error(api_error)

            if classified.should_compress:
                compressed = self._compressor.compress_with_fallback(
                    messages, todo_store=self._todo_store,
                )
                messages.clear()
                messages.extend(compressed)
                yield {"type": "error", "message": "Context too large, compressed and retrying..."}
                return None

            if classified.retryable:
                delay = jittered_backoff(
                    current_error_streak + 1,
                    base_delay=RETRY_BASE_DELAY,
                    max_delay=RETRY_MAX_DELAY,
                )
                logger.info("[Loop] Retryable error (%s), waiting %.1fs", classified.reason.value, delay)
                time.sleep(delay)
                return None

            yield {"type": "error", "message": f"LLM call failed: {classified.message}"}
            return None

    def _execute_tools(self, tool_calls: List[Dict], messages: List[Dict],
                       tools: List[Dict]) -> Generator[Dict, None, None]:
        """Execute tool calls and handle skill loading."""
        for tc in tool_calls:
            tc_name = tc.get("function", {}).get("name", "")

            # If load_skill, inject MCP tools
            if tc_name == "load_skill":
                raw_args = tc.get("function", {}).get("arguments", "{}")
                import json
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}
                skill_name = args.get("skill_name", "")
                if skill_name:
                    self._dispatcher.inject_skill_mcp_tools(skill_name, tools)

        self._dispatcher.execute_tool_calls(tool_calls, messages)
        yield {"type": "tool_executed", "count": len(tool_calls)}

    def _build_summary(self, messages: List[Dict]) -> str:
        """Build a brief summary of work done."""
        tool_counts = {}
        for m in messages:
            if "tool_calls" in m:
                for tc in m.get("tool_calls", []):
                    name = tc.get("function", {}).get("name", "?")
                    tool_counts[name] = tool_counts.get(name, 0) + 1

        parts = [f"Budget exhausted after {self._max_iterations} iterations."]
        if tool_counts:
            parts.append("Tools used: " + ", ".join(
                f"{k}({v})" for k, v in sorted(tool_counts.items())
            ))
        return " ".join(parts)
