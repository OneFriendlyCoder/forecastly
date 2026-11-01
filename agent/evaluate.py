"""Scores the agent on 50 open deals across the risk range. Run with: make eval-agent

Each deal's own top factors are the expected reasons. Answers are always generated fresh.
"""
import json
import statistics
from collections import Counter
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = 50
AGENT = "http://localhost:8090"
API = "http://localhost:8080"


def get(path):
    with urllib.request.urlopen(API + path, timeout=30) as response:
        return json.load(response)


def explain(deal_id):
    request = urllib.request.Request(f"{AGENT}/explain/{deal_id}?fresh=true", method="POST")
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def pick_deals(cases):
    deals = get("/deals/at-risk?limit=1000")["deals"]
    step = len(deals) / cases
    return [deals[int(i * step)] for i in range(cases)]


def score(deal, result):
    answer = result["answer"]
    expected = [factor["feature"] for factor in deal["factors"]]
    cited = {reason["feature"] for reason in answer["reasons"]}
    step = answer["next_step"]
    return {
        "deal_id": deal["deal_id"],
        "win_chance": round(deal["score"], 3),
        "groundedness": result["grounded"],
        "relevance": len(cited & set(expected)) >= 2,
        "actionability": bool(step and step.get("playbook_id") and len(step["text"].split()) >= 6),
        "retried": result.get("retried", False),
        "llm_calls": result.get("llm_calls", 0),
        "latency_ms": result["latency_ms"],
        "rejected": result.get("rejected", []),
        "answer": answer,
    }


def crashed(deal, error):
    """A failed request counts against the score and doesn't end the run."""
    return {"deal_id": deal["deal_id"], "win_chance": round(deal["score"], 3), "groundedness": False, "relevance": False,
            "actionability": False, "retried": False, "llm_calls": 0, "latency_ms": 0,
            "rejected": [f"request failed: {error}"], "answer": None}


def share(rows, field):
    return round(sum(bool(row[field]) for row in rows) / len(rows), 3)


def main():
    cases = int(sys.argv[1]) if len(sys.argv) > 1 else CASES  # a smaller run for a quick look
    rows = []
    for deal in pick_deals(cases):
        try:
            rows.append(score(deal, explain(deal["deal_id"])))
        except OSError as error:
            rows.append(crashed(deal, error))
        row = rows[-1]
        print(f"{len(rows)}/{cases} {row['deal_id']} grounded={row['groundedness']} relevant={row['relevance']} "
              f"{row['latency_ms']} ms {row['rejected']}", flush=True)
    finished = [row for row in rows if row["answer"]]  # failed requests have no real time or call count
    times = sorted(row["latency_ms"] for row in finished)
    sections = Counter(row["answer"]["next_step"]["playbook_id"] for row in finished if row["answer"]["next_step"])
    summary = {
        "cases": len(rows),
        "playbook_sections_used": len(sections),
        "top_two_sections_share": round(sum(n for _, n in sections.most_common(2)) / max(sum(sections.values()), 1), 3),
        "groundedness": share(rows, "groundedness"),
        "relevance": share(rows, "relevance"),
        "actionability": share(rows, "actionability"),
        "retried_share": share(rows, "retried"),
        "failed_requests": len(rows) - len(finished),
        "avg_llm_calls": round(statistics.mean(row["llm_calls"] for row in finished), 2),
        "p50_latency_ms": times[len(times) // 2],
        "p95_latency_ms": times[int(len(times) * 0.95)],
    }
    if cases == CASES:
        (ROOT / "data/agent_eval_results.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2) + "\n")
    else:
        print(json.dumps(rows[0]["answer"], indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
