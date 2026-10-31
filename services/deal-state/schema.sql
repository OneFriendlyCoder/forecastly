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
    published_at   timestamptz NOT NULL,                        -- when it entered Kafka
    received_at    timestamptz NOT NULL DEFAULT clock_timestamp()  -- when Postgres stored it
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

CREATE TABLE IF NOT EXISTS deals (  -- the CRM record; events don't carry these fields
    deal_id text PRIMARY KEY,
    product text NOT NULL,
    amount  double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS deal_scores (
    deal_id            text NOT NULL,
    as_of              timestamptz NOT NULL,
    model_version      text NOT NULL,
    score              double precision NOT NULL,
    factors            jsonb NOT NULL,                              -- top 3 reasons for the score
    features           jsonb NOT NULL,
    event_published_at timestamptz NOT NULL,                        -- when the newest event entered Kafka
    scored_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (deal_id, as_of, model_version)                     -- also what makes redelivery safe
);
