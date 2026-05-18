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
