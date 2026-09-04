# How to Publish AI Agent Conference on GitHub

This guide is written for beginners. Start with a **Private** repository, verify everything, and make it Public only when you are ready.

## Option 1 — Upload using the GitHub website

1. Sign in at [github.com](https://github.com).
2. Click **New repository**.
3. Enter the repository name:

   ```text
   ai-agent-conference
   ```

4. Enter this description:

   ```text
   Local-first multi-agent orchestration with a browser dashboard, hybrid LLM routing, MCP integration, human checkpoints, persistent memory, monitoring, and Google Sheets reports.
   ```

5. Select **Private** for the first upload.
6. Do not add a README, `.gitignore`, or license on GitHub—the package already contains the first two. Choose a license later after reviewing your needs.
7. Click **Create repository**.
8. On the empty repository page, click **uploading an existing file**.
9. Extract `AI-Agent-Conference-GitHub.zip` on your computer.
10. Open the extracted `AI-Agent-Conference-GitHub` folder.
11. Drag its contents into GitHub. Upload the contents, not the outer folder itself.
12. Use this commit message:

    ```text
    Initial release of AI Agent Conference
    ```

13. Click **Commit changes**.
14. Confirm that `README.md`, `agent_server.py`, `conference_mcp.py`, `google_sheet_reporter.py`, `web/`, `documentation/`, and the hidden `.gitignore` file are present.
15. Review the repository before changing visibility to Public.

> GitHub's browser uploader may not preserve an empty directory, but this project does not rely on empty directories. Hidden files such as `.gitignore` are already included in the ZIP.

## Option 2 — Upload using Git commands

Install Git, open PowerShell inside the extracted folder, and run:

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

Replace `YOUR-USERNAME` with your GitHub username.

If Git asks for your identity, configure it first:

```powershell
git config --global user.name "Your Name"
git config --global user.email "your-public-github-email@example.com"
```

GitHub no longer accepts an account password for command-line pushes. Sign in through Git Credential Manager, GitHub CLI, SSH, or a properly scoped personal access token. Never save a token inside this repository.

## Option 3 — Use GitHub Desktop

1. Install and open GitHub Desktop.
2. Choose **File → Add local repository**.
3. Select the extracted `AI-Agent-Conference-GitHub` folder.
4. If asked, choose **Create a repository here**.
5. Enter `Initial release of AI Agent Conference` as the summary.
6. Click **Commit to main**.
7. Click **Publish repository**.
8. Keep **Private** selected for the first publication.

## Recommended repository information

**Repository name**

```text
ai-agent-conference
```

**Title**

```text
AI Agent Conference — Local-First Multi-Agent Orchestration
```

**Description**

```text
Local-first multi-agent orchestration with a browser dashboard, hybrid LLM routing, MCP integration, human checkpoints, persistent memory, monitoring, and Google Sheets reports.
```

**Suggested topics**

```text
multi-agent ai-agents ollama mcp codex cline python automation google-sheets local-ai
```

## Suggested announcement

### I Built a Local-First AI Agent Conference Without an Automation Background

I started with no formal automation experience and learned by building. AI Agent Conference coordinates specialized AI roles through Ollama, Codex, VS Cline, and MCP, while keeping human approvals, persistent memory, monitoring, local outputs, and verified Google Sheets reports. This repository shares the source and architecture so others can study, improve, and adapt it safely.

## Safety check before making the repository Public

Confirm that the repository does **not** contain:

- OAuth credentials, API keys, passwords, cookies, or access tokens;
- a real `.env` file;
- private spreadsheet IDs;
- `memory.json`, chat history, notifications, or personal conversations;
- generated projects, customer files, reports, logs, or backups;
- provider usage, approval, or coach-state files;
- personal absolute paths or usernames.

Run these commands before pushing:

```powershell
git status
git diff --cached
git ls-files
```

For stronger protection, run a secret scanner such as Gitleaks. Review `SECURITY_CHECKLIST.md` as well.

## Update the repository later

After changing source or documentation:

```powershell
git status
git diff
git add .
git diff --cached
git commit -m "Describe the update clearly"
git push
```

Useful commit examples:

```text
Improve provider fallback handling
Add Google Sheets reporting documentation
Fix project progress synchronization
Update MCP setup instructions
```

## Create a GitHub release

After the repository is working:

1. Open the repository on GitHub.
2. Select **Releases → Draft a new release**.
3. Create a tag such as `v1.0.0`.
4. Use the title `AI Agent Conference v1.0.0`.
5. Summarize the main features and known limitations.
6. Attach a compiled application ZIP only if it contains no credentials, private memory, logs, or user data.
7. Click **Publish release**.

## Important notes

- Do not upload the live `D:\AI Conference` data folder or your personal agent-memory folder.
- Do not upload Google OAuth credentials.
- This package intentionally contains source code and safe examples, not private runtime state.
- No open-source license has been selected. Add one before inviting public reuse or contributions.
