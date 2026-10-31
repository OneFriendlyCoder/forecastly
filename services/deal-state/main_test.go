package main

import (
	"strings"
	"testing"
)

const validEvent = `{"event_id":"6f1d2b52-3f58-4c0e-9d3b-0d6c1f6c7a10","event_type":"stage_changed",
"occurred_at":"2017-03-14T10:22:05Z","tenant_id":"demo","deal_id":"opp_1","account_id":null,
"actor":{"kind":"system","id":"crm"},"payload":{"from":"Prospecting","to":"Engaging"},"schema_version":1}`

func TestParseEvent(t *testing.T) {
	schema, err := compileSchema()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := parseEvent(schema, []byte(validEvent)); err != nil {
		t.Fatalf("valid event rejected: %v", err)
	}
	bad := map[string]string{
		"not json":      `{oops`,
		"empty":         ``,
		"unknown type":  strings.Replace(validEvent, "stage_changed", "stage_jumped", 1),
		"bad uuid":      strings.Replace(validEvent, "6f1d2b52-3f58", "nope", 1),
		"bad date":      strings.Replace(validEvent, "2017-03-14", "2017-13-45", 1),
		"wrong payload": strings.Replace(validEvent, `"from":"Prospecting",`, "", 1),
		"new version":   strings.Replace(validEvent, `"schema_version":1`, `"schema_version":2`, 1),
		"nul character": strings.Replace(validEvent, "demo", `de\u0000mo`, 1),
	}
	for name, value := range bad {
		if _, err := parseEvent(schema, []byte(value)); err == nil {
			t.Errorf("%s: expected rejection", name)
		}
	}
}

func TestEveryEventTypeHasAQuery(t *testing.T) {
	if len(applyEvent) != 8 {
		t.Fatalf("got %d queries", len(applyEvent))
	}
}
