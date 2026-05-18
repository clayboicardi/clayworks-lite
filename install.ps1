#Requires -Version 5.1

<#
.SYNOPSIS
    Clayworks LITE installer for Windows (PowerShell 5.1+).

.DESCRIPTION
    Installs the Clayworks LITE components into ~/.claude/ without clobbering
    your existing setup. Any file the installer is about to overwrite is first
    copied to ~/.claude/.clayworks-lite-backup/<timestamp>/.

    What gets installed:
      - skills/clayworks-lite-*/       -> ~/.claude/skills/
      - hooks/examples/                -> ~/.claude/hooks/examples/
      - templates/CLAUDE.md.clayworks-template
                                       -> ~/.claude/CLAUDE.md.clayworks-template

    Your live ~/.claude/CLAUDE.md and ~/.claude/hooks/ contents are never touched.

.PARAMETER DryRun
    Show what would change without writing anything.

.PARAMETER ClaudeDir
    Install root. Defaults to ~/.claude. Override for testing.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -DryRun
    .\install.ps1 -ClaudeDir C:\tmp\test-claude
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Uninstall,
    [switch]$Verify,
    [string]$ClaudeDir = (Join-Path $HOME ".claude")
)

$ErrorActionPreference = "Stop"

# --- Paths -------------------------------------------------------------------

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }

$BackupRoot = Join-Path $ClaudeDir ".clayworks-lite-backup"
$Timestamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir  = Join-Path $BackupRoot $Timestamp

# --- State -------------------------------------------------------------------

$Installed  = [System.Collections.Generic.List[string]]::new()
$Updated    = [System.Collections.Generic.List[string]]::new()
$SkippedSet = [System.Collections.Generic.List[string]]::new()
$BackupRefs = [System.Collections.Generic.List[string]]::new()

# --- Output helpers ----------------------------------------------------------

function Write-Section { param([string]$Text)
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}
function Write-Info     { param([string]$Text) Write-Host "    $Text" }
function Write-Added    { param([string]$Text) Write-Host "  + $Text" -ForegroundColor Green }
function Write-Updated  { param([string]$Text) Write-Host "  ~ $Text" -ForegroundColor Yellow }
function Write-SkippedM { param([string]$Text) Write-Host "  - $Text" -ForegroundColor DarkGray }

# --- Hashing -----------------------------------------------------------------

function Get-PathHash {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
    # Directory: concat sorted "relpath:filehash" lines, then hash that string.
    $entries = [System.Collections.Generic.List[string]]::new()
    Get-ChildItem -LiteralPath $Path -Recurse -File | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($Path.Length).TrimStart('\','/').Replace('\','/')
        $h   = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        $entries.Add("${rel}:${h}")
    }
    $joined = ($entries -join "`n")
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($joined)
    $sha    = [System.Security.Cryptography.SHA256]::Create()
    $hash   = $sha.ComputeHash($bytes)
    return -join ($hash | ForEach-Object { $_.ToString("x2") })
}

# --- Operations --------------------------------------------------------------

function Backup-Path {
    param([string]$DestPath, [string]$RelBackup)
    $target = Join-Path $BackupDir $RelBackup
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Copy-Item -LiteralPath $DestPath -Destination $target -Recurse -Force
    $BackupRefs.Add($target)
}

function Test-NoSymlinksInSource {
    # Supply-chain hardening: refuse to install a source tree containing symlinks
    # or junctions. A tampered clone could include symlinks pointing at sensitive
    # files (e.g., %USERPROFILE%\.ssh\id_ed25519) and Copy-Item would follow them,
    # writing the target's contents into ~/.claude/ as regular files - a
    # predictable exfil channel. An honest LITE source tree has no symlinks.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $links = Get-ChildItem -LiteralPath $Path -Recurse -Force `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.LinkType -in 'SymbolicLink', 'Junction' }
    if ($links) {
        Write-Host ""
        Write-Host "ERROR: source tree contains symlinks/junctions (potential supply-chain risk):" -ForegroundColor Red
        foreach ($l in $links) { Write-Host "  $($l.FullName)" -ForegroundColor Red }
        Write-Host ""
        Write-Host "The LITE source tree should contain no symlinks. If you cloned from"
        Write-Host "github.com/clayboicardi/clayworks-lite and see this error, your"
        Write-Host "working copy may have been tampered with. Re-clone before installing."
        exit 4
    }
}

function Install-LiteItem {
    param(
        [string]$SourcePath,
        [string]$DestPath,
        [string]$Label,
        [string]$BackupRel
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        Write-SkippedM "${Label}: source missing in repo (skipped)"
        return
    }

    $destParent = Split-Path -Parent $DestPath
    if (-not (Test-Path -LiteralPath $destParent)) {
        if (-not $DryRun) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }
    }

    if (-not (Test-Path -LiteralPath $DestPath)) {
        if (-not $DryRun) {
            Copy-Item -LiteralPath $SourcePath -Destination $DestPath -Recurse -Force
        }
        Write-Added "${Label} -> $DestPath"
        $Installed.Add($Label)
        return
    }

    $srcHash  = Get-PathHash $SourcePath
    $destHash = Get-PathHash $DestPath

    if ($srcHash -eq $destHash) {
        Write-SkippedM "${Label}: already installed and unchanged"
        $SkippedSet.Add($Label)
        return
    }

    if (-not $DryRun) {
        Backup-Path -DestPath $DestPath -RelBackup $BackupRel
        Remove-Item -LiteralPath $DestPath -Recurse -Force
        Copy-Item -LiteralPath $SourcePath -Destination $DestPath -Recurse -Force
    }
    Write-Updated "${Label}: differed from source -> backed up + reinstalled"
    $Updated.Add($Label)
}

# --- Uninstall + Verify -----------------------------------------------------

function Uninstall-LiteItem {
    param([string]$DestPath, [string]$SourcePath, [string]$Label)

    if (-not (Test-Path -LiteralPath $DestPath)) {
        Write-SkippedM "${Label}: not present (already uninstalled)"
        return
    }

    if (Test-Path -LiteralPath $SourcePath) {
        $srcHash  = Get-PathHash $SourcePath
        $destHash = Get-PathHash $DestPath
        if ($srcHash -ne $destHash) {
            Write-Updated "${Label}: customized (hash differs from source) -- SKIPPING; remove manually if you want"
            return
        }
    }

    if (-not $DryRun) {
        Remove-Item -LiteralPath $DestPath -Recurse -Force
    }
    Write-Added "${Label}: removed"
}

function Invoke-Uninstall {
    Write-Host ""
    Write-Host "Clayworks LITE uninstaller" -ForegroundColor Cyan
    Write-Host ("=" * 60)
    Write-Info "Source repo  : $RepoRoot"
    Write-Info "Install root : $ClaudeDir"
    if ($DryRun) { Write-Info "Mode         : DRY RUN (no changes written)" }
    else         { Write-Info "Mode         : LIVE" }

    Write-Section "Removing LITE skills"
    $skillsSrc = Join-Path $RepoRoot "skills"
    $skillsDest = Join-Path $ClaudeDir "skills"
    if (Test-Path -LiteralPath $skillsSrc) {
        $skillDirs = Get-ChildItem -LiteralPath $skillsSrc -Directory |
            Where-Object { $_.Name -like "clayworks-lite-*" } |
            Sort-Object Name
        foreach ($d in $skillDirs) {
            Uninstall-LiteItem `
                -DestPath   (Join-Path $skillsDest $d.Name) `
                -SourcePath $d.FullName `
                -Label      "skill: $($d.Name)"
        }
    }

    Write-Section "Removing hook examples"
    Uninstall-LiteItem `
        -DestPath   (Join-Path $ClaudeDir "hooks/examples") `
        -SourcePath (Join-Path $RepoRoot "hooks/examples") `
        -Label      "hooks/examples"

    Write-Section "Removing CLAUDE.md starter template"
    Uninstall-LiteItem `
        -DestPath   (Join-Path $ClaudeDir "CLAUDE.md.clayworks-template") `
        -SourcePath (Join-Path $RepoRoot "templates/CLAUDE.md.clayworks-template") `
        -Label      "CLAUDE.md.clayworks-template"

    Write-Section "Removing settings.example.json"
    Uninstall-LiteItem `
        -DestPath   (Join-Path $ClaudeDir "settings.example.json") `
        -SourcePath (Join-Path $RepoRoot "templates/settings.example.json") `
        -Label      "settings.example.json"

    Write-Section "Did NOT touch"
    Write-Info "  $(Join-Path $ClaudeDir 'CLAUDE.md') (your live config)"
    Write-Info "  $(Join-Path $ClaudeDir 'settings.json') (your live config)"
    Write-Info "  $(Join-Path $ClaudeDir 'hooks/')  (excluding examples/ subdir)"
    Write-Info "  $(Join-Path $ClaudeDir '.clayworks-lite-backup/') (your backups -- remove manually)"

    Write-Section "Next steps"
    @"
If you wired Nudge or other LITE hooks into ~/.claude/settings.json,
remove those entries manually. The uninstaller can't safely edit
your settings.json -- JSON parsing of an arbitrary user file would
be too fragile.

To purge the backup folder:
  Remove-Item -Recurse -Force "$(Join-Path $ClaudeDir '.clayworks-lite-backup')"
"@ | Write-Host

    Write-Host ""
    Write-Host "Uninstall complete." -ForegroundColor Green
}

$script:VerifyFails = 0

function Test-Check {
    param([string]$Label, [string]$Status, [string]$Detail)
    switch ($Status) {
        "pass" { Write-Added "${Label}: ${Detail}" }
        "warn" { Write-Updated "${Label}: ${Detail}" }
        "fail" {
            Write-Host "  ? ${Label}: ${Detail}" -ForegroundColor Yellow
            $script:VerifyFails++
        }
    }
}

function Invoke-Verify {
    Write-Host ""
    Write-Host "Clayworks LITE -- verify install" -ForegroundColor Cyan
    Write-Host ("=" * 60)
    Write-Info "Install root : $ClaudeDir"
    $script:VerifyFails = 0

    Write-Section "Runtime"
    $py3 = Get-Command python3 -ErrorAction SilentlyContinue
    if (-not $py3) { $py3 = Get-Command python -ErrorAction SilentlyContinue }
    if ($py3) {
        $ver = & $py3.Source --version 2>&1
        Test-Check "python3" "pass" "$ver"
        & $py3.Source -c "import sqlite3" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Test-Check "python3 sqlite3 import" "pass" "ok"
        } else {
            Test-Check "python3 sqlite3 import" "fail" "cannot import -- Nudge skill will not work"
        }
    } else {
        Test-Check "python3" "fail" "not on PATH -- Nudge skill + hook examples will not work"
    }
    $cc = Get-Command claude -ErrorAction SilentlyContinue
    if ($cc) {
        $ccVer = & $cc.Source --version 2>&1 | Select-Object -First 1
        Test-Check "claude" "pass" "$ccVer"
    } else {
        Test-Check "claude" "warn" "not on PATH (CC may be installed but invoked differently)"
    }

    Write-Section "Skills"
    foreach ($s in @("clayworks-lite-nudge","clayworks-lite-memory-routing","clayworks-lite-heartbeat-concept")) {
        $f = Join-Path $ClaudeDir "skills/$s/SKILL.md"
        if (Test-Path -LiteralPath $f) {
            $first = (Get-Content -LiteralPath $f -TotalCount 1)
            if ($first -eq "---") {
                Test-Check $s "pass" "SKILL.md present + frontmatter ok"
            } else {
                Test-Check $s "fail" "SKILL.md present but frontmatter missing/malformed"
            }
        } else {
            Test-Check $s "fail" "SKILL.md missing at $f"
        }
    }

    Write-Section "Hook examples"
    foreach ($h in @("userpromptsubmit","pretooluse","posttooluse","sessionstart","sessionend","stop","subagentstart","subagentstop")) {
        $f = Join-Path $ClaudeDir "hooks/examples/$h.sh"
        if (Test-Path -LiteralPath $f) {
            $first = (Get-Content -LiteralPath $f -TotalCount 1)
            if ($first -eq "#!/usr/bin/env bash") {
                Test-Check "hooks/examples/$h.sh" "pass" "present + shebang ok"
            } else {
                Test-Check "hooks/examples/$h.sh" "fail" "present but shebang missing/corrupt (LF vs CRLF?)"
            }
        } else {
            Test-Check "hooks/examples/$h.sh" "fail" "missing"
        }
    }

    Write-Section "Templates"
    $tmpl = Join-Path $ClaudeDir "CLAUDE.md.clayworks-template"
    if (Test-Path -LiteralPath $tmpl) {
        Test-Check "CLAUDE.md.clayworks-template" "pass" "present"
    } else {
        Test-Check "CLAUDE.md.clayworks-template" "fail" "missing at $tmpl"
    }
    $setj = Join-Path $ClaudeDir "settings.example.json"
    if (Test-Path -LiteralPath $setj) {
        try {
            Get-Content -LiteralPath $setj -Raw | ConvertFrom-Json | Out-Null
            Test-Check "settings.example.json" "pass" "present + valid JSON"
        } catch {
            Test-Check "settings.example.json" "fail" "present but JSON parse failed"
        }
    } else {
        Test-Check "settings.example.json" "fail" "missing at $setj"
    }

    Write-Section "Verify summary"
    if ($script:VerifyFails -eq 0) {
        Write-Host "  PASS: all checks passed" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "  WARN: $script:VerifyFails check(s) need attention" -ForegroundColor Yellow
        exit 1
    }
}

# --- Dispatch ---------------------------------------------------------------

if ($Verify)    { Invoke-Verify }
if ($Uninstall) { Invoke-Uninstall; exit 0 }

# --- Pre-flight --------------------------------------------------------------

Write-Host ""
Write-Host "Clayworks LITE installer" -ForegroundColor Cyan
Write-Host ("=" * 60)
Write-Info "Source repo  : $RepoRoot"
Write-Info "Install root : $ClaudeDir"
if ($DryRun) { Write-Info "Mode         : DRY RUN (no changes written)" }
else         { Write-Info "Mode         : LIVE" }

if (-not (Test-Path -LiteralPath $ClaudeDir)) {
    if ($DryRun) {
        Write-Info "Would create install root: $ClaudeDir"
    } else {
        New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
        Write-Info "Created install root: $ClaudeDir"
    }
}

# Supply-chain check: refuse to proceed if the source tree contains symlinks.
Test-NoSymlinksInSource -Path $RepoRoot

# --- Install items -----------------------------------------------------------

Write-Section "Installing skills"
$skillsSrc  = Join-Path $RepoRoot "skills"
$skillsDest = Join-Path $ClaudeDir "skills"
if (Test-Path -LiteralPath $skillsSrc) {
    $skillDirs = Get-ChildItem -LiteralPath $skillsSrc -Directory |
        Where-Object { $_.Name -like "clayworks-lite-*" } |
        Sort-Object Name
    if ($skillDirs.Count -eq 0) {
        Write-SkippedM "No clayworks-lite-* skills found in repo"
    } else {
        foreach ($d in $skillDirs) {
            Install-LiteItem `
                -SourcePath $d.FullName `
                -DestPath  (Join-Path $skillsDest $d.Name) `
                -Label     "skill: $($d.Name)" `
                -BackupRel "skills/$($d.Name)"
        }
    }
} else {
    Write-SkippedM "No skills/ directory in repo (nothing to install)"
}

Write-Section "Installing hook examples"
Install-LiteItem `
    -SourcePath (Join-Path $RepoRoot "hooks/examples") `
    -DestPath   (Join-Path $ClaudeDir "hooks/examples") `
    -Label      "hooks/examples" `
    -BackupRel  "hooks/examples"

Write-Section "Installing CLAUDE.md starter template"
Install-LiteItem `
    -SourcePath (Join-Path $RepoRoot "templates/CLAUDE.md.clayworks-template") `
    -DestPath   (Join-Path $ClaudeDir "CLAUDE.md.clayworks-template") `
    -Label      "CLAUDE.md.clayworks-template" `
    -BackupRel  "CLAUDE.md.clayworks-template"

Write-Section "Installing settings.example.json"
Install-LiteItem `
    -SourcePath (Join-Path $RepoRoot "templates/settings.example.json") `
    -DestPath   (Join-Path $ClaudeDir "settings.example.json") `
    -Label      "settings.example.json" `
    -BackupRel  "settings.example.json"

# --- Summary -----------------------------------------------------------------

Write-Section "Summary"
Write-Info ("Installed (new) : {0}" -f $Installed.Count)
foreach ($i in $Installed)  { Write-Host "    + $i" -ForegroundColor Green }
Write-Info ("Updated  (diff) : {0}" -f $Updated.Count)
foreach ($u in $Updated)    { Write-Host "    ~ $u" -ForegroundColor Yellow }
Write-Info ("Skipped (same)  : {0}" -f $SkippedSet.Count)
foreach ($s in $SkippedSet) { Write-Host "    - $s" -ForegroundColor DarkGray }

if ($BackupRefs.Count -gt 0) {
    Write-Host ""
    Write-Host "Backups written to:" -ForegroundColor Cyan
    Write-Host "  $BackupDir"
    Write-Host "If you had local edits, they're preserved there."
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN COMPLETE - no files written." -ForegroundColor Cyan
    Write-Host "Re-run without -DryRun to actually install."
    exit 0
}

# --- Next steps --------------------------------------------------------------

Write-Section "Next steps"
@"
1. Restart Claude Code so it picks up new skills:
     close all CC sessions, then open a fresh one.

2. To use the CLAUDE.md starter template:
     copy ~/.claude/CLAUDE.md.clayworks-template -> ~/.claude/CLAUDE.md
     (back up any existing ~/.claude/CLAUDE.md first)
     then edit the <YOUR ...> placeholders.

3. To use the nudge skill (if installed):
     the skill auto-triggers when you mention a time
     ("stop me at 5pm", "remind me about standup at 9:55").
     For nudges to actually fire, wire the UserPromptSubmit hook -
     see ~/.claude/skills/clayworks-lite-nudge/SKILL.md.

4. To use a hook example:
     copy ~/.claude/hooks/examples/<event>.sh -> ~/.claude/hooks/<name>.sh
     customize, then register it in ~/.claude/settings.json (see the README
     inside the examples/ dir).

Verify the install:
     ls ~/.claude/skills/clayworks-lite-*/
"@ | Write-Host

Write-Host ""
Write-Host "Done." -ForegroundColor Green
