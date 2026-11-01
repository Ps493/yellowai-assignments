// Node: "Format Discord Message"  (mode: Run Once for Each Item)
// Builds the Discord embed. Runs after the LLM chain, so the profile is read back
// from "Build Prompt" and the pitch from this item's `text`.

const profile = $('Build Prompt').item.json;
const pick = $('Pick New Stargazers').item.json;

const FALLBACK_PITCH =
  'Influential open-source developer who just starred our target repo, worth a personal outreach.';

const trunc = (value, max) => {
  const s = String(value ?? '').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
};
const orDash = (value, max = 1000) => trunc(value, max) || '—';

// Single-line pitch, whatever the model returned.
const oneLine = String($json.text ?? '').replace(/\s+/g, ' ').trim();
const modelPitch = trunc(oneLine.replace(/^["'“”]+|["'“”]+$/g, '').trim(), 400);
// An empty reply (LLM error, or the token cap eaten by "thinking") must be visible
// in the channel, not silently papered over.
const usedFallback = !modelPitch;
const pitch = modelPitch || FALLBACK_PITCH;

const payload = {
  username: 'Lead Sniper',
  // Bios are user-controlled: never let them ping @everyone / roles / users.
  allowed_mentions: { parse: [] },
  embeds: [
    {
      title: trunc(`High-Value Lead: ${profile.name || profile.login}`, 250),
      url: profile.html_url,
      description: `**Why reach out:** ${pitch}`,
      color: 0xf5b700,
      thumbnail: { url: profile.avatar_url },
      fields: [
        { name: 'Bio', value: orDash(profile.bio), inline: false },
        { name: 'Company', value: orDash(profile.company, 200), inline: true },
        { name: 'Location', value: orDash(profile.location, 200), inline: true },
        { name: 'Followers', value: String(profile.followers ?? 0), inline: true },
        { name: 'Public repos', value: String(profile.public_repos ?? 0), inline: true },
        { name: 'Starred', value: pick.repo, inline: true },
      ],
      footer: { text: `@${profile.login}${usedFallback ? ' (auto-fallback pitch)' : ''}` },
      timestamp: pick.starred_at,
    },
  ],
};

return { json: { payload } };
