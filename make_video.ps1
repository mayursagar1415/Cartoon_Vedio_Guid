<#
.SYNOPSIS
    Flat Puppet Studio — Full Render & Video Encoding Pipeline (Windows Native)
#>
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host ">>> Rendering and streaming directly to FLAT-DEMO.mp4..." -ForegroundColor Cyan
python flat_puppet_demo.py encode --output FLAT-DEMO.mp4
if ($LASTEXITCODE -ne 0) {
    Write-Error "Render/encode failed with exit code $LASTEXITCODE"
}

Write-Host ">>> Done! Created FLAT-DEMO.mp4" -ForegroundColor Green
