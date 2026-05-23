"""Minimal LLM client - adapter for OpenAI-compatible chat completions API."""
import json
import os
import logging

logger = logging.getLogger(__name__)


class SimpleLLMClient:
    """Lightweight wrapper around OpenAI-compatible chat completions API."""

    def __init__(self, model: str = "", base_url: str = "",
                 api_key: str = ""):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.platform_name = "openai"

    def chat(self, messages: list, tools: list = None) -> dict:
        """Send messages to LLM and return structured response."""
        client = self._get_client()
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    def chat_stream(self, messages: list, callback=None, tools: list = None) -> dict:
        """Stream response, feeding chunks to callback."""
        client = self._get_client()
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = client.chat.completions.create(**kwargs)
        content = ""
        tool_calls = []
        tc_buffer = {}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            if callback:
                chunk_text = getattr(delta, "content", "") or ""
                callback(chunk_text)

            if delta.content:
                content += delta.content

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_buffer:
                        tc_buffer[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc_delta.id:
                        tc_buffer[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc_buffer[idx]["function"]["name"] += tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc_buffer[idx]["function"]["arguments"] += tc_delta.function.arguments

        for tc in tc_buffer.values():
            tool_calls.append(tc)

        return {"content": content, "tool_calls": tool_calls}

    def _get_client(self):
        """Lazy-import openai and create client."""
        from openai import OpenAI
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _parse_response(self, response):
        """Parse OpenAI response into our internal format."""
        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })
        return {"content": content, "tool_calls": tool_calls}
