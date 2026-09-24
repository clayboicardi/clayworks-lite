#Requires -Version 5.1

<#
.SYNOPSIS
    Upgrade and uninstall tests for install.ps1 against an older LITE release.

.DESCRIPTION
    I install that release with ITS install.ps1, use it like a 1.0.x user
    would, then run the current install.ps1 over it. I check that every
    untouched artifact goes away, that a legacy Nudge DB lands in
    nudge-import/ (where the runtime merges it) instead of in a backup or the bin, and
    that anything you edited or added stays put.

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
$Current  = Join-Path $RepoRoot "install.ps1"
New-Item -ItemType Directory -Path $Work -Force | Out-Null

# Most scenarios assert the default DB location, so an override would break
# them. The override scenario at the end sets its own.
Remove-Item Env:\CLAYWORKS_NUDGE_DB -ErrorAction SilentlyContinue

$script:Fails = 0
function Add-Failure { param([string]$Text) Write-Host "FAIL: $Text" -ForegroundColor Red; $script:Fails++ }
function Assert-Gone    { param([string]$Path) if (Test-Path -LiteralPath $Path) { Add-Failure "still present: $Path" } }
function Assert-Present { param([string]$Path) if (-not (Test-Path -LiteralPath $Path)) { Add-Failure "missing: $Path" } }

function Invoke-Current {
    param([string]$Target, [switch]$Uninstall)
    # I join the records myself: Out-String in Windows PowerShell 5.1 wraps
    # long lines at the console width, which splits the paths I assert on.
    $out = (& $Current -Uninstall:$Uninstall -ClaudeDir $Target *>&1 | ForEach-Object { "$_" }) -join "`n"
    Write-Host $out
    return $out
}

function Get-ImportedContent {
    # The content of the single legacy-*.db in a nudge-import dir, or $null.
    param([string]$Dir)
    $found = @(Get-ChildItem -LiteralPath $Dir -Filter "legacy-*.db" -File -ErrorAction SilentlyContinue)
    if ($found.Count -ne 1) {
        Add-Failure "expected exactly one legacy-*.db in $Dir, found $($found.Count)"
        return $null
    }
    return [System.IO.File]::ReadAllText($found[0].FullName)
}

function Read-Text { param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Leaf) { return [System.IO.File]::ReadAllText($Path) }
    return $null
}

try {
    git -C $RepoRoot worktree add --detach $OldTree $OldRef | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git worktree add $OldRef failed" }
    $oldInstaller = Join-Path $OldTree "install.ps1"

    # (a) + (e) A 1.0.x user ran Nudge (DB + __pycache__ in the skill dir)
    # and edited one hook example. Uninstall removes everything else, hands
    # the DB to nudge-import/, and names this root in the purge text.
    $a = Join-Path $Work "claude-a"
    & $oldInstaller -ClaudeDir $a *>&1 | Out-Null
    $nudgeScripts = Join-Path $a "skills/clayworks-lite-nudge/scripts"
    [System.IO.File]::WriteAllText((Join-Path $nudgeScripts "alerts.db"), "legacy-db-bytes")
    New-Item -ItemType Directory -Path (Join-Path $nudgeScripts "__pycache__") -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $nudgeScripts "__pycache__/x.pyc"), "x")
    [System.IO.File]::AppendAllText((Join-Path $a "hooks/examples/stop.sh"), "# my edit`n")

    $outA = Invoke-Current $a -Uninstall
    foreach ($s in @("clayworks-lite-nudge", "clayworks-lite-memory-routing", "clayworks-lite-heartbeat-concept")) {
        Assert-Gone (Join-Path $a "skills/$s")
    }
    Assert-Gone (Join-Path $a "CLAUDE.md.clayworks-template")
    Assert-Gone (Join-Path $a "settings.example.json")
    $stop = Join-Path $a "hooks/examples/stop.sh"
    Assert-Present $stop
    if (-not "$(Read-Text $stop)".Contains("# my edit")) { Add-Failure "user edit to stop.sh lost" }
    if ((Get-ImportedContent (Join-Path $a "clayworks-lite/nudge/nudge-import")) -ne "legacy-db-bytes") {
        Add-Failure "(a) legacy DB did not land in nudge-import/"
    }
    if ($outA -notmatch "Uninstall finished; 1 item\(s\) kept") { Add-Failure "(a) wrong closing line" }
    $backupLine = "Remove-Item -Recurse -Force '$(Join-Path $a '.clayworks-lite-backup')'"
    $nudgeLine  = "Remove-Item -Recurse -Force '$(Join-Path $a 'clayworks-lite')'"
    # Join-Path and Split-Path disagree on / vs \ across PowerShell versions,
    # so I compare with the separators normalized.
    $normA = $outA.Replace('/', '\')
    if (-not $normA.Contains($backupLine.Replace('/', '\'))) { Add-Failure "(e) purge text lacks this root's backup dir" }
    if (-not $normA.Contains($nudgeLine.Replace('/', '\')))  { Add-Failure "(e) purge text lacks this root's clayworks-lite dir" }
    if ($outA.Contains("~/.claude"))      { Add-Failure "(e) uninstall output still names ~/.claude" }

    # (b) You customized the Nudge skill and added a file to another skill.
    # Both stay, and alerts.db stays inside the kept Nudge dir for its 1.0.x
    # scripts.
    $b = Join-Path $Work "claude-b"
    & $oldInstaller -ClaudeDir $b *>&1 | Out-Null
    $notes = Join-Path $b "skills/clayworks-lite-memory-routing/my-notes.md"
    [System.IO.File]::WriteAllText($notes, "mine")
    [System.IO.File]::AppendAllText((Join-Path $b "skills/clayworks-lite-nudge/SKILL.md"), "# my tweak`n")
    $legacyB = Join-Path $b "skills/clayworks-lite-nudge/scripts/alerts.db"
    [System.IO.File]::WriteAllText($legacyB, "legacy")

    $outB = Invoke-Current $b -Uninstall
    Assert-Present $notes
    if ((Read-Text $legacyB) -ne "legacy") { Add-Failure "(b) alerts.db left the kept Nudge skill" }
    Assert-Gone (Join-Path $b "clayworks-lite/nudge/nudge-import")
    Assert-Gone (Join-Path $b "skills/clayworks-lite-heartbeat-concept")
    Assert-Gone (Join-Path $b "hooks/examples")
    if ($outB -notmatch "Uninstall finished; 2 item\(s\) kept") { Add-Failure "(b) wrong closing line" }

    # (c) A fresh install creates the Nudge dir the runtime uses as its marker.
    $c = Join-Path $Work "claude-c"
    Invoke-Current $c | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $c "clayworks-lite/nudge") -PathType Container)) {
        Add-Failure "(c) fresh install did not create clayworks-lite/nudge"
    }

    # (d) An install over a 1.0.x skill whose stable DB already exists: the
    # legacy DB lands in nudge-import/, not in the backup, and the stable DB is
    # intact.
    $d = Join-Path $Work "claude-d"
    & $oldInstaller -ClaudeDir $d *>&1 | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $d "skills/clayworks-lite-nudge/scripts/alerts.db"), "legacy-d")
    New-Item -ItemType Directory -Path (Join-Path $d "clayworks-lite/nudge") -Force | Out-Null
    $stableD = Join-Path $d "clayworks-lite/nudge/alerts.db"
    [System.IO.File]::WriteAllText($stableD, "stable")
    Invoke-Current $d | Out-Null
    if ((Get-ImportedContent (Join-Path $d "clayworks-lite/nudge/nudge-import")) -ne "legacy-d") {
        Add-Failure "(d) legacy DB did not land in nudge-import/"
    }
    if ((Read-Text $stableD) -ne "stable") { Add-Failure "(d) stable DB changed" }
    $backedUpDb = Get-ChildItem -LiteralPath (Join-Path $d ".clayworks-lite-backup") -Recurse -Filter "alerts.db" -ErrorAction SilentlyContinue
    if ($backedUpDb) { Add-Failure "(d) legacy DB ended up in the backup folder" }

    # CLAYWORKS_NUDGE_DB points into an existing shared dir. The nudge-import dir
    # goes next to that DB, and the purge text names only Nudge's own files
    # there.
    $f = Join-Path $Work "claude-f"
    $shared = Join-Path $Work "shared"
    & $oldInstaller -ClaudeDir $f *>&1 | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $f "skills/clayworks-lite-nudge/scripts/alerts.db"), "legacy-f")
    New-Item -ItemType Directory -Path $shared -Force | Out-Null
    $sharedDb = Join-Path $shared "alerts.db"
    $env:CLAYWORKS_NUDGE_DB = $sharedDb
    try { $outF = Invoke-Current $f -Uninstall } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    if ((Get-ImportedContent (Join-Path $shared "nudge-import")) -ne "legacy-f") {
        Add-Failure "(override) legacy DB not in the shared nudge-import dir"
    }
    Assert-Gone (Join-Path $f "skills/clayworks-lite-nudge")
    $normF = $outF.Replace('/', '\')
    if (-not $normF.Contains("Remove-Item -Force '$sharedDb'".Replace('/', '\'))) { Add-Failure "(override) purge text lacks the DB file" }
    if (-not $normF.Contains("Remove-Item -Recurse -Force '$(Join-Path $shared 'nudge-import')'".Replace('/', '\'))) {
        Add-Failure "(override) purge text lacks the nudge-import dir"
    }
    foreach ($bad in @("'$shared'", "'$(Join-Path $shared 'import')'")) {
        if ($normF.Contains("Remove-Item -Recurse -Force $bad".Replace('/', '\'))) {
            Add-Failure "(override) purge text names the shared dir or a generic import/"
        }
    }

    # CLAYWORKS_NUDGE_DB points at the 1.0.x DB inside the skill dir itself.
    # The nudge-import dir next to it would go down with the skill dir, so
    # both uninstall and install-over must fall back to
    # <root>/clayworks-lite/nudge/ and warn, and the alerts must survive there.
    $g = Join-Path $Work "claude-g"
    & $oldInstaller -ClaudeDir $g *>&1 | Out-Null
    $dbG = Join-Path $g "skills/clayworks-lite-nudge/scripts/alerts.db"
    [System.IO.File]::WriteAllText($dbG, "legacy-g")
    $env:CLAYWORKS_NUDGE_DB = $dbG
    try { $outG = Invoke-Current $g -Uninstall } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    Assert-Gone (Join-Path $g "skills/clayworks-lite-nudge")
    if ((Get-ImportedContent (Join-Path $g "clayworks-lite/nudge/nudge-import")) -ne "legacy-g") {
        Add-Failure "(db-in-skill uninstall) alerts lost"
    }
    if ($outG -notmatch "WARNING: CLAYWORKS_NUDGE_DB") { Add-Failure "(db-in-skill uninstall) no warning" }

    $h = Join-Path $Work "claude-h"
    & $oldInstaller -ClaudeDir $h *>&1 | Out-Null
    $dbH = Join-Path $h "skills/clayworks-lite-nudge/scripts/alerts.db"
    [System.IO.File]::WriteAllText($dbH, "legacy-h")
    $env:CLAYWORKS_NUDGE_DB = $dbH
    try { $outH = Invoke-Current $h } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    if ((Get-ImportedContent (Join-Path $h "clayworks-lite/nudge/nudge-import")) -ne "legacy-h") {
        Add-Failure "(db-in-skill install) alerts lost"
    }
    Assert-Gone (Join-Path $h "skills/clayworks-lite-nudge/scripts/nudge-import")
    if ($outH -notmatch "WARNING: CLAYWORKS_NUDGE_DB") { Add-Failure "(db-in-skill install) no warning" }
} finally {
    # Cleanup is best-effort; a leftover temp dir must not mask the result.
    $ErrorActionPreference = "Continue"
    git -C $RepoRoot worktree remove --force $OldTree 2>&1 | Out-Null
    Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue
}

if ($script:Fails -gt 0) {
    Write-Host "upgrade tests from ${OldRef}: $($script:Fails) failure(s)" -ForegroundColor Red
    exit 1
}
Write-Host "OK: upgrade tests from $OldRef passed" -ForegroundColor Green
