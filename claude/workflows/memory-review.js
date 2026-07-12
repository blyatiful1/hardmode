export const meta = {
  name: 'memory-review',
  description: 'Mine the fable-mem session journal for high-activity sessions that banked ZERO cross-project memories, then PROPOSE (never write) the durable lessons worth capturing — a periodic "we learned this but forgot to save it" sweep.',
  whenToUse: 'Invoke as /memory-review [--top=N] [--min-dirty=N] on demand (not every session) to catch sessions that did real work but left no banked memory. It only PROPOSES capture candidates — banking still happens explicitly via the postmortem skill. Not for routine sessions; run it occasionally when you suspect the corpus is lagging behind the work.',
  phases: [
    { title: 'Mine', detail: 'read the BASE-resolved journal, cluster by repo, flag high-activity zero-banked sessions' },
    { title: 'Assess', detail: 'per zero-banked cluster, a judge proposes bankable candidates with a three-way worth-banking verdict' },
  ],
}

// ---- args: optional --top=N (how many candidates to assess) / --min-dirty=N (activity floor) ----
const raw = (typeof args === 'string' ? args : '').trim()
let top = 6
let minDirty = 8
let badFlag = null
const residue = raw
  .replace(/--top=(\S+)/, (_, v) => { const n = Number(v); if (Number.isInteger(n) && n > 0) top = Math.min(20, n); else badFlag = `--top=${v}`; return '' })
  .replace(/--min-dirty=(\S+)/, (_, v) => { const n = Number(v); if (Number.isInteger(n) && n >= 0) minDirty = n; else badFlag = `--min-dirty=${v}`; return '' })
  .trim()
if (badFlag) return { error: `Bad flag ${badFlag}. Usage: /memory-review [--top=N] [--min-dirty=N]` }
// Reject anything left over (typo'd flag, --min_dirty=, `--top 5` with a space) rather
// than silently running with defaults — mirrors memory-gc.js (CONF19).
if (residue) return { error: `Unrecognized argument(s): "${residue}". Usage: /memory-review [--top=N] [--min-dirty=N]` }

// Every agent resolves the memory base the same way the CLI and hooks do — never
// hardcode ~/.claude, so a scratch CLAUDE_DIR is honored.
const BASE_HINT = 'Resolve the memory base once: BASE = the value of the CLAUDE_DIR environment variable if it is set and non-empty, otherwise ~/.claude. Every path below is under BASE.'

const CLUSTERS = {
  type: 'object',
  properties: {
    clusters: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          repo: { type: 'string', description: 'Short repo/project label (basename of git_root, or the cwd when no git_root)' },
          gitRoot: { type: 'string', description: 'Resolved git root path for the cluster, or the cwd if none' },
          sessions: { type: 'integer', description: 'Number of journal entries in this cluster' },
          totalDirty: { type: 'integer', description: "Sum of dirty_count across the cluster's sessions (0 when git never answered)" },
          maxDirty: { type: 'integer', description: 'Largest single-session dirty_count' },
          lastTs: { type: 'string', description: 'Most recent ISO timestamp seen for this cluster' },
          banked: { type: 'boolean', description: 'true if this repo has topic memory files beyond MEMORY.md, or global memories referencing it' },
          bankedNote: { type: 'string', description: 'What memory (if any) was found for this repo' },
        },
        required: ['repo', 'gitRoot', 'sessions', 'totalDirty', 'maxDirty', 'banked'],
      },
    },
    journalFound: { type: 'boolean', description: 'false when no journal.ndjson exists under BASE yet' },
  },
  required: ['clusters', 'journalFound'],
}

// ---- Mine ----
phase('Mine')
const mined = await agent(
  `Mine the fable-mem session journal to find high-activity work sessions that banked no cross-project memory. ${BASE_HINT}

Read $BASE/memory/journal.ndjson and, if present, the rotated $BASE/memory/journal.1.ndjson. Each line is one JSON object: {ts, cwd, reason, and — when git could answer — git_root, branch, dirty_count}. If neither file exists, return journalFound=false with an empty clusters list.

Cluster the entries by git_root (fall back to cwd when git_root is absent). For each cluster compute: session count, the sum and max of dirty_count (treat a missing dirty_count as 0), and the most recent ts.

For each cluster decide whether that repo has BANKED memories. The native per-repo corpus lives at $BASE/projects/<project>/memory/ where <project> is derived from the git root; a repo counts as banked if that directory holds topic files beyond MEMORY.md, OR the global corpus $BASE/memory/*.md contains a memory that references the repo by name. A repo with real activity but only MEMORY.md (or nothing) is NOT banked.

This is strictly read-only: do not write, index, or modify anything. Return every cluster with its activity numbers and banked flag.`,
  { label: 'mine', phase: 'Mine', schema: CLUSTERS }
)
if (!mined) return { error: 'journal miner died — re-run /memory-review' }
if (!mined.journalFound) {
  log('no session journal found under BASE — nothing to review')
  return { journalFound: false, proposals: [], note: 'No $BASE/memory/journal.ndjson yet — the SessionEnd journal hook writes it as sessions end.' }
}

const clusters = Array.isArray(mined.clusters) ? mined.clusters : []
const candidates = clusters
  .filter(c => c && c.banked === false && ((c.totalDirty ?? 0) >= minDirty || (c.sessions ?? 0) >= 3))
  .sort((a, b) => (b.totalDirty ?? 0) - (a.totalDirty ?? 0))
  .slice(0, top)
log(`${clusters.length} cluster(s) mined, ${candidates.length} high-activity zero-banked candidate(s)`)
if (!candidates.length) {
  return { journalFound: true, clustersMined: clusters.length, proposals: [], note: 'No high-activity session lacked banked memory — the corpus is keeping up.' }
}

const PROPOSAL = {
  type: 'object',
  properties: {
    verdict: {
      type: 'string',
      enum: ['confirmed', 'refuted', 'unverified'],
      description: 'confirmed = there is durable, non-obvious knowledge from this work worth banking; refuted = the activity was routine or session-local, nothing worth a cross-project memory; unverified = plausibly bankable but cannot be confirmed without the session transcript (which is not available here)',
    },
    rationale: { type: 'string', description: 'Why this verdict, in one or two sentences' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'Proposed memory title' },
          why: { type: 'string', description: 'The durable, falsifiable lesson and why it is worth remembering across sessions' },
          scope: { type: 'string', enum: ['project', 'global'], description: 'project = repo-specific; global = genuinely cross-project (state the one-line why-global)' },
          visibility: { type: 'string', enum: ['private', 'shareable'] },
        },
        required: ['title', 'why', 'scope'],
      },
    },
  },
  required: ['verdict', 'rationale', 'candidates'],
}

// ---- Assess: one judge per zero-banked cluster; proposals only, three-way verdict ----
phase('Assess')
const assessed = (await parallel(candidates.map((c, i) => () =>
  agent(
    `A work session did real activity in a repository but banked no cross-project memory. Decide whether there is a durable lesson worth PROPOSING for capture — you propose only; nothing is written here. ${BASE_HINT}

REPO: ${c.repo} (git root: ${c.gitRoot})
ACTIVITY: ${c.sessions ?? '?'} session(s), ${c.totalDirty ?? 0} dirty-file touches total (max ${c.maxDirty ?? 0} in one session), last seen ${c.lastTs || 'unknown'}.
BANKED MEMORY: none found${c.bankedNote ? ` (${c.bankedNote})` : ''}.

You do NOT have the session transcript — infer from the repo itself: read its git log for the active window, its diffs, README/CLAUDE.md, and any MEMORY.md, to judge whether the work embodies a non-obvious, durable, falsifiable lesson (an architecture decision, a hard-won gotcha, a convention worth keeping) versus routine edits not worth a memory.
verdict=confirmed ONLY when you can name at least one concrete, durable candidate memory; refuted when the activity is routine/session-local with nothing worth banking; unverified when it plausibly holds a lesson but you cannot confirm one from the repo alone. Propose each candidate as project- or global-scoped, and mark a global one only with a one-line why-global.`,
    // Judges are the verification layer: hold xhigh even on a low-effort driver.
    { label: `assess:${(c.repo || '').slice(0, 24) || i + 1}`, phase: 'Assess', schema: PROPOSAL, effort: 'xhigh' }
  ).then(v => ({ cluster: c, verdict: v }))
// A dead judge is not a clean "nothing to bank" — count it as unverified, surface it.
))).map((r, i) => ({
  cluster: r?.cluster ?? candidates[i],
  verdict: (r && r.verdict && r.verdict.verdict) ? r.verdict.verdict : 'unverified',
  rationale: r?.verdict?.rationale ?? 'judge did not return — treated as unverified',
  candidates: Array.isArray(r?.verdict?.candidates) ? r.verdict.candidates : [],
}))

const withVerdict = v => assessed.filter(a => a.verdict === v)
const confirmed = withVerdict('confirmed')
const unverified = withVerdict('unverified')
const refuted = withVerdict('refuted')
log(`assessed ${assessed.length}: ${confirmed.length} worth banking, ${unverified.length} unverified, ${refuted.length} routine`)

const toProposal = a => ({
  repo: a.cluster.repo,
  gitRoot: a.cluster.gitRoot,
  activity: { sessions: a.cluster.sessions ?? null, totalDirty: a.cluster.totalDirty ?? 0, maxDirty: a.cluster.maxDirty ?? 0, lastSeen: a.cluster.lastTs ?? null },
  verdict: a.verdict,
  rationale: a.rationale,
  candidates: a.candidates,
})

return {
  journalFound: true,
  clustersMined: clusters.length,
  candidatesAssessed: assessed.length,
  proposals: confirmed.map(toProposal),
  needsHumanReview: unverified.map(toProposal),
  dropped: refuted.map(a => ({ repo: a.cluster.repo, rationale: a.rationale })),
  note: 'Proposals only — nothing was banked. Capture the ones you agree with via the postmortem skill (project- or global-scoped; the privacy guard blocks any leaking global write).',
}
