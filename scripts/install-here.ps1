# Drop .mcp.json and .claude-plugin/plugin.json into the current directory so
# `claude --dangerously-load-development-channels server:wechat` works here.
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot

Copy-Item -Force "$repoRoot\.mcp.json" .\.mcp.json
New-Item -ItemType Directory -Force .\.claude-plugin | Out-Null
Copy-Item -Force "$repoRoot\.claude-plugin\plugin.json" .\.claude-plugin\plugin.json

Write-Host "Installed wechat channel files in $(Get-Location)"
Write-Host "Now run: claude --dangerously-load-development-channels server:wechat"
