COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: up down reset check snapshots train test test-e2e test-faults test-scoring test-api test-dashboard test-agent eval-agent load-test

up:
	$(COMPOSE) up -d --wait redpanda postgres
	$(COMPOSE) up create-topics
	$(COMPOSE) up -d --build deal-state scoring api agent web
	.venv/bin/python services/deal-state/seed_deals.py
	-$(COMPOSE) exec -T agent python index_playbook.py  # needs the key in .env

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
	go test ./...
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
