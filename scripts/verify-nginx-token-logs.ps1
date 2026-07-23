$ErrorActionPreference = "Stop"

$sentinel = "token-log-sentinel-$PID"
$network = "ai-interview-token-log-$PID"
$backend = "ai-interview-token-backend-$PID"
$nginx = "ai-interview-token-nginx-$PID"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$mount = "${root}\frontend\nginx.conf:/etc/nginx/conf.d/default.conf:ro"

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

    $paths = @(
        "/public/coding-tests/${sentinel}-coding",
        "/offer-confirm/${sentinel}-offer",
        "/public/review/${sentinel}-review",
        "/api/public/coding-tests/${sentinel}-coding",
        "/api/public/offers/confirm/${sentinel}-offer",
        "/api/public/review/${sentinel}-review"
    )
    foreach ($path in $paths) {
        $null = & docker exec $nginx wget -q -O /dev/null "http://127.0.0.1$path"
    }

    $null = & docker rm -f $backend
    $null = & docker exec $nginx wget -q -O /dev/null `
        "http://127.0.0.1/api/public/review/${sentinel}-review-upstream-failure"

    $logs = (& docker logs $nginx 2>&1 | Out-String)
    if ($logs.Contains($sentinel)) {
        throw "Nginx logs leaked the public-token sentinel"
    }

    Write-Output "Nginx public-token log verification passed"
}
finally {
    $null = & docker rm -f $nginx $backend 2>$null
    $null = & docker network rm $network 2>$null
}
