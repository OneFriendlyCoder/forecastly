# Dashboard

`web/` is a small React and TypeScript app. It shows which open deals are at risk and why. It starts with `make up` at `http://localhost:3000`.

## Pages

- **At-risk deals (`#/`):** open deals, riskiest first, with win chance, risk level and top reason. Clicking a row opens the deal.
- **Deal page (`#/deals/{id}`):** the current win chance, the top 3 reasons, an "Explain this deal" button for open deals (see [agent.md](agent.md)), a chart of the score over time, and activity counts. The chart has a table view for anyone who can't read it visually.

## How it works

- **Data:** the pages call the [API](api.md) and refresh every 5 seconds, so scores change on screen during a replay. If a refresh fails, the last data stays visible beside a warning.
- **Reasons:** `src/format.ts` turns model features into plain sentences. They're labelled "What moved this score", because they explain the model and not the deal's actual problem.
- **Risk levels:** under 40% is high, under 60% is medium, and anything else is lower. These cut-offs are simple guesses.
- **Running it:** Docker builds the site and serves it with nginx, which passes `/api/` requests to the API. For development, run `npm run dev` in `web/`, with the API running.

Run `npm ci` in `web/` and `npx playwright install chromium` before running the tests.

## Tests

- `make test` runs the unit tests for wording, formatting and risk cut-offs.
- `make test-dashboard` wipes local data, fills the real stack, and drives a browser with Playwright.

The browser tests click from the at-risk list into a deal and compare its score with the API. They also cover hovering on the chart, unknown deals, malformed addresses, loading, empty lists, and the API being down, both on first load and after data has appeared.

## Limits

- **No login, filters or search.** The list shows the 50 riskiest deals.
- **Refresh, not push:** the plan's live updates (SSE) are left out, so changes can take up to 5 seconds to appear.
- **Dates are event dates:** "Scored as of" shows the time of the deal's latest event, which is in 2017 for replayed data.
- **Large bundle:** the chart library takes the JavaScript over Vite's 500 kB warning. That doesn't matter for a local demo.
