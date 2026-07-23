$ErrorActionPreference = "Stop"

$sentinel = "token-log-sentinel-$PID"
$safeSentinel = "safe-access-log-$PID"
$network = "ai-interview-token-log-$PID"
$backend = "ai-interview-token-backend-$PID"
$nginx = "ai-interview-token-nginx-$PID"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$mount = "${root}\frontend\nginx.conf:/etc/nginx/conf.d/default.conf:ro"

function Get-HttpStatus {
    param([Parameter(Mandatory = $true)][string]$Path)

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& docker exec $nginx wget -S -O /dev/null "http://127.0.0.1$Path" 2>&1 | Out-String)
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $matches = [regex]::Matches($output, "HTTP/1\.[01]\s+(\d{3})")
    if ($matches.Count -eq 0) {
        throw "Cannot read the HTTP status for $Path`n$output"
    }
    return [int]$matches[$matches.Count - 1].Groups[1].Value
}

function Assert-HttpStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int[]]$Expected
    )

    $actual = Get-HttpStatus -Path $Path
    if ($Expected -notcontains $actual) {
        throw "$Path expected HTTP $($Expected -join '/') but received $actual"
    }
}

try {
    $null = & docker network create $network
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot create the Nginx log verification network"
    }

    $null = & docker run -d --name $backend --network $network `
        --network-alias backend busybox:1.36 httpd -f -p 8000
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot start the Nginx log verification backend"
    }

    $null = & docker run -d --name $nginx --network $network `
        -v $mount nginx:1.27-alpine
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot start the Nginx log verification container"
    }

    $ready = $false
    foreach ($attempt in 1..10) {
        $null = & docker exec $nginx wget -q -O /dev/null http://127.0.0.1/
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) {
        throw "The Nginx log verification container is not ready"
    }

    Assert-HttpStatus -Path "/$safeSentinel" -Expected @(200)

    $spaPaths = @(
        "/public/coding-tests/${sentinel}-coding",
        "/offer-confirm/${sentinel}-offer",
        "/public/review/${sentinel}-review"
    )
    foreach ($path in $spaPaths) {
        Assert-HttpStatus -Path $path -Expected @(200)
    }

    $apiPaths = @(
        "/api/public/coding-tests/${sentinel}-coding",
        "/api/public/offers/confirm/${sentinel}-offer",
        "/api/public/review/${sentinel}-review"
    )
    foreach ($path in $apiPaths) {
        Assert-HttpStatus -Path $path -Expected @(404)
    }

    $null = & docker rm -f $backend
    Assert-HttpStatus `
        -Path "/api/public/review/${sentinel}-review-upstream-failure" `
        -Expected @(502, 504)

    $running = (& docker inspect --format "{{.State.Running}}" $nginx | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $running -ne "true") {
        throw "The Nginx log verification container exited unexpectedly"
    }

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $logs = (& docker logs $nginx 2>&1 | Out-String)
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($logs.Contains($sentinel)) {
        throw "Nginx logs leaked the public-token sentinel"
    }
    if (-not $logs.Contains($safeSentinel)) {
        throw "The safe access-log sentinel is missing; logging may be globally disabled"
    }

    Write-Output "Nginx public-token log verification passed"
}
finally {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $null = & docker rm -f $nginx $backend 2>$null
        $null = & docker network rm $network 2>$null
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
}
