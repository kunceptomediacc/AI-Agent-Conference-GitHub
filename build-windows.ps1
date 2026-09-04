$ErrorActionPreference = "Stop"
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --onedir --name AgentConferenceServer --add-data "web;web" agent_server.py
python -m PyInstaller --noconfirm --clean --onefile --console --name AgentConferenceMCP --collect-submodules mcp.server --collect-submodules mcp.shared --collect-submodules mcp.client --collect-submodules mcp.types --collect-submodules mcp_types conference_mcp.py
Write-Host "Build complete. Review dist/ before distribution."
