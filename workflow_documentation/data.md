# Pipeline Pulse: Data

This document explains what data the project uses, what that data can and can't tell us, the assumptions we made, and what the simulator will add.

Status: data setup is finished and all table checks pass. The simulator is not built yet.

## Summary

- We use two sources: **Maven** (fictional sales deals) and **Enron** (real email timing).
- For each deal, Maven tells us who sold what to whom, when serious talks began, when the deal ended, and how it ended. It doesn't tell us what happened in between.
- Real data alone barely predicts whether a deal will be won, so the simulator will do most of the work.
- The simulator can show that the system works. It can't prove that its signals predict real sales, because we put those signals there ourselves.

## Which datasets we use

| Dataset | Used for | Status |
|---|---|---|
| Maven CRM Sales Opportunities | Deals, customers, reps, products, outcomes | Kept: the core of the project |
| Enron email corpus | Email timing only | Kept: only as saved summary numbers |
| Olist Marketing Funnel | Was planned as a second test set | Removed |

Salesforce, HubSpot and the Outreach portal are in the project plan too, but they are systems to connect to, not datasets. Salesforce will hold the same Maven deals and adds no new data.

### Why Olist was removed

Olist has leads and won deals, but no lost deals or close dates, and only 45 of its 842 deals show revenue. It could only test lead conversion, which isn't what this project predicts.

The cost is that Olist was the plan's answer to Maven being fictional. The pitch can no longer say the model was tested on real deals, and it should say plainly that the deals are sample data.

## Where the data lives

```text
data/
  raw/                 # original downloads, never edited, not in Git
    maven/
    enron/
  processed/           # cleaned tables, rebuilt from raw, not in Git
    deals.parquet
    accounts.parquet
    reps.parquet
    products.parquet
    enron_threads.parquet
  MANIFEST.json        # where each file came from, with its checksum
ml/data/
  download.py          # fetches the raw data
  build_tables.py      # cleans it into the tables above
  fit_distributions.py # saves real-data numbers for the simulator
  test_tables.py       # checks the tables are correct
ml/simulator/
  distributions.json   # the saved numbers
```

To rebuild everything, run from the repo root:

```bash
python3 ml/data/download.py
python3 ml/data/build_tables.py
python3 ml/data/fit_distributions.py
python3 ml/data/test_tables.py
```

The Enron download is 443 MB and took about 15 minutes.

## Maven: the four tables

Imagine a company selling 7 computer products to 85 business customers. Each row in the deals table is one attempt to make a sale.

### Deals (8,800 rows)

| Field | Meaning |
|---|---|
| `deal_id` | Unique code, such as `1C1I7A6R` (no duplicates) |
| `source` | Always `maven` |
| `account_id` | The customer (replaces the original name) |
| `owner_id` | The rep (replaces the original name) |
| `product` | What was being sold |
| `amount` | The product's list price (added by us) |
| `stage` | Where the deal ended up |
| `engaged_at` | The day serious talks began |
| `closed_at` | The day it was won or lost |
| `outcome` | Won, lost, or blank if unfinished |
| `close_value` | Money actually received, used only to judge results |

| Stage | Deals | Has start date? | Has end date? | Customer known? |
|---|---|---|---|---|
| Won | 4,238 | Yes | Yes | All |
| Lost | 2,473 | Yes | Yes | All |
| Engaging (in talks) | 1,589 | Yes | No | 501 of them |
| Prospecting (not started) | 500 | No | No | 163 of them |

Of the 6,711 finished deals, 63.2% were won.

### Accounts (85 customers)

- **Fields:** name, industry, year founded, yearly revenue in millions of dollars, employees, headquarters country, and parent company if any.
- **Size:** typically about $1.2 billion revenue and 2,800 employees, ranging from 9 to 34,288 staff.
- **Location:** 71 are in the US, and the rest are spread across 14 other countries.
- **Industries:** 10 in total, with retail the largest (17 customers) and employment the smallest (4).
- **Other:** 15 are subsidiaries. Finished deals per customer range from 38 to 193, with a typical customer around 75.

### Reps (30 people)

- **Structure:** 3 regional offices (Central, East, West), with 2 managers each and 5 reps per manager.
- **Deal volume:** each rep has 110-747 deals, typically about 278.
- **Win rate:** reps range from 55% to 70%. Regions (63-64%) and managers (62-64%) are almost identical.

### Products (7)

| Product | List price | Deals | Win rate |
|---|---|---|---|
| MG Special | $55 | 1,651 | 65% |
| GTX Basic | $550 | 1,866 | 64% |
| GTX Plus Basic | $1,096 | 1,383 | 62% |
| MG Advanced | $3,393 | 1,412 | 60% |
| GTX Pro | $4,821 | 1,480 | 64% |
| GTX Plus Pro | $5,482 | 968 | 64% |
| GTK 500 | $26,768 | 40 | 60% |

## What the deals tell us

- **Timeline:** talks began from October 2016 to December 2017. All closes fall between March and December 2017.
- **Revenue:** won deals brought in about $10 million in total, typically $1,117 each and $30,288 at most. GTX Pro earned the most, about $3.5 million.
- **Prices:** won deals typically closed near list price, usually between 87% and 112% of it.
- **Deal length:** 1-138 days. Deals either end fast (under 2 weeks) or take 2-3 months, with few in between. 42% of finished deals end within 14 days.
- **Won vs lost length:** the median is 57 days for won deals and 14 for lost deals.
- **Time and winning:** deals ending within 7 days win 53.5% of the time, and those ending after 90 days win 71%. This is the strongest real pattern, and it only shows up once a deal has ended.
- **Deal value:** won and lost deals have nearly the same list prices, so price doesn't help predict the result.
- **Prediction power:** nothing we know at the start of a deal changes the odds much.

## Quirks

- **It's clearly fictional:** deals close evenly across all 7 days, including weekends. Real sales data wouldn't look like that.
- **The open deals look stale:** the longest finished deal took 138 days, yet at least 75% of Engaging deals have been open longer than that (median 165 days). They look abandoned rather than active.
- **Older deals look better:** deals started in late 2016 won 82%, against about 60% later. This is partly because no deal closes before March 2017, so quick, often-lost deals from that period are probably missing. A train/test split by date needs to allow for this.
- **Few periods to judge a forecast:** closes cover only 10 months, so forecast accuracy rests on very few quarters. Report it quarter by quarter, as an early indication and not proof.

## Issues and the assumptions that resolve them

| # | Issue | Assumption or fix |
|---|---|---|
| 1 | There is no first-contact date | Treat `engaged_at` as the deal's real start. Anything earlier is simulated |
| 2 | There are no middle steps: every finished deal goes from talks straight to won or lost | Middle steps are simulated and never presented as real history |
| 3 | The usual stage-based comparison gives every finished deal the same 63%, so it's too easy to beat | Compare against win rate by stage and days the deal has been open, using real data only |
| 4 | Every lost deal has `close_value` = 0, which would hand the model the answer | Use list price as `amount`. Keep `close_value` only for judging results and revenue |
| 5 | Nothing shows a close date being pushed back | The simulator creates expected close dates and delays, so delay prediction shows only that the system works |
| 6 | 2,089 deals have no ending, and 1,425 have no customer | Train on the 6,711 finished deals. Use the 1,589 Engaging deals as live demo deals and leave out Prospecting |
| 7 | Small errors in the data | Fixed `GTXPro` to `GTX Pro` and `technolgy` to `technology`, and dropped 5 reps with no deals. `Philipines` is still misspelled, which does no harm |

## Enron: real email timing

Enron is kept only to make the simulated email timing more realistic. Without it, both the deals' behaviour and its timing would be our guesses. It lets us say "email timing is based on real data" and gives the realism check something real to compare against.

It doesn't teach the model anything directly, and its emails never become deal events. The simulator only reads summary numbers from `ml/simulator/distributions.json`.

- **What we kept:** 243,618 unique emails from 1998-2002, after removing copies of the same email saved in several folders. Each row has only the send time, a scrambled thread code, and reply information.
- **Privacy:** these are real people's emails, so no message text or email addresses are stored in our tables.
- **Reply speed:** 23,951 replies were matched to earlier emails. The typical reply took 1.75 hours, a quarter took over 16 hours, and a tenth took over 67 hours.
- **Threads:** most emails have no follow-up, and only 10% of threads reach 3 or more emails.
- **Days:** about 96% of emails were sent Monday to Friday.

### Enron's limits

- The hour of day looks shifted: email peaks around 6-9am and falls off by 4pm.
- These are coworker emails from about 25 years ago, so buyers probably reply more slowly.
- Replies were matched by subject line, sender and recipient, so some matches may be wrong.
- Reply speed also depends on deal health in the simulator, so Enron is a starting point that we adjust from.

## What the simulator will create

**The goal:** give each deal a believable activity history, so the model can learn from behaviour instead of from data that barely predicts anything.

**Kept real:** deal, customer, rep, product, start date, end date and outcome. The simulator never changes these.

**Added:**

- **People:** 1-6 buyers per deal, such as a champion or a budget holder, plus a skill level and habits for each rep.
- **Actions:** emails, opens, clicks, replies, calls, meetings, no-shows and new contacts, each dated.
- **Expected close dates:** a target date for each deal, and any delays to it.
- **A hidden health score:** rises or falls daily toward the real outcome and drives the activity. Healthy deals get quicker replies and more people involved, while failing ones go quiet and slip.
- **Deliberate messiness:** about 15% of deals break the usual patterns, so the model can't simply memorise our rules.

### What needs to be built

1. Settings file: seed, noise level and pattern strengths.
2. People: buyer contacts for each deal, and rep skill and habits.
3. Hidden health score: a daily score for each deal.
4. Event generator: turns health into activity, and handles very short deals sensibly.
5. Pre-engage activity: made-up first contacts before `engaged_at`.
6. Expected close dates and delays.
7. Won and lost patterns, including the deals that break them.
8. Realistic timing: reply delays and weekdays from Enron.
9. Open deals: activity for the 1,589 Engaging deals, with no ending.
10. Output and checks: a batch file, a live stream, and a validation report.

### What the final data will look like

- **`events.parquet`:** the main output, with one row per action. It will probably have 100,000+ rows, which is a rough guess.
- **`contacts.parquet`:** the generated buyers for each deal.
- **`health_paths.parquet`:** the hidden score, kept for debugging and never shown to the model.
- **`training_snapshots.parquet`:** one row per deal per checkpoint, holding only what was known that day, plus the eventual result. Checkpoints use days since engagement, because "75% through its life" would reveal when the deal ends.

An example timeline for one deal:

```text
deal_id   occurred_at        event_type      details
1C1I7A6R  2016-10-12 10:14   email_sent      to champion
1C1I7A6R  2016-10-13 09:02   email_replied   delay 22.8h, positive
1C1I7A6R  2016-10-20 00:00   stage_changed   Prospecting -> Engaging (real date)
1C1I7A6R  2017-02-08 15:30   meeting_held    pricing, economic buyer present
1C1I7A6R  2017-03-01 00:00   deal_closed     won, 1054 (real result)
```

The rows marked real and the `deal_closed` row come from the data. The others are made-up examples.

### How we'll judge it

Win rate and deal length will match the real data automatically, because the simulator copies real dates and outcomes. So the "matches real data within 5%" check proves little. These checks matter more:

- **Leakage check:** if a model scores near-perfectly on early events only, the patterns are too strong.
- **Real vs simulated comparison:** report results with real data only, and with simulated activity added.

## The biggest risk

Most of the activity data is invented by us. If the model does well on it, it may just be rediscovering our own rules. That's why we report both results above, and why the results must say which data is real.

## Decisions

- Use the fairer comparison in issue 3, and keep simulated middle steps out of it.
- Drop Olist, and use Enron only through its saved numbers.
- **Open deals in the demo:** treat them as active, simulate activity up to 31 December 2017, and say so openly.
- **Early-warning target:** the plan asks to flag 60% of lost deals 14+ days before close, but about half of lost deals last 14 days or less. We measure only lost deals that last more than 14 days.
- **Email hours:** use Enron's weekday pattern and assume normal working hours.
