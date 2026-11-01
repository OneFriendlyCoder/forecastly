# API

`services/api/` is a small read-only FastAPI service. It lets the dashboard, and later the agent, read deals and scores without touching Postgres directly. It starts with `make up` and listens on `http://localhost:8080`.

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /health` | `{"status":"ok"}`, or 503 if Postgres can't be reached |
| `GET /deals/summary` | Open deal totals, the count and amount per risk level, and the lists of products and reps |
| `GET /deals/at-risk` | Open deals with the riskiest first, with `total`, rep, risk level, previous score and top 3 reasons |
| `GET /deals/{id}` | One deal's latest score, reasons, features and activity counts |
| `GET /deals/{id}/scores` | The deal's newest scores, oldest first, for a trend chart |
| `GET /deals/{id}/events` | The deal's newest events, newest first, for the agent |

`at-risk`, `scores` and `events` take `?limit=`, a whole number from 1 to 1000. The default is 50.

`at-risk` also takes `offset`, `risk` (`high`, `medium` or `low`), `product`, `owner`, `q` (part of a deal ID) and `sort` (`riskiest`, `safest`, `largest` or `biggest_drop`).

- **Deals with no score:** a deal in the `deals` table with no activity returns 200, with `score` and `activity` set to `null`.
- **Closed deals:** they keep their detail and history but never appear in `at-risk`.
- **Interactive docs:** FastAPI serves them at `http://localhost:8080/docs`.
- **Errors:** an unknown deal gets 404, a bad limit gets 400, and database failures get 500 without internal details. Each error body is `{"error":"..."}`.
- **Reasons:** a positive `impact` raises the chance of winning, and a negative one lowers it.

## How it works

Postgres builds each JSON response, so Python only passes it through and the columns are defined in one place. All values reach the database as query parameters. Each query has a 5-second time limit.

## Tests

- `make test` checks bad limits and that only GET is allowed, with no database.
- `make test-api` replays every event through the real stack and wipes local data. It compares `at-risk`, deal detail and score history with Postgres, and checks closed deals, never-active deals, 404s and 400s.

## Limits

- **No login:** the port is bound to this machine only. A real deployment needs login and per-customer access.
- **Not load tested:** we haven't measured the API under concurrent traffic.
- **Dashboards must poll:** the plan's live updates (SSE) and `deal.scores` topic are left out for now.
- **Single tenant:** queries don't filter by `tenant_id`, and the demo has one tenant.
