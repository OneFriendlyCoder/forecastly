"""Talks to any OpenAI-compatible LLM. Swapping provider only means changing these settings."""
import http.client
import json
import os
import time
import urllib.error
import urllib.request

RETRIES = 4
MAX_TOKENS = 3000  # includes the model's thinking, which can use well over 1,000 tokens
TIMEOUT_SECONDS = 150


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, base_url, api_key, model, embed_model, sleep=time.sleep):
        self.base_url, self.api_key, self.model, self.embed_model = base_url, api_key, model, embed_model
        self.sleep = sleep

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                   os.environ.get("NVIDIA_API_KEY", ""),
                   os.environ.get("LLM_MODEL", "minimaxai/minimax-m3.1-flash"),
                   os.environ.get("EMBED_MODEL", "nvidia/nemotron-3-embed-1b"))

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

    def chat(self, messages, tools, deadline=None):
        response = self._post("/chat/completions", {"model": self.model, "messages": messages, "tools": tools,
                                                    "temperature": 0.2, "max_tokens": MAX_TOKENS}, deadline)
        try:
            return response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError("provider sent an unexpected reply") from error

    def embed(self, texts):
        response = self._post("/embeddings", {"model": self.embed_model, "input": texts, "encoding_format": "float"})
        try:
            return [item["embedding"] for item in response["data"]]
        except (KeyError, TypeError) as error:
            raise LLMError("provider sent an unexpected reply") from error
