<#
.SYNOPSIS
fable-protocol installer for Windows — copies the framework into ~\.claude with backups.

.DESCRIPTION
Native-Windows port of install.sh with full parity: out-of-tree backups, idempotent
re-runs, skill manifests with stale-file pruning, small-driver tier, strong-model
pinning. Never edits settings.json; prints the snippet to merge instead.

Hook commands on Windows execute through Git Bash (Git for Windows), which Claude
Code also needs for its Bash tool — install it if you haven't. The Windows settings
snippets invoke `python` (Windows Pythons ship no `python3`).

.PARAMETER Tier
'opus' (default) or 'small' — 'small' prints the small-driver settings snippet
(FABLE_LOOP_THRESHOLD=2, see docs/SUCCESSION.md).

.PARAMETER StrongModel
Pin the verification agents (verifier, oracle, plan-critic) to this model, e.g.
-StrongModel opus — draft cheap, verify strong. Re-runs with the flag keep the pin.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File install.ps1

.EXAMPLE
pwsh ./install.ps1 -Tier small -StrongModel opus
#>
[CmdletBinding()]
param(
    [ValidateSet('small', 'opus')]
    [string]$Tier = 'opus',
    [string]$StrongModel = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Src = Join-Path $PSScriptRoot 'claude'
$Dst = if ($env:CLAUDE_DIR) { $env:CLAUDE_DIR } else { Join-Path $HOME '.claude' }
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
# Backups live OUTSIDE the live agents/skills/... trees: a fable.bak-*/ directory
# left inside skills/ would itself be loaded by Claude Code as a duplicate skill.
$Bak = Join-Path (Join-Path $Dst 'fable-protocol-backups') $Stamp

function Backup-Target([string]$Target, [string]$Rel) {
    if (-not (Test-Path $Target)) { return }
    $dest = Join-Path $Bak $Rel
    $parent = Split-Path $dest -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -Recurse -Force $Target $dest
    Write-Host "  backed up: $Target -> $dest"
}

# True if $B exists and matches $A byte-for-byte (skip needless backups).
function Test-Identical([string]$A, [string]$B) {
    if (-not (Test-Path $B -PathType Leaf)) { return $false }
    return (Get-FileHash -Algorithm SHA256 $A).Hash -eq (Get-FileHash -Algorithm SHA256 $B).Hash
}

# Relative ship-list of a skill dir in the exact bytes install.sh records:
# `./path/with/forward/slashes`, ordinal-sorted, one per line (LF).
function Get-ShipList([string]$Dir) {
    $base = (Resolve-Path $Dir).Path
    $list = @(Get-ChildItem -Recurse -File -LiteralPath $base | ForEach-Object {
        './' + $_.FullName.Substring($base.Length).TrimStart('\', '/').Replace('\', '/')
    })
    [Array]::Sort($list, [System.StringComparer]::Ordinal)
    return $list
}

function Write-LfFile([string]$Path, [string[]]$Lines) {
    [System.IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"))
}

# True if every file the repo ships for this skill already matches the destination
# AND the recorded ship-list (.fable-manifest) is current. Files a USER added are
# ignored (and preserved); files a PREVIOUS kit version shipped are tracked in the
# manifest so upgrades can prune them.
function Test-SkillUnchanged([string]$SrcDir, [string]$DstDir) {
    $manifest = Join-Path $DstDir '.fable-manifest'
    if (-not (Test-Path $manifest -PathType Leaf)) { return $false }
    $want = (Get-ShipList $SrcDir) -join "`n"
    $have = ([System.IO.File]::ReadAllText($manifest)).Replace("`r`n", "`n").TrimEnd("`n")
    if ($want -ne $have) { return $false }
    $base = (Resolve-Path $SrcDir).Path
    foreach ($f in Get-ChildItem -Recurse -File -LiteralPath $base) {
        $rel = $f.FullName.Substring($base.Length).TrimStart('\', '/')
        $t = Join-Path $DstDir $rel
        if (-not (Test-Identical $f.FullName $t)) { return $false }
    }
    return $true
}

# Remove files the manifest says a previous kit version shipped but this version no
# longer does. User files (never in a manifest) are untouched. Runs after backup.
function Remove-StaleSkillFiles([string]$SrcDir, [string]$DstDir) {
    $manifest = Join-Path $DstDir '.fable-manifest'
    if (-not (Test-Path $manifest -PathType Leaf)) { return }
    foreach ($line in Get-Content $manifest) {
        $rel = $line.Trim() -replace '^\./', ''
        if (-not $rel) { continue }
        if (-not (Test-Path (Join-Path $SrcDir $rel) -PathType Leaf)) {
            Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $DstDir $rel)
        }
    }
}

# Agent markdown with a `model:` pin injected into the frontmatter when -StrongModel
# was given (asymmetric verification: draft cheap, verify strong). Skips injection
# if the frontmatter already pins a model.
function Get-RenderedAgent([string]$File) {
    $lines = [System.IO.File]::ReadAllLines($File)
    if ($StrongModel) {
        $close = -1
        $pinned = $false
        for ($i = 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -eq '---') { $close = $i; break }
            if ($lines[$i] -match '^model:') { $pinned = $true }
        }
        if ($close -gt 0 -and -not $pinned) {
            $lines = @($lines[0..($close - 1)]) + @("model: $StrongModel") + @($lines[$close..($lines.Count - 1)])
        }
    }
    return ($lines -join "`n") + "`n"
}

# Best python launcher on this machine: py -3, then python, then python3.
# Returned as a command array (the leading comma stops PowerShell unrolling it).
function Get-PythonCommand {
    foreach ($spec in 'py -3', 'python', 'python3') {
        $probe = @($spec -split ' ')
        $exe = Get-Command $probe[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        try {
            $pargs = @($probe | Select-Object -Skip 1) + '--version'
            & $probe[0] @pargs *> $null
            if ($LASTEXITCODE -eq 0) { return , $probe }
        } catch { }
    }
    return $null
}

$pinNote = if ($StrongModel) { " (verification agents pinned to model: $StrongModel)" } else { '' }
Write-Host "Installing fable-protocol into $Dst$pinNote"
foreach ($d in 'agents', 'workflows', 'skills', 'hooks') {
    New-Item -ItemType Directory -Force -Path (Join-Path $Dst $d) | Out-Null
}

foreach ($f in Get-ChildItem (Join-Path $Src 'agents') -Filter '*.md') {
    $t = Join-Path (Join-Path $Dst 'agents') $f.Name
    $rendered = Get-RenderedAgent $f.FullName
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("fable-agent-" + [System.IO.Path]::GetRandomFileName())
    [System.IO.File]::WriteAllText($tmp, $rendered)
    try {
        if (Test-Identical $tmp $t) { Write-Host "  agent:    $($f.Name) (unchanged)"; continue }
        Backup-Target $t "agents/$($f.Name)"
        Copy-Item -Force $tmp $t
        Write-Host "  agent:    $($f.Name)"
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue $tmp
    }
}

foreach ($f in Get-ChildItem (Join-Path $Src 'workflows') -Filter '*.js') {
    $t = Join-Path (Join-Path $Dst 'workflows') $f.Name
    if (Test-Identical $f.FullName $t) { Write-Host "  workflow: /$($f.BaseName) (unchanged)"; continue }
    Backup-Target $t "workflows/$($f.Name)"
    Copy-Item -Force $f.FullName $t
    Write-Host "  workflow: /$($f.BaseName)"
}

foreach ($d in Get-ChildItem (Join-Path $Src 'skills') -Directory) {
    $t = Join-Path (Join-Path $Dst 'skills') $d.Name
    if (Test-SkillUnchanged $d.FullName $t) { Write-Host "  skill:    $($d.Name) (unchanged)"; continue }
    Backup-Target $t "skills/$($d.Name)"
    Remove-StaleSkillFiles $d.FullName $t
    New-Item -ItemType Directory -Force -Path $t | Out-Null
    Copy-Item -Recurse -Force (Join-Path $d.FullName '*') $t
    Write-LfFile (Join-Path $t '.fable-manifest') (Get-ShipList $d.FullName)
    Write-Host "  skill:    $($d.Name)"
}

foreach ($f in Get-ChildItem (Join-Path $Src 'hooks') -Filter '*.py') {
    $t = Join-Path (Join-Path $Dst 'hooks') $f.Name
    if (Test-Identical $f.FullName $t) { Write-Host "  hook:     $($f.Name) (unchanged)"; continue }
    Backup-Target $t "hooks/$($f.Name)"
    Copy-Item -Force $f.FullName $t
    Write-Host "  hook:     $($f.Name)"
}

# mem CLI + memory corpus — a component KIND of its own (see install.sh for the full
# rationale). privacy.toml is the USER'S pattern file: seed only when absent, NEVER
# overwrite work-markers the user has tuned.
New-Item -ItemType Directory -Force -Path (Join-Path $Dst 'cli'), (Join-Path $Dst 'memory') | Out-Null
$memSrc = Join-Path (Join-Path $Src 'cli') 'mem.py'
$memDst = Join-Path (Join-Path $Dst 'cli') 'mem.py'
if (Test-Identical $memSrc $memDst) {
    Write-Host "  cli:      mem.py (unchanged)"
} else {
    Backup-Target $memDst 'cli/mem.py'
    Copy-Item -Force $memSrc $memDst
    Write-Host "  cli:      mem.py"
}
$privacyDst = Join-Path (Join-Path $Dst 'memory') 'privacy.toml'
if (Test-Path $privacyDst) {
    Write-Host "  memory:   privacy.toml (kept — your patterns are never overwritten)"
} else {
    Copy-Item (Join-Path (Join-Path $Src 'memory') 'privacy.toml') $privacyDst
    Write-Host "  memory:   privacy.toml (seeded — edit it to add your own work-markers)"
}

# Bootstrap the memory index ONCE, now — so the first SessionEnd journal hook never
# has to carry a cold full build inside its 10s budget. Soft-fail: a missing python
# must not abort the install.
$py = Get-PythonCommand
if ($py) {
    $prevClaudeDir = $env:CLAUDE_DIR
    $env:CLAUDE_DIR = $Dst
    try {
        $pargs = @($py | Select-Object -Skip 1) + @($memDst, 'index', '--rebuild')
        & $py[0] @pargs *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  index:    memory corpus indexed (mem index --rebuild)"
        } else {
            Write-Host "  WARNING: initial 'mem index --rebuild' failed — recall warms up on first SessionEnd."
        }
    } finally {
        if ($null -eq $prevClaudeDir) { Remove-Item Env:CLAUDE_DIR -ErrorAction SilentlyContinue }
        else { $env:CLAUDE_DIR = $prevClaudeDir }
    }
} else {
    Write-Host "  NOTE: no working Python found (tried py -3, python, python3) — skipped the"
    Write-Host "        initial memory index AND every hook will be inert until Python is installed."
    Write-Host "        Install from https://python.org (check 'Add python.exe to PATH')."
}

# CLAUDE.md: never clobber an existing doctrine
$doctrineSrc = Join-Path $Src 'CLAUDE.md'
$doctrineDst = Join-Path $Dst 'CLAUDE.md'
if (Test-Path $doctrineDst) {
    if (Test-Identical $doctrineSrc $doctrineDst) {
        Write-Host "  doctrine: CLAUDE.md (unchanged)"
    } else {
        Copy-Item -Force $doctrineSrc (Join-Path $Dst 'CLAUDE.fable-protocol.md')
        Write-Host "  NOTE: $doctrineDst already exists — wrote CLAUDE.fable-protocol.md next to it; merge manually."
    }
} else {
    Copy-Item $doctrineSrc $doctrineDst
    Write-Host "  doctrine: CLAUDE.md (edit the '## This machine' section for your box)"
}

# Soft version check: saved workflows need Claude Code >= 2.1.154.
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if ($claudeCmd) {
    $verLine = (& claude --version 2>$null | Out-String)
    if ($verLine -match '(\d+\.\d+\.\d+)') {
        $ver = $Matches[1]
        if ([version]$ver -lt [version]'2.1.154') {
            Write-Host ""
            Write-Host "  WARNING: Claude Code $ver detected; saved workflows (/paranoid-review etc.)"
            Write-Host "  need >= 2.1.154. Everything else in the kit still works."
        }
    }
} else {
    Write-Host ""
    Write-Host "  NOTE: 'claude' not found on PATH — could not verify Claude Code >= 2.1.154."
}

$snippetName = if ($Tier -eq 'small') { 'settings-snippet-windows-small.json' } else { 'settings-snippet-windows.json' }
$snippet = Join-Path (Join-Path $Src 'settings') $snippetName
Write-Host ""
Write-Host "Last step (manual): merge this into $Dst\settings.json:"
Write-Host "----------------------------------------------------------------"
Write-Host ([System.IO.File]::ReadAllText($snippet).TrimEnd("`n"))
Write-Host "----------------------------------------------------------------"
if ($Tier -eq 'small') {
    Write-Host "Small-driver tier (docs/SUCCESSION.md): FABLE_LOOP_THRESHOLD=2 — on a small model"
    Write-Host "the SECOND identical failure is already the signal. Prefer the scripted workflows"
    Write-Host "over free-form delegation, and run big work as /big-task <task> (checkpointed"
    Write-Host "steps, adversarial verify, commit every green)."
    if (-not $StrongModel) {
        Write-Host "TIP: re-run with -StrongModel <strongest tier your plan offers> to pin the"
        Write-Host "verification agents — draft cheap, verify strong. Never let the checker be"
        Write-Host "weaker than the drafter on work that matters."
    }
}
Write-Host "effortLevel xhigh is the single biggest lever on Opus 4.8. The hook set:"
Write-Host "  Stop         claim-audit gate (benchmarked: bench/RESULTS.md)"
Write-Host "  PreCompact + SessionStart(compact)  save/inject the original request verbatim"
Write-Host "               plus the actual git state after every compaction"
Write-Host "  PreToolUse   destructive-command guard (protects uncommitted work)"
if ($Tier -eq 'small') {
    Write-Host "  PostToolUse  loop alarm (2nd identical failing command -> stop and reassess)"
} else {
    Write-Host "  PostToolUse  loop alarm (3rd identical failing command -> stop and reassess)"
}
Write-Host "  PostToolUse  test-weakening alarm (skip/disable marker added to a test file)"
Write-Host "  UserPromptSubmit  cross-project memory recall (read-only mem CLI FTS query)"
Write-Host "  SessionEnd   session journal breadcrumb + incremental memory re-index"
Write-Host "  PreToolUse   memory privacy guard (blocks work-markers leaking into the global corpus)"
Write-Host "The mem CLI (cross-project memory, layered on native auto-memory):"
Write-Host "  python $Dst\cli\mem.py search|show|stats|doctor|gc-scan  (corpus: $Dst\memory\)"
Write-Host ""
Write-Host "Windows notes:"
Write-Host "  - Hook commands run through Git Bash (Git for Windows) — Claude Code needs it"
Write-Host "    for its Bash tool anyway; without it the hooks above are inert."
Write-Host "  - The snippet invokes 'python' (Windows Pythons ship no 'python3'); make sure"
Write-Host "    'python --version' works in Git Bash. Using only the 'py' launcher? Replace"
Write-Host "    'python ' with 'py -3 ' in every hook command when you merge."
Write-Host ""
Write-Host "After merging, verify the install deterministically:"
Write-Host "  powershell -ExecutionPolicy Bypass -File tools\doctor.ps1"
Write-Host ""
Write-Host "Done. Start a new Claude Code session and ask: 'quote the first bullet of your"
Write-Host "Evidence before claims doctrine' to confirm the load."
