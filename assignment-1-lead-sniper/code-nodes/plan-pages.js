// Node: "Plan Pages"  (mode: Run Once for All Items)
// GitHub lists stargazers oldest-first and has no "since" filter, so the newest
// stars live on the LAST page. Read the star count, work out the last page, and
// fetch it plus the one before it (a safety overlap for pages that just rolled over).

const PER_PAGE = 100;
const total = $input.first().json.stargazers_count ?? 0;
const lastPage = Math.max(1, Math.ceil(total / PER_PAGE));
const pages = lastPage > 1 ? [lastPage - 1, lastPage] : [1];

return pages.map((page) => ({ json: { page, per_page: PER_PAGE, total } }));
