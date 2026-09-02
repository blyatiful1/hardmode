---
description: How often the hardmode floor actually fired — sessions observed, sessions in which the hooks were witnessed running, blocks/nudges/denials per hook, overrides — from the firing ledger
argument-hint: "[--since DAYS] [--last N]"
allowed-tools: Bash(python3:*)
---

Firing statistics from the ledger:

```
!`python3 "${CLAUDE_PLUGIN_ROOT}/tools/stats.py" $ARGUMENTS`
```

Relay the numbers as printed. If the output warns that the floor was never witnessed,
say plainly that the hooks are not running and point at /hardmode:doctor. Do not
speculate beyond the numbers.
