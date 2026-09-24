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
      - templates/settings.example.json
                                       -> ~/.claude/settings.example.json

    Your live ~/.claude/CLAUDE.md, ~/.claude/settings.json, and ~/.claude/hooks/
    contents are never touched. Nudge alerts live in
    ~/.claude/clayworks-lite/nudge/ and survive reinstall and uninstall.

.PARAMETER DryRun
    Show what would change without writing anything.

.PARAMETER Uninstall
    Remove LITE-shipped files, skipping any you've customized.

.PARAMETER Verify
    Check the install: file presence, Python + sqlite3, template JSON.

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
# PID suffix protects against directory collision if two installers run in
# the same second (rare, but possible from CI matrices or scripted retries).
$Timestamp  = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$PID"
$BackupDir  = Join-Path $BackupRoot $Timestamp

# Absolute, normalized form of a path that may not exist yet, for comparing
# paths. I resolve relative paths against the PowerShell location, not the
# process working dir, which can differ.
function Get-NormalizedPath {
    param([string]$Path)
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    return [System.IO.Path]::GetFullPath($full).TrimEnd('\', '/')
}

function Test-PathWithin {
    # True if Path is Dir or lies inside it. Windows paths compare
    # case-insensitively.
    param([string]$Path, [string]$Dir)
    $p = Get-NormalizedPath $Path
    $d = Get-NormalizedPath $Dir
    $cmp = [System.StringComparison]::Ordinal
    if ([System.Environment]::OSVersion.Platform -eq 'Win32NT') {
        $cmp = [System.StringComparison]::OrdinalIgnoreCase
    }
    return $p.Equals($d, $cmp) -or $p.StartsWith($d + [System.IO.Path]::DirectorySeparatorChar, $cmp)
}

function Test-NudgeStoreRel {
    # True if Rel (a /-separated relpath inside the Nudge skill dir) is one of
    # NudgeStoreRels or its -wal / -shm sidecar. Windows paths compare
    # case-insensitively.
    param([string]$Rel)
    $cmp = [System.StringComparison]::Ordinal
    if ([System.Environment]::OSVersion.Platform -eq 'Win32NT') {
        $cmp = [System.StringComparison]::OrdinalIgnoreCase
    }
    foreach ($s in $NudgeStoreRels) {
        foreach ($candidate in @($s, "$s-wal", "$s-shm")) {
            if ($Rel.Equals($candidate, $cmp)) { return $true }
        }
    }
    return $false
}

function ConvertTo-PSLiteral {
    # A single-quoted PowerShell literal for Text, so a path like O'Brien
    # pastes back safely.
    param([string]$Text)
    return "'" + $Text.Replace("'", "''") + "'"
}

# Nudge alerts: the same DB path nudge_db.py resolves for a script install
# into ClaudeDir, with a leading ~ expanded the way nudge_db.py does it. The
# runtime merges every *.db in the nudge-import dir next to the DB on its next
# run, so I hand a legacy DB over by dropping it there; I never merge myself.
# NudgeMarkerDir is always under ClaudeDir, even with an override: the
# runtime uses it to recognize a script-install root.
# I trim the override the way the runtime's .strip() does, so a whitespace-only
# value counts as unset in both places.
$NudgeDbOverride = if ($env:CLAYWORKS_NUDGE_DB) { $env:CLAYWORKS_NUDGE_DB.Trim() } else { '' }
if ($NudgeDbOverride) {
    $NudgeDb = $NudgeDbOverride
} else {
    $NudgeDb = Join-Path $ClaudeDir "clayworks-lite/nudge/alerts.db"
}
if ($NudgeDb -eq '~' -or $NudgeDb -match '^~[\\/]') {
    $NudgeDb = $HOME + $NudgeDb.Substring(1)
}
$NudgeDbDir = Split-Path -Parent $NudgeDb
if (-not $NudgeDbDir) { $NudgeDbDir = "." }
$NudgeMarkerDir = Join-Path $ClaudeDir "clayworks-lite/nudge"
$NudgeSkillDir  = Join-Path $ClaudeDir "skills/clayworks-lite-nudge"
$NudgeImportDir = Join-Path $NudgeDbDir "nudge-import"
# Alert stores that live inside the Nudge skill dir, as relpaths from it:
# where 1.0.x kept the DB, plus the CLAYWORKS_NUDGE_DB file when it points in
# there. Install replaces that dir and uninstall removes it, so I hand every
# one of them to nudge-import/ first.
$NudgeStoreRels = [System.Collections.Generic.List[string]]::new()
$NudgeStoreRels.Add("scripts/alerts.db")
# If CLAYWORKS_NUDGE_DB points inside the Nudge skill dir, a nudge-import dir
# next to it would go down with that dir. I fall back to the default Nudge
# dir and warn.
$NudgeDbInSkill = (Test-PathWithin $NudgeDb $NudgeSkillDir) -or (Test-PathWithin $NudgeImportDir $NudgeSkillDir)
if ($NudgeDbInSkill) {
    $NudgeImportDir = Join-Path $NudgeMarkerDir "nudge-import"
    $dbNorm    = Get-NormalizedPath $NudgeDb
    $skillNorm = Get-NormalizedPath $NudgeSkillDir
    if ($dbNorm.Length -gt $skillNorm.Length + 1 -and (Test-PathWithin $NudgeDb $NudgeSkillDir)) {
        $dbRel = $dbNorm.Substring($skillNorm.Length + 1).Replace('\', '/')
        if (-not (Test-NudgeStoreRel $dbRel)) { $NudgeStoreRels.Add($dbRel) }
    }
}

function Write-NudgeDbWarning {
    if (-not $NudgeDbInSkill) { return }
    Write-Host "  WARNING: CLAYWORKS_NUDGE_DB ($NudgeDb) points inside $NudgeSkillDir," -ForegroundColor Yellow
    Write-Host "  which install replaces and uninstall removes. I hand its alerts to" -ForegroundColor Yellow
    Write-Host "  $NudgeImportDir instead. Point CLAYWORKS_NUDGE_DB somewhere else." -ForegroundColor Yellow
}

# .installer/shipped-hashes.txt lists "<installed-relpath><TAB><sha256>" for
# every version of every file LITE ever shipped (tools/gen-shipped-hashes.py
# writes it from git history). Uninstall uses it to recognize an older
# version's files as mine to remove.
$ShippedManifest = Join-Path $RepoRoot ".installer/shipped-hashes.txt"
$ShippedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
if (Test-Path -LiteralPath $ShippedManifest -PathType Leaf) {
    foreach ($line in [System.IO.File]::ReadAllLines($ShippedManifest)) {
        if ($line -and -not $line.StartsWith('#')) { [void]$ShippedSet.Add($line) }
    }
}

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

# --- Python discovery --------------------------------------------------------
# The Nudge scripts need Python 3.10+. On Windows the executable is often
# `python` or the `py` launcher rather than `python3`, and `python3` may be a
# Microsoft Store alias that only prints an install hint, so probe each one.

function Find-Python {
    $probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    $candidates = @(
        @{ Name = 'python3'; Extra = @() },
        @{ Name = 'python';  Extra = @() },
        @{ Name = 'py';      Extra = @('-3') }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Name -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $cmd) { continue }
        $extra = $c.Extra
        try {
            & $cmd.Source @extra -c $probe 2>$null | Out-Null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{
                Exe   = $cmd.Source
                Extra = $extra
                Label = (@($c.Name) + $extra) -join ' '
            }
        }
    }
    return $null
}

# --- Hashing -----------------------------------------------------------------

function Get-PathHash {
    # SkipNudgeStores leaves the Nudge alert stores out (see Test-NudgeStoreRel).
    param([string]$Path, [switch]$SkipNudgeStores)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
    # Directory: concat sorted "relpath:filehash" lines, then hash that string.
    # -Name yields paths relative to $Path. Slicing FullName by $Path.Length
    # breaks when $Path holds an 8.3 short name (e.g. C:\Users\RUNNER~1\...,
    # the default %TEMP% form): Get-ChildItem expands it, so the lengths differ.
    $entries = [System.Collections.Generic.List[string]]::new()
    Get-ChildItem -LiteralPath $Path -Recurse -File -Name | Sort-Object | ForEach-Object {
        $rel = $_.Replace('\','/')
        if ($SkipNudgeStores -and (Test-NudgeStoreRel $rel)) { return }
        $h   = (Get-FileHash -LiteralPath (Join-Path $Path $_) -Algorithm SHA256).Hash
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

# --- Nudge alerts DB: hand a pre-1.1.0 DB to the runtime --------------------
# Before 1.1.0 the Nudge DB lived inside the skill dir, which install replaces
# wholesale and uninstall removes. I move that legacy DB into nudge-import/
# before either one touches the skill dir, and the runtime merges it into the
# stable DB on its next run. I never merge, and I never skip the move because
# the stable DB already exists: a legacy DB left behind would end up in a
# backup folder or deleted.
# I don't touch ACLs here: a new dir inherits them from its parent, and a
# shared dir that CLAYWORKS_NUDGE_DB points into keeps its owner's settings.

function Move-NudgeStore {
    # Move one alert store, plus its -wal / -shm sidecars, to
    # nudge-import/legacy-<timestamp>-<pid>.db, where Nudge merges it.
    param([string]$StorePath, [string]$Label)
    $target = Join-Path $NudgeImportDir "legacy-$Timestamp.db"
    $n = 1
    while (Test-Path -LiteralPath $target) {
        $target = Join-Path $NudgeImportDir "legacy-$Timestamp-$n.db"
        $n++
    }
    if ($DryRun) {
        Write-Updated "would move $Label -> $target (Nudge merges it on its next run)"
        return
    }
    if (-not (Test-Path -LiteralPath $NudgeImportDir)) {
        New-Item -ItemType Directory -Path $NudgeImportDir -Force | Out-Null
    }
    Move-Item -LiteralPath $StorePath -Destination $target
    foreach ($ext in @("-wal", "-shm")) {
        if (Test-Path -LiteralPath "$StorePath$ext" -PathType Leaf) {
            Move-Item -LiteralPath "$StorePath$ext" -Destination "$target$ext"
        }
    }
    Write-Updated "moved $Label -> $target (Nudge merges it on its next run)"
}

function Move-NudgeStoreSet {
    # Hand every alert store inside SkillDir to nudge-import/. Returns $false
    # if there was none.
    param([string]$SkillDir)
    $found = $false
    foreach ($s in $NudgeStoreRels) {
        $storePath = Join-Path $SkillDir $s
        if (Test-Path -LiteralPath $storePath -PathType Leaf) {
            Move-NudgeStore -StorePath $storePath -Label $s
            $found = $true
        }
    }
    return $found
}

# --- Uninstall + Verify -----------------------------------------------------

$script:Kept = 0

function Test-ShippedVersion {
    # True if DestPath holds nothing but files some LITE version shipped at
    # the same installed path, apart from the Nudge alert stores when
    # SkipNudgeStores is set. I also skip __pycache__/ and *.pyc, which 1.0.x
    # left behind by running Python from inside the skill dir. A symlink or
    # junction, an extra file, or an edited file means you touched it, so the
    # answer is no.
    param([string]$DestPath, [string]$InstalledRel, [switch]$SkipNudgeStores)
    if ($ShippedSet.Count -eq 0) { return $false }
    $item = Get-Item -LiteralPath $DestPath -Force
    if ($item.LinkType) { return $false }
    if (-not $item.PSIsContainer) {
        $hash = (Get-FileHash -LiteralPath $DestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        return $ShippedSet.Contains("$InstalledRel`t$hash")
    }
    $links = Get-ChildItem -LiteralPath $DestPath -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.LinkType }
    if ($links) { return $false }
    # -Name yields paths relative to DestPath (see Get-PathHash for why).
    foreach ($rel in (Get-ChildItem -LiteralPath $DestPath -Recurse -File -Force -Name)) {
        $relPosix = $rel.Replace('\', '/')
        if ($relPosix -match '(^|/)__pycache__/' -or $relPosix.EndsWith('.pyc')) { continue }
        if ($SkipNudgeStores -and (Test-NudgeStoreRel $relPosix)) { continue }
        $hash = (Get-FileHash -LiteralPath (Join-Path $DestPath $rel) -Algorithm SHA256).Hash.ToLowerInvariant()
        if (-not $ShippedSet.Contains("$InstalledRel/$relPosix`t$hash")) { return $false }
    }
    return $true
}

function Uninstall-LiteItem {
    # Remove DestPath if it matches the current source, or failing that, if
    # every file in it matches some shipped version. Otherwise keep it and
    # count it. SkipNudgeStores marks the Nudge skill dir: I leave its alert
    # stores (NudgeStoreRels) out of that decision. When DestPath goes, I
    # hand them to the nudge-import dir first; when DestPath stays, they stay
    # with it, because the retained 1.0.x scripts still read them there.
    param([string]$DestPath, [string]$SourcePath, [string]$Label, [string]$InstalledRel, [switch]$SkipNudgeStores)

    if (-not (Test-Path -LiteralPath $DestPath)) {
        Write-SkippedM "${Label}: not present (already uninstalled)"
        return
    }

    if ((Test-Path -LiteralPath $SourcePath) -and
        ((Get-PathHash $SourcePath -SkipNudgeStores:$SkipNudgeStores) -eq
         (Get-PathHash $DestPath -SkipNudgeStores:$SkipNudgeStores))) {
        $how = "removed"
    } elseif (Test-ShippedVersion -DestPath $DestPath -InstalledRel $InstalledRel -SkipNudgeStores:$SkipNudgeStores) {
        $how = "removed (matches a shipped LITE version)"
    } else {
        Write-Updated "${Label}: customized (differs from every shipped version) -- SKIPPING; remove manually if you want"
        $script:Kept++
        return
    }

    if ($SkipNudgeStores) {
        [void](Move-NudgeStoreSet -SkillDir $DestPath)
    }
    if (-not $DryRun) {
        Remove-Item -LiteralPath $DestPath -Recurse -Force
    }
    Write-Added "${Label}: $how"
}

function Invoke-Uninstall {
    Write-Host ""
    Write-Host "Clayworks LITE uninstaller" -ForegroundColor Cyan
    Write-Host ("=" * 60)
    Write-Info "Source repo  : $RepoRoot"
    Write-Info "Install root : $ClaudeDir"
    if ($DryRun) { Write-Info "Mode         : DRY RUN (no changes written)" }
    else         { Write-Info "Mode         : LIVE" }
    Write-NudgeDbWarning

    Write-Section "Removing LITE skills"
    $skillsSrc = Join-Path $RepoRoot "plugin/skills"
    $skillsDest = Join-Path $ClaudeDir "skills"
    # Every skill the current tree ships, plus any an older version shipped.
    $skillNames = [System.Collections.Generic.SortedSet[string]]::new([System.StringComparer]::Ordinal)
    if (Test-Path -LiteralPath $skillsSrc) {
        Get-ChildItem -LiteralPath $skillsSrc -Directory |
            Where-Object { $_.Name -like "clayworks-lite-*" } |
            ForEach-Object { [void]$skillNames.Add($_.Name) }
    }
    foreach ($entry in $ShippedSet) {
        if ($entry -match '^skills/(clayworks-lite-[^/\t]+)/') { [void]$skillNames.Add($Matches[1]) }
    }
    foreach ($name in $skillNames) {
        # A Nudge skill dir may still hold alert stores, which I leave out of
        # the keep-or-remove decision.
        Uninstall-LiteItem `
            -DestPath        (Join-Path $skillsDest $name) `
            -SourcePath      (Join-Path $skillsSrc $name) `
            -Label           "skill: $name" `
            -InstalledRel    "skills/$name" `
            -SkipNudgeStores:($name -eq "clayworks-lite-nudge")
    }

    Write-Section "Removing hook examples"
    Uninstall-LiteItem `
        -DestPath     (Join-Path $ClaudeDir "hooks/examples") `
        -SourcePath   (Join-Path $RepoRoot "plugin/hooks/examples") `
        -Label        "hooks/examples" `
        -InstalledRel "hooks/examples"

    Write-Section "Removing CLAUDE.md starter template"
    Uninstall-LiteItem `
        -DestPath     (Join-Path $ClaudeDir "CLAUDE.md.clayworks-template") `
        -SourcePath   (Join-Path $RepoRoot "plugin/templates/CLAUDE.md.clayworks-template") `
        -Label        "CLAUDE.md.clayworks-template" `
        -InstalledRel "CLAUDE.md.clayworks-template"

    Write-Section "Removing settings.example.json"
    Uninstall-LiteItem `
        -DestPath     (Join-Path $ClaudeDir "settings.example.json") `
        -SourcePath   (Join-Path $RepoRoot "plugin/templates/settings.example.json") `
        -Label        "settings.example.json" `
        -InstalledRel "settings.example.json"

    Write-Section "Did NOT touch"
    Write-Info "  $(Join-Path $ClaudeDir 'CLAUDE.md') (your live config)"
    Write-Info "  $(Join-Path $ClaudeDir 'settings.json') (your live config)"
    Write-Info "  $(Join-Path $ClaudeDir 'hooks/')  (excluding examples/ subdir)"
    Write-Info "  $NudgeDb and $NudgeImportDir (your Nudge alerts -- remove manually if desired)"
    Write-Info "  $BackupRoot (your backups -- remove manually)"

    Write-Section "Next steps"
    @"
If you wired Nudge or other LITE hooks into $(Join-Path $ClaudeDir 'settings.json'),
remove those entries manually. The uninstaller can't safely edit
your settings.json -- JSON parsing of an arbitrary user file would
be too fragile. A leftover Nudge hook entry points at a launcher
that no longer exists, so it shows a hook error on every prompt.

To purge the backup folder and your Nudge alerts:
"@ | Write-Host
    # I list only paths LITE owns. An override's DB may sit in a shared dir,
    # so I name the DB file and the nudge-import dir, never their parent.
    # -LiteralPath keeps [ ] in a path from acting as a wildcard.
    $liteDir = Join-Path $ClaudeDir "clayworks-lite"
    Write-Host "  Remove-Item -Recurse -Force -LiteralPath $(ConvertTo-PSLiteral $BackupRoot)"
    Write-Host "  Remove-Item -Recurse -Force -LiteralPath $(ConvertTo-PSLiteral $liteDir)"
    if (-not (Test-PathWithin $NudgeDb $liteDir)) {
        Write-Host "  Remove-Item -Force -LiteralPath $(ConvertTo-PSLiteral $NudgeDb)"
    }
    if (-not (Test-PathWithin $NudgeImportDir $liteDir)) {
        Write-Host "  Remove-Item -Recurse -Force -LiteralPath $(ConvertTo-PSLiteral $NudgeImportDir)"
    }

    Write-Host ""
    if ($DryRun) { Write-Host "DRY RUN - nothing removed." -ForegroundColor Cyan }
    if ($script:Kept -gt 0) {
        Write-Host "Uninstall finished; $($script:Kept) item(s) kept because they differ from any shipped version." -ForegroundColor Yellow
    } else {
        Write-Host "Uninstall complete." -ForegroundColor Green
    }
}

$script:VerifyFails = 0

function Test-Check {
    param([string]$Label, [string]$Status, [string]$Detail)
    switch ($Status) {
        "pass" { Write-Added "${Label}: ${Detail}" }
        "warn" { Write-Updated "${Label}: ${Detail}" }
        "skip" { Write-SkippedM "${Label}: ${Detail}" }
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
    $py = Find-Python
    if ($py) {
        $pyExtra = $py.Extra
        $ver = & $py.Exe @pyExtra --version 2>&1
        Test-Check "python ($($py.Label))" "pass" "$ver"
        if ($py.Label -ne 'python3') {
            Test-Check "python3 name" "warn" "not on PATH; the Nudge hook launcher falls back to '$($py.Label)', but the hook examples call python3 by name"
        }
        try { & $py.Exe @pyExtra -c "import sqlite3" 2>$null | Out-Null } catch { $null = $_ }
        if ($LASTEXITCODE -eq 0) {
            Test-Check "python sqlite3 import" "pass" "ok"
        } else {
            Test-Check "python sqlite3 import" "fail" "cannot import -- Nudge skill will not work"
        }
    } else {
        Test-Check "python" "warn" "no Python 3.10+ found (tried python3, python, py -3) -- Nudge skill + hook examples will not work until you install one"
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

    Write-Section "Nudge hook launcher"
    $nudgeDir = Join-Path $ClaudeDir "skills/clayworks-lite-nudge/scripts"
    foreach ($nf in @("run-python.sh", "nudge_db.py", "check_alerts.py")) {
        $nfPath = Join-Path $nudgeDir $nf
        if (Test-Path -LiteralPath $nfPath) {
            Test-Check "nudge/scripts/$nf" "pass" "present"
        } else {
            Test-Check "nudge/scripts/$nf" "fail" "missing at $nfPath"
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

Write-Section "Nudge alerts database"
Write-NudgeDbWarning
# I always create the default Nudge dir: the runtime treats it as the sign
# that this root holds a script install.
if (Test-Path -LiteralPath $NudgeMarkerDir -PathType Container) {
    Write-SkippedM "${NudgeMarkerDir}: already present"
} elseif ($DryRun) {
    Write-Added "would create $NudgeMarkerDir"
} else {
    New-Item -ItemType Directory -Path $NudgeMarkerDir -Force | Out-Null
    Write-Added "created $NudgeMarkerDir"
}
# Hand every alert store in the skill dir to the runtime before I replace it.
if (-not (Move-NudgeStoreSet -SkillDir $NudgeSkillDir)) {
    Write-SkippedM "nothing to migrate (alerts live in $NudgeDb)"
}

# --- Install items -----------------------------------------------------------

Write-Section "Installing skills"
$skillsSrc  = Join-Path $RepoRoot "plugin/skills"
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
    -SourcePath (Join-Path $RepoRoot "plugin/hooks/examples") `
    -DestPath   (Join-Path $ClaudeDir "hooks/examples") `
    -Label      "hooks/examples" `
    -BackupRel  "hooks/examples"

Write-Section "Installing CLAUDE.md starter template"
Install-LiteItem `
    -SourcePath (Join-Path $RepoRoot "plugin/templates/CLAUDE.md.clayworks-template") `
    -DestPath   (Join-Path $ClaudeDir "CLAUDE.md.clayworks-template") `
    -Label      "CLAUDE.md.clayworks-template" `
    -BackupRel  "CLAUDE.md.clayworks-template"

Write-Section "Installing settings.example.json"
Install-LiteItem `
    -SourcePath (Join-Path $RepoRoot "plugin/templates/settings.example.json") `
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
1. Claude Code picks up new skills in a running session. If
     ~/.claude/skills/ didn't exist before this install, start a new
     session so Claude Code can watch the new directory.

2. To use the CLAUDE.md starter template:
     copy ~/.claude/CLAUDE.md.clayworks-template -> ~/.claude/CLAUDE.md
     (back up any existing ~/.claude/CLAUDE.md first)
     then edit the <YOUR ...> placeholders.

3. To use the nudge skill (if installed):
     the skill auto-triggers when you mention a time
     ("stop me at 5pm", "remind me about standup at 9:55").
     For nudges to actually fire, add the UserPromptSubmit hook from
     ~/.claude/settings.example.json to ~/.claude/settings.json
     (details in ~/.claude/skills/clayworks-lite-nudge/SKILL.md).
     The hook needs bash, which Git for Windows provides; Claude Code
     uses the same Git Bash to run hooks. Claude Code applies
     settings.json edits without a restart. Skip this if you also
     installed LITE as a plugin: the plugin registers the same hook,
     and you'd see every alert twice.

4. To use a hook example:
     copy ~/.claude/hooks/examples/<event>.sh -> ~/.claude/hooks/<name>.sh
     customize, then register it in ~/.claude/settings.json (see the README
     inside the examples/ dir).

Verify the install:
     ls ~/.claude/skills/clayworks-lite-*/
"@ | Write-Host

Write-Host ""
Write-Host "Done." -ForegroundColor Green
