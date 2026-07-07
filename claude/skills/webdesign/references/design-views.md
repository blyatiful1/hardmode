# Design views

A design view is the load-bearing decision of a website build: it sets the tech
ceiling, the motion vocabulary, and the performance budget in one move. Pick it in
Stage W0, name it, and let it discipline everything downstream. Mixed sites declare
the mix per page/section ("animated hero on a static site") — an undeclared mix is
how brochure sites end up shipping app frameworks.

## Decision table

| Dominant signal from the brief | View |
|---|---|
| Content changes rarely; visitors come to read, check, contact | **static** |
| The brand moment IS the site; "wow", launch, agency, portfolio | **animated** |
| Visitors perform tasks: configure, calculate, filter, book | **interactive** |
| A story told through the scroll; journalism, flagship campaign | **immersive** |
| Visitors buy things | **commerce** |

When in doubt: **static, with selectively animated sections** — it is the cheapest
view to build, the fastest to load, and the easiest to upgrade later. Never pick
immersive by default; it is the most expensive view per visitor-second.

## Core Web Vitals floor (all views)

75th percentile, measured on throttled mid-range mobile — not the dev box:
**LCP ≤ 2.5 s · INP ≤ 200 ms · CLS ≤ 0.1** (web.dev/vitals; INP replaced FID in
March 2024). These are the *worst acceptable* numbers; the per-view budgets below
tighten them where the view can afford it and never loosen them. Always: dimensioned images (`width`/`height` or `aspect-ratio` — CLS),
responsive `srcset` + AVIF/WebP, lazy-load below the fold only, self-hosted assets,
`font-display: swap` with metric-compatible fallback (or system stack).

## static / content-first

Brochure and presence sites: restaurants, craftsmen/trades, professional services,
docs, blogs, portfolios-without-theatre.

- **Tech ceiling:** semantic HTML + modern CSS. A static site generator (Astro,
  Eleventy, Hugo) when pages share structure; **no client-side framework** — an SPA
  here is a design failure, not a preference. Prefer Baseline-native widgets over
  JS: `popover` (Baseline since 2025-01), `<dialog>`, `<details>`, `:has()`,
  scroll-snap. Remaining JS only for behavior CSS can't do (menu toggle, lightbox,
  form UX), a few KB, deferred.
- **Motion:** micro only — hover/focus transitions (~150–250 ms), at most one
  entrance fade. No scroll-triggered choreography, no parallax.
- **Budget:** LCP ≤ 1.8 s, total transfer ≤ 500 KB/page, JS ≤ 50 KB gz,
  zero render-blocking third parties, CLS ≈ 0.
- **Failure mode countered:** "we might need React later." You won't; upgrade the
  section that needs it when it exists.

## animated / motion-rich

Marketing sites where motion carries the brand: product launches, agencies,
startups, event sites.

- **Tech, in preference order (support verified 2026-07):**
  1. **CSS scroll-driven animations** (`animation-timeline: view()/scroll()`) behind
     `@supports (animation-timeline: view())` — zero-JS, compositor-friendly.
     Chrome/Edge 115+ and Safari 26+ (Apple jumped 18.x→26 — "Safari 18" claims are
     wrong), **not in stable Firefox in mid-2026** (~84% global,
     caniuse.com/mdn-css_properties_animation-timeline_scroll) — the guard is
     mandatory and the page must read perfectly without it.
  2. **IntersectionObserver + CSS classes** — the baseline that works everywhere.
  3. **View Transitions API**: same-document `document.startViewTransition` is
     cross-browser (Chrome 111+, Safari 18+, Firefox 144+; ~88%) behind a feature
     check; cross-document (MPA) transitions are Chrome 126+/Safari 18.2+ with
     Firefox only partial — enhancement only, never required for function.
  4. **GSAP** when timeline complexity earns a library — 100% free incl. all
     formerly-paid plugins (ScrollTrigger, SplitText, …) since 2025-04-30 under
     Webflow (gsap.com/pricing); ScrollTrigger costs ~30–45 KB gz. **Motion**
     (motion.dev — install `motion`, import `'motion/react'`; `framer-motion` is
     the legacy package) in React contexts.
- **Motion discipline:** animate `transform` and `opacity` only (compositor); never
  layout properties — on a scroll timeline they force main-thread work every frame.
  Durations 150–700 ms; one easing family per site. Scroll-driven ≠ scroll-jacked:
  never hijack the wheel or override scroll speed. Anything auto-playing > 5 s
  (hero video loops, carousels, marquees) needs a visible pause control (WCAG 2.2.2
  Level A — inside the EU legal baseline via EN 301 549).
- **`prefers-reduced-motion`: wrap, don't dampen.** All CSS choreography sits
  inside `@media (prefers-reduced-motion: no-preference)`; the reduced experience
  is the complete site minus theatre — content present, opacity 1, positions final
  (replace movement with opacity/color where a state change must stay visible).
  **The media query does not gate JS animation** — GSAP/Motion/WAAPI each need
  their own `matchMedia` gate (`gsap.matchMedia()`, Motion's `reducedMotion`).
  Verify in Stage W3 by driving the page with the preference enabled.
- **Budget:** LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 even mid-animation (reserve
  space), JS ≤ 150 KB gz with animation code loaded after first paint.

## interactive / app-like

Sites whose value is a task the visitor performs: configurators, calculators,
dashboards, booking flows.

- **Tech:** this is the view where a framework (React/Vue/Svelte) earns its place —
  for the stateful parts. Marketing/SEO pages around the app stay static (islands/
  hybrid rendering). State lives in the URL where a visitor would expect to share it.
- **Interaction discipline:** INP is the god metric — every tap answers within
  200 ms, with optimistic UI over spinners where safe. Full keyboard operability;
  ARIA only where native semantics run out; focus management on every view change.
- **Motion:** functional only — state transitions that explain causality (~200 ms),
  no decoration inside task flows.
- **Budget:** INP ≤ 200 ms, initial JS ≤ 300 KB gz, LCP ≤ 2.5 s on the entry page.

## immersive / scrollytelling

Narrative scroll experiences: data journalism, flagship brand campaigns, launches
where the story needs staging. The most expensive view per visitor — say so when
proposing it.

- **Tech:** sticky-scene pattern (CSS `position: sticky` + scroll progress) first;
  canvas only when 3D IS the story — three.js via **`WebGPURenderer`** (import from
  `'three/webgpu'`; tries WebGPU, falls back to WebGL 2 automatically; old GLSL
  `ShaderMaterial` patterns break with it). The LCP element is real HTML (poster/
  headline), never the canvas; lazy-init the GL context after first paint; cap
  `devicePixelRatio` at ~1.5–2; pause render loops off-screen and in hidden tabs;
  dispose GPU resources on scene exit. Narrative text stays real, selectable DOM.
- **Degradation is part of the design, not an afterthought:** reduced-motion (and
  low-end devices) get the "reader edition" — the same story as a flowing document
  with stills. If the story doesn't survive as a document, it isn't a story.
- **Budget:** LCP ≤ 2.5 s via poster frame; total payload staged, ≤ 1.5 MB before
  first interaction; watch CPU/battery on mobile — cap canvas work when
  `navigator.deviceMemory`/frame budget says so.

## commerce

Shops and conversion-first sites. Speed is revenue here — treat the budget as a
business requirement.

- **Tech:** a proven shop platform or SSR/hybrid framework; product and category
  pages render server-side/static-fast; cart/checkout may be app-like. Images do
  most of the selling: responsive, modern formats, never lazy-load the LCP image.
- **Conversion surface:** trust signals near every commitment point; payment methods
  visible before checkout; shipping cost and delivery time on the product page, not
  as a checkout surprise.
- **German shops:** the german-market.md gate is non-negotiable here — price display
  ("inkl. MwSt., zzgl. Versand"), Grundpreis (PAngV), the §312j BGB order button
  wording ("zahlungspflichtig bestellen"), Widerruf, AGB, and the German payment mix
  (PayPal, Klarna, Rechnung, SEPA) are conversion AND legal requirements.
- **Budget:** product page LCP ≤ 2.0 s, INP ≤ 200 ms under filtering, CLS ≤ 0.05
  (layout shift on a buy button is money lost).

## Cross-view invariants (verify in W3, every build)

- Semantic landmarks (`header/nav/main/footer`), one `h1`, heading order intact.
- Keyboard: every interaction reachable, `:focus-visible` styled, skip link on
  multi-nav pages.
- `lang` attribute matches content language (and `hyphens: auto` needs it — see
  german-market.md for German text).
- Contrast AA: 4.5:1 body text, 3:1 large text/UI — checked against the actual hex
  pairs, not eyeballed. Check every interactive STATE, not just resting: hover,
  focus, and active pairs each pass on the background they actually sit on
  (classic fail: a ghost/outline button whose hover fill nearly matches its text
  color, especially when an inline style overrides the class's hover rule).
- Motion honors `prefers-reduced-motion` (wrap, don't dampen) — drive it once per
  build. `scroll-behavior: smooth` IS motion: it belongs inside
  `@media (prefers-reduced-motion: no-preference)` like every other animation.
- Sticky/fixed header ⇒ `scroll-margin-top` (≥ header height) on every anchor
  target, or in-page links land with their heading hidden under the bar.
- No horizontal scroll down to 320 px (WCAG 1.4.10 reflow — test 320, design
  comfortably at 360) on EVERY page, not just index: legal/secondary pages break
  as easily (`white-space: nowrap` on a long German badge or compound is the
  classic fail); touch targets ≥ 24×24 px; text resizes to 200% without loss.

## Sources (support/threshold facts verified 2026-07)

- Core Web Vitals thresholds (unchanged; INP since 2024-03; no "CWV 2.0" exists):
  https://web.dev/articles/vitals · budgets: https://web.dev/articles/performance-budgets-101
- Scroll-driven animations: https://caniuse.com/mdn-css_properties_animation-timeline_scroll
- View Transitions (same-document / cross-document): https://caniuse.com/view-transitions ·
  https://caniuse.com/cross-document-view-transitions
- GSAP free since 2025-04-30: https://gsap.com/pricing/ · Motion: https://motion.dev/
- prefers-reduced-motion: https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion ·
  WCAG 2.2.2: https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html
- three.js WebGPURenderer: https://threejs.org/manual/en/webgpurenderer.html
- Popover API (Baseline 2025-01): https://developer.mozilla.org/en-US/docs/Web/API/Popover_API
