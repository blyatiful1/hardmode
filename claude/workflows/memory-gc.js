export const meta = {
  name: 'memory-gc',
  description: 'Corpus-health sweep for fable-mem: run the mechanical gc-scan, put LLM contradiction judges (three-way) on same-topic pairs, absolutize relative dates in place, rebuild the index, and report. NEVER deletes — every removal comes back as a proposal for you to act on.',
  whenToUse: 'Invoke as /memory-gc [--dry-run] when the cross-project memory corpus feels stale, before a big promotion, or periodically as hygiene. It edits ONLY to absolutize relative dates and rebuilds the disposable index; contradictions, duplicates, and stale entries return as PROPOSALS — it never removes a memory. Not routine per-session work. --dry-run proposes the date fixes instead of applying them.',
  phases: [
    { title: 'Scan', detail: 'mem gc-scan --json — mechanical near-dup / stale / relative-date / same-topic candidates' },
    { title: 'Judge', detail: 'LLM contradiction judges read each same-topic pair, three-way verdict (unverified is NOT safe)' },
    { title: 'Repair', detail: 'absolutize relative dates where a date anchor exists, then rebuild the index' },
  ],
}

// ---- args: optional --dry-run (propose date fixes instead of applying them) ----
const raw = (typeof args === 'string' ? args : '').trim()
const rest = raw.replace(/--dry-run\b/g, '').trim()
if (rest) return { error: `Unrecognized argument "${rest}". Usage: /memory-gc [--dry-run]` }
const dryRun = /--dry-run\b/.test(raw)

// Every agent resolves the memory base the same way the CLI and hooks do — never
// hardcode ~/.claude, so a scratch CLAUDE_DIR is honored.
const BASE_HINT = 'Resolve the memory base once: BASE = the value of the CLAUDE_DIR environment variable if it is set and non-empty, otherwise ~/.claude. Export CLAUDE_DIR into the environment of any mem.py call so the CLI reads the same base. On Windows, invoke `python` wherever a command below says `python3` (Windows Pythons ship no python3 launcher).'

const SCAN = {
  type: 'object',
  properties: {
    near_duplicates: {
      type: 'array',
      items: { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' }, reason: { type: 'string' } }, required: ['a', 'b'] },
    },
    stale: {
      type: 'array',
      items: { type: 'object', properties: { path: { type: 'string' }, age_days: { type: 'integer' }, scope: { type: 'string' } }, required: ['path'] },
    },
    relative_dates: {
      type: 'array',
      items: { type: 'object', properties: { path: { type: 'string' }, matches: { type: 'array', items: { type: 'string' } } }, required: ['path'] },
    },
    same_topic_pairs: {
      type: 'array',
      items: { type: 'object', properties: { a: { type: 'string' }, b: { type: 'string' }, shared: { type: 'array', items: { type: 'string' } } }, required: ['a', 'b'] },
    },
  },
  required: ['near_duplicates', 'stale', 'relative_dates', 'same_topic_pairs'],
}

// ---- Scan: mechanical gc-scan runs FIRST; the LLM layers only judge its candidates ----
phase('Scan')
const scan = await agent(
  `Run the mechanical fable-mem corpus-health scan and return its JSON verbatim. ${BASE_HINT}

Run exactly: python3 "$BASE/cli/mem.py" gc-scan --json
The command is read-only with respect to memory files — it only refreshes the disposable sqlite index. It prints a JSON object with keys near_duplicates, stale, relative_dates, same_topic_pairs. Parse that JSON and return it unchanged (empty arrays are fine). Do not edit any memory file.`,
  { label: 'gc-scan', phase: 'Scan', schema: SCAN }
)
if (!scan) return { error: 'gc-scan agent died — re-run /memory-gc, or run `python3 $CLAUDE_DIR/cli/mem.py gc-scan --json` by hand' }
const nearDup = Array.isArray(scan.near_duplicates) ? scan.near_duplicates : []
const stale = Array.isArray(scan.stale) ? scan.stale : []
const relDates = Array.isArray(scan.relative_dates) ? scan.relative_dates : []
const topicPairs = Array.isArray(scan.same_topic_pairs) ? scan.same_topic_pairs : []
log(`gc-scan: ${nearDup.length} near-dup, ${stale.length} stale, ${relDates.length} relative-date, ${topicPairs.length} same-topic pair(s)`)

const VERDICT = {
  type: 'object',
  properties: {
    verdict: {
      type: 'string',
      enum: ['confirmed', 'refuted', 'unverified'],
      description: 'confirmed = the two memories genuinely CONTRADICT (assert incompatible facts about the same thing); refuted = they are compatible, complementary, or duplicative-but-consistent; unverified = a file could not be read or the relationship cannot be judged',
    },
    conflict: { type: 'string', description: 'On confirmed: the two incompatible claims, quoted. Otherwise the relationship (e.g. "complementary", "duplicate").' },
    olderPath: { type: 'string', description: 'On a contradiction: which file is the likely-stale one to RETIRE (by created/verified date, else mtime) — this feeds a deletion PROPOSAL only, never an auto-delete' },
  },
  required: ['verdict', 'conflict'],
}

// ---- Judge: contradiction judges over same-topic pairs (unverified != refuted) ----
phase('Judge')
const judged = topicPairs.length ? (await parallel(topicPairs.map((pair, i) => () =>
  agent(
    `Two cross-project memories were flagged as same-topic. Judge whether they CONTRADICT each other. ${BASE_HINT}

Read BOTH files in full:
  A: ${pair.a}
  B: ${pair.b}
${pair.shared?.length ? `Shared keywords: ${pair.shared.join(', ')}.` : ''}
A contradiction means they assert INCOMPATIBLE facts about the same subject — not mere overlap or repetition. If they are compatible, complementary, or say the same thing consistently, that is NOT a contradiction.
verdict=confirmed ONLY for a real contradiction — quote the two conflicting claims and name which file is the likely-stale one to retire (by created/verified frontmatter date, else file mtime). verdict=refuted if compatible/complementary/consistent-duplicate. verdict=unverified if you cannot read a file or genuinely cannot tell — an unverified pair is NOT safe; it is surfaced for human review, never auto-resolved. You never delete or edit anything here.`,
    // Contradiction judges are the verification layer: xhigh regardless of driver effort.
    { label: `judge:${i + 1}`, phase: 'Judge', schema: VERDICT, effort: 'xhigh' }
  ).then(v => ({ pair, verdict: v }))
// A dead judge is not a "no contradiction" — count it unverified, fail toward review.
))) : []

const pairResult = judged.map((r, i) => ({
  pair: r?.pair ?? topicPairs[i],
  verdict: (r && r.verdict && r.verdict.verdict) ? r.verdict.verdict : 'unverified',
  conflict: r?.verdict?.conflict ?? 'judge did not return — treated as unverified, not safe',
  olderPath: r?.verdict?.olderPath ?? null,
}))
const contradictions = pairResult.filter(p => p.verdict === 'confirmed')
const unresolvedPairs = pairResult.filter(p => p.verdict === 'unverified')
log(`contradiction judges: ${contradictions.length} confirmed, ${pairResult.filter(p => p.verdict === 'refuted').length} refuted, ${unresolvedPairs.length} unverified`)

// ---- Repair: absolutize relative dates (in place, anchored) then rebuild the index ----
const DATEFIX = {
  type: 'object',
  properties: {
    rewritten: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          changes: { type: 'array', items: { type: 'string' }, description: 'e.g. "yesterday -> 2026-07-07"' },
          anchor: { type: 'string', description: 'the date source used (frontmatter verified/created, git commit date, or file mtime)' },
        },
        required: ['path', 'changes'],
      },
    },
    skipped: {
      type: 'array',
      items: { type: 'object', properties: { path: { type: 'string' }, reason: { type: 'string' } }, required: ['path', 'reason'] },
    },
  },
  required: ['rewritten', 'skipped'],
}

phase('Repair')
let dateFix = { rewritten: [], skipped: relDates.map(r => ({ path: r.path, reason: 'dry-run — proposed, not applied' })) }
if (relDates.length && !dryRun) {
  const fixed = await agent(
    `Absolutize relative dates in the fable-mem corpus so they stay meaningful in future sessions. ${BASE_HINT}

These memory files contain relative-date expressions (from the mechanical scan):
${relDates.map(r => `- ${r.path}: ${(r.matches || []).join(', ')}`).join('\n')}

For each file, find a reliable ANCHOR date IN PREFERENCE ORDER: the frontmatter \`verified:\` date, else \`created:\`, else the file's last git commit date (git log -1 --format=%cs -- <file>), else the file mtime. Rewrite each relative expression ("yesterday", "3 days ago", "last week", …) to the absolute ISO date (YYYY-MM-DD) it denotes relative to that anchor, editing the file in place. Where an expression is too vague to pin confidently (e.g. "recently") or no trustworthy anchor exists, LEAVE it and record it under skipped — never guess a date. Change ONLY date wording; touch nothing else, and never delete a file. Report exactly what you rewrote and what you skipped and why.`,
    { label: 'absolutize-dates', phase: 'Repair', schema: DATEFIX }
  )
  if (fixed) dateFix = { rewritten: Array.isArray(fixed.rewritten) ? fixed.rewritten : [], skipped: Array.isArray(fixed.skipped) ? fixed.skipped : [] }
  else { log('date-absolutizer died — relative dates left as proposals'); dateFix = { rewritten: [], skipped: relDates.map(r => ({ path: r.path, reason: 'absolutizer died — apply by hand' })) } }
}

// Rebuild is safe (writes only the disposable index) — run it so recall reflects any date fixes.
const rebuilt = await agent(
  `Rebuild the fable-mem sqlite index so it reflects the current corpus (including any absolutized dates). ${BASE_HINT}
Run: python3 "$BASE/cli/mem.py" index --rebuild
This writes only the disposable index, never a memory file. Report the command's summary line (changed / total / mode).`,
  { label: 'reindex', phase: 'Repair', effort: 'low' }
)
if (rebuilt == null) log('reindex agent died — run `python3 $CLAUDE_DIR/cli/mem.py index --rebuild` by hand')

// In --dry-run the date fixes are PROPOSED (they land in dateFix.skipped, not
// .rewritten), so report the candidate count, not the applied count (CONF18).
const dateFixCount = dryRun ? relDates.length : dateFix.rewritten.length
log(`memory-gc done — ${contradictions.length + nearDup.length + stale.length} deletion/merge proposal(s), ${dateFixCount} date fix(es) ${dryRun ? 'proposed' : 'applied'}`)
return {
  dryRun,
  scan: { nearDuplicates: nearDup.length, stale: stale.length, relativeDates: relDates.length, sameTopicPairs: topicPairs.length },
  contradictions: contradictions.map(c => ({ a: c.pair.a, b: c.pair.b, conflict: c.conflict, proposeRetiring: c.olderPath })),
  needsHumanReview: unresolvedPairs.map(p => ({ a: p.pair.a, b: p.pair.b, note: p.conflict })),
  duplicateProposals: nearDup.map(d => ({ a: d.a, b: d.b, reason: d.reason || 'near-duplicate' })),
  staleProposals: stale.map(s => ({ path: s.path, ageDays: s.age_days ?? null, scope: s.scope ?? null })),
  dateFixes: dateFix,
  reindex: rebuilt ?? '(reindex agent died — rebuild by hand)',
  note: 'PROPOSALS ONLY — no memory file was deleted. Contradictions, duplicates, and stale entries are for you to resolve (retire via git/postmortem). The only mutations made were absolutizing relative dates and rebuilding the disposable index.',
}
