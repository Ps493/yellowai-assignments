# Assignment 1: Lead Sniper (n8n)

An n8n workflow that watches a GitHub repo for new stars, looks up each stargazer, keeps only influential developers, has an LLM write a one-line sales pitch, and posts the lead to Discord.

```
Schedule / Manual
      |
   Config  ->  Check Rate Limit -> Enough Quota? --no--> Skip Run
                                        | yes
   Get Repo -> Plan Pages -> Fetch Stargazer Pages -> Pick New Stargazers
                                                              |
   Get User Profile -> Is High-Value Lead? --no--> (stop)
                              | yes (>100 followers OR >50 repos)
   Build Prompt -> Generate Sales Pitch (Gemini) -> Format Discord Message -> Send to Discord
```

## Files

| File | Purpose |
|---|---|
| `lead-sniper.workflow.json` | The workflow. Import it into n8n. |
| `LOGIC_LOG.md` | The logic, and how I handle GitHub rate limits. |
| `code-nodes/*.js` | Readable source of each Code node |
| `scripts/build-workflow.mjs` | Regenerates the workflow JSON from those sources (`npm run build`) |
| `tests/code-nodes.test.mjs` | Unit tests for the Code nodes (`npm test`) |

## Setup

1. **Import.** In n8n: Workflows > Import from File > `lead-sniper.workflow.json`.
2. **GitHub token.** Create a classic token at github.com/settings/tokens (no scopes needed for public data). In n8n add a **Header Auth** credential called `GitHub Token`: name `Authorization`, value `Bearer <token>`. Select it on the four GitHub nodes (Check Rate Limit, Get Repo, Fetch Stargazer Pages, Get User Profile).
3. **LLM.** The workflow uses Google Gemini (free key from aistudio.google.com). Create the credential and select it on **Gemini Chat Model**. To use another provider, swap that node for the matching chat-model node and connect it to **Generate Sales Pitch**.
4. **Discord.** Channel settings > Integrations > Webhooks > New Webhook > Copy URL. Paste it into `discord_webhook_url` in the **Config** node.

   > **Replace `PASTE_DISCORD_WEBHOOK_URL_HERE` with your webhook, and scrub it again before exporting or sharing the workflow.** I kept it as a plain field in Config because n8n has no credential type for a bare webhook URL; reading it from an environment variable is blocked on some n8n installs.
5. **Repo and thresholds.** Everything is in **Config** (`repo_owner`, `repo_name`, `min_followers`, `min_public_repos`, `max_per_run`, ...).
6. Run **Manual Test Run**, then activate the workflow for the 15-minute schedule.

## Design decisions and trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| Poll every 15 min instead of a GitHub webhook | Works on any public repo; a repo webhook needs admin rights on the repo | Up to 15 min of delay; uses API quota even when nothing happened |
| Fetch only the last two stargazer pages | The API is oldest-first with no `since`, so new stars are at the end. Cost stays at ~2 calls however large the repo is. | A burst of 200+ stars between polls could be missed |
| Watermark in workflow static data (`starred_at` plus logins at that second) | No external database needed; handles same-second stars | Not locked against overlapping runs; moves before delivery (see Logic Log) |
| `/rate_limit` gate before each run | Free call, one simple comparison, no wasted run | Only protects the start of a run |
| Per-run cap and request batching | Bounded cost, stays under burst limits | A backlog drains over several polls |
| Untrusted-data prompt hygiene for bios | A bio is attacker-controlled text going into an LLM | Reduces, but does not eliminate, prompt-injection risk |
| `allowed_mentions: {parse: []}` on Discord | A bio can't ping `@everyone` | None worth noting |
| Fallback pitch, flagged in the footer | A dead LLM shouldn't drop a good lead, and I should be able to see it happened | The lead goes out with a generic pitch |

## Testing

The unit tests (`npm test`) run the four Code nodes against stubbed n8n inputs and cover: stargazer page maths, the watermark (first run, repeat runs, per-run cap, same-second stars), prompt cleaning and truncation, the Discord embed (limits, missing fields, fallback pitch and its footer flag), the filter thresholds, the token cap, and that the exported JSON contains no secrets.

The unit tests do not exercise real GitHub, Gemini or Discord. I ran the full workflow in n8n myself:

- Date of live run: `____`
- Result: `____`
