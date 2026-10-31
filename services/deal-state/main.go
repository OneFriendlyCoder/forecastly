// Command deal-state reads activity events from Kafka and keeps a live record per deal in Postgres.
//
// Delivery is at-least-once: offsets are committed only after Postgres commits, and the events
// primary key turns any redelivery into a no-op. Broken events go to a dead-letter topic.
package main

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/OneFriendlyCoder/outreach/schemas"
)

const (
	topic    = "activity.events"
	dlqTopic = "activity.events.dlq"
	group    = "deal-state"
	maxBatch = 2000
)

//go:embed schema.sql
var schemaSQL string

// Each query is built from a fixed event type, never from message data. The schema check
// limits event_type to these keys, and one statement keeps the insert and count atomic.
var applyEvent = func() map[string]string {
	types := []string{"email_sent", "email_replied", "meeting_held", "meeting_no_show",
		"contact_added", "close_date_changed", "stage_changed", "deal_closed"}
	queries := make(map[string]string, len(types))
	for _, eventType := range types {
		queries[eventType] = fmt.Sprintf(`
WITH inserted AS (
    INSERT INTO events (event_id, event_type, occurred_at, tenant_id, deal_id, account_id, actor, payload, schema_version)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT (event_id) DO NOTHING
    RETURNING deal_id, occurred_at, event_id
)
INSERT INTO deal_health (deal_id, %[1]s, last_event_at, last_event_id)
SELECT deal_id, 1, occurred_at, event_id FROM inserted
ON CONFLICT (deal_id) DO UPDATE SET
    %[1]s = deal_health.%[1]s + 1,
    -- event_id breaks ties, so the result doesn't depend on arrival order
    last_event_id = CASE WHEN (EXCLUDED.last_event_at, EXCLUDED.last_event_id) > (deal_health.last_event_at, deal_health.last_event_id)
                         THEN EXCLUDED.last_event_id ELSE deal_health.last_event_id END,
    last_event_at = GREATEST(deal_health.last_event_at, EXCLUDED.last_event_at),
    updated_at = now()`, eventType)
	}
	return queries
}()

type event struct {
	EventID       string          `json:"event_id"`
	EventType     string          `json:"event_type"`
	OccurredAt    string          `json:"occurred_at"`
	TenantID      string          `json:"tenant_id"`
	DealID        string          `json:"deal_id"`
	AccountID     *string         `json:"account_id"`
	Actor         json.RawMessage `json:"actor"`
	Payload       json.RawMessage `json:"payload"`
	SchemaVersion int             `json:"schema_version"`
	occurredAt    time.Time
}

func compileSchema() (*jsonschema.Schema, error) {
	document, err := jsonschema.UnmarshalJSON(bytes.NewReader(schemas.EventV1))
	if err != nil {
		return nil, err
	}
	compiler := jsonschema.NewCompiler()
	compiler.AssertFormat()
	if err := compiler.AddResource("event.v1.json", document); err != nil {
		return nil, err
	}
	return compiler.Compile("event.v1.json")
}

// parseEvent returns an error for any message that must go to the dead-letter topic.
// It rejects everything Postgres would refuse, so one bad message can't stop the consumer.
func parseEvent(schema *jsonschema.Schema, value []byte) (event, error) {
	var e event
	if bytes.Contains(value, []byte(`\u0000`)) {
		return e, errors.New("contains a NUL character")
	}
	document, err := jsonschema.UnmarshalJSON(bytes.NewReader(value))
	if err != nil {
		return e, fmt.Errorf("not valid JSON: %w", err)
	}
	if err := schema.Validate(document); err != nil {
		return e, fmt.Errorf("breaks the schema: %w", err)
	}
	if err := json.Unmarshal(value, &e); err != nil {
		return e, err
	}
	e.occurredAt, err = time.Parse(time.RFC3339, e.OccurredAt)
	if err != nil {
		return e, fmt.Errorf("bad occurred_at: %w", err)
	}
	return e, nil
}

func save(ctx context.Context, db *pgx.Conn, events []event) error {
	batch := &pgx.Batch{}
	for _, e := range events {
		batch.Queue(applyEvent[e.EventType], e.EventID, e.EventType, e.occurredAt, e.TenantID, e.DealID,
			e.AccountID, string(e.Actor), string(e.Payload), e.SchemaVersion)
	}
	return pgx.BeginFunc(ctx, db, func(tx pgx.Tx) error {
		return tx.SendBatch(ctx, batch).Close()
	})
}

func handle(ctx context.Context, schema *jsonschema.Schema, db *pgx.Conn, client *kgo.Client, records []*kgo.Record) error {
	events := make([]event, 0, len(records))
	var dead []*kgo.Record
	for _, record := range records {
		e, err := parseEvent(schema, record.Value)
		if err != nil {
			slog.Warn("sending to dead-letter topic", "partition", record.Partition, "offset", record.Offset, "error", err)
			dead = append(dead, &kgo.Record{Topic: dlqTopic, Key: record.Key, Value: record.Value,
				Headers: []kgo.RecordHeader{{Key: "error", Value: []byte(err.Error())}}})
			continue
		}
		events = append(events, e)
	}
	if err := save(ctx, db, events); err != nil {
		return fmt.Errorf("saving events: %w", err)
	}
	if len(dead) > 0 {
		if err := client.ProduceSync(ctx, dead...).FirstErr(); err != nil {
			return fmt.Errorf("writing dead letters: %w", err)
		}
	}
	return nil
}

func run(ctx context.Context) error {
	schema, err := compileSchema()
	if err != nil {
		return fmt.Errorf("compiling schema: %w", err)
	}
	db, err := pgx.Connect(ctx, getenv("DATABASE_URL", "postgres://pulse:pulse@localhost:5432/pipeline_pulse"))
	if err != nil {
		return fmt.Errorf("connecting to postgres: %w", err)
	}
	defer db.Close(context.Background())
	if _, err := db.Exec(ctx, schemaSQL); err != nil {
		return fmt.Errorf("creating tables: %w", err)
	}

	client, err := kgo.NewClient(
		kgo.SeedBrokers(getenv("KAFKA_BROKERS", "localhost:19092")),
		kgo.ConsumerGroup(group),
		kgo.ConsumeTopics(topic),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
		kgo.DisableAutoCommit(),
		kgo.SessionTimeout(10*time.Second), // a killed consumer's partitions move on after this long
		kgo.BlockRebalanceOnPoll(),
	)
	if err != nil {
		return err
	}
	defer client.Close()

	slog.Info("consuming", "topic", topic)
	for {
		fetches := client.PollRecords(ctx, maxBatch)
		if ctx.Err() != nil {
			return nil
		}
		if err := fetches.Err(); err != nil {
			return fmt.Errorf("polling: %w", err)
		}
		records := fetches.Records()
		if len(records) > 0 {
			if err := handle(ctx, schema, db, client, records); err != nil {
				return err // restart and read these again; the primary key makes that safe
			}
			if err := client.CommitRecords(ctx, records...); err != nil {
				return fmt.Errorf("committing offsets: %w", err)
			}
		}
		client.AllowRebalance()
	}
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx); err != nil {
		slog.Error("stopping", "error", err)
		os.Exit(1)
	}
}
