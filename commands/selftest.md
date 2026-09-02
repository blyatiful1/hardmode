---
description: Run the hardmode self-test — the real shipped hooks against planted failure modes in a throwaway sandbox, plus the hooks.json wiring check. Run it after a Claude Code update
allowed-tools: Bash(python3:*)
---

Self-test output:

```
!`python3 "${CLAUDE_PLUGIN_ROOT}/tools/demo.py"`
```

Report the final `demo: N/N` line. If any scenario printed `[FAIL]`, quote each failing
line verbatim and say which guard is no longer firing — that guard's rule is advisory
only until it is fixed.
