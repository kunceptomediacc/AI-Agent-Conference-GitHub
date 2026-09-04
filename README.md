# AI Agent Conference

> A local-first multi-agent workspace that coordinates specialized AI roles through Ollama, Codex, VS Cline, MCP, human approvals, persistent memory, and verified Google Sheets reporting.

## Short GitHub description

Local-first multi-agent orchestration with a browser dashboard, hybrid LLM routing, MCP integration, human checkpoints, persistent memory, monitoring, and Google Sheets reports.

## Why I built it

I started without a background in automation. I learned by turning one practical problem at a time into a workflow: giving AI agents clear roles, connecting local and external models, saving their work, requiring approval for sensitive actions, and verifying the final result. AI Agent Conference is the result—a working system built through curiosity, repeated testing, mistakes, and improvement.

## Simple flow

```text
User / MCP Client
       ↓
Browser UI or Codex / VS Cline
       ↓
Julia analyzes and creates a workflow
       ↓
Specialists: JessieJay → Oreo → Mercedes → Ab
       ↓
Human checkpoint before file/read/run operations
       ↓
Codex, Cline, or Ollama executes each task
       ↓
Julia verifies → local output → Google Sheets report
       ↘
      Hidden Master Coach monitors health and stalls
```

## Agent team

| Agent | Responsibility | Smart-routing preference |
|---|---|---|
| Julia | Lead orchestration and final verification | Codex |
| Oreo | Coding and frontend implementation | VS Cline |
| JessieJay | UI/UX and workflow design | Ollama |
| Mercedes | API, MCP, infrastructure, networking, security | VS Cline |
| Ab | Debugging, QA, and regression validation | Codex |
| Master Coach | Hidden health, latency, provider, and stall monitoring | Background system |

## Technology

- Python 3.14 and `ThreadingHTTPServer`
- Vanilla HTML, CSS, and JavaScript
- Ollama with `qwen2.5:3b` and `qwen2.5-coder:7b`
- OpenAI Codex and VS Cline as external execution providers
- Model Context Protocol (MCP) Python SDK over stdio
- Google Sheets API with OAuth 2.0 refresh tokens
- PyInstaller for Windows executables

## Modules

- `agent_server.py` — HTTP API, agents, orchestration, routing, memory, approvals, coach, and persistent state
- `conference_mcp.py` — 16-tool MCP bridge for Codex and VS Cline
- `google_sheet_reporter.py` — idempotent project and daily Google Sheets reporting
- `web/` — responsive browser dashboard
- `examples/agent-instructions/` — safe public examples of role instructions

## Quick start from source

### Requirements

1. Windows with Python 3.14+.
2. Ollama running at `http://localhost:11434`.
3. Models: `qwen2.5:3b` and `qwen2.5-coder:7b`.
4. Install dependencies:

```powershell
python -m pip install -r requirements.txt
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:7b
```

### Configure

Set environment variables in PowerShell. Never commit real credentials.

```powershell
$env:AGENT_CONFERENCE_OUTPUT_DIR="$HOME\AI-Agent-Conference\output"
$env:AGENT_CONFERENCE_MEMORY_DIR="$HOME\AI-Agent-Conference\memory"
$env:GOOGLE_SHEETS_SPREADSHEET_ID="your-spreadsheet-id"
$env:GOOGLE_OAUTH_CREDENTIALS_PATH="$HOME\AI-Agent-Conference\credentials.json"
```

Copy the role examples into the memory directory as `<agent>/INSTRUCTIONS.md`, or run:

```powershell
.\setup-instructions.ps1
```

### Run

```powershell
python agent_server.py
```

Open `http://localhost:8766`.

## Best starter prompt

```text
Project name: [clear project name]
Goal: [what must be created or solved]
Inputs: [files, text, APIs, or constraints]
Required output: [exact files/report/result]
Acceptance criteria:
1. [measurable requirement]
2. [measurable requirement]
3. [validation requirement]
Use smart routing. Ask for human approval before file or command operations. Report the actual provider used, exact artifacts, validation evidence, blockers, and next steps. Do not claim completion without evidence.
```

## MCP registration

Build `conference_mcp.py` or run it with Python, then register it as a stdio MCP server. Set a different identity for each client:

```text
AGENT_CONFERENCE_CLIENT=codex
AGENT_CONFERENCE_CLIENT=cline
```

The bridge exposes health, agents, providers, tasks, checkpoints, coach state, chat, projects, progress, notifications, service control, and UI tools.

## Google Sheets reporting

Reporting is optional. Provide an OAuth credential file containing `client_id`, `client_secret`, and `refresh_token`, and set the approved spreadsheet ID. The reporter creates one safely named worksheet per project and appends one daily summary. Duplicate completion and daily reports are prevented by local state.

## Safety and privacy

- The server binds to `127.0.0.1` by default.
- File read/write/run operations require human approval.
- Provider identity headers are checked for task completion and heartbeat calls.
- Credentials, memories, chat, generated output, logs, and state are excluded by `.gitignore`.
- Use a private repository until you complete your own secret scan.

## Suggested first GitHub post

**Title:** I Built a Local-First AI Agent Conference Without an Automation Background

**Message:** I started with no formal automation experience and learned by building. AI Agent Conference coordinates specialized AI roles through Ollama, Codex, VS Cline, and MCP, while keeping human approvals, persistent memory, monitoring, local outputs, and verified Google Sheets reports. This repository shares the source and architecture so others can study, improve, and adapt it safely.

## Before publishing

- Run the checks in `SECURITY_CHECKLIST.md`.
- Review every file in the commit.
- Keep credentials and personal memory outside the repository.
- Choose and add a license before accepting external reuse or contributions.

## Publish this project on GitHub

For complete beginner-friendly instructions, read [`GITHUB_PUBLISHING_GUIDE.md`](GITHUB_PUBLISHING_GUIDE.md).

Quick command-line method:

```powershell
git init
git branch -M main
git add .
git status
git diff --cached
git commit -m "Initial release of AI Agent Conference"
git remote add origin https://github.com/YOUR-USERNAME/ai-agent-conference.git
git push -u origin main
```

Create the GitHub repository as **Private** first. Replace `YOUR-USERNAME`, inspect the complete commit, run the security checklist, and make it Public only after confirming that no credentials, private memory, chat, logs, or generated user data are present.
