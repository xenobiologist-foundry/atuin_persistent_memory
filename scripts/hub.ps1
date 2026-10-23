[CmdletBinding()]
param(
    [Parameter(Position=0)][ValidateSet('setup','build','start','stop','doctor','test','test-import','backup','restore')][string]$Action = 'doctor',
    [string]$PublicKey,
    [string]$Project = 'atuin-ssh',
    [string]$BackupDirectory,
    [string]$Archive
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker exited with status $LASTEXITCODE" }
}
function Invoke-Compose {
    Invoke-Docker compose --project-name $Project --file (Join-Path $repoRoot 'compose.yaml') @args
}
function Get-Hub {
    $containerId = (& docker compose --project-name $Project --file (Join-Path $repoRoot 'compose.yaml') ps --all --quiet hub).Trim()
    if (!$containerId) { throw 'Create the hub first: ./scripts/hub.ps1 start' }
    $inspection = & docker inspect $containerId | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the hub container.' }
    return $inspection[0]
}
function Invoke-ImportVerification {
    $priorTestPort = [Environment]::GetEnvironmentVariable('TEST_HUB_PORT', 'Process')
    try {
        $env:TEST_HUB_PORT = '22224'
        Invoke-Docker compose --project-name atuin-ssh-import-check --file compose.test.yaml up --no-build --detach hub destination
        Invoke-Docker compose --project-name atuin-ssh-import-check --file compose.test.yaml exec --no-TTY destination /bin/bash -c 'install -m 0600 -o remote -g remote /dev/null /home/remote/import_history; touch /home/remote/.bash_profile; grep -qxF "export HISTFILE=/home/remote/import_history" /home/remote/.bash_profile || printf "\nexport HISTFILE=/home/remote/import_history\n" >> /home/remote/.bash_profile; chown remote:remote /home/remote/.bash_profile; chmod 0600 /home/remote/.bash_profile'
        Invoke-Docker compose --project-name atuin-ssh-import-check --file compose.test.yaml run --rm import-client
    } finally {
        try {
            Invoke-Docker compose --project-name atuin-ssh-import-check --file compose.test.yaml down
        } finally {
            [Environment]::SetEnvironmentVariable('TEST_HUB_PORT', $priorTestPort, 'Process')
        }
    }
}
switch ($Action) {
    'setup' {
        if (!$PublicKey) { $PublicKey = Join-Path $HOME '.ssh/id_ed25519.pub' }
        $resolvedKey = (Resolve-Path -LiteralPath $PublicKey).Path
        $keyText = Get-Content -LiteralPath $resolvedKey -Raw
        if ($keyText -notmatch '(?m)^(ssh-ed25519|ssh-rsa|ecdsa-sha2-|sk-ssh-|sk-ecdsa-)') { throw 'The supplied file must contain an SSH public key.' }
        if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
        if (Test-Path -LiteralPath 'config/authorized_keys') { throw 'config/authorized_keys already exists; edit it to add or remove keys.' }
        [IO.File]::WriteAllText((Join-Path $repoRoot 'config/authorized_keys'), ($keyText.TrimEnd() + "`n"), [Text.UTF8Encoding]::new($false))
        Write-Output 'Configured. Run: docker compose build; docker compose up -d; ssh -p 2222 hubuser@localhost'
    }
    'build' { Invoke-Compose build }
    'start' { Invoke-Compose up --detach }
    'stop' { Invoke-Compose stop }
    'doctor' { Invoke-Compose exec --no-TTY hub /bin/bash -c 'exec runuser -u "$HUB_USER" -- env ATUIN_HOME=/state/atuin ATUIN_CONFIG_DIR=/state/atuin ATUIN_SSH_STATE_DIR=/state/bridge atuin-ssh doctor' }
    'test' {
        # Test resources have their own fixed project name and cannot target production.
        Invoke-Docker compose --project-name atuin-ssh-test --file compose.test.yaml up --build --detach hub destination
        Invoke-Docker compose --project-name atuin-ssh-test --file compose.test.yaml run --rm client
        Invoke-Docker run --rm --network none --entrypoint python atuin-ssh:test /opt/atuin-ssh/privacy-probe.py
        Invoke-Docker run --rm --network none --entrypoint python atuin-ssh:test /opt/atuin-ssh/blesh-privacy-probe.py
        Invoke-ImportVerification
    }
    'test-import' { Invoke-ImportVerification }
    'backup' {
        $hubInfo = Get-Hub
        $stateMount = $hubInfo.Mounts | Where-Object Destination -eq '/state'
        $homeMount = $hubInfo.Mounts | Where-Object { $_.Destination -like '/home/*' }
        if ($stateMount.Type -ne 'volume' -or $homeMount.Type -ne 'volume') { throw 'This backup command requires the default named state and home volumes.' }
        if (!$BackupDirectory) { $BackupDirectory = Join-Path $repoRoot ('backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
        New-Item -ItemType Directory -Path $BackupDirectory -ErrorAction Stop | Out-Null
        $backupPath = (Resolve-Path -LiteralPath $BackupDirectory).Path
        $wasRunning = $hubInfo.State.Running
        try {
            Invoke-Compose stop hub
            Invoke-Docker run --rm --entrypoint /bin/tar --mount "type=volume,src=$($stateMount.Name),dst=/snapshot/state,readonly" --mount "type=volume,src=$($homeMount.Name),dst=/snapshot/home,readonly" --mount "type=bind,src=$backupPath,dst=/backup" $hubInfo.Image --numeric-owner -czf /backup/hub.tar.gz -C /snapshot state home
            @{ format = 1; created_utc = [DateTime]::UtcNow.ToString('o'); project = $Project; image_id = $hubInfo.Image; consistent = 'all hub writers stopped'; includes = @('state','home') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupPath 'manifest.json') -Encoding utf8
            (Get-FileHash -LiteralPath (Join-Path $backupPath 'hub.tar.gz') -Algorithm SHA256).Hash | Set-Content -LiteralPath (Join-Path $backupPath 'hub.tar.gz.sha256') -Encoding ascii
            Write-Output "Complete consistent backup: $backupPath"
        } finally {
            if ($wasRunning) { Invoke-Compose start hub }
        }
    }
    'restore' {
        if (!$Archive) { throw 'Specify -Archive with a hub.tar.gz created by the backup command.' }
        $archivePath = (Resolve-Path -LiteralPath $Archive).Path
        $archiveDir = Split-Path -Parent $archivePath
        $archiveName = Split-Path -Leaf $archivePath
        Invoke-Compose create hub
        $hubInfo = Get-Hub
        if ($hubInfo.State.Running) { throw 'Restore requires a stopped fresh hub. Stop it before restoring.' }
        $stateMount = $hubInfo.Mounts | Where-Object Destination -eq '/state'
        $homeMount = $hubInfo.Mounts | Where-Object { $_.Destination -like '/home/*' }
        if ($stateMount.Type -ne 'volume' -or $homeMount.Type -ne 'volume') { throw 'Restore requires default named volumes.' }
        Invoke-Docker run --rm --entrypoint /bin/bash --mount "type=volume,src=$($stateMount.Name),dst=/restore/state" --mount "type=volume,src=$($homeMount.Name),dst=/restore/home" --mount "type=bind,src=$archiveDir,dst=/backup,readonly" $hubInfo.Image /usr/share/atuin-ssh/restore.sh "/backup/$archiveName"
        Write-Output 'Restored into the stopped hub. Run start when ready. Keep the original hub stopped when moving its writer identity.'
    }
}
