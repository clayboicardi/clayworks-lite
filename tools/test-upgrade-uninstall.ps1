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

function Get-PurgeTarget {
    # The paths the printed Remove-Item purge commands name, decoded by the
    # PowerShell parser exactly as it would read them if you pasted them.
    param([string]$Output)
    $targets = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($Output -split "`n")) {
        if ($line -notmatch '^\s+Remove-Item .*-LiteralPath ') { continue }
        $tokens = $null
        $errors = $null
        $ast = [System.Management.Automation.Language.Parser]::ParseInput($line.Trim(), [ref]$tokens, [ref]$errors)
        if ($errors.Count -gt 0) {
            Add-Failure "(quoting) purge line does not parse: $line"
            continue
        }
        $cmd = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)
        $els = $cmd.CommandElements
        for ($i = 0; $i -lt $els.Count - 1; $i++) {
            if ($els[$i] -is [System.Management.Automation.Language.CommandParameterAst] -and
                $els[$i].ParameterName -eq 'LiteralPath') {
                $targets.Add([string]$els[$i + 1].SafeGetValue())
            }
        }
    }
    return ,$targets
}

function Test-PurgeTarget {
    # True if one of the printed purge commands names Path.
    param([string]$Output, [string]$Path)
    $want = [System.IO.Path]::GetFullPath($Path)
    foreach ($t in (Get-PurgeTarget $Output)) {
        if ([System.IO.Path]::GetFullPath($t) -eq $want) { return $true }
    }
    return $false
}

function Assert-Refused {
    # Install and uninstall against Root must both refuse. I check both the
    # refusal message and exit code 5, so a stale LASTEXITCODE from an
    # earlier command can't pass for a refusal.
    param([string]$Root, [string]$Label)
    foreach ($mode in @($false, $true)) {
        $out = (& $Current -Uninstall:$mode -ClaudeDir $Root *>&1 | ForEach-Object { "$_" }) -join "`n"
        if ($LASTEXITCODE -ne 5 -or $out -notmatch "is a symlink or junction") {
            Add-Failure "($Label) $(if ($mode) { 'uninstall' } else { 'install' }) did not refuse"
        }
    }
}

function ConvertTo-TestLiteral {
    # The single-quoted literal install.ps1 prints for a path.
    param([string]$Text)
    return "'" + $Text.Replace("'", "''") + "'"
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
    if (-not (Test-PurgeTarget $outA (Join-Path $a '.clayworks-lite-backup'))) {
        Add-Failure "(e) purge text lacks this root's backup dir"
    }
    if (-not (Test-PurgeTarget $outA (Join-Path $a 'clayworks-lite'))) {
        Add-Failure "(e) purge text lacks this root's clayworks-lite dir"
    }
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

    # A custom.pyc beside a skill's SKILL.md is yours, so that skill stays; a
    # .pyc inside __pycache__\ is Python's, so it doesn't hold its skill back.
    $pRoot = Join-Path $Work "claude-p"
    & $oldInstaller -ClaudeDir $pRoot *>&1 | Out-Null
    $customPyc = Join-Path $pRoot "skills/clayworks-lite-memory-routing/custom.pyc"
    [System.IO.File]::WriteAllText($customPyc, "mine")
    $cacheDir = Join-Path $pRoot "skills/clayworks-lite-heartbeat-concept/__pycache__"
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $cacheDir "x.pyc"), "x")
    $outP = Invoke-Current $pRoot -Uninstall
    Assert-Present $customPyc
    Assert-Gone (Join-Path $pRoot "skills/clayworks-lite-heartbeat-concept")
    if ($outP -notmatch "skill: clayworks-lite-memory-routing: customized") {
        Add-Failure "(pyc) custom.pyc beside SKILL.md did not mark the skill customized"
    }

    # (c) A fresh install creates the Nudge dir the runtime uses as its marker.
    $c = Join-Path $Work "claude-c"
    $outC = Invoke-Current $c
    if (-not (Test-Path -LiteralPath (Join-Path $c "clayworks-lite/nudge") -PathType Container)) {
        Add-Failure "(c) fresh install did not create clayworks-lite/nudge"
    }
    # Its next steps name this root as quoted literals, not ~/.claude.
    $settingsLit = ConvertTo-TestLiteral (Join-Path $c 'settings.json')
    if (-not $outC.Replace('/', '\').Contains($settingsLit.Replace('/', '\'))) {
        Add-Failure "(c) next steps do not name this root"
    }
    if ($outC.Contains("~/.claude")) { Add-Failure "(c) next steps still name ~/.claude" }

    # A junctioned clayworks-lite\nudge that points outside the root: install
    # and uninstall must both refuse before writing anything, and nothing may
    # land outside the root. A junction needs no admin rights.
    $l = Join-Path $Work "claude-l"
    $outside = Join-Path $Work "outside"
    New-Item -ItemType Directory -Path (Join-Path $l "clayworks-lite") -Force | Out-Null
    New-Item -ItemType Directory -Path $outside -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $l "clayworks-lite/nudge") -Target $outside | Out-Null
    Assert-Refused $l "junctioned nudge dir"
    if (Get-ChildItem -LiteralPath $outside -Force) { Add-Failure "(junction) the installer wrote outside the root" }
    Assert-Gone (Join-Path $l "skills")

    # A junctioned Nudge skill dir, and separately a junctioned skills\,
    # pointing at an unrelated folder that holds scripts\alerts.db: install
    # and uninstall must both refuse, and that DB must stay untouched.
    $ext = Join-Path $Work "external-skill"
    New-Item -ItemType Directory -Path (Join-Path $ext "scripts") -Force | Out-Null
    $extDb = Join-Path $ext "scripts/alerts.db"
    [System.IO.File]::WriteAllText($extDb, "external-db")
    $m = Join-Path $Work "claude-m"
    New-Item -ItemType Directory -Path (Join-Path $m "skills") -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $m "skills/clayworks-lite-nudge") -Target $ext | Out-Null
    Assert-Refused $m "junctioned skill dir"
    $extSkills = Join-Path $Work "external-skills"
    New-Item -ItemType Directory -Path $extSkills -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $extSkills "clayworks-lite-nudge") -Target $ext | Out-Null
    $nRoot = Join-Path $Work "claude-n"
    New-Item -ItemType Directory -Path $nRoot -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $nRoot "skills") -Target $extSkills | Out-Null
    Assert-Refused $nRoot "junctioned skills dir"
    if ((Read-Text $extDb) -ne "external-db") { Add-Failure "(junctioned skill dir) the external alerts.db was moved or changed" }
    $extItems = @(Get-ChildItem -LiteralPath $ext -Recurse -Force | ForEach-Object { $_.Name })
    if (($extItems -join ',') -ne 'scripts,alerts.db') {
        Add-Failure "(junctioned skill dir) the installer changed the external folder: $($extItems -join ',')"
    }

    # CLAYWORKS_NUDGE_DB inside another LITE skill, which install replaces
    # and uninstall removes: both must refuse with exit 2, and the store must
    # stay put with its row.
    $sRoot = Join-Path $Work "claude-s"
    Invoke-Current $sRoot | Out-Null
    $storeS = Join-Path $sRoot "skills/clayworks-lite-memory-routing/custom.db"
    [System.IO.File]::WriteAllText($storeS, "row-s")
    $env:CLAYWORKS_NUDGE_DB = $storeS
    try {
        foreach ($mode in @($false, $true)) {
            $outS = (& $Current -Uninstall:$mode -ClaudeDir $sRoot *>&1 | ForEach-Object { "$_" }) -join "`n"
            $modeName = if ($mode) { 'uninstall' } else { 'install' }
            if ($LASTEXITCODE -ne 2 -or $outS -notmatch "CLAYWORKS_NUDGE_DB points inside") {
                Add-Failure "(db in managed skill) $modeName did not refuse"
            }
        }
    } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    if ((Read-Text $storeS) -ne "row-s") { Add-Failure "(db in managed skill) the store moved or changed" }
    $backedUpS = Get-ChildItem -LiteralPath (Join-Path $sRoot ".clayworks-lite-backup") -Recurse -Filter "custom.db" -ErrorAction SilentlyContinue
    if ($backedUpS) { Add-Failure "(db in managed skill) the store was backed up, so install replaced its skill" }

    # A junctioned install root itself is fine (dotfile setups): install and
    # uninstall through it work as usual.
    $realRoot = Join-Path $Work "real-root"
    New-Item -ItemType Directory -Path $realRoot -Force | Out-Null
    $linkedRoot = Join-Path $Work "linked-root"
    New-Item -ItemType Junction -Path $linkedRoot -Target $realRoot | Out-Null
    $outRoot = Invoke-Current $linkedRoot
    if (-not (Test-Path -LiteralPath (Join-Path $realRoot "skills/clayworks-lite-nudge/SKILL.md"))) {
        Add-Failure "(junctioned root) install refused or skipped a junctioned root: $outRoot"
    }
    $outRoot = Invoke-Current $linkedRoot -Uninstall
    if ($outRoot -notmatch "Uninstall complete") { Add-Failure "(junctioned root) uninstall refused a junctioned root" }

    # A junctioned hooks\ pointing at an external dir that holds examples\:
    # install and uninstall must both refuse, and the external dir must stay
    # intact.
    $extHooks = Join-Path $Work "external-hooks"
    New-Item -ItemType Directory -Path (Join-Path $extHooks "examples") -Force | Out-Null
    $extStop = Join-Path $extHooks "examples/stop.sh"
    [System.IO.File]::WriteAllText($extStop, "theirs")
    $q = Join-Path $Work "claude-q"
    New-Item -ItemType Directory -Path $q -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $q "hooks") -Target $extHooks | Out-Null
    Assert-Refused $q "junctioned hooks dir"
    $extHookItems = @(Get-ChildItem -LiteralPath (Join-Path $extHooks "examples") -Force | ForEach-Object { $_.Name })
    if ((Read-Text $extStop) -ne "theirs" -or ($extHookItems -join ',') -ne 'stop.sh') {
        Add-Failure "(junctioned hooks dir) the external examples\ changed"
    }
    Assert-Gone (Join-Path $q "skills")

    # A link you added inside an otherwise unchanged skill: uninstall keeps
    # that skill (and your link) and removes the rest.
    $r = Join-Path $Work "claude-r"
    Invoke-Current $r | Out-Null
    $linkTarget = Join-Path $Work "link-target"
    New-Item -ItemType Directory -Path $linkTarget -Force | Out-Null
    $mineLink = Join-Path $r "skills/clayworks-lite-memory-routing/mine-link"
    New-Item -ItemType Junction -Path $mineLink -Target $linkTarget | Out-Null
    $outR = Invoke-Current $r -Uninstall
    if (-not (Test-Path -LiteralPath $mineLink)) { Add-Failure "(inner link) your link was removed" }
    Assert-Present (Join-Path $r "skills/clayworks-lite-memory-routing/SKILL.md")
    Assert-Gone (Join-Path $r "skills/clayworks-lite-heartbeat-concept")
    if ($outR -notmatch "skill: clayworks-lite-memory-routing: customized") {
        Add-Failure "(inner link) the skill holding your link was not kept as customized"
    }

    # Remove the junctions themselves so cleanup never walks through them.
    foreach ($j in @((Join-Path $l "clayworks-lite/nudge"), (Join-Path $m "skills/clayworks-lite-nudge"),
                     (Join-Path $nRoot "skills"), (Join-Path $extSkills "clayworks-lite-nudge"), $linkedRoot,
                     (Join-Path $q "hooks"), $mineLink)) {
        if (Test-Path -LiteralPath $j) { [System.IO.Directory]::Delete($j) }
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
    if (-not (Test-PurgeTarget $outF $sharedDb)) { Add-Failure "(override) purge text lacks the DB file" }
    if (-not (Test-PurgeTarget $outF (Join-Path $shared 'nudge-import'))) {
        Add-Failure "(override) purge text lacks the nudge-import dir"
    }
    foreach ($bad in @($shared, (Join-Path $shared 'import'))) {
        if (Test-PurgeTarget $outF $bad) {
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

    # CLAYWORKS_NUDGE_DB names some other file inside the skill dir, with a
    # WAL sidecar. Install-over and uninstall must both hand that store (and
    # its sidecar) to the fallback nudge-import/ before the skill dir goes,
    # and keep it out of the backup.
    $i = Join-Path $Work "claude-i"
    & $oldInstaller -ClaudeDir $i *>&1 | Out-Null
    $dbI = Join-Path $i "skills/clayworks-lite-nudge/scripts/custom.db"
    [System.IO.File]::WriteAllText($dbI, "custom-i")
    [System.IO.File]::WriteAllText("$dbI-wal", "wal-i")
    [System.IO.File]::WriteAllText("$dbI-journal", "journal-i")
    $env:CLAYWORKS_NUDGE_DB = $dbI
    try { $outI = Invoke-Current $i } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    $importI = Join-Path $i "clayworks-lite/nudge/nudge-import"
    if ((Get-ImportedContent $importI) -ne "custom-i") { Add-Failure "(custom-db install) store lost" }
    $walI = @(Get-ChildItem -LiteralPath $importI -Filter "legacy-*.db-wal" -File -ErrorAction SilentlyContinue)
    if ($walI.Count -ne 1 -or [System.IO.File]::ReadAllText($walI[0].FullName) -ne "wal-i") {
        Add-Failure "(custom-db install) WAL sidecar lost"
    }
    $journalI = @(Get-ChildItem -LiteralPath $importI -Filter "legacy-*.db-journal" -File -ErrorAction SilentlyContinue)
    if ($journalI.Count -ne 1 -or [System.IO.File]::ReadAllText($journalI[0].FullName) -ne "journal-i") {
        Add-Failure "(custom-db install) rollback journal did not move with the store"
    }
    $backedUpI = Get-ChildItem -LiteralPath (Join-Path $i ".clayworks-lite-backup") -Recurse -Filter "custom.db*" -ErrorAction SilentlyContinue
    if ($backedUpI) { Add-Failure "(custom-db install) store ended up in the backup folder" }
    if ($outI -notmatch "WARNING: CLAYWORKS_NUDGE_DB") { Add-Failure "(custom-db install) no warning" }

    $j = Join-Path $Work "claude-j"
    & $oldInstaller -ClaudeDir $j *>&1 | Out-Null
    $dbJ = Join-Path $j "skills/clayworks-lite-nudge/scripts/custom.db"
    [System.IO.File]::WriteAllText($dbJ, "custom-j")
    $env:CLAYWORKS_NUDGE_DB = $dbJ
    try { $outJ = Invoke-Current $j -Uninstall } finally { Remove-Item Env:\CLAYWORKS_NUDGE_DB }
    Assert-Gone (Join-Path $j "skills/clayworks-lite-nudge")
    if ((Get-ImportedContent (Join-Path $j "clayworks-lite/nudge/nudge-import")) -ne "custom-j") {
        Add-Failure "(custom-db uninstall) store lost"
    }
    if ($outJ -notmatch "WARNING: CLAYWORKS_NUDGE_DB") { Add-Failure "(custom-db uninstall) no warning" }

    # A claude dir with an apostrophe and a space. The PowerShell parser must
    # read each printed purge command back as the right path.
    $k = Join-Path $Work "O'Brien root"
    Invoke-Current $k | Out-Null
    $outK = Invoke-Current $k -Uninstall
    foreach ($want in @((Join-Path $k '.clayworks-lite-backup'), (Join-Path $k 'clayworks-lite'))) {
        if (-not (Test-PurgeTarget $outK $want)) { Add-Failure "(quoting) no purge command for $want" }
    }
    if (-not $outK.Contains("O''Brien root")) { Add-Failure "(quoting) apostrophe not doubled in the purge text" }
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
