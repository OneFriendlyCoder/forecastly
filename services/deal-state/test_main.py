"""Run with: python3 services/deal-state/test_main.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from main import APPLY_EVENT, EVENT_TYPES, load_validator, parse_event

VALID = ('{"event_id":"6f1d2b52-3f58-4c0e-9d3b-0d6c1f6c7a10","event_type":"stage_changed",'
         '"occurred_at":"2017-03-14T10:22:05Z","tenant_id":"demo","deal_id":"opp_1","account_id":null,'
         '"actor":{"kind":"system","id":"crm"},"payload":{"from":"Prospecting","to":"Engaging"},"schema_version":1}')
CLOSED = VALID.replace("stage_changed", "deal_closed").replace('"from":"Prospecting","to":"Engaging"', '"outcome":"won","amount":10')


def check_parse_event():
    validator = load_validator()
    event, occurred_at = parse_event(validator, VALID.encode())
    assert event["deal_id"] == "opp_1" and occurred_at.isoformat() == "2017-03-14T10:22:05+00:00"
    bad = {
        "not json": "{oops",
        "empty": "",
        "not an object": "[1]",
        "unknown type": VALID.replace("stage_changed", "stage_jumped"),
        "bad uuid": VALID.replace("6f1d2b52-3f58", "nope"),
        "bad date": VALID.replace("2017-03-14", "2017-13-45"),
        "wrong payload": VALID.replace('"from":"Prospecting",', ""),
        "new version": VALID.replace('"schema_version":1', '"schema_version":2'),
        "nul character": VALID.replace("demo", "de\\u0000mo"),
        "broken text": VALID.replace("demo", "de\\ud800mo"),
        "huge number": CLOSED.replace('"amount":10', '"amount":1e999'),
        "infinity": CLOSED.replace('"amount":10', '"amount":Infinity'),
    }
    for name, value in bad.items():
        try:
            parse_event(validator, value.encode())
        except ValueError:
            continue
        raise AssertionError(f"{name}: expected rejection")
    try:
        parse_event(validator, b"\xff\xfe")
    except ValueError:
        return
    raise AssertionError("bad UTF-8: expected rejection")


def check_every_event_type_has_a_query():
    schema = json.loads((Path(__file__).parents[2] / "schemas/event.v1.json").read_text())
    assert set(APPLY_EVENT) == set(EVENT_TYPES) == set(schema["properties"]["event_type"]["enum"])


if __name__ == "__main__":
    check_parse_event()
    check_every_event_type_has_a_query()
    print("all deal-state checks passed")
