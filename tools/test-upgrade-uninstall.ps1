#Requires -Version 5.1

<#
.SYNOPSIS
    Upgrade-uninstall test for install.ps1.

.DESCRIPTION
    I install an older LITE release with ITS install.ps1, use it like a 1.0.x
    user would, then uninstall with the current install.ps1. I check that
    every untouched artifact goes away, the legacy Nudge DB moves to its
    stable home first, and anything you edited or added stays put.

    Needs the old ref in local history (CI: actions/checkout fetch-depth: 0).

.PARAMETER OldRef
    The release to upgrade from. Defaults to v1.0.1.
#>

[CmdletBinding()]
param([string]$OldRef = "v1.0.1")

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Work     = Join-Path ([System.IO.Path]::GetTempPath()) "cw-upgrade-$PID"
$OldTree  = Join-Path $Work "old"
New-Item -ItemType Directory -Path $Work -Force | Out-Null

# The test asserts the default DB location, so an override would break it.
Remove-Item Env:\CLAYWORKS_NUDGE_DB -ErrorAction SilentlyContinue

$script:Fails = 0
function Add-Failure { param([string]$Text) Write-Host "FAIL: $Text" -ForegroundColor Red; $script:Fails++ }
function Assert-Gone    { param([string]$Path) if (Test-Path -LiteralPath $Path) { Add-Failure "still present: $Path" } }
function Assert-Present { param([string]$Path) if (-not (Test-Path -LiteralPath $Path)) { Add-Failure "missing: $Path" } }

function Invoke-CurrentUninstall {
    param([string]$Target)
    $out = & (Join-Path $RepoRoot "install.ps1") -Uninstall -ClaudeDir $Target *>&1 | Out-String
    Write-Host $out
    return $out
}

try {
    git -C $RepoRoot worktree add --detach $OldTree $OldRef | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git worktree add $OldRef failed" }
    $oldInstaller = Join-Path $OldTree "install.ps1"

    # Scenario A: a 1.0.x user ran Nudge (DB + __pycache__ in the skill dir)
    # and edited one hook example. Everything else must go; the edit stays.
    $a = Join-Path $Work "claude-a"
    & $oldInstaller -ClaudeDir $a *>&1 | Out-Null
    $nudgeScripts = Join-Path $a "skills/clayworks-lite-nudge/scripts"
    [System.IO.File]::WriteAllText((Join-Path $nudgeScripts "alerts.db"), "legacy-db-bytes")
    New-Item -ItemType Directory -Path (Join-Path $nudgeScripts "__pycache__") -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $nudgeScripts "__pycache__/x.pyc"), "x")
    [System.IO.File]::AppendAllText((Join-Path $a "hooks/examples/stop.sh"), "# my edit`n")

    $outA = Invoke-CurrentUninstall $a
    foreach ($s in @("clayworks-lite-nudge", "clayworks-lite-memory-routing", "clayworks-lite-heartbeat-concept")) {
        Assert-Gone (Join-Path $a "skills/$s")
    }
    Assert-Gone (Join-Path $a "CLAUDE.md.clayworks-template")
    Assert-Gone (Join-Path $a "settings.example.json")
    $stop = Join-Path $a "hooks/examples/stop.sh"
    Assert-Present $stop
    if ((Test-Path -LiteralPath $stop) -and -not ([System.IO.File]::ReadAllText($stop).Contains("# my edit"))) {
        Add-Failure "user edit to stop.sh lost"
    }
    $movedDb = Join-Path $a "clayworks-lite/nudge/alerts.db"
    if (-not (Test-Path -LiteralPath $movedDb) -or [System.IO.File]::ReadAllText($movedDb) -ne "legacy-db-bytes") {
        Add-Failure "legacy alerts.db did not move to $movedDb"
    }
    if ($outA -notmatch "Uninstall finished; 1 item\(s\) kept") { Add-Failure "scenario A: wrong closing line" }

    # Scenario B: a file you added to a skill, and a legacy DB that can't move
    # because the stable DB already exists. Both dirs must stay.
    $b = Join-Path $Work "claude-b"
    & $oldInstaller -ClaudeDir $b *>&1 | Out-Null
    $notes = Join-Path $b "skills/clayworks-lite-memory-routing/my-notes.md"
    [System.IO.File]::WriteAllText($notes, "mine")
    $legacyB = Join-Path $b "skills/clayworks-lite-nudge/scripts/alerts.db"
    [System.IO.File]::WriteAllText($legacyB, "legacy")
    New-Item -ItemType Directory -Path (Join-Path $b "clayworks-lite/nudge") -Force | Out-Null
    $stableB = Join-Path $b "clayworks-lite/nudge/alerts.db"
    [System.IO.File]::WriteAllText($stableB, "stable")

    $outB = Invoke-CurrentUninstall $b
    Assert-Present $notes
    Assert-Present $legacyB
    Assert-Gone (Join-Path $b "skills/clayworks-lite-heartbeat-concept")
    Assert-Gone (Join-Path $b "hooks/examples")
    if ([System.IO.File]::ReadAllText($stableB) -ne "stable") { Add-Failure "stable DB was overwritten" }
    if ($outB -notmatch "Uninstall finished; 2 item\(s\) kept") { Add-Failure "scenario B: wrong closing line" }
} finally {
    # Cleanup is best-effort; a leftover temp dir must not mask the result.
    $ErrorActionPreference = "Continue"
    git -C $RepoRoot worktree remove --force $OldTree 2>&1 | Out-Null
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}

if ($script:Fails -gt 0) {
    Write-Host "upgrade-uninstall from ${OldRef}: $($script:Fails) failure(s)" -ForegroundColor Red
    exit 1
}
Write-Host "OK: upgrade-uninstall from $OldRef passed" -ForegroundColor Green
