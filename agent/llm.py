"""Talks to Claude, or to any OpenAI-compatible LLM. Embeddings always use the OpenAI-compatible provider,
as Claude has no embeddings API. Swapping chat model only means changing LLM_MODEL."""
import http.client
import json
import os
import time
import urllib.error
import urllib.request

import anthropic

RETRIES = 4
CLAUDE_RETRIES = 2
MAX_TOKENS = 3000  # includes the model's thinking, which can use well over 1,000 tokens
TIMEOUT_SECONDS = 150


class LLMError(Exception):
    pass


def to_claude(messages, tools):
    """Our history is in OpenAI's shape. Returns the system prompt, the turns and the tools in Claude's."""
    system, turns = "", []
    for message in messages:
        if message["role"] == "system":
            system = message["content"]
        elif message["role"] == "tool":
            result = {"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}
            if isinstance(turns[-1]["content"], list) and turns[-1]["role"] == "user":
                turns[-1]["content"].append(result)  # results of one step must share one message
            else:
                turns.append({"role": "user", "content": [result]})
        else:
            turns.append({"role": message["role"], "content": message.get("blocks") or message["content"]})
    return system, turns, [{"name": tool["function"]["name"], "description": tool["function"]["description"],
                            "input_schema": tool["function"]["parameters"]} for tool in tools]


def from_claude(response):
    """blocks must go back unchanged in the next request, as they can hold the model's thinking."""
    if response.stop_reason in ("refusal", "max_tokens"):
        raise LLMError(f"model stopped: {response.stop_reason}")
    content = "".join(block.text for block in response.content if block.type == "text")
    calls = [{"id": block.id, "type": "function", "function": {"name": block.name, "arguments": json.dumps(block.input)}}
             for block in response.content if block.type == "tool_use"]
    return {"content": content, "tool_calls": calls, "blocks": response.content}


class LLM:
    def __init__(self, base_url, api_key, model, embed_model, sleep=time.sleep, claude_key=""):
        self.base_url, self.api_key, self.model, self.embed_model = base_url, api_key, model, embed_model
        self.sleep = sleep
        self.claude = anthropic.Anthropic(api_key=claude_key, max_retries=CLAUDE_RETRIES) if claude_key else None

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                   os.environ.get("NVIDIA_API_KEY", ""),
                   os.environ.get("LLM_MODEL", "claude-haiku-5-5"),
                   os.environ.get("EMBED_MODEL", "nvidia/nemotron-3-embed-1b"),
                   claude_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    def _post(self, path, body, deadline=None):
        if self.api_key in ("", "your-key-here"):
            raise LLMError("no API key set")
        request = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        for attempt in range(RETRIES):
            remaining = TIMEOUT_SECONDS if deadline is None else min(TIMEOUT_SECONDS, deadline - time.monotonic())
            if remaining <= 0:
                raise LLMError("ran out of time")
            try:
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code != 429 and error.code < 500:
                    raise LLMError(f"provider returned {error.code}") from error
                reason, wait = f"provider returned {error.code}", float(error.headers.get("Retry-After") or 2 ** attempt)
            except (OSError, http.client.HTTPException, ValueError) as error:  # dropped, timed out or garbled
                reason, wait = f"provider unreachable: {error}", 2 ** attempt
            if attempt < RETRIES - 1 and (deadline is None or time.monotonic() + wait < deadline):
                self.sleep(wait)
        raise LLMError(reason)

    def _chat_claude(self, messages, tools, deadline):
        if self.claude is None:
            raise LLMError("no API key set")
        remaining = TIMEOUT_SECONDS if deadline is None else min(TIMEOUT_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise LLMError("ran out of time")
        system, turns, definitions = to_claude(messages, tools)
        try:
            # each try gets a share, so retries can't run past the deadline
            return from_claude(self.claude.with_options(timeout=remaining / (CLAUDE_RETRIES + 1)).messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=system, messages=turns, tools=definitions,
                output_config={"effort": "low"}))
        except anthropic.APIError as error:
            raise LLMError(f"provider failed: {type(error).__name__}") from error

    def chat(self, messages, tools, deadline=None):
        if self.model.startswith("claude-"):
            return self._chat_claude(messages, tools, deadline)
        response = self._post("/chat/completions", {"model": self.model, "messages": messages, "tools": tools,
                                                    "temperature": 0.2, "max_tokens": MAX_TOKENS}, deadline)
        try:
            return response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError("provider sent an unexpected reply") from error

    def embed(self, texts, input_type):
        """input_type is "query" or "passage". Leaving it out gives no error, only poor search results."""
        response = self._post("/embeddings", {"model": self.embed_model, "input": texts, "input_type": input_type,
                                              "encoding_format": "float"})
        try:
            return [item["embedding"] for item in response["data"]]
        except (KeyError, TypeError) as error:
            raise LLMError("provider sent an unexpected reply") from error
