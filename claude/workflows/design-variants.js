export const meta = {
  name: 'design-variants',
  description: 'Judge-panel web design: an art director sets 3 competing design directions (different design views — static, animated, interactive, …), 3 builders produce self-contained HTML previews, judges with distinct lenses score them, one synthesis names the winner and what to graft',
  whenToUse: 'Invoke as /design-variants <design brief> when the visual direction for a website/landing page is genuinely open — new site, redesign, or the user cannot articulate the aesthetic yet. Mention Germany/German/DACH in the brief to add a German-market compliance judge. For a site whose direction is already fixed, apply the webdesign skill directly instead.',
  phases: [
    { title: 'Direct', detail: 'art director sets 3 competing directions' },
    { title: 'Design', detail: '3 builders, one self-contained HTML preview each' },
    { title: 'Judge', detail: 'distinct-lens judges score every preview' },
    { title: 'Synthesize', detail: 'winner + grafts from the losers' },
  ],
}

const brief = (typeof args === 'string' && args.trim()) ? args.trim() : null
if (!brief) return { error: 'Usage: /design-variants <design brief — audience, purpose, market, any fixed constraints>' }

// German-market mode: adds a compliance judge and puts the german-market checklist
// in every builder's brief. An explicit market keyword turns it on outright. Absent
// that, a SINGLE umlaut is not enough — an English brief naming "Motörhead" or
// "Zürich" must not trip it (CONF26) — so a brief merely WRITTEN in German needs at
// least two independent language signals. When in doubt, say "German market".
const germanKeyword = /german|deutsch|germany|dach\b|\.de\b|impressum|dsgvo/i.test(brief)
const languageSignals = [/[äöüß]/, /„/, /\bGmbH\b/, /\bund\b/i, /\beine[nrms]?\b/i]
  .filter(re => re.test(brief)).length
const german = germanKeyword || languageSignals >= 2
if (german && !germanKeyword) log(`german-market mode enabled by language heuristic (${languageSignals} signals) — add an explicit market keyword to be sure`)

const SKILL_HINT = `If the installed webdesign skill references exist — default location ~/.claude/skills/webdesign/references/, or under $CLAUDE_DIR/skills/webdesign/references/ when that env var is set — read design-views.md${german ? ' AND german-market.md' : ''} from there FIRST and follow them; if absent, proceed from the constraints in this prompt alone.`

const DIRECTIONS = {
  type: 'object',
  properties: {
    directions: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string', description: 'Short evocative name for the direction' },
          view: { type: 'string', description: 'The design view: static/content-first, animated/motion-rich, interactive/app-like, immersive/scrollytelling, or commerce' },
          concept: { type: 'string', description: 'The design concept in 2-3 sentences: mood, audience read, what makes it distinct from the other two' },
          typography: { type: 'string', description: 'Type direction: scale, weights, pairing intent (self-hostable/system fonts only)' },
          palette: { type: 'string', description: 'Color direction with concrete hex anchors and contrast intent' },
          motion: { type: 'string', description: 'Motion vocabulary: what moves, what never moves, reduced-motion stance' },
        },
        required: ['name', 'view', 'concept', 'typography', 'palette', 'motion'],
      },
      minItems: 3,
      maxItems: 3,
    },
  },
  required: ['directions'],
}

phase('Direct')
const directed = await agent(
  `You are the art director. ${SKILL_HINT}

DESIGN BRIEF: ${brief}

Set exactly 3 COMPETING design directions for this brief. They must differ in design view where the brief allows it (e.g. one static/content-first, one animated/motion-rich, one interactive or immersive) — if the brief pins a view, keep the view and differentiate aesthetic instead. Each direction must be buildable as a single self-contained HTML file: no external requests, no CDN assets, system or embedded fonts only.${german ? ' The target market is Germany: every direction must plan for the German compliance and typography rules (Impressum/Datenschutz footer links, consent-free asset stack, „…“ quotes, hyphenation, formal/informal address chosen deliberately).' : ''}`,
  { label: 'art-director', phase: 'Direct', schema: DIRECTIONS }
)
if (!directed) return { error: 'art director died — re-run, or set directions manually and apply the webdesign skill' }

const BUILD = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'Path of the HTML preview you wrote' },
    summary: { type: 'string', description: 'What was built and how it embodies the direction, 2-4 sentences' },
    self_check: { type: 'array', items: { type: 'string' }, description: 'Checklist items you verified on your own output (contrast, reduced-motion, viewport meta, semantic landmarks, …) — only ones you actually checked' },
  },
  required: ['file', 'summary', 'self_check'],
}

phase('Design')
// Builders are TOLD the exact output path; the workflow enforces it below rather
// than trusting the reported path (judge prompts embed it verbatim).
const slugOf = v => v.split('/')[0].toLowerCase().replace(/[^a-z]+/g, '-').replace(/^-+|-+$/g, '') || 'view'
const previews = (await parallel(directed.directions.map((d, i) => () =>
  agent(
    `You are a web designer-engineer. ${SKILL_HINT}

DESIGN BRIEF: ${brief}

YOUR DIRECTION (build THIS, not a compromise):
name: ${d.name}
view: ${d.view}
concept: ${d.concept}
typography: ${d.typography}
palette: ${d.palette}
motion: ${d.motion}

Build ONE polished, self-contained HTML preview at design-previews/variant-${i + 1}-${slugOf(d.view)}.html (create the directory if needed; overwrite if present). Hard constraints:
- Single file, zero external requests: inline all CSS/JS, system font stack or embedded fonts, inline SVG or CSS art instead of image files.
- Real representative content for the brief (no lorem ipsum), responsive from 360px to desktop, semantic landmarks, visible focus states.
- Motion only via CSS/vanilla JS, fully disabled under prefers-reduced-motion (wrap it, don't dampen it).${german ? '\n- German market: German-language content with correct „…“ quotation marks, ß where the words need it, lang="de" + hyphens:auto on prose, Impressum and Datenschutzerklärung placeholder links in the footer (AGB/Widerrufsbelehrung additionally ONLY if the brief is a shop), no consent-requiring assets.' : ''}
Then report the file path, a summary, and ONLY the checks you actually performed on the written file.`,
    { label: `build:${d.name.slice(0, 24)}`, phase: 'Design', schema: BUILD }
    // Enforce the instructed path — never let a builder-reported path steer judges.
  ).then(b => b && { ...b, reported_file: b.file, file: `design-previews/variant-${i + 1}-${slugOf(d.view)}.html`, direction: d, index: i + 1 })
))).filter(Boolean)

if (!previews.length) return { error: 'all builders died' }
if (previews.length < directed.directions.length) log(`${directed.directions.length - previews.length} builder(s) died — judging the survivors only`)
previews.filter(p => p.reported_file !== p.file).forEach(p => log(`builder for variant ${p.index} reported path "${p.reported_file}" — using the instructed ${p.file}`))

const SCORES = {
  type: 'object',
  properties: {
    scores: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          variant: { type: 'integer', description: '1-based variant index' },
          score: { type: 'integer', description: '0-10' },
          notes: { type: 'string', description: 'Decisive strengths/defects found in the ACTUAL file, cited by element/selector' },
        },
        required: ['variant', 'score', 'notes'],
      },
    },
  },
  required: ['scores'],
}

const variantsText = previews.map(p =>
  `VARIANT ${p.index} (${p.direction.name}, view: ${p.direction.view}) — file: ${p.file}\nconcept: ${p.direction.concept}\nbuilder summary: ${p.summary}`
).join('\n\n')

phase('Judge')
const LENSES = [
  'craft — visual hierarchy, typography (scale, rhythm, line length), spacing system, color contrast (check actual hex values against WCAG AA), coherence of the composition',
  'audience fit — does this design earn the trust of the brief\'s stated audience and read correctly for its market and industry; penalize genericness and template-smell as hard as ugliness',
  'engineering — read the code: responsiveness across 360px-desktop, semantic HTML and keyboard/focus quality, motion implementation (does prefers-reduced-motion actually disable it), performance weight, self-containment (zero external requests)',
]
if (german) LENSES.push('German-market compliance — Impressum/Datenschutz links present, no consent-requiring or external assets, „…“ quotation marks, lang="de" and hyphenation on prose, ß used correctly, date/number formats, deliberate Sie/du choice — cite each violation by element')

const votes = (await parallel(LENSES.map((lens, i) => () =>
  agent(
    `Judge these competing design previews for the brief below. Your lens: ${lens}. ${SKILL_HINT}

DESIGN BRIEF: ${brief}

${variantsText}

READ each preview file in full before scoring — judge the artifact, not the builder's summary. Score each variant 0-10 through your lens with decisive, element-level notes.`,
    // Judges are the verification layer: hold xhigh regardless of session effort.
    { label: `judge:${i + 1}`, phase: 'Judge', schema: SCORES, effort: 'xhigh' }
  )
))).filter(Boolean)

if (!votes.length) return { error: 'all judges died — previews exist but are unranked', files: previews.map(p => p.file) }
let omissions = 0
const totals = previews.map(p =>
  votes.reduce((sum, v) => {
    const s = v.scores.find(s => s.variant === p.index)
    if (!s) { omissions++; return sum }  // counted as 0, but visibly — never silently
    return sum + Math.max(0, Math.min(10, s.score))
  }, 0))
if (omissions) log(`${omissions} score(s) omitted by judges — counted as 0`)
const winner = totals.indexOf(Math.max(...totals))
const judgeNotes = votes.flatMap(v => v.scores).map(s => `variant ${s.variant} (${s.score}/10): ${s.notes}`).join('\n')
log(`scores: ${previews.map((p, i) => `variant${p.index}=${totals[i]}`).join(' ')} — winner: variant ${previews[winner].index} (${previews[winner].direction.name})`)

phase('Synthesize')
const recommendation = await agent(
  `Synthesize the design decision.

DESIGN BRIEF: ${brief}

${variantsText}

JUDGE VERDICTS (${votes.length} judges, distinct lenses):
${judgeNotes}

The winner is VARIANT ${previews[winner].index} (${previews[winner].direction.name}). Read the winning file. Produce a markdown recommendation: (1) why it won, in the brief's terms; (2) every judge-flagged defect in it, each with a concrete fix; (3) what to graft from the losing variants (specific elements/techniques, not vibes); (4) the concrete next steps to take it from preview to production site${german ? ', including the German compliance items a preview cannot carry (real Impressum/Datenschutzerklärung content, consent stance, BFSG accessibility statement if in scope)' : ''}.`,
  { label: 'synthesize', phase: 'Synthesize' }
)
if (recommendation == null) log('synthesizer died — previews and scores stand; write the recommendation manually from the judge notes')

return {
  files: previews.map(p => p.file),
  scores: Object.fromEntries(previews.map((p, i) => [`variant${p.index}`, totals[i]])),
  winner: `variant ${previews[winner].index} (${previews[winner].direction.name}, ${previews[winner].direction.view})`,
  german_mode: german,
  recommendation: recommendation ?? '(synthesizer died — see judge notes in the run transcript)',
  lostBuilders: directed.directions.length - previews.length,
  lostJudges: LENSES.length - votes.length,
}
