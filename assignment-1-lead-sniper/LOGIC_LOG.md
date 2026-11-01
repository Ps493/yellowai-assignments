# Logic Log: Lead Sniper

## How the workflow decides

1. **Trigger.** A Schedule Trigger polls every 15 minutes. A Manual Trigger feeds the same path for testing.
2. **Find new stars.** GitHub lists stargazers oldest-first and has no `since` filter, so the newest stars are on the *last* page. The workflow reads `stargazers_count` from the repo, works out the last page, and fetches that page plus the one before it. Asking for the `star+json` media type adds `starred_at` to every entry.
3. **De-duplicate.** A watermark lives in workflow static data: the newest `starred_at` handled so far, plus the logins already handled at exactly that timestamp (two people can star in the same second). Only newer stars continue. Stars go oldest-first and are capped at `max_per_run` (25); the watermark only advances to the last star actually taken, so any overflow is picked up by the next poll.
4. **Enrich.** `GET /users/{login}` for each new star.
5. **Filter.** `followers > 100 OR public_repos > 50` continues; everything else stops (the IF node's false output is deliberately unconnected). Missing values count as 0.
6. **AI pitch.** An LLM chain receives the user's bio, company, followers and repo count and returns one sentence.
7. **Output.** A Discord embed with name, bio, company, location, stats and the pitch.

## Rate limits

GitHub allows **60 requests/hour unauthenticated** and **5,000/hour with a token**, so the first decision was to authenticate every GitHub call. On top of that:

| Layer | What I did | Why |
|---|---|---|
| Pre-flight gate | `GET /rate_limit` at the start of each run (this endpoint does not count against the quota). If `resources.core.remaining` is below `min_quota_remaining` (50), the run is skipped. | Don't start a run I can't finish. A skipped run does not move the watermark, so the next poll catches up. |
| Request budget | At most 2 stargazer pages and 25 profiles per run, so a normal run is about 30 calls. | The worst case is bounded: 4 runs an hour x ~30 calls is ~120 of the 5,000 allowed. |
| Throttling | Profile lookups use the HTTP node's batching: 5 requests per 1,000 ms. Discord posts go 1 per 1,000 ms. | GitHub also has secondary (burst) limits, and Discord webhooks allow roughly 5 posts per 2 s. |
| Retries | Retry On Fail on GitHub calls: 3 tries, a fixed 2 s pause. | Covers short blips and transient 5xx errors. |

**What the retries do not do.** n8n's retry waits a fixed time, so it does *not* honour GitHub's `retry-after` header. If GitHub answers a secondary-limit 403 or 429 with `retry-after: 60`, my 2 s retries will most likely fail again. That run's items then fail, and the next 15-minute poll picks up the work because the watermark only moves for stars that were actually taken.

**Which headers matter.** GitHub reports the real state in `x-ratelimit-remaining`, `x-ratelimit-reset` (epoch seconds when the window resets) and, on a limit hit, `retry-after`. I chose the `/rate_limit` gate over reading those headers off each response because it gives the same numbers in one free call, up front, and it is a plain number comparison in an IF node. Reading headers on every response would mean turning on "include response headers" and adding code to branch on them. The trade-off is that the gate only protects the start of a run; a run can still hit a limit halfway through.

## Other decisions

- **Prompt injection.** A GitHub bio is written by a stranger and goes into an LLM. The prompt flattens it to one line, cuts it at 400 characters, labels it untrusted, and the system prompt tells the model never to follow it.
- **Discord mentions.** The same bio is posted into a channel, so the payload sets `allowed_mentions: {parse: []}`. A bio containing `@everyone` pings nobody.
- **Empty or failed LLM output.** If the model call fails or returns nothing, the lead is still delivered with a generic pitch, and the embed footer says `(auto-fallback pitch)` so I can tell. I set the Gemini output cap to 1024 tokens because Gemini 2.5 models spend part of the cap on internal "thinking"; a small cap such as 120 can leave the visible answer empty.
- **Missing profiles.** If a profile lookup fails (for example a deleted account), that item is skipped instead of failing the whole batch.
- **First run.** With no watermark only the latest 10 stars are processed, so the channel isn't flooded with history. n8n does not keep static data for *manual* executions, so a manual run always behaves like a first run.

## Known limits

- **Delivery is at-most-once.** The watermark advances in the "Pick New Stargazers" step, before enrichment and before Discord. If Discord is down after that point, those leads are lost rather than retried. Fixing it properly means moving the watermark update to after delivery, or keeping a queue.
- **Same-second stars.** The watermark keeps the logins seen at the newest timestamp, so two stars with an identical `starred_at` are not skipped at the per-run cap boundary. That case is covered by a unit test.
- **Bursts.** If a repo gains more than about 200 stars between two polls, the oldest of the burst can fall outside the two pages fetched. Shorten the interval for a very busy repo.
- **Very deep pages.** The last-page calculation is unit-tested, but I have not confirmed GitHub's behaviour on the very deep stargazer pages of a huge repository.
- **Overlapping runs.** Static data is not locked. If a run took longer than 15 minutes, two runs could overlap and a lead could be posted twice.
- Static data only persists for *active* workflows.
