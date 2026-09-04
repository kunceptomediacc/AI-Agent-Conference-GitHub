$ErrorActionPreference = "Stop"
$root = if ($env:AGENT_CONFERENCE_MEMORY_DIR) { $env:AGENT_CONFERENCE_MEMORY_DIR } else { Join-Path $HOME "AI-Agent-Conference\memory" }
$examples = Join-Path $PSScriptRoot "examples\agent-instructions"
$agents = @("oreo", "jessiejay", "mercedes", "abby", "julia", "master-coach")

foreach ($agent in $agents) {
    $directory = Join-Path $root $agent
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    Copy-Item (Join-Path $examples "$agent-INSTRUCTIONS.md") (Join-Path $directory "INSTRUCTIONS.md") -Force
}

Write-Host "Agent instruction examples installed under $root"
