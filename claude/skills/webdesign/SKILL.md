---
name: webdesign
description: Design and build websites with an explicit design view — static/content-first, animated/motion-rich, interactive app-like, immersive/scrollytelling, or commerce — a written design brief before code, empirical verification (screenshots, reduced-motion, contrast), and a hard German-market compliance gate (Impressum, DSGVO, TDDDG consent, BFSG accessibility, self-hosted fonts). Use for any website, landing page, or web-UI design/restyle work; mandatory when the site targets Germany/DACH. Not for pure backend/API work or non-web UIs.
---

# Web design protocol

You are designing a website, not just writing markup. The failure modes this protocol
counters: view-less design (a static brochure loaded with app framework, an animated
site with no motion discipline), code before design decisions, "looks fine" claims
without evidence, and German-market sites that are Abmahnung bait. Two reference
documents carry the specifics — read them at the stage that needs them, not upfront:

- `references/design-views.md` — the design-view taxonomy: decision table, per-view
  tech ceiling, motion vocabulary, and performance budget.
- `references/german-market.md` — the German/DACH gate: legal checklist (with source
  URLs), typography rules, and market conventions.

## Stage W0 — Frame the site (always)
1. One paragraph before any code: audience, purpose, market(s), language(s), and what
   the site must make a visitor feel in the first 3 seconds. If the user didn't say,
   ask — these are scope, not implementation details.
2. Pick the design view from the decision table in `references/design-views.md`. Name
   the view and the one-line reason. A site that mixes views (animated hero, static
   content pages) declares the mix explicitly.
3. Market gate: if the site targets Germany/DACH — German-language audience, .de
   domain, German business — `references/german-market.md` becomes a HARD GATE for
   Stage W3. Read it now; several of its items (font sourcing, consent stance,
   accessibility scope) change what you're allowed to build, not just what you add.

## Stage W1 — Design brief before code
Write the brief as a short token sheet the implementation must obey:
- Type: faces (self-hostable or system only), scale (name the ratio), line-length cap.
- Color: palette with hex values, roles, and the contrast pairs you checked (AA
  minimum) — check them now, not after the build.
- Space: the spacing scale; grid/breakpoint intent from 360px up.
- Motion: what moves, what never moves, duration/easing vocabulary, and the
  `prefers-reduced-motion` stance (per the chosen view's budget).
- Content: real representative copy for the key sections — design with lorem ipsum is
  design deferred.
Genuinely open visual direction (new site, redesign, user can't articulate the
aesthetic)? `/design-variants <brief>` builds competing directions as self-contained
previews under `design-previews/` in the cwd, judged, one recommended. The
orchestration opt-in rule applies unchanged: launch it only when the user invoked
the command, asked for orchestration in their own words, or the session is opted in
(ultracode) — otherwise propose it in one line (~9 agents, judged previews) and
continue single-track until the user says yes. Skip it entirely when the direction
is already fixed.

## Stage W2 — Implement by the view's rules
- The chosen view's spec in `references/design-views.md` sets the tech ceiling (no
  SPA framework for a brochure site), the motion budget, and the performance budget.
  Exceeding it is a design change — say so and re-justify, don't drift.
- Non-negotiables regardless of view: semantic landmarks, keyboard-reachable
  interactions with visible focus, `lang` attribute correct for the content language,
  every asset self-hosted, motion wrapped so `prefers-reduced-motion` disables it.
- Build mobile-first; the desktop composition is earned, not assumed.

## Stage W3 — Verify like a visitor, then like a lawyer
- Screenshots at 320/768/1440 (or drive the real browser) — never assert what a page
  looks like without capturing it; that is doctrine, not preference.
- Drive one full pass with reduced motion enabled and one keyboard-only walk of the
  primary flow. Check the weight and request count against the view's budget.
- German gate (when armed in W0): walk `references/german-market.md` top to bottom
  and report each checklist item pass/fail — a German site that skips the gate is
  not done, whatever it looks like.

## Stage W4 — Ship honestly
- Every claim in the final report is backed by a check run this session; anything
  unchecked is labeled "unverified" (kit doctrine applies unchanged).
- Legal texts you generated (Impressum, Datenschutzerklärung, AGB) are structured
  templates, not legal advice — say exactly that and name the fields the site owner
  must confirm with counsel.
- Bank non-obvious lessons (client conventions, rejected directions and why) via the
  postmortem skill.

## Composition
This skill governs WHAT you build (the design layer). The fable protocol governs HOW
(plan-critique, verified increments, adversarial review) — on hard or multi-page
builds run both: fable's stages carry the process, this skill's stages carry the
design decisions. Match depth to stakes: a one-section placeholder page needs W0, a
paragraph of W1, and a screenshot — not the full ceremony.
