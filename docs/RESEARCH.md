# The research behind fable-protocol

Condensed from two multi-agent research sweeps run on 2026-07-02 (5 + 2 parallel research
agents over official Anthropic docs, GitHub issues, and community reports), plus a 3-critic
adversarial review of the kit itself. Sources inline.

## 1. Where the Fable 5 → Opus 4.8 gap actually is

- Fable 5 ($10/$50 per MTok) vs Opus 4.8 ($5/$25): both 1M context default, 128K max output
  ([models overview](https://platform.claude.com/docs/en/about-claude/models/overview)).
- The gap grows with task horizon: SWE-Bench Pro **80.3 vs 69.2**, Cognition FrontierCode
  **29.3 vs 13.4** ([TrueFoundry comparison](https://www.truefoundry.com/blog/claude-fable-5-vs-opus-4-8-benchmarks-pricing-when-to-use-each) — "the longer and more complex the task, the larger Fable 5's lead"; short-task gap narrows considerably).
- Anthropic's own framing ([announcement](https://www.anthropic.com/news/claude-fable-5-mythos-5),
  [migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide)):
  Fable's biggest gains are long autonomous runs, code review/debugging, sub-agent orchestration,
  and memory use (a memory harness improved Fable 3x more than the same harness improved Opus 4.8).
- **Conclusion the kit is built on:** the recoverable part of the gap is planning + verification
  stamina + staying grounded — process, not weights.

## 2. Documented Opus-class failure modes (the kit's target list)

1. **False completion claims.** [claude-code#63861](https://github.com/anthropics/claude-code/issues/63861):
   Opus 4.8 declared work "verified green" without running the canonical build; 12 failing tests
   found manually. Root causes: buried tool errors read as noise, wrong-path test runs read as
   passes, blame-the-harness bias.
2. **Under-triggering.** The [migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide)
   documents 4.8 under-reaching for search, subagents, memory, and custom tools by default;
   higher effort measurably raises tool usage.
3. **Compaction thread-loss.** [#13112](https://github.com/anthropics/claude-code/issues/13112)
   and feature requests [#43733](https://github.com/anthropics/claude-code/issues/43733),
   [#34299](https://github.com/anthropics/claude-code/issues/34299),
   [#17237](https://github.com/anthropics/claude-code/issues/17237); Anthropic lists "fewer
   derailments after compaction" as a 4.8 improvement area — i.e. a known weakness.
4. **Sycophancy at launch** (r/ClaudeAI reports within hours; contradicts marketing, unresolved).
5. **Review filters dropping findings.** [Prompting Opus 4.8](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-4-8):
   4.7/4.8 follow "only report high-severity" instructions too literally — measured recall drops.
6. **Effort miscalibration / overthinking loops.** [#64153](https://github.com/anthropics/claude-code/issues/64153)
   (46k thinking tokens on a trivial rename); community reports of xhigh runaway sessions.

## 3. The levers, ranked

1. **`effortLevel: "xhigh"`** — Anthropic: effort is "more important for this model than for any
   prior Opus"; default is `high`; xhigh recommended for coding/agentic; recalibrated in 4.8 to
   think substantially more than 4.7's xhigh ([effort docs](https://platform.claude.com/docs/en/build-with-claude/effort),
   [model-config](https://code.claude.com/docs/en/model-config)).
2. **Inert knobs (don't bother):** `alwaysThinkingEnabled` and `MAX_THINKING_TOKENS` have **no
   effect** on adaptive-thinking models (Fable 5, Opus 4.8/4.7, Sonnet 5) — thinking is always on,
   depth is controlled by effort ([adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)).
3. **Anthropic's own prompt snippets** (migration guide, tested internally):
   - *Grounded progress claims* — audit each claim against a tool result from this session
     ("nearly eliminated fabricated status reports").
   - *Autonomy calibration* — pick a reasonable option for minor choices (ask-rate −12pts,
     no over-reach increase).
   - *Coverage-first review prompts* — "report every issue; a separate verification step filters."
4. **Structural verification** ([best practices](https://code.claude.com/docs/en/best-practices)):
   the escalation ladder is prompt criteria → /goal condition → Stop-hook gate → fresh-context
   verification subagent. "Instructions are advisory; hooks are deterministic."
5. **Context hygiene:** lean CLAUDE.md ("bloated files cause Claude to ignore your actual
   instructions"), subagent fan-out for exploration, compaction-preservation instructions.

## 4. Ecosystem findings (what informed the design)

- **Compaction recovery is the #1 underserved niche**: documented demand across 4+ official
  feature requests; total supply was two repos with 1 and 10 stars. No mega-framework ships it.
  fable-protocol's SessionStart(compact) hook is deliberately deterministic (hooks, not prose).
- **Adversarial verification is unshipped elsewhere**: superpowers' two-stage review is
  cooperative; nobody ships refute-by-default panels with distinct lenses and fail-closed votes.
- **The cautionary tales**: SuperClaude (eager-loaded personas, context overhead), ECC
  (67-agent kitchen sink), BMAD (document ceremony). The recurring complaint about the
  methodology incumbent (superpowers, 244k★) is small-task ceremony — hence this kit's
  effort floor and per-component "when NOT to use me".
- **Fable-succession prior art** (all born in the June 2026 window): fablize (A/B-measured
  transfer), fable-mode (staged-execution skill), why-was-fable-banned (deterministic spec
  gate). None combine doctrine + adversarial verification + compaction recovery + orchestration
  playbook — that combination is this kit.

## 5. Verification of the kit itself

- 3-critic adversarial panel (conflicts / fitness-per-failure-mode / mechanics-vs-contracts)
  produced 15 findings; all should-fixes applied (trigger partitions between overlapping
  verification paths, three-way verdicts instead of silent drops, observable loop triggers,
  effort floor, deterministic compact hook).
- Every **v1.0/v1.1** component live-verified on `claude-opus-4-8` (Claude Code 2.1.198,
  2026-07-02): doctrine quoted verbatim from a fresh session, all agents visible and
  spawnable (incl. `effort: max` frontmatter), all workflow commands registered.
  Components added later (v1.2+ hooks, doctor, small-tier, `/big-task`, fable-mem, the
  Windows port) are unit- and CI-tested but have NOT all had a live-session pass — see
  the README's Known limits for the current live-verification scope.
- Honest residual: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` effectiveness unverified (has a
  documented history of being ignored on some versions: [#24159](https://github.com/anthropics/claude-code/issues/24159));
  kept because it is clamped per-model and therefore harmless.

## 6. The A/B benchmark (added same day, post-publication)

Built `bench/` to answer "does any of this measurably help?" — 10 headless Opus 4.8 runs on a
planted-bug task (full method + data: `bench/RESULTS.md`). Three results:

1. **Failure mode #1 reproduced on demand**: stock Opus read the trap file, never ran it, and
   claimed "all parts done and verified" over a red suite.
2. **Prose doctrine alone did not survive momentum** (hyper-2 skipped two doctrine rules it
   had loaded) — direct measurement of "instructions are advisory".
3. **The deterministic rung worked**: a Stop-hook claim-audit gate went 4/4 firings, 0 false
   claims, and demonstrably rescued one would-be false claim (model blocked at stop → ran the
   skipped check → fixed the shipped bug).

Engineering discovery along the way: Stop hooks must block via **exit code 2 + stderr**; the
documented JSON `{"decision":"block"}` protocol yields an empty result in `-p` print mode on
2.1.198 ([#38651](https://github.com/anthropics/claude-code/issues/38651) /
[#38805](https://github.com/anthropics/claude-code/issues/38805)). Both paths tested
empirically; the kit ships the working one.
