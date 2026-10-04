# PrivacyWorm installer for Windows.
#
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/simonlpaige/privacyworm/main/install.ps1 | iex"
#
# Or double-click install.cmd, which runs this for you.
#
# What it does (nothing needs to be installed first - not git, not Python):
#   1. Gets "uv", a small, widely used Python app manager (astral.sh/uv),
#      unless you already have it.
#   2. Uses uv to install PrivacyWorm into its own private folder, with its
#      own copy of Python if your computer doesn't have a recent one.
#   3. Checks for Chrome/Edge (or downloads a private Chromium) and adds
#      PrivacyWorm to your Start menu and Desktop.
#
# Run it again any time to update. Your saved info is kept.
# Uninstall: privacyworm uninstall
#
# Options (environment variables):
#   PRIVACYWORM_REF=<branch or tag>   install a different version (default: main)
#   PRIVACYWORM_SOURCE=<path or URL>  install from a local folder or other archive
#   PRIVACYWORM_NO_SHORTCUT=1         don't add Start menu / Desktop shortcuts
#   PRIVACYWORM_NO_LAUNCH=1           don't open PrivacyWorm at the end

function Install-PrivacyWorm {
    # 'Continue', not 'Stop': Windows PowerShell 5.1 turns any stderr output
    # from a native program (uv prints progress there) into a terminating
    # error under 'Stop'. We check $LASTEXITCODE explicitly instead.
    $ErrorActionPreference = 'Continue'
    $ProgressPreference = 'SilentlyContinue'
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

    $repo = 'simonlpaige/privacyworm'
    $ref = if ($env:PRIVACYWORM_REF) { $env:PRIVACYWORM_REF } else { 'main' }
    $source = if ($env:PRIVACYWORM_SOURCE) { $env:PRIVACYWORM_SOURCE } else { "https://github.com/$repo/archive/refs/heads/$ref.zip" }

    function Step($msg) { Write-Host ''; Write-Host '==> ' -ForegroundColor Green -NoNewline; Write-Host $msg -ForegroundColor White }
    function Note($msg) { Write-Host "    $msg" }
    function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }

    function Find-Uv {
        $cmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
        foreach ($p in @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe", "$env:LOCALAPPDATA\uv\uv.exe")) {
            if (Test-Path $p) { return $p }
        }
        return $null
    }

    Write-Host ''
    Write-Host 'PrivacyWorm installer' -ForegroundColor White
    Note 'Finds your info on people-search sites and helps you get it removed.'

    # 1. uv ------------------------------------------------------------------
    Step 'Getting the installer helper (uv)'
    $uv = Find-Uv
    if ($uv) {
        Note "Already have it: $uv"
    } else {
        Note 'Downloading uv from astral.sh ...'
        try {
            $installer = Invoke-RestMethod -UseBasicParsing -ErrorAction Stop 'https://astral.sh/uv/install.ps1'
            & ([scriptblock]::Create($installer)) *> $null
        } catch {
            throw "Couldn't install uv. Check your internet connection and try again. ($_)"
        }
        # Pick up the PATH change uv just made, without a new window.
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $uv = Find-Uv
        if (-not $uv) { throw "uv installed but can't be found. Open a new PowerShell window and run this again." }
        Note 'Installed uv.'
    }

    # 2. PrivacyWorm -----------------------------------------------------------
    Step 'Installing PrivacyWorm (this can take a minute the first time)'
    $log = Join-Path $env:TEMP 'privacyworm-install.log'
    & $uv tool install --force --reinstall --python '>=3.11' "privacyworm[mugshot] @ $source" *> $log
    if ($LASTEXITCODE -ne 0) {
        Get-Content $log | Write-Host
        throw "uv couldn't install PrivacyWorm (details above)."
    }
    $binDir = (& $uv tool dir --bin 2>$null | Select-Object -First 1).Trim()
    $pw = Join-Path $binDir 'privacyworm.exe'
    if (-not (Test-Path $pw)) { $pw = Join-Path $binDir 'privacyworm' }  # PowerShell on macOS/Linux
    if (-not (Test-Path $pw)) { throw "Install finished but $pw is missing." }
    Note "Installed to $binDir"

    # Make 'privacyworm' work in new terminal windows.
    & $uv tool update-shell *> $null

    # 3. Browser + shortcuts ---------------------------------------------------
    Step 'Setting up the browser and shortcuts'
    $setupArgs = @('setup')
    if ($env:PRIVACYWORM_NO_SHORTCUT -eq '1') { $setupArgs += '--no-shortcut' }
    & $pw @setupArgs
    if ($LASTEXITCODE -ne 0) {
        Warn "The browser isn't ready yet. Follow the hint above, then run: privacyworm doctor"
    }

    Write-Host ''
    Write-Host 'PrivacyWorm is installed.' -ForegroundColor Green
    Note 'Open it from the Start menu or the Desktop shortcut ("PrivacyWorm"),'
    Note 'or type  privacyworm  in a new terminal window.'
    Note 'To update later, run this same install command again.'

    if ($env:PRIVACYWORM_NO_LAUNCH -ne '1') {
        Write-Host ''
        Note 'Opening PrivacyWorm in a new window...'
        Start-Process -FilePath $pw -WorkingDirectory $env:USERPROFILE
    }
}

try {
    Install-PrivacyWorm
} catch {
    Write-Host ''
    Write-Host "Install stopped: $_" -ForegroundColor Red
    Write-Host 'If this keeps happening, open an issue at https://github.com/simonlpaige/privacyworm/issues'
}
