# Pipeline Pulse: Project Overview

Pipeline Pulse is an event-driven engine that tracks B2B deals. The final project will also predict which deals are at risk and explain why. This page shows what's built today and where to find the details.

The main aim is to show software engineering and problem solving. Data and model quality matter less, as long as the results are reported honestly.

## What's built

```text
Maven + Enron data -> simulator -> events.parquet
                                        |
                                        v
                                   replay tool (faults, scale, bursts)
                                        |
                                        v
                                   Kafka: activity.events ----> activity.events.dlq
                                        |                       (broken events)
                                        v
                                   Python deal-state service
                                        |
                                        v
                                   Postgres: events, deal_health
                                        |
                                        v
                                   Kafka: deal.features
                                        |
                                        v
                                   Python scoring service
                                        |
                                        v
                                   Postgres: deal_scores
                                        |
                                        v
                                   FastAPI API
                                        |
                                        v
                                   React dashboard <-> Agent <-> NVIDIA LLM
                                                       |
                                                       v
                                                  MCP clients
```

| Part | Status | Details |
|---|---|---|
| Data download and cleaning | Done | [data.md](data.md) |
| Simulator generator | Done | [simulator.md](simulator.md) |
| Local infrastructure | Done | [infrastructure.md](infrastructure.md) |
| Replay tool | Done | [replay_tool.md](replay_tool.md) |
| Python deal-state service | Done | [deal_state.md](deal_state.md) |
| Fault and load testing | Done | [deal_state.md](deal_state.md) |
| Problems found while building | Ongoing | [issues_resolved.md](issues_resolved.md) |
| Features and training data | Done | [features.md](features.md) |
| Model | Done | [model.md](model.md) |
| Live features and scoring | Done | [scoring.md](scoring.md) |
| FastAPI API | Done | [api.md](api.md) |
| Dashboard | Done | [dashboard.md](dashboard.md) |
| Agent over MCP | Done | [agent.md](agent.md) |
| CRM connector | Not started | |
| Future scope | Planned | [future_scope.md](future_scope.md) |
| CI | Not started | |

## Run it from a fresh clone

You need Docker and Python.

```bash
python3 -m venv .venv
.venv/bin/pip install -r ml/requirements.txt

.venv/bin/python ml/data/download.py          # 443 MB Enron download, about 15 minutes
.venv/bin/python ml/data/build_tables.py
.venv/bin/python ml/data/fit_distributions.py
.venv/bin/python ml/simulator/simulate.py

make snapshots
make train
cp .env.example .env                          # then add your NVIDIA key; optional, used by the agent
make up
.venv/bin/python ml/simulator/replay.py --fast
```

## Main results so far

These come from a laptop in Docker. See [deal_state.md](deal_state.md) and [scoring.md](scoring.md) for the limits.

| Measure | Result |
|---|---|
| Events simulated | 439,821 across 8,300 deals |
| Clean-vs-faults proof | Final state identical with about 18,000 injected faults and 3 forced kills |
| Target rate of 1M events/hour | Handled with no backlog, p95 of 0.237 s from event to score |
| Maximum throughput with scoring | 7,597 events/s with 1 consumer, 10,824 with 3, on the earlier Go version. Not yet remeasured on Python |

## Changes from the original plan

| Plan | Now | Why |
|---|---|---|
| Go services | Python `deal-state` and FastAPI API | The project owner needs to explain and maintain the code. The Go version is on the `agent` branch |
| Three real data sources | Maven and Enron only | Olist couldn't test deal outcomes. See [data.md](data.md) |
| Stage-weighted baseline | Win rate by stage and days open | The plan's version gives every finished deal the same 63% |
| Model numbers as targets | Numbers to report honestly | The simulator's settings could decide the score |
| Early warning on all lost deals | Only lost deals lasting over 14 days | About half of lost deals end within 14 days |
| 12 event types | 8 | The extra types added little to the engineering |
| Tuning the simulator to match real data | Rule checks and a leakage check | The simulator is mainly a test tool |
| `processed_events` table | Primary key on `events` | It does the same job with less code |
| Redis at the start | Added when it's needed | Nothing uses it yet |
| Pitch leads with Brier score | Pitch leads with reliability and throughput | These are the strongest measured results |

Redis, the connector, Kubernetes and the rest of the plan are still open, and each will be decided step by step.

## Working method

Each step is proposed, approved and then built, one at a time. Work so far is on the `data-setup` branch.
