"""The real agent, the real model and the real stack. Run with: make test-agent"""
import asyncio
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/simulator"))
sys.path.insert(0, str(ROOT / "services/deal-state"))
from replay import load_events, replay
from test_e2e import BROKERS, sql, wait_until_scored

AGENT = "http://localhost:8090"
SEARCHES = {  # a real embedding setting bug once scored 4 of 10 here, with no error
    "negative replies from the buyer": "negative-replies",
    "buyer has gone silent, no reply for weeks": "reengage-silent-deals",
    "close date keeps moving": "close-date-hygiene",
    "buyer missed a meeting, no-show": "missed-meetings",
    "buyers are replying slowly": "slow-reply-times",
    "only one buyer is involved": "multithread-the-account",
    "many emails sent with few replies": "too-many-emails",
    "pricing objection": "pricing-objections",
    "deal stalled at late stage": "stalled-late-stage",
    "should we keep this deal open": "qualify-or-close",
}
TOOLS = {"list_at_risk_deals", "get_deal", "get_recent_events", "search_playbook", "explain_deal"}


def post(path):
    request = urllib.request.Request(AGENT + path, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def top_deal():
    with urllib.request.urlopen("http://localhost:8080/deals/at-risk?limit=1", timeout=10) as response:
        return json.load(response)["deals"][0]["deal_id"]


def check_explanation(deal_id):
    status, first = post(f"/explain/{deal_id}")
    assert status == 200 and not first["cached"], first
    print(json.dumps(first, indent=2))
    assert first["grounded"], f"answer failed the guard: {first.get('why_not')}"
    cited = first["answer"]["next_step"]["playbook_id"]
    assert sql(f"SELECT count(*) AS n FROM playbook_chunks WHERE chunk_id = '{cited}'")["n"][0] == 1
    print(f"ok: grounded answer in {first['latency_ms']} ms, citing {cited}")

    status, second = post(f"/explain/{deal_id}")
    assert status == 200 and second["cached"] and second["answer"] == first["answer"]
    print("ok: the second request came from the cache")


def check_errors():
    assert post("/explain/nope")[0] == 404
    untouched = sql("SELECT d.deal_id FROM deals d LEFT JOIN deal_scores s USING (deal_id) WHERE s.deal_id IS NULL LIMIT 1").iloc[0, 0]
    assert post(f"/explain/{untouched}")[0] == 409
    print("ok: unknown deals get 404, unscored deals get 409")


async def check_mcp(deal_id):
    async with Client(f"{AGENT}/mcp") as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert TOOLS <= names, names
        result = await client.call_tool("get_deal", {"deal_id": deal_id})
        assert deal_id in str(result.content)
        hits = 0
        for query, guide in SEARCHES.items():
            found = await client.call_tool("search_playbook", {"query": query})
            hits += guide in str(found.content)
        assert hits >= 9, f"playbook search found {hits} of {len(SEARCHES)} expected guides"
        print(f"ok: playbook search found {hits} of {len(SEARCHES)} expected guides")
    print(f"ok: an MCP client sees {len(names)} tools and can call them")


def main():
    subprocess.run(["make", "reset", "up"], cwd=ROOT, check=True, capture_output=True)
    chunks = sql("SELECT count(*) AS n FROM playbook_chunks")["n"][0]
    assert chunks >= 30, f"only {chunks} playbook sections indexed"
    print(f"ok: {chunks} playbook sections indexed")
    replay(load_events(ROOT / "data/simulated/events.parquet"), BROKERS, "activity.events", seconds_per_day=0)
    wait_until_scored()
    deal_id = top_deal()
    check_explanation(deal_id)
    check_errors()
    asyncio.run(check_mcp(deal_id))


if __name__ == "__main__":
    main()
