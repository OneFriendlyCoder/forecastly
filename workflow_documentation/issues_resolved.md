# Pipeline Pulse: Issues Resolved

This records what went wrong during the build, how it was found and how it was fixed. Add new issues here as they come up.

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

## Features and model

| Problem | How it was found | Fix |
|---|---|---|
| `account_id` is missing on 68% of open deals but never on finished ones, so a model would meet a gap it never saw in training | Profiling fields before choosing features | Leave account fields out |
| A deal's rows are nearly identical, so a row-level split would inflate test scores | Reviewing the split design | Split by deal, and test that no deal is on both sides |
| LightGBM didn't beat the logistic regression baseline (0.639 vs 0.641 over 5 splits) | Repeating the comparison after a tie on one split | Accepted and documented. We kept LightGBM for the reasons in [model.md](model.md) |

## Live scoring

| Problem | How it was found | Fix |
|---|---|---|
| The model needs product and amount, but events don't carry them | Comparing the model's inputs with the event format | Add a `deals` table, filled by `make up` |
| Scored time can't be the real clock, because replayed events are from 2016-2017 and every deal would look years silent | Reviewing the design | Use the time of the deal's latest event as "now" |
| A deal's last score before closing depends on how events were batched, so closed deals can't be compared between runs | Reviewing the fault test design | Compare final scores on open deals only |
| Load test deal copies have new IDs, so they weren't in the `deals` table and wouldn't be scored | Reading the load test before changing it | Seed matching copies for those runs |
| `rpk` reports no lag before a consumer's first commit, the same trap as before | Known from the pipeline issue above | Read committed offsets directly, and compare them with Kafka |
| Calculating features cut top throughput from 11,888 to 7,597 events/s with one consumer | The load test | Accepted. It's about 27 times the target rate, and one update per deal per batch limits the cost |

## API and dashboard

| Problem | How it was found | Fix |
|---|---|---|
| The chart's date axis repeated "Aug 2017", because Recharts ignores the tick count on time axes | Looking at a screenshot. The tests passed | Set evenly spaced ticks by hand, and show the day |
| A malformed address like `#/deals/%` would crash the page into a blank screen | Reviewing the address handling | Catch the bad address, and let the page say the deal wasn't found |
| Vitest tried to run the Playwright browser tests | The first test run | Limit Vitest to `src` |
| Rerunning tests appeared to confirm the fixes, but a typo had stopped the fix script | The run showed 5 tests when 7 were expected | Apply the fixes again and rerun |

## Agent

| Problem | How it was found | Fix |
|---|---|---|
| NVIDIA's docs didn't confirm tool calling, and sources disagreed on the free MiniMax model | Searching before building | Test the real key first. `minimaxai/minimax-m3.1-flash` is available and tool calling works |
| Three of the four embedding models tried returned 404 on this key | Testing each one | Use `nvidia/nemotron-3-embed-1b`, the one that responded |
| The embeddings have 2,048 dimensions, above pgvector's 2,000 index limit | Reading the model's output size | Scan without an index, which is instant for 30 sections |
| MCP version 2 renamed `FastMCP` to `MCPServer` | Inspecting the installed library before writing code | Write against the new name |
| The fact guard accepted an invented "12 negative replies", because 12 appeared inside the date `2017-12-05` | A unit test with a fake model | Count only real data values, not digits inside dates or IDs. The agent is told not to quote calendar dates |
| Empty model content crashed the answer parser | A unit test with a fake model | Treat empty content as an invalid answer, which triggers the normal retry |
| The first live answer quoted no numbers, needed a retry, and took 75 seconds | Reading the real output after the test passed | Require each reason to quote its value, and record what the guard rejects |
| Nearly every first answer failed as invalid JSON, and one in six fell back to plain facts, at about 2 minutes each | Recording rejections, then reading raw replies. The model spent all 1,500 reply tokens on thinking (`finish_reason: length`) | Treat the cause: send only useful event fields, cap events at 10, and drop duplicated features. Raise the limit to 3,000 tokens and the timeout to 150 seconds |
| The agent returned a 500 and stopped the evaluation at case 9, when NVIDIA dropped a connection | The 50-case run crashed. The logs showed `RemoteDisconnected`, which the retry code didn't catch | Retry every network failure, turn odd replies into a normal LLM error, and report broken tools to the model. The evaluation now counts a failed request as a failed case |
| 7 of 50 evaluation cases passed the 10-minute limit. One slow call could take four attempts of 150 seconds each, and an abandoned request kept running in the background | The evaluation, then timing rejected requests with it stopped. They still took 95 seconds to 15 minutes, which points to provider queueing | Add a 5-minute limit across a whole explanation. After that, the work stops and the reader gets plain facts. Provider speed itself is still outside our control |
| The saved evaluation counted timed-out cases as 0-second responses, which made the speed look better than it was | Checking the summary against the raw cases | Exclude failed requests from timing and call counts |
| A live test failed at the first 4-minute limit, even though the limit worked | The final test run. 31 of 50 evaluation answers fit in 4 minutes, and 34 fit in 5 | Raise the limit to 5 minutes. It's a trade-off: a shorter wait, but more plain facts answers when the provider is slow |

## Open issues

These are known and not fixed yet:

- An open explanation can stay on screen after the score changes.
- A late event can change a score and still reuse the saved explanation.
- 33 of 43 next steps came from just two playbook sections.

## Lessons

The two false "backlog is 0" results taught the same thing: a monitoring number can be wrong while the system is fine. Both only surfaced because the tests compared the final data, not just the status number.

Passing tests aren't the end of a check either. The repeated chart dates and the vague agent answer both passed every test and only showed up when a person looked at the real output.
