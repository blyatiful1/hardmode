---
description: Verify the hardmode install — plugin registration and version, hook wiring against this harness, settings keys and kill switches, doctrine, privacy patterns, state dir, and whether the floor was witnessed running in recent sessions
argument-hint: "[--strict] [--demo] [--init-privacy]"
allowed-tools: Bash(python3:*)
---

The doctor just ran against the live config dir. Its output:

```
!`python3 "${CLAUDE_PLUGIN_ROOT}/tools/doctor.py" $ARGUMENTS`
```

Relay it faithfully: restate every FAIL and WARN line with its one-line fix (the
evidence already names it), then the summary line. If every row is OK, say so in one
line. Do not paraphrase evidence and do not run anything else unless asked.
