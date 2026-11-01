"""Serves deals and their scores from Postgres over read-only HTTP."""
import logging
import os
from contextlib import asynccontextmanager
from enum import Enum

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

# The one place the risk cut-offs live. They're simple guesses, not fitted values.
RISK_LEVEL = "CASE WHEN {score} < 0.4 THEN 'high' WHEN {score} < 0.6 THEN 'medium' ELSE 'low' END"

OPEN_DEALS = f"""
    SELECT d.deal_id, d.product, d.amount, d.owner, s.score, s.as_of, s.model_version, s.factors,
           p.score AS previous_score, {RISK_LEVEL.format(score="s.score")} AS risk
    FROM deal_health h
    JOIN deals d USING (deal_id)
    CROSS JOIN LATERAL ({LATEST_SCORE}) s
    LEFT JOIN LATERAL (
        SELECT s2.score FROM deal_scores s2 WHERE s2.deal_id = d.deal_id
        ORDER BY s2.as_of DESC, s2.scored_at DESC OFFSET 1 LIMIT 1
    ) p ON true
    WHERE h.deal_closed = 0"""


class Risk(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Sort(str, Enum):
    riskiest = "riskiest"
    safest = "safest"
    largest = "largest"
    biggest_drop = "biggest_drop"


ORDER_BY = {  # fixed text, chosen by the validated Sort value
    Sort.riskiest: "score, deal_id",
    Sort.safest: "score DESC, deal_id",
    Sort.largest: "amount DESC, score, deal_id",
    Sort.biggest_drop: "coalesce(score - previous_score, 0), score, deal_id",
}

# Postgres builds each JSON response, so the columns live in one place.
AT_RISK_SQL = f"""
WITH filtered AS (
    SELECT * FROM ({OPEN_DEALS}) o
    WHERE (%(risk)s::text IS NULL OR risk = %(risk)s)
      AND (%(product)s::text IS NULL OR product = %(product)s)
      AND (%(owner)s::text IS NULL OR owner = %(owner)s)
      AND (%(q)s::text IS NULL OR position(upper(%(q)s) IN upper(deal_id)) > 0)
)
SELECT json_build_object(
    'total', (SELECT count(*) FROM filtered),
    'deals', (
        SELECT coalesce(json_agg(t ORDER BY t.position), '[]')
        FROM (
            SELECT *, row_number() OVER (ORDER BY {{order}}) AS position
            FROM filtered ORDER BY position LIMIT %(limit)s OFFSET %(offset)s
        ) t
    )
)::text"""

SUMMARY_SQL = f"""
WITH o AS ({OPEN_DEALS})
SELECT json_build_object(
    'open_deals', (SELECT count(*) FROM deal_health WHERE deal_closed = 0),
    'scored_deals', (SELECT count(*) FROM o),
    'high', (SELECT json_build_object('deals', count(*), 'amount', coalesce(sum(amount), 0)) FROM o WHERE risk = 'high'),
    'medium', (SELECT json_build_object('deals', count(*), 'amount', coalesce(sum(amount), 0)) FROM o WHERE risk = 'medium'),
    'low', (SELECT json_build_object('deals', count(*), 'amount', coalesce(sum(amount), 0)) FROM o WHERE risk = 'low'),
    'products', (SELECT coalesce(json_agg(DISTINCT product), '[]') FROM o),
    'owners', (SELECT coalesce(json_agg(DISTINCT owner), '[]') FROM o)
)::text"""

DEAL_SQL = f"""
SELECT row_to_json(t)::text
FROM (
    SELECT d.deal_id, d.product, d.amount, d.owner, coalesce(h.deal_closed > 0, false) AS closed, h.last_event_at,
           s.score, s.as_of, s.model_version, s.factors, s.features,
           CASE WHEN s.score IS NOT NULL THEN {RISK_LEVEL.format(score="s.score")} END AS risk,
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

# Built from deal_health and the newest scores, as this runs every couple of seconds during a replay.
LIVE_SQL = """
WITH h AS (
    SELECT sum(email_sent + email_replied + meeting_held + meeting_no_show + contact_added
               + close_date_changed + stage_changed + deal_closed) AS events,
           max(last_event_at) AS simulated_at, max(updated_at) AS updated_at
    FROM deal_health
), latest AS (
    SELECT scored_at - event_published_at AS took FROM deal_scores ORDER BY scored_at DESC LIMIT 200
)
SELECT json_build_object(
    'events', coalesce(h.events, 0),
    'simulated_at', h.simulated_at,
    'seconds_since_update', extract(epoch FROM now() - h.updated_at),
    'scores', (SELECT count(*) FROM deal_scores),
    'event_to_score_seconds', (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM took)) FROM latest),
    'recent', (
        SELECT coalesce(json_agg(t), '[]')
        FROM (
            SELECT e.deal_id, e.event_id, e.event_type, e.occurred_at, e.payload
            FROM deal_health d JOIN events e ON e.event_id = d.last_event_id
            ORDER BY d.updated_at DESC, d.last_event_at DESC LIMIT 4
        ) t
    )
)::text
FROM h"""

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
    return error(400, f"bad query value: limit must be from 1 to {MAX_LIMIT}, and filters must use listed values")


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


@app.get("/live")
def live():
    return respond(LIVE_SQL, None)


@app.get("/deals/summary")
def summary():
    return respond(SUMMARY_SQL, None)


@app.get("/deals/at-risk")
def at_risk(limit: int = Limit, offset: int = Query(0, ge=0), risk: Risk | None = None,
            product: str | None = None, owner: str | None = None, q: str | None = None,
            sort: Sort = Sort.riskiest):
    return respond(AT_RISK_SQL.format(order=ORDER_BY[sort]), {
        "limit": limit, "offset": offset, "risk": risk.value if risk else None,
        "product": product, "owner": owner, "q": q or None})


@app.get("/deals/{deal_id}")
def deal(deal_id: str):
    return respond(DEAL_SQL, (deal_id,))


@app.get("/deals/{deal_id}/scores")
def scores(deal_id: str, limit: int = Limit):
    return respond(SCORES_SQL, {"id": deal_id, "limit": limit})


@app.get("/deals/{deal_id}/events")
def events(deal_id: str, limit: int = Limit):
    return respond(EVENTS_SQL, {"id": deal_id, "limit": limit})
