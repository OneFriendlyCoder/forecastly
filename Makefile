COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: up down reset check snapshots train test test-e2e test-faults test-scoring test-api test-dashboard test-agent eval-agent load-test demo-setup demo demo-check

DEMO_SPEED ?= 0.5  # real seconds per simulated day; much faster risks a backlog on a laptop
KEEP_AWAKE := $(shell command -v caffeinate >/dev/null && echo caffeinate -i)

up:
	$(COMPOSE) up -d --wait redpanda postgres
	$(COMPOSE) up create-topics
	$(COMPOSE) up -d --build deal-state scoring api agent web
	.venv/bin/python services/deal-state/seed_deals.py
	-$(COMPOSE) exec -T agent python index_playbook.py  # needs the key in .env

demo-setup:  # wipes local Kafka and Postgres data, then leaves an empty dashboard
	$(MAKE) reset up
	@echo "Ready: open http://localhost:3000, then run make demo"

demo:  # run demo-setup first; add FAULTS=--faults to send duplicate, late and broken events too
	$(KEEP_AWAKE) .venv/bin/python ml/simulator/replay.py --seconds-per-day $(DEMO_SPEED) $(FAULTS)

demo-check:  # events and scores stored, events still waiting, and events rejected
	@$(COMPOSE) exec -T postgres psql -U pulse -d pipeline_pulse -Atc "SELECT 'stored: ' || count(*) || ' events' FROM events; SELECT 'scored: ' || count(*) || ' times' FROM deal_scores"
	@$(COMPOSE) exec -T redpanda rpk group describe deal-state | awk '/TOTAL-LAG/ {print "waiting for deal-state: " $$2}'
	@$(COMPOSE) exec -T redpanda rpk group describe scoring | awk '/TOTAL-LAG/ {print "waiting for scoring: " $$2}'
	@$(COMPOSE) exec -T redpanda rpk topic describe activity.events.dlq -p | awk 'NR > 1 {n += $$NF} END {print "rejected: " n}'

down:
	$(COMPOSE) down

reset:  # also deletes stored data
	$(COMPOSE) down -v

check:
	@$(COMPOSE) exec -T postgres psql -U pulse -d pipeline_pulse -tc "SELECT 'postgres ok'"
	@$(COMPOSE) exec -T redpanda rpk topic describe activity.events | grep -E '^(NAME|PARTITIONS)'
	@$(COMPOSE) exec -T redpanda rpk topic create smoke.test >/dev/null
	@MSG=check-$$(date +%s); \
	echo $$MSG | $(COMPOSE) exec -T redpanda rpk topic produce smoke.test >/dev/null; \
	$(COMPOSE) exec -T redpanda rpk topic consume smoke.test -n 1 -f '%v\n' | grep -q $$MSG \
		&& echo "kafka ok: message sent and read back"; \
	STATUS=$$?; $(COMPOSE) exec -T redpanda rpk topic delete smoke.test >/dev/null; exit $$STATUS

snapshots:
	.venv/bin/python ml/features/build_snapshots.py

train:
	.venv/bin/python ml/model/train.py

test: snapshots
	.venv/bin/python services/deal-state/test_main.py
	.venv/bin/python services/api/test_main.py
	.venv/bin/python ml/simulator/test_simulate.py
	.venv/bin/python ml/features/test_features.py
	.venv/bin/python ml/model/test_train.py
	.venv/bin/python agent/test_agent.py
	cd web && npm test

test-e2e:  # wipes local Kafka and Postgres data
	$(MAKE) reset up
	.venv/bin/python services/deal-state/test_e2e.py

test-faults:  # wipes local Kafka and Postgres data, several times
	$(MAKE) up
	.venv/bin/python services/deal-state/test_faults.py

test-scoring:  # wipes local Kafka and Postgres data, several times
	.venv/bin/python ml/scoring/test_scoring.py

test-api:  # wipes local Kafka and Postgres data
	.venv/bin/python services/api/test_api.py

test-dashboard: test-api  # wipes local Kafka and Postgres data
	cd web && npm run test:e2e

test-agent:  # wipes local Kafka and Postgres data, uses the LLM
	.venv/bin/python agent/test_live.py

eval-agent:  # needs a filled stack, makes about 200 LLM calls
	.venv/bin/python agent/evaluate.py

load-test:  # wipes local Kafka and Postgres data, several times
	$(MAKE) up
	.venv/bin/python services/deal-state/load_test.py
