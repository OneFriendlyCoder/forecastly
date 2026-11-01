# Agent

The Deal Risk Agent turns a score into plain advice. It says why a deal looks at risk, using real data, and suggests one next step from a sales playbook. The dashboard shows it through the "Explain this deal" button, and other AI agents can reach the same tools over MCP.

## How a request flows

1. `POST /explain/{deal_id}` loads the deal. If the score hasn't changed since the last answer, the saved answer is returned.
2. The model gets the deal's facts and can call two tools: `get_recent_events` and `search_playbook`.
3. It replies in a fixed JSON format, naming the feature behind each reason and the playbook section behind the next step.
4. The fact guard checks the reply. A failed check sends the problems back for one retry.
5. If it still fails, or the LLM can't be reached, code builds a plain facts answer that can't contain invented claims.

## Live progress

The dashboard uses `POST /explain/{deal_id}/stream`, which sends one JSON object per line: progress steps, then the final result or an error. `POST /explain/{deal_id}` stays as plain JSON for the evaluation script.

Only steps are streamed, never the answer's words. The fact guard runs on the finished answer, so streaming the text would show unchecked claims. If the reader leaves, the agent still finishes and saves a grounded answer.

## Files

| File | Purpose |
|---|---|
| `agent/llm.py` | The provider layer, with retries for rate limits and failures |
| `agent/tools.py` | Read-only tools, shared by the agent and MCP |
| `agent/agent.py` | The agent loop and the fact guard |
| `agent/server.py` | The HTTP route, the cache and the MCP server, on port 8090 |
| `agent/index_playbook.py` | Splits and embeds the playbook into Postgres |
| `agent/playbook/` | 10 short guides, split into 30 sections |
| `agent/evaluate.py` | The 50-case evaluation |

## Provider

The agent writes with Claude Haiku 5.5 (`claude-haiku-5-5`) at low effort, through the Anthropic SDK. Playbook search still uses NVIDIA's `nvidia/nemotron-3-embed-1b`, as Claude has no embeddings API, so both keys are needed. Setting `LLM_MODEL` to another Claude model, or to an OpenAI-compatible one such as `minimaxai/minimax-m3.1-flash`, changes the writer with no code change. Another embedding size needs a schema change.

The keys live in `.env`, which is ignored by git and Docker builds. Without a key, the stack still runs and the agent returns plain facts. `make up` indexes the playbook when a key is present.

Only sample and simulated deal data and the playbook are sent to Anthropic and NVIDIA. Real customer data would need a review first.

## Fact guard

An answer is rejected if:

- A number in its text isn't in the data the agent saw. Rounded values and the win percentage are allowed.
- A reason names a feature the deal doesn't have.
- The next step cites a playbook section that search didn't return.
- It claims a cause, using words like "because" or "due to".
- It has fewer than 2 reasons, or is missing a summary or next step.

**What the guard can't check:** numbers written as words, and whether a sentence describes a fact fairly. It checks that "7" is a real value, not that it's attached to the right claim. The prompt also bans calendar dates because they can't be checked.

## MCP tools

An MCP client can connect to `http://localhost:8090/mcp`. The tools are `list_at_risk_deals`, `get_deal`, `get_recent_events`, `search_playbook` and `explain_deal`.

## Tests

- `make test` runs `agent/test_agent.py` with a fake model, so it needs no key. It covers the guard, retries, fallbacks, the step limit and rate-limit handling.
- `make test-agent` uses the real model and stack. It checks a grounded answer, the cache, error codes, playbook search and an MCP client.
- `make eval-agent` scores 50 open deals across the risk range and writes `data/agent_eval_results.json`.

The evaluation scores three things. **Groundedness:** the answer passed the guard. **Relevance:** it cited at least 2 of the deal's top 3 factors. **Actionability:** it has a cited next step of at least 6 words.

These are simple checks. Relevance can't judge the quality of the wording, and groundedness only covers what the guard can check.

## Results

This run covered 50 deals with the real model. Full answers are in `data/agent_eval_results.json`.

| Measure | Result |
|---|---|
| Groundedness | 43 of 50 |
| Relevance | 43 of 50 |
| Actionability | 43 of 50 |
| Answers rejected by the guard | 0 |
| Requests that timed out at 10 minutes | 7 of 50 |
| Median response time, of the 43 that finished | 3.1 minutes |
| Slowest response that finished | 8.2 minutes |

All 7 failures were timeouts, not bad answers. Every answer that came back passed all three checks with no retry. Each took 2 LLM calls.

**Speed depends on the model.** With Claude Haiku 5.5, a 20-deal sample took 6.4 seconds at p50 and 9.8 seconds at p95, with 2.35 LLM calls an answer. The same agent on NVIDIA's free tier took 2 to 5 minutes. All 20 answers passed the fact guard, and 25% needed a rewrite, mostly for cause words. The prompt and guard were tuned on the NVIDIA model.

**The results predate the 5-minute limit.** Only 34 of these 50 answers finished inside 5 minutes, so at the same speed the other 16 would now show plain facts. The live test after the change gave a grounded answer in 3.5 minutes.

**Advice is repetitive.** 33 of the 43 next steps came from just two playbook sections, so the checks don't show that the advice is varied or well matched.

**These 50-case results predate the search fix.** Search was finding the right guide for only 4 of 10 known questions at the time, so they don't describe the current agent. A later 5-deal sample gave 3 grounded answers, 1 plain facts answer, and 1 failure from restarting the agent during the run. Answers took about 3 to 5 minutes. All 3 grounded answers used the same playbook section, which is too small a sample to judge variety.

## Limits

- **Slow:** answers took from under a minute to about 8 minutes, which is why it's a button and answers are saved. After 5 minutes, the agent stops and shows plain facts.
- **Late events:** saved answers are tied to the deal's latest event time, so a late event can change the score and still reuse the old answer.
- **Rate limits:** the agent retries, but heavy use would still slow it down.
- **Prompt injection:** deal data is passed to the model. The agent can only read and its tools can't change anything, but real CRM text would need more care.
- **No login:** the port is bound to this machine only.
- **Reasons aren't causes:** the answers describe what moved the model, and the rep has to judge the real problem.

## Differences from the project plan

- **Shorter playbook:** 10 short guides, instead of 10-15 pages.
- **No cost tracking:** only response time and LLM calls are tracked, though Claude calls now cost money. Tokens used per answer haven't been measured.
- **Evaluation cases are built live:** each deal's own top factors are the expected reasons, instead of a hand-written set.
