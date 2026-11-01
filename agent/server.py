"""Serves explanations to the dashboard and the agent's tools over MCP."""
import json
import time

import psycopg
import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from agent import cache_key, explain
from llm import LLM
from tools import DealNotFound, Tools

llm = LLM.from_env()
tools = Tools(llm)
mcp = MCPServer("pipeline-pulse", instructions="Read deal risk scores, activity and sales playbook advice.")

FIND = """SELECT answer, grounded, latency_ms FROM deal_explanations
WHERE deal_id = %s AND as_of = %s AND model_version = %s AND llm_model = %s AND score = %s"""
SAVE = """INSERT INTO deal_explanations (deal_id, as_of, model_version, llm_model, score, answer, grounded, latency_ms)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (deal_id, as_of, model_version, llm_model, score) DO UPDATE SET
    answer = EXCLUDED.answer, grounded = EXCLUDED.grounded, latency_ms = EXCLUDED.latency_ms"""


def explain_deal_cached(deal_id, fresh=False):
    """An answer stays valid until the deal's score changes. Fallbacks aren't kept, so a later try can do better."""
    deal = tools.get_deal(deal_id)
    if deal["score"] is None:
        return None
    key = cache_key(deal, llm.model)
    with psycopg.connect(tools.database_url) as db:
        row = None if fresh else db.execute(FIND, key).fetchone()
        if row:
            return {"grounded": row[1], "answer": row[0], "cached": True, "latency_ms": row[2]}
        started = time.monotonic()
        result = explain(deal, llm, tools)
        latency_ms = round((time.monotonic() - started) * 1000)
        if result["grounded"]:
            db.execute(SAVE, (*key, json.dumps(result["answer"]), True, latency_ms))
    return {**result, "cached": False, "latency_ms": latency_ms}


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/explain/{deal_id}", methods=["POST"])
async def explain_route(request):
    fresh = request.query_params.get("fresh") == "true"
    try:
        result = await run_in_threadpool(explain_deal_cached, request.path_params["deal_id"], fresh)
    except DealNotFound:
        return JSONResponse({"error": "deal not found"}, status_code=404)
    if result is None:
        return JSONResponse({"error": "deal has no score yet"}, status_code=409)
    return JSONResponse(result)


@mcp.tool()
async def list_at_risk_deals(limit: int = 20) -> list[dict]:
    """Open deals with the lowest chance of winning, riskiest first."""
    return await run_in_threadpool(tools.list_at_risk, min(limit, 100))


@mcp.tool()
async def get_deal(deal_id: str) -> dict:
    """A deal's latest score, the factors that moved it, and its activity counts."""
    return await run_in_threadpool(tools.get_deal, deal_id)


@mcp.tool()
async def get_recent_events(deal_id: str, limit: int = 20) -> list[dict]:
    """A deal's newest activity events."""
    return await run_in_threadpool(tools.get_recent_events, deal_id, min(limit, 50))


@mcp.tool()
async def search_playbook(query: str) -> list[dict]:
    """Search the sales playbook for advice on a situation."""
    return await run_in_threadpool(tools.search_playbook, query)


@mcp.tool()
async def explain_deal(deal_id: str) -> dict | None:
    """A fact-checked explanation of a deal's risk with one next step. Empty if the deal has no score."""
    return await run_in_threadpool(explain_deal_cached, deal_id)


if __name__ == "__main__":
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=8090)
