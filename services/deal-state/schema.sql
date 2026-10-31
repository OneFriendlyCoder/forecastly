CREATE TABLE IF NOT EXISTS events (
    event_id       uuid PRIMARY KEY,  -- also what makes redelivery safe
    event_type     text NOT NULL,
    occurred_at    timestamptz NOT NULL,
    tenant_id      text NOT NULL,
    deal_id        text NOT NULL,
    account_id     text,
    actor          jsonb NOT NULL,
    payload        jsonb NOT NULL,
    schema_version int NOT NULL,
    received_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_deal_time ON events (deal_id, occurred_at);

CREATE TABLE IF NOT EXISTS deal_health (
    deal_id            text PRIMARY KEY,
    email_sent         int NOT NULL DEFAULT 0,
    email_replied      int NOT NULL DEFAULT 0,
    meeting_held       int NOT NULL DEFAULT 0,
    meeting_no_show    int NOT NULL DEFAULT 0,
    contact_added      int NOT NULL DEFAULT 0,
    close_date_changed int NOT NULL DEFAULT 0,
    stage_changed      int NOT NULL DEFAULT 0,
    deal_closed        int NOT NULL DEFAULT 0,
    last_event_at      timestamptz NOT NULL,
    last_event_id      uuid NOT NULL,
    updated_at         timestamptz NOT NULL DEFAULT now()
);
