"""The Deal Risk Agent: explains a score from real data, then checks its own answer."""
import json
import re
import time

from llm import LLMError
from tools import DEFINITIONS

MAX_STEPS = 6
TIME_LIMIT_SECONDS = 300  # past this, the reader gets plain facts and the work stops
MIN_REASONS = 2
EVENTS_SHOWN = 10
WINDOW_DAYS = 14.0  # the features' "last 14 days"

SYSTEM = """Think briefly, then answer. You explain to a sales rep why a deal has a low chance of winning, and suggest one next step.

Use get_recent_events to see what happened. Use search_playbook to find advice for the deal's own largest factors, and
base the next step on the section that fits this deal best.
Only state facts that appear in the data you were given. Never invent numbers, names or events.
Don't quote calendar dates or work out new numbers. Use the day counts already in the features.
The factors show what moved a statistical model's score. Don't say what caused the deal's trouble, and never use the
words "because", "caused" or "due to".

When finished, reply with only this JSON:
{"summary": "one or two plain sentences",
 "reasons": [{"text": "one plain sentence", "feature": "a feature name from the deal data"}],
 "next_step": {"text": "one specific action for the rep", "playbook_id": "the chunk_id you used"}}
Give 2 or 3 reasons, starting with the factors with the largest impact. Each reason must say what actually happened
and quote the factor's value, such as "7 negative replies so far" or "25 days since the last buyer reply". Round
values to whole numbers. Don't mention the model or its impact numbers."""

CAUSE_CLAIM = re.compile(r"\b(because|caused?|causing|due to)\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def numbers_in(text):
    return {float(value) for value in NUMBER.findall(text.replace(",", ""))}


def walk_numbers(value):
    """Real data values only. Digits inside dates and ids must not vouch for an invented number."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "body":  # playbook text
                yield from numbers_in(str(item))
            else:
                yield from walk_numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_numbers(item)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield float(value)


def known_numbers(deal, sources):
    """Every number the agent has seen, as written and rounded, as a person would quote it."""
    seen = {*walk_numbers(deal), *walk_numbers(sources), WINDOW_DAYS, float(EVENTS_SHOWN)}  # "the last 10 events" is true
    if deal.get("score") is not None:
        seen.add(float(round(deal["score"] * 100)))
    return seen | {round(n, 1) for n in seen} | {float(round(n)) for n in seen}


def guard(answer, deal, sources, chunks):
    """Returns what's wrong with an answer. An empty list means every checkable claim is grounded."""
    if not isinstance(answer, dict):
        return ["the reply must be a JSON object"]
    reasons, step, summary = answer.get("reasons"), answer.get("next_step"), answer.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return ["summary is missing"]
    if not isinstance(reasons, list) or len(reasons) < MIN_REASONS:
        return [f"give at least {MIN_REASONS} reasons"]
    if not all(isinstance(r, dict) and isinstance(r.get("text"), str) for r in reasons):
        return ["each reason needs text and a feature"]
    if not isinstance(step, dict) or not isinstance(step.get("text"), str) or not step["text"].strip():
        return ["next_step is missing"]

    problems = []
    features = set(deal.get("features") or {}) | {f["feature"] for f in deal.get("factors") or []}
    for reason in reasons:
        if reason.get("feature") not in features:
            problems.append(f"unknown feature {reason.get('feature')!r}")
    if step.get("playbook_id") not in chunks:
        problems.append(f"playbook_id {step.get('playbook_id')!r} wasn't returned by search_playbook")

    written = " ".join([summary, step["text"], *(r["text"] for r in reasons)])
    allowed = known_numbers(deal, sources)
    invented = sorted(numbers_in(written) - allowed)
    if invented:
        problems.append(f"these numbers aren't in the data: {invented}")
    if CAUSE_CLAIM.search(written):
        problems.append("don't claim a cause, only say what moved the score")
    return problems


def parse(content):
    """Models sometimes wrap the JSON in text or code fences."""
    content = content or ""
    start, end = content.find("{"), content.rfind("}")
    try:
        return json.loads(content[start:end + 1])
    except ValueError:
        return None


def plain_facts(deal, why):
    """Used when no checked answer is possible. It's built by code, so it can't invent anything."""
    reasons = [{"text": f"{f['feature'].replace('_', ' ')}: {f['value']}", "feature": f["feature"]}
               for f in deal.get("factors") or []]
    return {"grounded": False, "why_not": why, "answer": {"summary": "These are the facts behind the score.",
                                                          "reasons": reasons, "next_step": None}}


def compact_event(event):
    """Only what an explanation can use. Ids and templates bloat the prompt, and the model overthinks long prompts."""
    payload = event.get("payload") or {}
    kept = {key: payload[key] for key in ("sentiment", "meeting_type", "old", "new", "outcome") if key in payload}
    return {"type": event["event_type"], "at": event["occurred_at"][:10], **kept}


def run_tool(call, tools):
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
        if call["function"]["name"] == "get_recent_events":
            limit = min(int(args.get("limit", EVENTS_SHOWN)), EVENTS_SHOWN)
            return [compact_event(event) for event in tools.get_recent_events(args["deal_id"], limit)]
        if call["function"]["name"] == "search_playbook":
            return tools.search_playbook(args["query"])
        return {"error": f"unknown tool {call['function']['name']}"}
    except (KeyError, TypeError, ValueError) as error:
        return {"error": f"bad arguments: {error}"}
    except LLMError:
        raise
    except Exception as error:  # a broken tool is reported to the model, never to the reader
        return {"error": f"tool failed: {type(error).__name__}"}


def cache_key(deal, llm_model):
    """Includes the score, because a late event can change it without changing the deal's latest event time."""
    return deal["deal_id"], deal["as_of"], deal["model_version"], llm_model, deal["score"]


def explain(deal, llm, tools):
    """deal is a get_deal result with a score. The result is always safe to show."""
    facts = {key: deal.get(key) for key in ("deal_id", "product", "amount", "score", "factors", "activity")}
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Explain this deal.\n{json.dumps(facts)}"}]
    sources, chunks, retried, calls, rejected = [], set(), False, 0, []
    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    try:
        for _ in range(MAX_STEPS):
            calls += 1
            message = llm.chat(messages, DEFINITIONS, deadline)
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
                for call in tool_calls:
                    result = run_tool(call, tools)
                    sources.append(result)
                    if call["function"]["name"] == "search_playbook" and isinstance(result, list):
                        chunks |= {chunk["chunk_id"] for chunk in result}
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                continue

            answer = parse(message.get("content"))
            problems = guard(answer, deal, sources, chunks)
            if not problems:
                return {"grounded": True, "answer": answer, "retried": retried, "llm_calls": calls, "rejected": rejected}
            rejected += problems
            if retried:
                return {**plain_facts(deal, "; ".join(problems)), "retried": True, "llm_calls": calls, "rejected": rejected}
            retried = True
            messages.append({"role": "assistant", "content": message.get("content") or ""})
            messages.append({"role": "user", "content": "Your answer failed a fact check: " + "; ".join(problems)
                             + ". Reply again with corrected JSON only."})
        return {**plain_facts(deal, "ran out of steps"), "retried": retried, "llm_calls": calls, "rejected": rejected}
    except LLMError as error:
        return {**plain_facts(deal, str(error)), "retried": retried, "llm_calls": calls, "rejected": rejected}
