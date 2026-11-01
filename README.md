# Forecastly

Forecastly watches B2B sales activity as it happens, predicts each open deal's chance of winning, and explains the score in plain language with one suggested next step.

It's an independent demo for Outreach AI, not an Outreach product. The code, containers and docs use the working name Pipeline Pulse.

**About the data:** deal records come from a public sample dataset, and all deal activity is simulated. The project shows engineering and problem solving. Its results say nothing about predicting real sales.

## What it does

- **Reacts to events.** Emails, replies, meetings and close date changes flow through Kafka, and each one updates the deal's features and score.
- **Scores deals.** A LightGBM model gives a win chance and the top factors that moved it.
- **Shows the pipeline.** A React dashboard lists open deals by risk, with filters, a score history and a live activity strip.
- **Explains scores.** An LLM agent reads the deal's events, searches a sales playbook, and writes a summary and next step. A fact check runs before anything is shown.
- **Survives failure.** Duplicate, late and broken events don't change the final data, and a stopped service catches up by itself.

## How it works

```text
Maven + Enron data -> simulator -> events.parquet
                                        |
                                        v
                                   replay tool (can add faults, scale and bursts)
                                        |
                                        v
                                   Kafka: activity.events ----> activity.events.dlq
                                        |                       (broken events)
                                        v
                                   deal-state service
                                        |
                                        v
                                   Postgres: events, deal_health
                                        |
                                        v
                                   Kafka: deal.features
                                        |
                                        v
                                   scoring service (LightGBM)
                                        |
                                        v
                                   Postgres: deal_scores
                                        |
                                        v
                                   FastAPI API
                                        |
                                        v
                                   React dashboard <-> Agent <-> Claude
                                                       |
                                                       v
                                                  MCP clients
```

Delivery is at-least-once, and writes are safe to repeat. Offsets are committed only after Postgres commits, and primary keys make redelivery harmless.

| Area | Tools |
|---|---|
| Streaming | Redpanda (Kafka API) |
| Storage | Postgres with pgvector |
| Services | Python, FastAPI, confluent-kafka, psycopg |
| Model | LightGBM |
| Agent | Claude Haiku 5.5 through the Anthropic SDK, NVIDIA embeddings, MCP |
| Dashboard | React, TypeScript, Vite, Recharts, nginx |
| Running it | Docker Compose, Make |
| Tests | Plain Python checks, Vitest, Playwright |

## Run it

### What you need

- Git and Make
- Docker with Compose, and Docker must be running
- Python 3.11
- Node 20, only for the dashboard tests
- About 15 minutes for the first data download
- API keys for the agent, which are optional (see step 3)

### 1. Get the code and install

```bash
git clone https://github.com/OneFriendlyCoder/outreach.git
cd outreach
python3 -m venv .venv
.venv/bin/pip install -r ml/requirements.txt -r agent/requirements.txt
```

### 2. Build the data and the model

The data and model aren't stored in git, so a fresh clone needs this once.

```bash
.venv/bin/python ml/data/download.py            # 443 MB Enron download, about 15 minutes
.venv/bin/python ml/data/build_tables.py
.venv/bin/python ml/data/fit_distributions.py
.venv/bin/python ml/simulator/simulate.py

make snapshots
make train
```

### 3. Add API keys

```bash
cp .env.example .env
```

Then fill in `.env`:

| Key | Used for |
|---|---|
| `ANTHROPIC_API_KEY` | Writing explanations. Each one costs a small amount |
| `NVIDIA_API_KEY` | Playbook search, as Claude has no embeddings API |

Without keys, everything else still runs, and the agent shows plain facts instead of a written explanation. `.env` is ignored by git, so never commit it. `make up` indexes the playbook, so if you add keys later, run it again.

### 4. Start it

```bash
make up
.venv/bin/python ml/simulator/replay.py --fast
```

The first command starts the system and the second loads all events with no pauses. Then open:

| What | Address |
|---|---|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8080 |
| API reference | http://localhost:8080/docs |
| Agent's MCP endpoint | http://localhost:8090/mcp |

To stop it, run `make down`. To also delete all stored data, run `make reset`.

## Run the live demo

This replays the deal history at a watchable speed, starting from an empty dashboard.

```bash
make demo-setup     # about 30 seconds, wipes local data
# open http://localhost:3000
make demo           # about 4 minutes
```

Run `make demo-setup` before every demo, because a second replay of the same events changes nothing.

| Time | What to show |
|---|---|
| 0:00 | The empty dashboard, then start the replay. The first minute is quiet, as the history starts with few deals |
| 1:00 | The live strip and risk cards filling up |
| 2:00 | Click **Follow deal ALZNZ666** |
| 2:00 to 3:45 | Its win chance peaks near 91%, then falls to about 35% |
| After 3:45 | Click **Explain this deal** to see the agent's steps and a checked answer |

Open deals start at 0, peak at about 2,800, and end at 1,589. The late fall is because the history stops at the end of 2017, so no new deals replace the ones that close.

**To add bad data,** run `make demo FAULTS=--faults`. It sends duplicate, late and broken messages.

**To show recovery,** run this in a second terminal during the replay:

```bash
docker stop pipeline-pulse-deal-state-1     # the strip changes to "Waiting for events"
make demo-check                             # shows events waiting in Kafka
docker start pipeline-pulse-deal-state-1    # it catches up by itself
```

When the replay ends and nothing is waiting, `make demo-check` shows 439,821 events stored. With faults on, it also shows 433 rejected.

See [demo.md](workflow_documentation/demo.md) for talking points.

## Run the tests

| Command | What it checks | Notes |
|---|---|---|
| `make test` | Fast checks with no running stack | Needs `cd web && npm install` once |
| `make test-e2e` | The full pipeline, from replay to scores | Wipes local data |
| `make test-faults` | Faults and forced kills leave the data unchanged | Wipes local data, several times |
| `make test-scoring` | Live scoring | Wipes local data, several times |
| `make test-api` | Every endpoint against Postgres | Wipes local data |
| `make test-dashboard` | The API test, then browser tests | Wipes local data. Needs `cd web && npx playwright install chromium` once |
| `make test-agent` | The real agent and model, playbook search and MCP | Wipes local data, uses the API keys |
| `make eval-agent` | Scores the agent on 50 deals | Needs a filled stack, uses the API keys |
| `make load-test` | Throughput | Wipes local data, several times |

For a quicker agent check, run `.venv/bin/python agent/evaluate.py 10` to score 10 deals.

## API

| Endpoint | Returns |
|---|---|
| `GET /health` | Whether the API can reach Postgres |
| `GET /live` | Live counts, the simulated date and the newest events |
| `GET /deals/summary` | Totals by risk level |
| `GET /deals/at-risk` | Open deals, with `limit`, `offset`, `risk`, `product`, `owner`, `q` and `sort` |
| `GET /deals/{id}` | One deal, with its score, factors and activity |
| `GET /deals/{id}/scores` | Score history |
| `GET /deals/{id}/events` | Newest events |

The agent listens on port 8090:

| Endpoint | Returns |
|---|---|
| `POST /explain/{id}` | A checked explanation as JSON |
| `POST /explain/{id}/stream` | Progress steps, then the explanation, one JSON object per line |
| `/mcp` | The tools `list_at_risk_deals`, `get_deal`, `get_recent_events`, `search_playbook` and `explain_deal` |

## How the agent stays honest

Only progress steps are streamed, never the words of the answer, because the fact check runs on the finished text. An answer must pass these checks:

- Every number appears in the deal's data.
- Each reason names a real feature.
- The next step cites a playbook section that search returned.
- It doesn't claim a cause, as the factors only show what moved the model.

A failed answer gets one rewrite. If it fails again, or the model can't be reached, code builds a plain facts answer instead.

To change the writing model, set `LLM_MODEL` in `.env`. It accepts another Claude model, or an OpenAI-compatible one through `LLM_BASE_URL` and the matching key in `NVIDIA_API_KEY`.

## Results

These come from one laptop running Docker, on simulated data.

| Measure | Result |
|---|---|
| Events simulated | 439,821 across 8,300 deals |
| Faults | Final state identical with about 18,000 injected faults and 3 forced kills |
| Target rate of 1M events an hour | No backlog, with a p95 of 0.431 s from event to score |
| Maximum throughput | 2,866 events/s with 1 consumer |
| Model AUC on held-out deals | 0.653, tied with logistic regression |
| Model AUC using real deal fields only | 0.518 |
| Explanation time, 20 deals | 6.4 s at p50, 9.8 s at p95 |
| Answers passing the fact check, 20 deals | 20 of 20, with 25% needing a rewrite |

## Known limits

- **The model learns a pattern we built in.** The simulator's hidden health score is steered by the real outcome, which is why activity predicts results at all.
- **Three consumers ran slower than one,** and the burst load test hasn't been run.
- **Agent advice can repeat.** Two playbook sections made up 75% of answers on a 20-deal sample.
- **The fact check doesn't prove the advice is good.** It checks numbers, citations and cause claims.
- **Passing the fact check isn't the same as being relevant.** A 12-deal sample after the last prompt change scored 83% on relevance.
- **Token cost per answer hasn't been measured.**
- **There's no login.** The dashboard, API and agent can only be reached from this machine, but Postgres (5432) and Kafka (19092) are open to your local network, with a demo password on Postgres. Use a trusted network.
- **Real customer data would need a review first,** as deal data is sent to Anthropic and NVIDIA.

## Project layout

```text
agent/                     LLM agent, fact check, MCP server, sales playbook
data/                      Results files. Raw data and models are created locally
deploy/docker-compose.yml  All services
ml/data/                   Download and clean the source data
ml/simulator/              Generate events and replay them into Kafka
ml/features/               Feature definitions and training snapshots
ml/model/                  Train and evaluate the model
ml/scoring/                Live scoring service
schemas/                   Event contract
services/deal-state/       Reads events, stores them and builds live features
services/api/              Read-only FastAPI service
web/                       React dashboard and browser tests
workflow_documentation/    Detailed docs for each part
```

## More detail

| Topic | Doc |
|---|---|
| Overview and changes from the plan | [overview.md](workflow_documentation/overview.md) |
| Data and simulator | [data.md](workflow_documentation/data.md), [simulator.md](workflow_documentation/simulator.md) |
| Replay and infrastructure | [replay_tool.md](workflow_documentation/replay_tool.md), [infrastructure.md](workflow_documentation/infrastructure.md) |
| Pipeline | [deal_state.md](workflow_documentation/deal_state.md), [scoring.md](workflow_documentation/scoring.md) |
| Features and model | [features.md](workflow_documentation/features.md), [model.md](workflow_documentation/model.md) |
| API and dashboard | [api.md](workflow_documentation/api.md), [dashboard.md](workflow_documentation/dashboard.md) |
| Agent | [agent.md](workflow_documentation/agent.md) |
| Live demo | [demo.md](workflow_documentation/demo.md) |
| Problems found and how they were fixed | [issues_resolved.md](workflow_documentation/issues_resolved.md) |
| What's next | [future_scope.md](workflow_documentation/future_scope.md) |
