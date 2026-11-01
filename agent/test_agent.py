"""Run with: python3 agent/test_agent.py. Uses a fake model, so it needs no key and no stack."""
import http.client
import json
import sys
import time
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from agent import cache_key, compact_event, explain, guard, known_numbers, parse
from llm import LLM, LLMError

CHUNK = {"chunk_id": "negative-replies#move", "guide": "Negative replies", "title": "Move", "body": "Offer a ten minute call."}
EVENT = {"event_type": "email_replied", "occurred_at": "2017-12-05T10:00:00+00:00", "payload": {"sentiment": "negative"}}
DEAL = {"deal_id": "D1", "product": "GTX Pro", "amount": 4821, "score": 0.196,
        "factors": [{"feature": "negative_replies", "value": 7, "impact": -0.5}, {"feature": "days_since_last_reply", "value": 25.48, "impact": -0.4}],
        "features": {"negative_replies": 7, "days_since_last_reply": 25.48, "emails_sent_14d": 8}, "activity": {"email_sent": 51}}
GOOD = {"summary": "This deal has a 20% chance of winning.",
        "reasons": [{"text": "It has 7 negative replies.", "feature": "negative_replies"},
                    {"text": "It's been 25 days since the last reply.", "feature": "days_since_last_reply"}],
        "next_step": {"text": "Offer a ten minute call.", "playbook_id": CHUNK["chunk_id"]}}


def tool_call(name, args):
    return {"tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


SEARCH = tool_call("search_playbook", {"query": "negative replies"})
EVENTS = tool_call("get_recent_events", {"deal_id": "D1"})


def text(answer):
    return {"content": json.dumps(answer)}


class FakeLLM:
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def chat(self, messages, tools, deadline=None):
        self.calls.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeTools:
    def get_recent_events(self, deal_id, limit=20):
        return [{**EVENT, "event_id": "e1"}]

    def search_playbook(self, query):
        return [CHUNK]


def run(*script):
    llm = FakeLLM(*script)
    return explain(DEAL, llm, FakeTools()), llm


def changed(**fields):
    return {**GOOD, **fields}


def check_good_answer_passes():
    result, llm = run(EVENTS, SEARCH, text(GOOD))
    assert result["grounded"] and not result["retried"] and result["llm_calls"] == 3
    assert llm.calls[-1][-1]["role"] == "tool"


def check_guard_rejections():
    chunks, sources = {CHUNK["chunk_id"]}, [[EVENT], [CHUNK]]
    assert guard(GOOD, DEAL, sources, chunks) == []
    bad = {
        "invented number": changed(summary="It has 12 negative replies."),
        "unknown feature": changed(reasons=[GOOD["reasons"][0], {"text": "Budget cut.", "feature": "budget"}]),
        "invented playbook": changed(next_step={"text": "Call.", "playbook_id": "made-up"}),
        "cause claim": changed(summary="It stalled because of pricing."),
        "too few reasons": changed(reasons=GOOD["reasons"][:1]),
        "no next step": changed(next_step=None),
        "no summary": changed(summary=""),
        "wrong types": changed(reasons="several"),
        "not an object": ["a list"],
    }
    for name, answer in bad.items():
        assert guard(answer, DEAL, sources, chunks), f"{name} must be rejected"
    assert guard(GOOD, DEAL, sources, set()), "a playbook id must come from a real search"


def check_numbers_people_would_quote():
    seen = known_numbers(DEAL, [[EVENT]])
    assert {20.0, 7.0, 25.0, 25.5, 4821.0, 14.0} <= seen
    assert not {12.0, 5.0, 2017.0} & seen, "digits inside a date don't count as known"
    allowed = changed(summary="A $4,821 deal with a 20% chance after 25 days.")
    assert guard(allowed, DEAL, [], {CHUNK["chunk_id"]}) == []


def check_retry_then_success():
    bad = changed(summary="It has 12 negative replies.")
    result, llm = run(EVENTS, SEARCH, text(bad), text(GOOD))
    assert result["grounded"] and result["retried"]
    assert "fact check" in llm.calls[-1][-1]["content"] and "12" in llm.calls[-1][-1]["content"]


def check_two_failures_fall_back_to_facts():
    bad = changed(summary="It has 12 negative replies.")
    result, _ = run(SEARCH, text(bad), text(bad))
    assert not result["grounded"] and result["answer"]["next_step"] is None
    assert [r["feature"] for r in result["answer"]["reasons"]] == ["negative_replies", "days_since_last_reply"]
    assert "12" not in json.dumps(result["answer"]), "a rejected claim must never reach the reader"


def check_other_failures_fall_back():
    assert not run(LLMError("provider returned 429"))[0]["grounded"]
    assert not run({"content": "not json"}, {"content": "still not"})[0]["grounded"]
    assert not run(*[EVENTS] * 6)[0]["grounded"], "the agent must stop after its step limit"


def check_bad_tool_input_doesnt_crash():
    call = tool_call("unknown_tool", {})
    broken = tool_call("search_playbook", {"wrong": 1})
    result, llm = run(call, broken, SEARCH, text(GOOD))
    assert result["grounded"]
    assert "unknown tool" in llm.calls[1][-1]["content"]


def check_events_are_compacted():
    event = {"event_id": "uuid", "event_type": "email_replied", "occurred_at": "2017-12-05T10:00:00+00:00",
             "actor": {"id": "x"}, "payload": {"message_id": "m", "sentiment": "negative", "reply_delay_hours": 3}}
    assert compact_event(event) == {"type": "email_replied", "at": "2017-12-05", "sentiment": "negative"}


def check_dropped_connections_are_retried():
    waits = []
    llm = LLM("http://x", "key", "m", "e", sleep=waits.append)
    dropped = http.client.RemoteDisconnected("closed")
    good = mock.MagicMock()
    good.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
    with mock.patch("urllib.request.urlopen", side_effect=[dropped, TimeoutError(), good]):
        assert llm.chat([], [])["content"] == "hi"
    assert waits == [1, 2]
    with mock.patch("urllib.request.urlopen", side_effect=dropped):
        try:
            llm.chat([], [])
            raise AssertionError("repeated drops must become an LLMError")
        except LLMError:
            pass
    empty = mock.MagicMock()
    empty.__enter__.return_value.read.return_value = b"{}"
    with mock.patch("urllib.request.urlopen", return_value=empty):
        try:
            llm.chat([], [])
            raise AssertionError("an odd reply must become an LLMError")
        except LLMError:
            pass


def check_the_time_limit_stops_retries():
    llm = LLM("http://x", "key", "m", "e", sleep=lambda _: None)
    try:
        llm.chat([], [], deadline=time.monotonic() - 1)
        raise AssertionError("no time left must stop the call")
    except LLMError as error:
        assert "out of time" in str(error)
    timeouts = []

    def timed_out(request, timeout):
        timeouts.append(timeout)
        raise TimeoutError()

    with mock.patch("urllib.request.urlopen", side_effect=timed_out):
        try:
            llm.chat([], [], deadline=time.monotonic() + 5)
        except LLMError:
            pass
    assert timeouts and max(timeouts) <= 5, "one request must not outlive the deadline"
    assert not explain(DEAL, FakeLLM(LLMError("ran out of time")), FakeTools())["grounded"]


def check_a_broken_tool_doesnt_crash():
    class BrokenTools(FakeTools):
        def get_recent_events(self, deal_id, limit=20):
            raise ConnectionError("api down")

    llm = FakeLLM(EVENTS, SEARCH, text(GOOD))
    result = explain(DEAL, llm, BrokenTools())
    assert result["grounded"]
    assert "tool failed" in llm.calls[1][-1]["content"]


def check_a_new_score_needs_a_new_answer():
    deal = {**DEAL, "as_of": "2017-12-30", "model_version": "m1"}
    assert cache_key(deal, "llm") == cache_key(dict(deal), "llm")
    assert cache_key(deal, "llm") != cache_key({**deal, "score": 0.3}, "llm"), "a late event can change only the score"


def check_embeddings_say_what_they_are():
    sent = []
    llm = LLM("http://x", "key", "m", "e")
    llm._post = lambda path, body: sent.append(body) or {"data": [{"embedding": [1.0]}]}
    llm.embed(["text"], "query")
    assert sent[0]["input_type"] == "query", "without this the model searches badly and gives no error"
    index_source = (Path(__file__).parent / "index_playbook.py").read_text()
    assert '"passage"' in index_source, "documents must be embedded as passages"


def check_parse_tolerates_wrapping():
    assert parse('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse("nothing") is None and parse(None) is None


def check_llm_retries_rate_limits():
    waits = []
    llm = LLM("http://x", "key", "m", "e", sleep=waits.append)
    limited = urllib.error.HTTPError("http://x", 429, "slow down", {"Retry-After": "3"}, None)
    good = mock.MagicMock()
    good.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
    with mock.patch("urllib.request.urlopen", side_effect=[limited, good]):
        assert llm.chat([], [])["content"] == "hi"
    assert waits == [3.0]
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("http://x", 401, "no", {}, None)):
        try:
            llm.chat([], [])
            raise AssertionError("a bad key must not retry")
        except LLMError as error:
            assert "401" in str(error) and len(waits) == 1
    try:
        LLM("http://x", "your-key-here", "m", "e").chat([], [])
        raise AssertionError("the placeholder key must be refused")
    except LLMError as error:
        assert "no API key" in str(error)


def main():
    check_good_answer_passes()
    check_guard_rejections()
    check_numbers_people_would_quote()
    check_retry_then_success()
    check_two_failures_fall_back_to_facts()
    check_other_failures_fall_back()
    check_bad_tool_input_doesnt_crash()
    check_events_are_compacted()
    check_dropped_connections_are_retried()
    check_a_new_score_needs_a_new_answer()
    check_embeddings_say_what_they_are()
    check_the_time_limit_stops_retries()
    check_a_broken_tool_doesnt_crash()
    check_parse_tolerates_wrapping()
    check_llm_retries_rate_limits()
    print("all agent checks passed")


if __name__ == "__main__":
    main()
