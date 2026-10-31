# Pipeline Pulse: Local Infrastructure

Everything runs on one machine through Docker Compose, defined in `deploy/docker-compose.yml`. It's for development and demos, and isn't production-ready.

## Services

| Service | Job | Reach it at |
|---|---|---|
| `redpanda` | Kafka-compatible event log | `localhost:19092` from the Mac, `redpanda:9092` inside Docker |
| `postgres` | Permanent storage | `localhost:5432` |
| `create-topics` | Creates Kafka topics, then exits | |
| `deal-state` | The Go service, built from `services/deal-state/Dockerfile` | |

Redpanda has two addresses because the Mac and the containers reach it differently. Each client must use the address for where it runs.

## Kafka topics

| Topic | Partitions | Holds |
|---|---|---|
| `activity.events` | 6 | All activity, keyed by `deal_id` |
| `activity.events.dlq` | 6 | Broken events, with the reason in a header |

Six partitions allow up to six consumers to share the work. Replication is 1, because there's only one broker.

## Commands

| Command | What it does |
|---|---|
| `make up` | Starts everything, creates topics, rebuilds the service |
| `make down` | Stops everything and keeps the data |
| `make reset` | Stops everything and deletes the data |
| `make check` | Tests Postgres and Kafka |
| `make test` | Runs unit tests and generator checks |
| `make test-e2e` | Runs the full pipeline test, wiping local data first |
| `make test-faults` | Runs the clean-vs-faults proof, wiping local data several times |
| `make load-test` | Runs the load scenarios, wiping local data several times |

`make check` uses a temporary topic, so it never adds test messages to real topics. `test_replay.py` does the same.

## Connection settings

The service reads two environment variables and has local defaults for both.

| Variable | Local default | In Docker |
|---|---|---|
| `KAFKA_BROKERS` | `localhost:19092` | `redpanda:9092` |
| `DATABASE_URL` | `postgres://pulse:pulse@localhost:5432/pipeline_pulse` | Points to `postgres` |

The Postgres password in the Compose file is a demo value for local use only.

## Things to know

- **Tables:** the service creates missing tables when it starts, but it doesn't change existing ones. After a table change, run `make reset`.
- **Go version:** `go.mod` needs Go 1.26, and the Docker image matches it.
- **Python:** use `.venv`. The system Python's NumPy doesn't work with LightGBM.
- **Running more consumers:** `docker compose -f deploy/docker-compose.yml up -d --scale deal-state=3 deal-state`.

## What deployment would change

| Part | Local | On AWS |
|---|---|---|
| Kafka | Redpanda container | MSK, Confluent Cloud or Redpanda Cloud |
| Postgres | Container | RDS |
| Services | Docker Compose | Kubernetes (EKS) with Helm |
| Secrets | Compose file | AWS Secrets Manager |
| Setup | `make up` | Terraform |

The services read their addresses from settings, so the code wouldn't need to change. A deployment would still add more copies of each part, encrypted connections, private networks and monitoring.
