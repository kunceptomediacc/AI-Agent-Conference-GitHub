#!/usr/bin/env python3
"""Codex MCP bridge for the AI Agent Conference HTTP server."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from mcp.server.mcpserver import MCPServer


SERVER_URL = os.environ.get("AGENT_CONFERENCE_URL", "http://localhost:8766").rstrip("/")
CLIENT_ID = os.environ.get("AGENT_CONFERENCE_CLIENT", "codex").strip().lower()
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

mcp = MCPServer(
    "agent-conference",
    title="AI Agent Conference",
    description="Delegate work to Julia and the specialist agent team while tracking it in the browser UI.",
    instructions=(
        "Use conference_start_project for multi-agent work and conference_chat for a specific specialist. "
        "Use conference_get_progress to retrieve Julia's live progress and final results."
    ),
    version="1.0.0",
)


def _server_command():
    if getattr(sys, "frozen", False):
        executable = os.path.join(APP_DIR, "AgentConferenceServer.exe")
        return [executable] if os.path.isfile(executable) else None
    source = os.path.join(APP_DIR, "agent_server.py")
    return [sys.executable, source] if os.path.isfile(source) else None


def _request(path, method="GET", payload=None, retry=True):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        SERVER_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "X-Agent-Conference-Client": CLIENT_ID},
    )
    try:
        with urllib.request.urlopen(request, timeout=330) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", str(error))
        except Exception:
            detail = str(error)
        raise RuntimeError(detail) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        if retry and _start_server():
            return _request(path, method, payload, retry=False)
        raise RuntimeError("Agent Conference server is unavailable: " + str(error)) from error


def _start_server():
    command = _server_command()
    if not command:
        return False
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen(
            command,
            cwd=APP_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        for _ in range(30):
            time.sleep(0.2)
            try:
                _request("/health", retry=False)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _heartbeat():
    return _request("/providers/heartbeat", "POST", {"provider": CLIENT_ID})


def _heartbeat_loop():
    while True:
        try:
            _heartbeat()
        except Exception:
            pass
        time.sleep(30)


@mcp.tool()
def conference_health() -> dict:
    """Check the shared Agent Conference server, Ollama, and agent-service state."""
    health = _request("/health")
    _heartbeat()
    health["client"] = CLIENT_ID
    return health


@mcp.tool()
def conference_list_agents() -> dict:
    """List Julia and all specialist agents, including their tools and permissions."""
    _heartbeat()
    return _request("/agents")


@mcp.tool()
def conference_get_providers() -> dict:
    """Get Codex, VS Cline, and Ollama connection state, role routing, and estimated usage."""
    _heartbeat()
    return _request("/providers")


@mcp.tool()
def conference_get_assigned_tasks() -> dict:
    """Get pending hybrid workflow tasks assigned to this MCP client (Codex or VS Cline)."""
    _heartbeat()
    return _request("/provider-tasks")


@mcp.tool()
def conference_get_checkpoints(pending_only: bool = True) -> dict:
    """List human approval checkpoints requested by agents before file read/write/run operations."""
    data = _request("/approvals")
    items = data.get("approvals", [])
    if pending_only:
        items = [item for item in items if item.get("status") == "pending"]
    return {"approvals": items}


@mcp.tool()
def conference_resolve_checkpoint(approval_id: str, approve: bool) -> dict:
    """Approve or deny one human checkpoint. Review its tool, path, and message before approving."""
    return _request("/approvals/resolve", "POST", {"id": approval_id, "decision": "approve" if approve else "deny"})


@mcp.tool()
def conference_get_coach_status() -> dict:
    """Get hidden Master Coach API/MCP health, provider state, stalled projects, and Cline usage budget."""
    _heartbeat()
    return _request("/coach")


@mcp.tool()
def conference_complete_assigned_task(task_id: str, result: str, input_tokens: int = 0, output_tokens: int = 0) -> dict:
    """Submit completed work for a task previously returned by conference_get_assigned_tasks."""
    if not task_id.strip() or not result.strip():
        raise ValueError("task_id and result are required")
    return _request("/provider-tasks/complete", "POST", {
        "task_id": task_id, "provider": CLIENT_ID, "result": result,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "usage_type": "reported"}
    })


@mcp.tool()
def conference_chat(agent_id: str, message: str) -> dict:
    """Send a message or focused task to one agent. IDs: oreo, jessiejay, mercedes, abby, julia."""
    if not message.strip():
        raise ValueError("message is required")
    aliases = {"ab": "abby", "jessie": "jessiejay"}
    agent_id = aliases.get(agent_id.strip().lower(), agent_id.strip().lower())
    _heartbeat()
    return _request("/chat/" + agent_id, "POST", {"message": message, "source": CLIENT_ID})


@mcp.tool()
def conference_start_project(instruction: str, project_name: str = "", routing_mode: str = "smart") -> dict:
    """Delegate a multi-agent project to Julia. Returns a project_id for conference_get_progress."""
    if not instruction.strip():
        raise ValueError("instruction is required")
    _heartbeat()
    return _request("/instruction", "POST", {"text": instruction, "project_name": project_name, "async": True, "source": CLIENT_ID, "routing_mode": routing_mode})


@mcp.tool()
def conference_get_progress(project_id: str) -> dict:
    """Get live percentage, current agent/task, completed steps, outputs, and Julia's final report."""
    _heartbeat()
    return _request("/progress/" + project_id.strip())


@mcp.tool()
def conference_list_projects(status: str = "") -> dict:
    """List persisted project progress records, optionally filtered by status."""
    data = _request("/progress")
    projects = data.get("progress", [])
    if status.strip():
        projects = [item for item in projects if item.get("status") == status.strip()]
    projects.sort(key=lambda item: item.get("ts", ""), reverse=True)
    return {"progress": projects}


@mcp.tool()
def conference_get_notifications(unread_only: bool = True) -> dict:
    """Get agent messages, questions, task completions, and errors shown by the browser UI."""
    data = _request("/notifications")
    items = data.get("notifications", [])
    if unread_only:
        items = [item for item in items if not item.get("read")]
    return {"notifications": items}


@mcp.tool()
def conference_mark_notifications_read(notification_id: str = "") -> dict:
    """Mark one notification read by ID, or mark all read when notification_id is empty."""
    payload = {"id": notification_id} if notification_id.strip() else {}
    return _request("/notifications/read", "POST", payload)


@mcp.tool()
def conference_set_service(enabled: bool) -> dict:
    """Resume or pause agent processing while leaving the browser UI reachable."""
    return _request("/service/toggle", "POST", {"enabled": enabled})


@mcp.tool()
def conference_open_ui() -> dict:
    """Open the visual Agent Conference dashboard in the default browser."""
    _request("/health")
    opened = webbrowser.open(SERVER_URL)
    return {"opened": bool(opened), "url": SERVER_URL}


if __name__ == "__main__":
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    mcp.run(transport="stdio")