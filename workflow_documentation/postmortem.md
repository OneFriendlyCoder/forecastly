# Pipeline Pulse: Postmortem Log

This records what went wrong during the build, how it was found and how it was fixed.

## Data

| Problem | How it was found | Fix |
|---|---|---|
| Every lost deal had `close_value` = 0, which would reveal the outcome | Profiling Maven | Use list price as `amount`, and keep `close_value` for judging results only |
| The stage-weighted baseline gives every finished deal the same 63% | Profiling Maven | Use win rate by stage and days open |
| Enron looked too big, at 495,098 emails | The count seemed high for the corpus | `Message-ID` differs between folder copies, so copies are matched on content. That left 243,618 |
| Enron's hour of day looks shifted | Mail peaked around 6-9am | Use its weekday pattern, and assume working hours |

## Simulator

| Problem | How it was found | Fix |
|---|---|---|
| Emails within a day had their steps out of order | Reading a sample timeline by eye | Sort a day's send times before numbering them |
| Same-second events from one deal could be reordered in the file | Reviewing the sort while building replay | Use a stable sort on time only |
| Close-date pushes run backwards: won deals get more | Comparing averages by outcome | Accepted, because it's a realism issue. See [simulator.md](simulator.md) |

## Infrastructure

| Problem | How it was found | Fix |
|---|---|---|
| `make check` left a test message in `activity.events`, which the service would have read as real | Reviewing the check after it passed | Use a temporary topic |
| The Docker build failed, because a dependency needs Go 1.26 | The image build error | Use the Go 1.26 image |

## Pipeline

| Problem | How it was found | Fix |
|---|---|---|
| The latest event could depend on arrival order when timestamps tied | Reviewing the code while adding late events | Use `event_id` to break ties |
| After a kill, the restarted service sat idle for up to 45 seconds | The kill test | Set the consumer session timeout to 10 seconds |
| Kafka reports a backlog of 0 during a rebalance | The kill test appeared to finish with data missing | Trust the number only when the group is stable |
| Kafka also reports 0 before a consumer's first commit | The load test stopped with 22,782 of 1,319,463 events stored | Measure backlog as messages in Kafka minus events in Postgres |

## Lesson

The two false "backlog is 0" results taught the same thing: a monitoring number can be wrong while the system is fine. Both only surfaced because the tests compared the final data, not just the status number.
