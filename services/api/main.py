"""Serves deals and their scores from Postgres over read-only HTTP."""
import logging
import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from psycopg_pool import ConnectionPool, PoolTimeout

DEFAULT_LIMIT = 50
MAX_LIMIT = 1000
QUERY_TIMEOUT_MS = 5000

log = logging.getLogger("api")

LATEST_SCORE = """
    SELECT s.score, s.as_of, s.model_version, s.factors, s.features
    FROM deal_scores s WHERE s.deal_id = d.deal_id
    ORDER BY s.as_of DESC, s.scored_at DESC LIMIT 1"""

# Postgres builds each JSON response, so the columns live in one place.
AT_RISK_SQL = f"""
SELECT json_build_object('deals', coalesce(json_agg(t ORDER BY t.score, t.deal_id), '[]'))::text
FROM (
    SELECT d.deal_id, d.product, d.amount, s.score, s.as_of, s.model_version, s.factors
    FROM deal_health h
    JOIN deals d USING (deal_id)
    CROSS JOIN LATERAL ({LATEST_SCORE}) s
    WHERE h.deal_closed = 0
    ORDER BY s.score, d.deal_id
    LIMIT %s
) t"""

DEAL_SQL = f"""
SELECT row_to_json(t)::text
FROM (
    SELECT d.deal_id, d.product, d.amount, coalesce(h.deal_closed > 0, false) AS closed, h.last_event_at,
           s.score, s.as_of, s.model_version, s.factors, s.features,
           to_jsonb(h) - 'deal_id' - 'last_event_at' - 'last_event_id' - 'updated_at' AS activity
    FROM deals d
    LEFT JOIN deal_health h USING (deal_id)
    LEFT JOIN LATERAL ({LATEST_SCORE}) s ON true
    WHERE d.deal_id = %s
) t"""

# The newest scores, returned oldest first so a chart can draw them in order.
SCORES_SQL = """
SELECT json_build_object('deal_id', d.deal_id, 'scores', (
    SELECT coalesce(json_agg(t ORDER BY t.as_of), '[]')
    FROM (
        SELECT s.as_of, s.score, s.model_version FROM deal_scores s
        WHERE s.deal_id = d.deal_id ORDER BY s.as_of DESC LIMIT %(limit)s
    ) t
))::text
FROM deals d WHERE d.deal_id = %(id)s"""

# The newest events first, which is what the agent reads.
EVENTS_SQL = """
SELECT json_build_object('deal_id', d.deal_id, 'events', (
    SELECT coalesce(json_agg(t ORDER BY t.occurred_at DESC, t.event_id), '[]')
    FROM (
        SELECT e.event_id, e.event_type, e.occurred_at, e.actor, e.payload FROM events e
        WHERE e.deal_id = d.deal_id ORDER BY e.occurred_at DESC, e.event_id LIMIT %(limit)s
    ) t
))::text
FROM deals d WHERE d.deal_id = %(id)s"""

pool = ConnectionPool(os.environ.get("DATABASE_URL", "postgres://pulse:pulse@localhost:5432/pipeline_pulse"),
                      open=False, timeout=QUERY_TIMEOUT_MS / 1000,
                      kwargs={"options": f"-c statement_timeout={QUERY_TIMEOUT_MS}"})


@asynccontextmanager
async def lifespan(_app):
    pool.open()  # connects in the background, so the API can start before Postgres is ready
    yield
    pool.close()


app = FastAPI(title="Pipeline Pulse API", lifespan=lifespan)
Limit = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


def error(status, message):
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(RequestValidationError)
async def bad_request(_request: Request, _error: RequestValidationError):
    return error(400, f"limit must be from 1 to {MAX_LIMIT}")


@app.exception_handler(psycopg.Error)
@app.exception_handler(PoolTimeout)
async def database_failed(request: Request, failure: Exception):
    log.error("query failed on %s: %s", request.url.path, failure)
    return error(500, "internal error")


def respond(query, params):
    """Runs a query that returns one row of JSON. No row means the deal doesn't exist."""
    with pool.connection() as db:
        row = db.execute(query, params).fetchone()
    if row is None:
        return error(404, "deal not found")
    return Response(row[0], media_type="application/json")


@app.get("/health")
def health():
    try:
        with pool.connection() as db:
            db.execute("SELECT 1")
    except (psycopg.Error, PoolTimeout):
        return error(503, "database unavailable")
    return {"status": "ok"}


@app.get("/deals/at-risk")
def at_risk(limit: int = Limit):
    return respond(AT_RISK_SQL, (limit,))


@app.get("/deals/{deal_id}")
def deal(deal_id: str):
    return respond(DEAL_SQL, (deal_id,))


@app.get("/deals/{deal_id}/scores")
def scores(deal_id: str, limit: int = Limit):
    return respond(SCORES_SQL, {"id": deal_id, "limit": limit})


@app.get("/deals/{deal_id}/events")
def events(deal_id: str, limit: int = Limit):
    return respond(EVENTS_SQL, {"id": deal_id, "limit": limit})
