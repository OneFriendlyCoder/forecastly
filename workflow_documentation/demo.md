# Live Demo

This replays the saved deal history into the running system, so an audience can watch events become scores and explanations. The data is simulated, and the demo should say so.

## Before you start

- Docker is running, and `.env` has `ANTHROPIC_API_KEY` and `NVIDIA_API_KEY`.
- `make demo-setup` wipes local data, so don't run it if you need what's there.
- Each new demo needs `make demo-setup` first. A second replay changes nothing, as repeated events are ignored.

## Run it

```bash
make demo-setup            # about 30 seconds, then the dashboard is empty
# open http://localhost:3000
make demo                  # about 4 minutes
```

To include bad data, run `make demo FAULTS=--faults` instead. It adds duplicate, late and broken messages. To change the pace, use `make demo DEMO_SPEED=1`, where the number is real seconds per simulated day. Speeds well under 0.5 risk a backlog on a laptop.

## Script

| Time | Do | Say |
|---|---|---|
| 0:00 | Show the empty dashboard, run `make demo` | Events go to Kafka, become features, then the model scores the deal |
| 1:00 | Point at the live strip and risk cards | Each event updates a deal's features, and the score lands in about a second |
| 2:00 | Click **Follow deal ALZNZ666** | This deal's chart starts around now |
| 2:00 to 3:45 | Watch the chart | Its win chance peaks at 91%, then falls to 35% as activity turns bad |
| After 3:45 | Click **Explain this deal** | The agent reads events, searches the playbook, and every number is fact checked |

The first minute is quiet, as the history starts with few deals.

## Show that it survives failure

Run this in a second terminal during the replay:

```bash
docker stop pipeline-pulse-deal-state-1     # the strip changes to "Waiting for events"
make demo-check                             # shows events waiting in Kafka
docker start pipeline-pulse-deal-state-1    # it catches up by itself
```

Event-to-score time rises while it catches up, which is expected. When the replay ends and nothing is waiting, `make demo-check` shows 439,821 events stored, even with faults on. With faults on, it also shows 433 rejected.
