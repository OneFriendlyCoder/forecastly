COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: up down reset check

up:
	$(COMPOSE) up -d --wait redpanda postgres
	$(COMPOSE) up create-topics

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
