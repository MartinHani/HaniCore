$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = Join-Path $Root "C167BootTool"
$Zip = Join-Path $Root "C167BootTool-main.zip"
$Tmp = Join-Path $Root "_c167_tmp"

Write-Host "[1/3] Installing pyserial..."
py -m pip install --user pyserial

if (-not (Test-Path (Join-Path $RepoDir "ME7BootTool.py"))) {
    Write-Host "[2/3] Downloading EcuProg7/C167BootTool..."
    Invoke-WebRequest -Uri "https://github.com/EcuProg7/C167BootTool/archive/refs/heads/main.zip" -OutFile $Zip

    if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp }
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force

    $Extracted = Join-Path $Tmp "C167BootTool-main"
    if (-not (Test-Path $Extracted)) { throw "Downloaded archive layout was not expected." }

    if (Test-Path $RepoDir) { Remove-Item -Recurse -Force $RepoDir }
    Move-Item $Extracted $RepoDir
    Remove-Item -Recurse -Force $Tmp
    Remove-Item -Force $Zip
} else {
    Write-Host "[2/3] C167BootTool already present; leaving it unchanged."
}

Write-Host "[3/3] Checking CLI..."
py (Join-Path $Root "hanicore_me7boot.py") ports

Write-Host ""
Write-Host "Installed. Example commands:"
Write-Host "  py .\hanicore_me7boot.py --port COM3 read backup.bin"
Write-Host "  py .\hanicore_me7boot.py --port COM3 write HaniCore.bin"
Write-Host "  py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin"
Write-Host "  py .\hanicore_me7boot.py --port COM3 diffWrite HaniCore.bin --verify"
Write-Host "  py .\hanicore_me7boot.py --port COM3 verify HaniCore.bin"
