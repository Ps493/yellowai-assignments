// Node: "Pick New Stargazers"  (mode: Run Once for All Items)
// Keeps only stars we have not processed yet.
//
// Watermark = the newest `starred_at` handled so far, plus the logins already handled
// AT that exact timestamp. Two people can star in the same second, so a plain ">"
// comparison could skip one of them when the per-run cap cuts between the two.
// We use ">=" and drop the logins we have already seen.
//
// - Oldest-first and capped per run, so whatever does not fit is picked up by the next poll.
// - First run (no watermark): take only the latest N stars instead of flooding the
//   channel with history. Manual test runs behave like this too, because n8n does
//   not persist static data for manual executions.
// - The watermark advances here, before delivery. A Discord failure after this point
//   loses that lead (documented in LOGIC_LOG.md).

const cfg = $('Config').first().json;
const store = $getWorkflowStaticData('global');

const stars = $input
  .all()
  .map((item) => item.json)
  .filter((s) => s && s.user && s.user.login && s.starred_at)
  .sort((a, b) => (a.starred_at < b.starred_at ? -1 : a.starred_at > b.starred_at ? 1 : 0));

const mark = store.lastStarredAt;
const seen = new Set(store.seenAtMark ?? []);

const fresh = mark
  ? stars.filter(
      (s) => s.starred_at > mark || (s.starred_at === mark && !seen.has(s.user.login)),
    )
  : stars.slice(-Number(cfg.first_run_lookback));

if (fresh.length === 0) return [];

const batch = fresh.slice(0, Number(cfg.max_per_run));
const newMark = batch[batch.length - 1].starred_at;

// Logins handled at the new mark. If the mark did not move, keep the old ones too.
const atMark = batch.filter((s) => s.starred_at === newMark).map((s) => s.user.login);
store.seenAtMark = newMark === mark ? [...seen, ...atMark] : atMark;
store.lastStarredAt = newMark;

return batch.map((s) => ({
  json: {
    login: s.user.login,
    starred_at: s.starred_at,
    repo: `${cfg.repo_owner}/${cfg.repo_name}`,
  },
}));
