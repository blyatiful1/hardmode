<#
.SYNOPSIS
fable-protocol doctor for Windows — verifies an installation is actually live, not silently inert.

.DESCRIPTION
Native-Windows port of tools/doctor.sh with the same checks and exit semantics.
The kit's weakest link is the one manual step: merging the settings snippet. A
botched merge leaves every hook unwired and the whole kit inert with zero
symptoms — the exact failure the kit exists to prevent. This script makes the
check deterministic. Run it after install.ps1 (and after Claude Code updates).

Exit 0 = installation verified; exit 1 = at least one FAIL line above.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

$Src = Join-Path (Split-Path $PSScriptRoot -Parent) 'claude'
$Dst = if ($env:CLAUDE_DIR) { $env:CLAUDE_DIR } else { Join-Path $HOME '.claude' }
$script:fail = 0

function Ok([string]$Msg)   { Write-Host "  ok:   $Msg" }
function Bad([string]$Msg)  { Write-Host "  FAIL: $Msg"; $script:fail = 1 }
function Warn([string]$Msg) { Write-Host "  warn: $Msg" }

function Test-Identical([string]$A, [string]$B) {
    if (-not (Test-Path $B -PathType Leaf)) { return $false }
    return (Get-FileHash -Algorithm SHA256 $A).Hash -eq (Get-FileHash -Algorithm SHA256 $B).Hash
}

# Content compare tolerant of CRLF/LF differences: autocrlf makes the installed
# copy and the repo checkout differ on line endings without real drift, and
# install.ps1 rewrites agents to LF. Staleness is reported as a warn, not a FAIL.
function Get-NormContent([string]$Path) { return ([System.IO.File]::ReadAllText($Path)) -replace "`r", '' }
function Test-ContentSame([string]$A, [string]$B) {
    if (-not (Test-Path $B -PathType Leaf)) { return $false }
    return (Get-NormContent $A) -eq (Get-NormContent $B)
}
# Like Test-ContentSame but ignores an installer-injected `model:` frontmatter pin
# (-StrongModel), so a pinned install is not misreported as drift.
function Test-AgentSame([string]$A, [string]$B) {
    if (-not (Test-Path $B -PathType Leaf)) { return $false }
    $ca = (Get-NormContent $A) -split "`n" | Where-Object { $_ -notmatch '^model: ' }
    $cb = (Get-NormContent $B) -split "`n" | Where-Object { $_ -notmatch '^model: ' }
    return (($ca -join "`n") -eq ($cb -join "`n"))
}

# event -> set of wired hook basenames, from a parsed settings/snippet object.
function Get-EventHookMap($Obj) {
    $map = @{}
    if ($null -eq $Obj) { return $map }
    $hp = $Obj.PSObject.Properties['hooks']
    if ($null -eq $hp -or $null -eq $hp.Value) { return $map }
    foreach ($ev in $hp.Value.PSObject.Properties) {
        $names = New-Object 'System.Collections.Generic.HashSet[string]'
        foreach ($group in @($ev.Value)) {
            if ($null -eq $group) { continue }
            $gh = $group.PSObject.Properties['hooks']
            if ($null -eq $gh) { continue }
            foreach ($h in @($gh.Value)) {
                $cp = $h.PSObject.Properties['command']
                if ($null -eq $cp) { continue }
                [void]$names.Add(((([string]$cp.Value).TrimEnd()) -split '/')[-1])
            }
        }
        $map[$ev.Name] = $names
    }
    return $map
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

function Invoke-Python($Py, [string[]]$PyArgs) {
    $Py = @($Py)
    $pargs = @($Py | Select-Object -Skip 1) + $PyArgs
    & $Py[0] @pargs 2>$null
}

Write-Host "fable-protocol doctor — checking $Dst"

# 0. Claude Code version — saved workflows (/paranoid-review etc.) need >= 2.1.154.
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    $cver = ''
    try { if ((& claude --version 2>$null | Out-String) -match '(\d+\.\d+\.\d+)') { $cver = $Matches[1] } } catch {}
    if ($cver) {
        $need = [version]'2.1.154'
        if ([version]$cver -lt $need) {
            Warn "Claude Code $cver detected; saved workflows need >= 2.1.154 (everything else still works)"
        } else {
            Ok "Claude Code $cver (>= 2.1.154)"
        }
    }
} else {
    Warn "'claude' not on PATH — could not verify Claude Code >= 2.1.154"
}

# 1. Python — every hook runs through it. The Windows snippets invoke `python`.
$py = Get-PythonCommand
if ($py) {
    $ver = (Invoke-Python $py @('--version') | Out-String).Trim()
    Ok "python on PATH ($ver via '$($py -join ' ')')"
    if ($py[0] -ne 'python') {
        Warn "'python' itself is not the working launcher — the settings snippet invokes 'python'; adjust the hook commands to '$($py -join ' ')' when you merge"
    }
} else {
    Bad "no working Python found (tried py -3, python, python3) — every hook is inert"
}

# 1b. Windows only: hook commands execute through Git Bash (Git for Windows).
if ($env:OS -eq 'Windows_NT') {
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        Ok "Git Bash on PATH (hook command shell)"
    } else {
        Bad "bash not on PATH — on Windows, hook commands run through Git Bash; install Git for Windows (https://gitforwindows.org) or every hook is inert"
    }
}

# 2. Every component the repo ships is installed (and hooks compile).
foreach ($f in Get-ChildItem (Join-Path $Src 'hooks') -Filter '*.py') {
    $t = Join-Path (Join-Path $Dst 'hooks') $f.Name
    if (-not (Test-Path $t -PathType Leaf)) {
        Bad "hook missing: $t (re-run install.ps1)"
    } elseif ($py) {
        Invoke-Python $py @('-m', 'py_compile', $t) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Bad "hook does not compile: $t"
        } elseif (-not (Test-ContentSame $f.FullName $t)) {
            Warn "hook differs from this repo checkout: $t (older kit version? re-run install.ps1)"
        } else {
            Ok "hook: $($f.Name)"
        }
    } elseif (-not (Test-ContentSame $f.FullName $t)) {
        Warn "hook differs from this repo checkout: $t (older kit version? re-run install.ps1)"
    } else {
        Ok "hook: $($f.Name)"
    }
}
foreach ($f in Get-ChildItem (Join-Path $Src 'agents') -Filter '*.md') {
    $t = Join-Path (Join-Path $Dst 'agents') $f.Name
    if (-not (Test-Path $t -PathType Leaf)) { Bad "agent missing: $t" }
    elseif (-not (Test-AgentSame $f.FullName $t)) { Warn "agent differs from this repo checkout: $t (re-run install.ps1)" }
    else { Ok "agent: $($f.Name)" }
}
foreach ($f in Get-ChildItem (Join-Path $Src 'workflows') -Filter '*.js') {
    $t = Join-Path (Join-Path $Dst 'workflows') $f.Name
    if (-not (Test-Path $t -PathType Leaf)) { Bad "workflow missing: $t" }
    elseif (-not (Test-ContentSame $f.FullName $t)) { Warn "workflow differs from this repo checkout: $t (re-run install.ps1)" }
    else { Ok "workflow: /$($f.BaseName)" }
}
foreach ($d in Get-ChildItem (Join-Path $Src 'skills') -Directory) {
    $complete = $true
    $drifted = $false
    $base = $d.FullName
    foreach ($f in Get-ChildItem -Recurse -File -LiteralPath $base) {
        $rel = $f.FullName.Substring($base.Length).TrimStart('\', '/')
        $t = Join-Path (Join-Path (Join-Path $Dst 'skills') $d.Name) $rel
        if (-not (Test-Path $t -PathType Leaf)) {
            Bad "skill file missing: $t"; $complete = $false
        } elseif (-not (Test-ContentSame $f.FullName $t)) {
            Warn "skill file differs from this repo checkout: $t (older kit version? re-run install.ps1)"; $drifted = $true
        }
    }
    if ($complete -and -not $drifted) { Ok "skill: $($d.Name)" }
}

# 2b. The mem CLI is a component KIND of its own — the four globs above don't see
# claude/cli/, so it gets a hand-written check: present, compiles, and its own
# self-diagnostic runs clean, reporting its FTS mode (fts5 / degraded-like).
$mem = Join-Path (Join-Path $Dst 'cli') 'mem.py'
if (-not (Test-Path $mem -PathType Leaf)) {
    Bad "mem CLI missing: $mem (re-run install.ps1)"
} elseif ($py) {
    Invoke-Python $py @('-m', 'py_compile', $mem) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Bad "mem CLI does not compile: $mem"
    } else {
        $prevClaudeDir = $env:CLAUDE_DIR
        $env:CLAUDE_DIR = $Dst
        try {
            $out = Invoke-Python $py @($mem, 'doctor') | Out-String
            $rc = $LASTEXITCODE
        } finally {
            if ($null -eq $prevClaudeDir) { Remove-Item Env:CLAUDE_DIR -ErrorAction SilentlyContinue }
            else { $env:CLAUDE_DIR = $prevClaudeDir }
        }
        $mode = 'unknown'
        foreach ($line in ($out -split "`r?`n")) {
            if ($line -match '^mode=(.+)$') { $mode = $Matches[1]; break }
        }
        if ($rc -eq 0) { Ok "mem CLI (mode=$mode)" }
        else { Bad "mem CLI self-check failed: (with CLAUDE_DIR=$Dst) python $mem doctor" }
        if (-not (Test-ContentSame (Join-Path (Join-Path $Src 'cli') 'mem.py') $mem)) {
            Warn "mem CLI differs from this repo checkout: $mem (re-run install.ps1)"
        }
    }
}

# Memory corpus dir writable + privacy pattern seed present.
$memDir = Join-Path $Dst 'memory'
try {
    New-Item -ItemType Directory -Force -Path $memDir | Out-Null
    $probe = Join-Path $memDir '.doctor-probe'
    New-Item -ItemType File -Force -Path $probe | Out-Null
    Remove-Item -Force $probe
    Ok "memory dir writable: $memDir"
} catch {
    Bad "memory dir not writable: $memDir — recall + journal re-indexing will be inert"
}
if (Test-Path (Join-Path $memDir 'privacy.toml') -PathType Leaf) {
    Ok "privacy.toml present"
} else {
    Warn "privacy.toml missing in $memDir — the privacy guard has no patterns to match (fails open)"
}

# 3. Doctrine is loadable.
$doctrine = Join-Path $Dst 'CLAUDE.md'
$doctrineText = if (Test-Path $doctrine -PathType Leaf) { [System.IO.File]::ReadAllText($doctrine) } else { '' }
if ($doctrineText.Contains('Evidence before claims')) {
    Ok "doctrine present in CLAUDE.md"
    if ($doctrineText.Contains('Replace with 3-6 lines')) {
        Warn "the '## This machine' section is still the placeholder — fill it in"
    }
} elseif (Test-Path (Join-Path $Dst 'CLAUDE.fable-protocol.md') -PathType Leaf) {
    Bad "doctrine NOT merged: it sits unloaded in CLAUDE.fable-protocol.md next to your CLAUDE.md"
} else {
    Bad "doctrine missing: no Evidence-before-claims section in $doctrine"
}

# 4. The manual step: settings.json actually wires the hooks.
$settingsPath = Join-Path $Dst 'settings.json'
if (-not (Test-Path $settingsPath -PathType Leaf)) {
    Bad "settings.json missing — no hooks are wired, the enforcement layer is OFF"
} else {
    $settingsText = [System.IO.File]::ReadAllText($settingsPath)
    $settings = $null
    try { $settings = $settingsText | ConvertFrom-Json } catch { }
    if ($null -eq $settings) {
        Bad "settings.json is not valid JSON — Claude Code will ignore it"
    } else {
        Ok "settings.json parses"
        # Event-level wiring: a substring test of the filename cannot tell a hook
        # wired to the WRONG event, nor a partial merge that dropped one block of a
        # multi-event hook (e.g. the loop alarm's PostToolUseFailure) from a correct
        # one. Compare each hook's presence PER EVENT against the shipped snippet's
        # own event map (matcher-agnostic, so the widened Bash|PowerShell matcher is
        # accepted).
        $snippetPath = Join-Path (Join-Path $Src 'settings') 'settings-snippet-windows.json'
        $expected = Get-EventHookMap ([System.IO.File]::ReadAllText($snippetPath) | ConvertFrom-Json)
        $actual = Get-EventHookMap $settings
        foreach ($ev in ($expected.Keys | Sort-Object)) {
            foreach ($name in ($expected[$ev] | Sort-Object)) {
                if ($actual.ContainsKey($ev) -and $actual[$ev].Contains($name)) {
                    Ok "wired: $name [$ev]"
                } else {
                    Bad "NOT wired under $ev in settings.json: $name (merge the snippet from install.ps1)"
                }
            }
        }
        $effort = $null
        try { $effort = $settings.effortLevel } catch { }
        if ($effort -eq 'xhigh') {
            Ok "effortLevel: xhigh (the single biggest lever)"
        } else {
            Warn "effortLevel is not 'xhigh' in settings.json — on Opus 4.8 this is THE lever"
        }
        if ($settingsText.Contains('python3 ')) {
            Warn "settings.json invokes 'python3' — Windows Pythons ship no 'python3'; use the Windows snippet (python) or those hooks are inert"
        }
    }
}

# 5. Hook state dir is writable (loop alarm, weakening alarm, compaction save).
$state = if ($env:FABLE_STATE_DIR) { $env:FABLE_STATE_DIR } else { Join-Path (Join-Path $Dst 'tmp') 'fable-protocol' }
try {
    New-Item -ItemType Directory -Force -Path $state | Out-Null
    $probe = Join-Path $state '.doctor-probe'
    New-Item -ItemType File -Force -Path $probe | Out-Null
    Remove-Item -Force $probe
    Ok "state dir writable: $state"
} catch {
    Bad "state dir not writable: $state — stateful hooks (loop alarm, compaction save) will be inert"
}

Write-Host ""
if ($script:fail -ne 0) {
    Write-Host "DOCTOR: FAILED — fix the FAIL lines above, then re-run."
    exit 1
}
Write-Host "DOCTOR: installation verified. Final live check (needs a real session):"
Write-Host "  ask a fresh session to 'quote the first bullet of your Evidence before claims doctrine'."
exit 0
