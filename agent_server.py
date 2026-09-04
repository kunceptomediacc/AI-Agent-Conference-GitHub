#!/usr/bin/env python3
"""AI Agent Conference Server - Ollama + Tools/Plugins + Memory + Orchestrator + Web UI"""
import json, sys, os, subprocess, mimetypes, shutil, re, threading, time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import google_sheet_reporter

PORT = int(os.environ.get("AGENT_CONFERENCE_PORT", "8766"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
SERVICE_ENABLED = True
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else SOURCE_DIR
RESOURCE_DIR = getattr(sys, "_MEIPASS", SOURCE_DIR)
WEB_DIR = os.path.join(RESOURCE_DIR, "web")
MEMORY_ROOT = os.path.abspath(os.path.expanduser(os.environ.get(
    "AGENT_CONFERENCE_MEMORY_DIR", "~/AI-Agent-Conference/memory")))
BACKUP_ROOT = os.path.join(MEMORY_ROOT, "_backups")
WORKSPACE = os.path.join(APP_DIR, "workspace")

# Organized output directory
OUTPUT_DIR = os.path.abspath(os.path.expanduser(os.environ.get(
    "AGENT_CONFERENCE_OUTPUT_DIR", "~/AI-Agent-Conference/output")))
PROJECTS_DIR = os.path.join(OUTPUT_DIR, "projects")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")
INSTRUCTIONS_DIR = os.path.join(OUTPUT_DIR, "instructions")
PROGRESS_DIR = os.path.join(OUTPUT_DIR, "progress")
OUTPUT_BACKUP_DIR = os.path.join(OUTPUT_DIR, "backups")
CHAT_DIR = os.path.join(OUTPUT_DIR, "chat")
CHAT_PATH = os.path.join(CHAT_DIR, "messages.json")
PROVIDERS_PATH = os.path.join(OUTPUT_DIR, "providers.json")
USAGE_PATH = os.path.join(OUTPUT_DIR, "usage.json")
PROVIDER_TASKS_PATH = os.path.join(OUTPUT_DIR, "provider_tasks.json")
APPROVALS_PATH = os.path.join(OUTPUT_DIR, "approvals.json")
COACH_STATE_PATH = os.path.join(OUTPUT_DIR, "coach_state.json")
COACH_CONFIG_PATH = os.path.join(OUTPUT_DIR, "coach_config.json")
STATE_LOCK = threading.Lock()
MEMORY_LOCK = threading.RLock()
NOTIFICATION_LOCK = threading.RLock()
MAX_REQUEST_BYTES = 1024 * 1024
COACH_INTERVAL_SECONDS = 15
APPROVAL_TIMEOUT_SECONDS = 300
DEFAULT_COACH_CONFIG = {
    "cline_token_budget": 100000,
    "provider_stale_seconds": 120,
    "project_stale_seconds": 300,
    "high_latency_ms": 3000
}

ROLE_PROVIDERS = {
    "julia": "codex", "oreo": "cline", "jessiejay": "ollama",
    "mercedes": "cline", "abby": "codex"
}

# Ensure output directories exist
for d in [OUTPUT_DIR, PROJECTS_DIR, REPORTS_DIR, INSTRUCTIONS_DIR, PROGRESS_DIR, OUTPUT_BACKUP_DIR, CHAT_DIR]:
    os.makedirs(d, exist_ok=True)

def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json_file(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def add_chat_message(sender, content, agent_id=None, source="web", is_conference=False, message_id=None, severity="normal"):
    item = {
        "id": message_id or (str(datetime.now().timestamp()) + "-" + str(abs(hash(content)) % 10000)),
        "sender": sender, "content": content[:10000], "agent_id": agent_id,
        "source": source, "is_conference": bool(is_conference), "ts": datetime.now().isoformat(),
        "severity": severity
    }
    with STATE_LOCK:
        items = load_json_file(CHAT_PATH, [])
        existing = next((entry for entry in items if entry.get("id") == item["id"]), None)
        if existing:
            return existing
        items.append(item)
        save_json_file(CHAT_PATH, items[-1000:])
    return item

def provider_snapshot():
    data = load_json_file(PROVIDERS_PATH, {})
    now = datetime.now().timestamp()
    result = {"ollama": {"connected": True, "last_seen": datetime.now().isoformat()}}
    stale_seconds = int(load_json_file(COACH_CONFIG_PATH, {}).get("provider_stale_seconds", 120))
    for provider in ("codex", "cline"):
        item = data.get(provider, {})
        item["connected"] = now - float(item.get("timestamp", 0)) < stale_seconds
        result[provider] = item
    return result

def provider_heartbeat(provider):
    provider = provider.lower()
    if provider not in ("codex", "cline"): return
    with STATE_LOCK:
        data = load_json_file(PROVIDERS_PATH, {})
        data[provider] = {"timestamp": datetime.now().timestamp(), "last_seen": datetime.now().isoformat(), "connected": True}
        save_json_file(PROVIDERS_PATH, data)

def record_usage(provider, agent_id, source, input_text, output_text, project_id=None, reported_usage=None):
    reported_usage = reported_usage or {}
    has_reported = reported_usage.get("input_tokens", 0) or reported_usage.get("output_tokens", 0)
    event = {
        "id": str(datetime.now().timestamp()), "ts": datetime.now().isoformat(),
        "provider": provider, "agent": agent_id, "source": source,
        "project_id": project_id, "requests": 1,
        "input_tokens_estimated": max(1, len(input_text) // 4),
        "output_tokens_estimated": max(1, len(output_text) // 4),
        "input_tokens_reported": int(reported_usage.get("input_tokens", 0)),
        "output_tokens_reported": int(reported_usage.get("output_tokens", 0)),
        "usage_type": "reported" if has_reported else "estimated"
    }
    with STATE_LOCK:
        items = load_json_file(USAGE_PATH, [])
        items.append(event)
        save_json_file(USAGE_PATH, items[-5000:])
    return event

def usage_summary():
    events = load_json_file(USAGE_PATH, [])
    totals = {}
    for event in events:
        provider = event.get("provider", "unknown")
        item = totals.setdefault(provider, {"requests": 0, "input_tokens_estimated": 0, "output_tokens_estimated": 0, "input_tokens_reported": 0, "output_tokens_reported": 0})
        item["requests"] += 1
        item["input_tokens_estimated"] += event.get("input_tokens_estimated", 0)
        item["output_tokens_estimated"] += event.get("output_tokens_estimated", 0)
        item["input_tokens_reported"] += event.get("input_tokens_reported", 0)
        item["output_tokens_reported"] += event.get("output_tokens_reported", 0)
    return {"totals": totals, "events": events[-100:]}

def coach_config():
    config = DEFAULT_COACH_CONFIG.copy()
    config.update(load_json_file(COACH_CONFIG_PATH, {}))
    return config

def system_report(message, key=None, cooldown=300):
    """Publish a deduplicated red Conference message and notification."""
    now = time.time()
    key = key or re.sub(r"\W+", "-", message.lower())[:80]
    with STATE_LOCK:
        state = load_json_file(COACH_STATE_PATH, {})
        alerts = state.setdefault("alerts", {})
        if now - float(alerts.get(key, 0)) < cooldown:
            return None
        alerts[key] = now
        state["last_check"] = datetime.now().isoformat()
        save_json_file(COACH_STATE_PATH, state)
    item = add_chat_message("System", message, None, "master-coach", True, severity="error")
    add_notification("system", "System", message, "error")
    if provider_snapshot().get("codex", {}).get("connected") and key not in ("codex-offline",):
        existing = [task for task in load_json_file(PROVIDER_TASKS_PATH, [])
                    if task.get("project_id") == "coach-" + key and task.get("status") == "pending"]
        if not existing:
            coach_instructions = load_agent_instructions("master-coach")
            create_provider_task("codex", "master-coach",
                "%s\n\nCURRENT ISSUE:\n%s" % (coach_instructions, message),
                "coach-" + key)
    return item

def create_approval(agent_id, agent_name, tool_name, message, path=None):
    item = {
        "id": str(datetime.now().timestamp()) + "-" + str(abs(hash(message)) % 10000),
        "agent_id": agent_id, "agent_name": agent_name, "tool": tool_name,
        "message": message[:1000], "path": path, "status": "pending",
        "created": datetime.now().isoformat(), "resolved": None
    }
    with STATE_LOCK:
        items = load_json_file(APPROVALS_PATH, [])
        items.append(item)
        save_json_file(APPROVALS_PATH, items[-500:])
    system_report("Human checkpoint: %s requests permission to %s%s." % (
        agent_name, tool_name.replace("_", " "), " — " + path if path else ""
    ), "approval-" + item["id"], cooldown=0)
    return item

def resolve_approval(approval_id, decision):
    with STATE_LOCK:
        items = load_json_file(APPROVALS_PATH, [])
        target = next((item for item in items if item.get("id") == approval_id), None)
        if not target:
            return None
        if target.get("status") == "pending":
            target["status"] = "approved" if decision == "approve" else "denied"
            target["resolved"] = datetime.now().isoformat()
            save_json_file(APPROVALS_PATH, items)
        return target

def wait_for_approval(approval_id, timeout=APPROVAL_TIMEOUT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = next((x for x in load_json_file(APPROVALS_PATH, []) if x.get("id") == approval_id), None)
        if item and item.get("status") in ("approved", "denied"):
            return item.get("status")
        time.sleep(1)
    resolve_approval(approval_id, "deny")
    return "timeout"

def create_provider_task(provider, agent_id, task, project_id):
    item = {
        "id": str(datetime.now().timestamp()) + "-" + str(abs(hash(task)) % 10000),
        "provider": provider, "agent": agent_id, "task": task,
        "project_id": project_id, "status": "pending", "created": datetime.now().isoformat(),
        "result": ""
    }
    with STATE_LOCK:
        items = load_json_file(PROVIDER_TASKS_PATH, [])
        items.append(item)
        save_json_file(PROVIDER_TASKS_PATH, items[-1000:])
    return item

def list_provider_tasks(provider, status="pending"):
    items = load_json_file(PROVIDER_TASKS_PATH, [])
    return [item for item in items if item.get("provider") == provider and (not status or item.get("status") == status)]

def complete_provider_task(task_id, provider, result, usage=None):
    with STATE_LOCK:
        items = load_json_file(PROVIDER_TASKS_PATH, [])
        target = next((item for item in items if item.get("id") == task_id and item.get("provider") == provider), None)
        if not target:
            return None
        target["status"] = "completed"
        target["result"] = result[:20000]
        target["completed"] = datetime.now().isoformat()
        target["reported_usage"] = usage or {}
        save_json_file(PROVIDER_TASKS_PATH, items)
    record_usage(provider, target.get("agent"), provider, target.get("task", ""), result, target.get("project_id"), usage)
    return target

def wait_for_provider_task(task_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        item = next((x for x in load_json_file(PROVIDER_TASKS_PATH, []) if x.get("id") == task_id), None)
        if item and item.get("status") == "completed":
            return item.get("result", "")
        time.sleep(1)
    with STATE_LOCK:
        items = load_json_file(PROVIDER_TASKS_PATH, [])
        for item in items:
            if item.get("id") == task_id and item.get("status") == "pending":
                item["status"] = "fallback"
                item["completed"] = datetime.now().isoformat()
        save_json_file(PROVIDER_TASKS_PATH, items)
    return ""

def measure_url(url, timeout=4):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(32)
        return True, int((time.perf_counter() - started) * 1000), ""
    except Exception as error:
        return False, int((time.perf_counter() - started) * 1000), str(error)

def master_coach_check():
    """Monitor APIs, providers, workflows and usage without becoming a chat agent."""
    config = coach_config()
    checks = {}
    ollama_ok, ollama_ms, ollama_error = measure_url(OLLAMA_URL + "/api/tags")
    checks["ollama"] = {"ok": ollama_ok, "latency_ms": ollama_ms, "error": ollama_error}
    if not ollama_ok:
        system_report("Master Coach: Ollama API is unavailable. Local agent work and fallback execution are blocked. Start Ollama and verify port 11434.", "ollama-down")
    elif ollama_ms > config["high_latency_ms"]:
        system_report("Master Coach: Ollama API latency is high (%d ms). Check model load, RAM/VRAM, and queued requests." % ollama_ms, "ollama-latency")

    providers = provider_snapshot()
    for provider in ("codex", "cline"):
        if not providers.get(provider, {}).get("connected"):
            system_report("Master Coach: %s MCP client is offline. Assigned work will use local Ollama fallback." % ("VS Cline" if provider == "cline" else "Codex"), provider + "-offline", cooldown=600)

    usage = usage_summary().get("totals", {}).get("cline", {})
    cline_tokens = (usage.get("input_tokens_reported", 0) + usage.get("output_tokens_reported", 0)) or (
        usage.get("input_tokens_estimated", 0) + usage.get("output_tokens_estimated", 0)
    )
    if cline_tokens >= config["cline_token_budget"]:
        system_report("Master Coach: VS Cline usage reached the configured budget (%d/%d tokens). New Cline work should pause or fall back until the budget is reset." % (cline_tokens, config["cline_token_budget"]), "cline-budget", cooldown=3600)

    now = time.time()
    stalled = []
    for project in list_progress():
        if project.get("status") in ("completed", "failed"):
            continue
        try:
            age = now - datetime.fromisoformat(project.get("updated_at") or project.get("ts", "")).timestamp()
        except Exception:
            age = 0
        if age > config["project_stale_seconds"] and project.get("percent", 0) < 100:
            stalled.append(project.get("id"))
            system_report("Master Coach: project %s appears stalled at %s%%. Current task: %s. The coach will preserve the record and use configured fallback behavior." % (
                project.get("id"), project.get("percent", 0), project.get("current_task") or "unknown"
            ), "stalled-" + str(project.get("id")), cooldown=600)

    state = load_json_file(COACH_STATE_PATH, {})
    state.update({"last_check": datetime.now().isoformat(), "checks": checks, "providers": providers,
                  "cline_tokens": cline_tokens, "stalled_projects": stalled, "status": "monitoring"})
    state["instruction_chars_loaded"] = len(load_agent_instructions("master-coach"))
    save_json_file(COACH_STATE_PATH, state)
    return state

def master_coach_loop():
    time.sleep(3)
    while True:
        try:
            master_coach_check()
        except Exception as error:
            print("Master Coach error:", error)
        time.sleep(COACH_INTERVAL_SECONDS)

def report_to_google_sheet(record):
    """Write completion evidence asynchronously; never fail the project on reporting errors."""
    try:
        result = google_sheet_reporter.write_project_report_once(record)
        if not result.get("skipped"):
            add_memory("julia", "google_sheet_report", "Verified project report written to worksheet: " + result.get("sheet", "unknown"))
    except Exception as error:
        system_report("Julia Google Sheets report failed: %s. Project output remains saved locally." % error,
                      "google-sheet-project-" + str(record.get("id")), cooldown=600)

def google_sheet_daily_loop():
    """Write one daily Conference summary at/after the configured local time."""
    time.sleep(10)
    while True:
        try:
            settings = google_sheet_reporter.config()
            now = datetime.now()
            if settings.get("enabled", True) and (now.hour, now.minute) >= (
                    int(settings.get("daily_hour", 18)), int(settings.get("daily_minute", 0))):
                google_sheet_reporter.write_daily_summary_once(now.strftime("%Y-%m-%d"))
        except Exception as error:
            system_report("Julia daily Google Sheets report failed: %s" % error,
                          "google-sheet-daily-" + datetime.now().strftime("%Y-%m-%d"), cooldown=3600)
        time.sleep(60)

AGENTS = {
    "oreo": {
        "name": "Oreo", "type": "Coding",
        "description": "Coding - JSON, Python, CSS, HTML, JS. Can create, read and run files.",
        "personality": "bully",
        "avatar": {"emoji": "\U0001F415", "bg": "#3f4147", "breed": "Shih Tzu x Pomeranian mix - black/grey/brown, male"},
        "permissions": ["read", "write", "run"],
        "tools": ["write_code", "read_file", "run_python"],
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You are Oreo, a coding expert (JSON, Python, CSS, HTML, JS) with a BULLY personality - blunt, sarcastic, calls bad code out, but always gives the correct solution. Short and punchy. You CAN: create and save code files, read files, and run Python files on the user's machine when asked."
    },
    "jessiejay": {
        "name": "JessieJay", "type": "UI/UX Design",
        "description": "UI design, architecture, workflow analysis, business process.",
        "personality": "sweet",
        "avatar": {"emoji": "\U0001F415", "bg": "#e8e4dc", "breed": "Maltese x Shih Tzu mix - white, female"},
        "permissions": ["read"],
        "tools": ["review_ui"],
        "model": "qwen2.5:3b",
        "system_prompt": "You are JessieJay, a sweet UI/UX design and architecture expert. Encouraging, uses 'honey/sweetie/dear' and warm emojis. You CAN review HTML/CSS files and give design feedback."
    },
    "mercedes": {
        "name": "Mercedes", "type": "IT Infrastructure",
        "description": "IT networking, MCP, API, hosting, database, security.",
        "personality": "silent_shy",
        "avatar": {"emoji": "\U0001F415", "bg": "#b5622a", "breed": "Japanese Shiba Inu - brown, male"},
        "permissions": ["read", "run"],
        "tools": ["ping", "ipconfig", "netstat", "nslookup"],
        "model": "qwen2.5:3b",
        "system_prompt": "You are Mercedes, an IT infrastructure expert (networking, APIs, hosting, databases, security, guardrails). SHY and SILENT - short minimal sentences, 5-10 words max. Technically brilliant. You CAN run real network diagnostics: ping, ipconfig, netstat, nslookup."
    },
    "abby": {
        "name": "Ab", "type": "Debugging & QA",
        "description": "Debugging, QA testing, workflow analysis, redundancy checks.",
        "personality": "strict",
        "avatar": {"emoji": "\U0001F415", "bg": "#23201d", "breed": "Pitbull - black/brown/white, male"},
        "permissions": ["read", "run"],
        "tools": ["check_file", "list_workspace"],
        "model": "qwen2.5:3b",
        "system_prompt": "You are Ab, a strict debugging and QA expert. You demand excellence: 'Unacceptable.', 'Fix this immediately.' Thorough, methodical, zero tolerance for bugs. You CAN syntax-check files (python/js) and inspect the workspace."
    },
    "julia": {
        "name": "Julia", "type": "Lead / Orchestrator",
        "description": "Receives instructions, analyzes, builds workflows, distributes tasks, verifies and reports.",
        "personality": "professional",
        "avatar": {"emoji": "\U0001F415", "bg": "#7a4a21", "breed": "Brown Dachshund, female"},
        "permissions": ["read", "run"],
        "scripts": {
            "scan": os.environ.get("JULIA_SCAN_SCRIPT", ""),
            "report": os.environ.get("JULIA_REPORT_SCRIPT", ""),
            "cloudflare": os.environ.get("JULIA_CLOUDFLARE_SCRIPT", "")
        },
        "model": "qwen2.5:3b",
        "system_prompt": "You are Julia, the LEAD agent. You receive instructions, analyze them, build workflows, distribute tasks to the team, verify results, and write final reports. PROFESSIONAL and organized. You have REAL tools: 'scan' runs project_scanner.py, 'report' runs daily_report.py, 'cloudflare' runs cloudflare_scanner.py. Summarize real tool output faithfully - never invent data."
    }
}

# ================= MEMORY SYSTEM (with backups) =================
def memory_dir(agent_id):
    return os.path.join(MEMORY_ROOT, agent_id)

def memory_path(agent_id):
    return os.path.join(memory_dir(agent_id), "memory.json")

def instruction_path(agent_id):
    return os.path.join(memory_dir(agent_id), "INSTRUCTIONS.md")

def load_agent_instructions(agent_id):
    path = instruction_path(agent_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def composed_system_prompt(agent_id, base_prompt):
    instructions = load_agent_instructions(agent_id)
    memory = memory_context(agent_id)
    parts = []
    if instructions:
        parts.append("MANDATORY OPERATIONAL INSTRUCTIONS — read and follow completely:\n" + instructions)
    else:
        parts.append("WARNING: The operational instruction file is missing. Do not guess; report this configuration problem.")
    if memory:
        parts.append(memory)
    parts.append("CURRENT ROLE/TASK INSTRUCTIONS:\n" + base_prompt)
    parts.append("Use memory for relevant learnings and prior mistakes, but verify current facts. Never hallucinate evidence or completion.")
    return "\n\n".join(parts)

def backup_file(src, tag=""):
    """Copy a file into the backup folder with a timestamp."""
    if not os.path.exists(src):
        return
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(src)
    dst = os.path.join(BACKUP_ROOT, tag + "_" + ts + "_" + name)
    try:
        shutil.copy2(src, dst)
        prune_backups()
    except Exception as e:
        print("Backup failed:", e)

def prune_backups(keep=100):
    try:
        files = sorted([f for f in os.listdir(BACKUP_ROOT) if f.endswith(".json")])
        for f in files[:-keep]:
            os.remove(os.path.join(BACKUP_ROOT, f))
    except Exception:
        pass

def load_memory(agent_id):
    p = memory_path(agent_id)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"agent": agent_id, "created": datetime.now().isoformat(), "entries": []}

def save_memory(agent_id, mem):
    os.makedirs(memory_dir(agent_id), exist_ok=True)
    p = memory_path(agent_id)
    backup_file(p, agent_id)          # always backup before writing
    with open(p, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)

def add_memory(agent_id, mtype, summary):
    with MEMORY_LOCK:
        mem = load_memory(agent_id)
        mem.setdefault("entries", []).append({
            "ts": datetime.now().isoformat(),
            "type": mtype,
            "summary": summary[:2000]
        })
        mem["entries"] = mem["entries"][-200:]   # keep last 200 entries
        save_memory(agent_id, mem)

def save_response_learning(agent_id, reply):
    """Persist an explicitly reported learning/mistake without inventing one."""
    match = re.search(r"(?is)(?:MEMORY LEARNING|MEMORY LEARNINGS)\s*:?\s*(.+)$", reply or "")
    if match:
        learning = match.group(1).strip()[:1500]
        if learning:
            add_memory(agent_id, "learning", learning)

def memory_context(agent_id, limit=200):
    mem = load_memory(agent_id)
    entries = mem.get("entries", [])[-limit:]
    if not entries:
        return ""
    lines = ["- [%s] %s: %s" % (e.get("ts", "")[:16], e.get("type", "chat"), e.get("summary", "")[:300]) for e in entries]
    return "\nYour complete retained memory (most recent last):\n" + "\n".join(lines)

def preload_memories():
    """Called at startup: every agent reads its memory before starting."""
    print("--- Agents loading memory from", MEMORY_ROOT, "---")
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for aid, agent in AGENTS.items():
        mem = load_memory(aid)
        n = len(mem.get("entries", []))
        p = memory_path(aid)
        if os.path.exists(p):
            try:
                dst = os.path.join(BACKUP_ROOT, "startup_%s_%s_memory.json" % (ts, aid))
                shutil.copy2(p, dst)
            except Exception:
                pass
        instructions = load_agent_instructions(aid)
        print("  %s: %d memories, %d instruction chars loaded" % (agent["name"], n, len(instructions)))
    print("--------------------------------------")

# ================= TOOLS / PLUGINS (with permissions) =================
def has_permission(agent, perm):
    return perm in agent.get("permissions", [])

def python_runtime():
    """Find a real Python interpreter; a frozen server executable is not Python."""
    candidates = []
    configured = os.environ.get("AGENT_CONFERENCE_PYTHON")
    if configured:
        candidates.append(configured)
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    candidates.extend([shutil.which("python"), shutil.which("py")])
    return next((path for path in candidates if path and os.path.isfile(path)), None)

PATH_RE = re.compile(r"([A-Za-z]:[\/][^\"'*?<>|\r\n]+)")

def extract_path(message):
    m = PATH_RE.search(message)
    return m.group(1).strip().strip('"\'') if m else None

def tool_read_file(agent, message):
    if not has_permission(agent, "read"):
        return "[tool denied] no read permission"
    path = extract_path(message)
    if not path or not os.path.isfile(path):
        return "[tool] File not found. Give a full path to the file."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(6000)
        return "[Real file content of %s]\n%s" % (path, data)
    except Exception as e:
        return "[tool error] %s" % e

def tool_run_python(agent, message):
    if not has_permission(agent, "run"):
        return "[tool denied] no run permission"
    path = extract_path(message)
    if not path or not os.path.isfile(path):
        return "[tool] Give a full path to a .py file to run."
    python = python_runtime()
    if not python:
        return "[tool] Python runtime is unavailable in the compiled application."
    try:
        r = subprocess.run([python, path], capture_output=True, text=True,
                           timeout=120, cwd=os.path.dirname(path))
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return "[Real run of %s (exit %s)]\n%s" % (path, r.returncode, out[-3000:])
    except subprocess.TimeoutExpired:
        return "[tool] Run timed out after 120s."

def tool_write_code(agent, message, model=None):
    if not has_permission(agent, "write"):
        return "[tool denied] no write permission"
    name = None
    m = re.search(r"([\w\-.]+\.(?:py|html|css|js|json|md|txt|csv))", message, re.I)
    if m:
        name = m.group(1)
    if not name:
        ext = ".py"
        if re.search(r"html|page|site", message, re.I): ext = ".html"
        elif re.search(r"css|style", message, re.I): ext = ".css"
        elif re.search(r"js|javascript", message, re.I): ext = ".js"
        elif re.search(r"json", message, re.I): ext = ".json"
        name = "file_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ext
    topic = re.sub(r"(?i)(oreo|create|write|make|save|file|please)", "", message).strip() or "a useful example"
    prompt = "Write complete, working code for: %s. Respond with ONE code block only." % topic
    code = ollama_generate(agent.get("model", "qwen2.5-coder:7b"), prompt)
    if not code.strip():
        return "[tool] Code generation failed; no file was written."
    cm = re.search(r"```(?:[\w+]*\n)?(.*?)```", code, re.S)
    if cm:
        code = cm.group(1)
    # Save to organized projects directory
    path = os.path.join(PROJECTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return "[Real file created: %s (%d bytes)]" % (path, len(code))

def tool_review_ui(agent, message):
    if not has_permission(agent, "read"):
        return "[tool denied] no read permission"
    path = extract_path(message)
    if not path or not os.path.isfile(path):
        return "[tool] Give a full path to an HTML/CSS file to review."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(6000)
        return "[Real file content of %s for design review]\n%s" % (path, data)
    except Exception as e:
        return "[tool error] %s" % e

def tool_check_file(agent, message):
    if not has_permission(agent, "run"):
        return "[tool denied] no run permission"
    path = extract_path(message)
    if not path:
        # check everything in workspace
        if os.path.isdir(WORKSPACE):
            files = [os.path.join(WORKSPACE, f) for f in os.listdir(WORKSPACE)]
            if files:
                results = []
                for fp in files[-5:]:
                    results.append(check_one(fp))
                return "[Real QA check of workspace]\n" + "\n".join(results)
        return "[tool] Workspace is empty. Give a full path to check."
    if not os.path.isfile(path):
        return "[tool] File not found: " + path
    return "[Real QA check]\n" + check_one(path)

def check_one(path):
    try:
        if path.endswith(".py"):
            python = python_runtime()
            if not python:
                return "%s: BLOCKED (Python runtime unavailable)" % os.path.basename(path)
            r = subprocess.run([python, "-m", "py_compile", path],
                               capture_output=True, text=True, timeout=60)
            return ("%s: %s" % (os.path.basename(path), "PASS" if r.returncode == 0 else "FAIL: " + (r.stderr or "")[-300:]))
        elif path.endswith(".js"):
            r = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=60)
            return ("%s: %s" % (os.path.basename(path), "PASS" if r.returncode == 0 else "FAIL: " + (r.stderr or "")[-300:]))
        else:
            return "%s: skipped (not .py/.js)" % os.path.basename(path)
    except Exception as e:
        return "%s: ERROR %s" % (os.path.basename(path), e)

def tool_net(agent, message):
    if not has_permission(agent, "run"):
        return "[tool denied] no run permission"
    ml = message.lower()
    try:
        if "ping" in ml:
            m = re.search(r"ping\s+([\w.\-]+)", ml)
            host = m.group(1) if m else "8.8.8.8"
            r = subprocess.run(["ping", "-n", "4", host], capture_output=True, text=True, timeout=30)
            return "[Real ping output]\n" + (r.stdout or r.stderr)[-1200:]
        if "ipconfig" in ml:
            r = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=20)
            return "[Real ipconfig output]\n" + (r.stdout or "")[-1500:]
        if "netstat" in ml:
            r = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=30)
            return "[Real netstat output]\n" + (r.stdout or "")[-1500:]
        if "nslookup" in ml:
            m = re.search(r"nslookup\s+([\w.\-]+)", ml)
            host = m.group(1) if m else "localhost"
            r = subprocess.run(["nslookup", host], capture_output=True, text=True, timeout=20)
            return "[Real nslookup output]\n" + (r.stdout or r.stderr)[-1000:]
    except Exception as e:
        return "[tool error] %s" % e
    return None

# ================= OLLAMA ENGINE =================
def ollama_generate(model, prompt, system=None, temperature=0.7):
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 1024}
    }
    if system:
        payload["system"] = system
    payload["prompt"] = prompt
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode()).get("response", "")
    except Exception as e:
        return ""

def ollama_chat(model, system_prompt, user_content, temperature=0.7):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 1024}
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode()).get("message", {}).get("content", "")
    except Exception as e:
        return ""

def run_agent_script(script, label):
    if not os.path.exists(script):
        return None
    python = python_runtime()
    if not python:
        return "[Output of %s tool]\nPython runtime unavailable." % label
    try:
        result = subprocess.run([python, script], capture_output=True,
                                text=True, timeout=180, cwd=os.path.dirname(script))
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        body = out if out else err
        return "[Real output from %s tool]\n%s" % (label, body[-3000:])
    except subprocess.TimeoutExpired:
        return "[Output of %s tool]\nTimed out after 180s." % label
    except Exception as e:
        return "[Output of %s tool]\nFailed: %s" % (label, e)

TOOL_MAP = {
    "read_file": tool_read_file,
    "run_python": tool_run_python,
    "write_code": tool_write_code,
    "review_ui": tool_review_ui,
    "check_file": tool_check_file,
    "ping": tool_net,
    "ipconfig": tool_net,
    "netstat": tool_net,
    "nslookup": tool_net,
}

APPROVAL_TOOLS = {"read_file", "write_code", "run_python", "review_ui", "check_file"}

def agent_id_for(agent):
    for agent_id, configured in AGENTS.items():
        if configured is agent:
            return agent_id
    return "unknown"

def run_with_approval(agent, tool_name, message, callback):
    """Require explicit human approval before file read/write/execute tools."""
    agent_id = agent_id_for(agent)
    approval = create_approval(agent_id, agent.get("name", agent_id), tool_name, message, extract_path(message))
    decision = wait_for_approval(approval["id"])
    if decision != "approved":
        return "[Human checkpoint %s] Permission %s for %s." % (
            approval["id"], "denied" if decision == "denied" else "timed out", tool_name
        )
    return callback()

def detect_tool(agent, message):
    """Return (tool_name, tool_result) if a real tool should run, else (None, None)."""
    ml = message.lower()
    scripts = agent.get("scripts")
    if scripts:
        for kw, script in scripts.items():
            if kw in ml:
                out = run_with_approval(agent, "script:" + kw, message + "\n" + script,
                                        lambda: run_agent_script(script, kw))
                if out:
                    return ("script:" + kw, out)
    tools = agent.get("tools", [])
    for t in tools:
        if t == "write_code" and re.search(r"(?i)(create|write|make|save)\s+(a\s+)?(file|code|page|script)", ml):
            return (t, run_with_approval(agent, t, message, lambda: tool_write_code(agent, message)))
        if t == "read_file" and re.search(r"(?i)(read|open|show)\s+(the\s+)?file", ml):
            return (t, run_with_approval(agent, t, message, lambda: tool_read_file(agent, message)))
        if t == "run_python" and re.search(r"(?i)\brun\b.*\.py", ml):
            return (t, run_with_approval(agent, t, message, lambda: tool_run_python(agent, message)))
        if t == "review_ui" and re.search(r"(?i)(review|analyze|feedback).*(ui|design|html|css)|((ui|design|html|css).*review)", ml):
            return (t, run_with_approval(agent, t, message, lambda: tool_review_ui(agent, message)))
        if t == "check_file" and re.search(r"(?i)(check|test|lint|qa|debug)", ml):
            return (t, run_with_approval(agent, t, message, lambda: tool_check_file(agent, message)))
        if t in ("ping", "ipconfig", "netstat", "nslookup") and t in ml:
            return (t, tool_net(agent, message))
    return (None, None)

# ================= HANDLER =================
class AgentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/agents":
            lst = []
            for aid, a in AGENTS.items():
                lst.append({"id": aid, "name": a["name"], "type": a["type"],
                            "description": a["description"], "personality": a["personality"],
                            "avatar": a.get("avatar"), "permissions": a.get("permissions", []),
                            "tools": a.get("tools", []), "status": "connected"})
            self.send_json(200, {"agents": lst})
        elif parsed.path == "/health":
            self.send_json(200, {"status": "ok", "ollama": self.check_ollama(), "service_enabled": SERVICE_ENABLED})
        elif parsed.path == "/instructions":
            self.send_json(200, {"instructions": load_instructions()})
        elif parsed.path == "/progress":
            self.send_json(200, {"progress": list_progress()})
        elif parsed.path.startswith("/progress/"):
            pid = parsed.path.split("/")[-1]
            p = get_progress(pid)
            if p:
                self.send_json(200, p)
            else:
                self.send_json(404, {"error": "Not found"})
        elif parsed.path == "/notifications":
            self.send_json(200, {"notifications": get_notifications()})
        elif parsed.path == "/chat-history":
            self.send_json(200, {"messages": load_json_file(CHAT_PATH, [])})
        elif parsed.path == "/providers":
            self.send_json(200, {"providers": provider_snapshot(), "routing": ROLE_PROVIDERS, "usage": usage_summary()})
        elif parsed.path == "/provider-tasks":
            provider = (self.headers.get("X-Agent-Conference-Client") or "").lower()
            self.send_json(200, {"tasks": list_provider_tasks(provider)})
        elif parsed.path == "/approvals":
            items = load_json_file(APPROVALS_PATH, [])
            self.send_json(200, {"approvals": items[-200:]})
        elif parsed.path == "/coach":
            self.send_json(200, {"coach": load_json_file(COACH_STATE_PATH, {"status": "starting"}), "config": coach_config()})
        else:
            self.serve_static(parsed.path)

    def do_POST(self):
        global SERVICE_ENABLED
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 0 or length > MAX_REQUEST_BYTES:
                self.send_json(413, {"error": "Request body too large"}); return
            data = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON object"}); return
        if re.fullmatch(r"/chat/[^/]+", parsed.path):
            if not SERVICE_ENABLED:
                self.send_json(503, {"error": "Agent server is paused"}); return
            aid = parsed.path.split("/")[-1]
            if aid == "ab":
                aid = "abby"
            if aid not in AGENTS:
                self.send_json(404, {"error": "Agent not found"}); return
            source = (data.get("source") or "web").lower()
            message = str(data.get("message", "")).strip()
            if not message:
                self.send_json(400, {"error": "Message is required"}); return
            is_conference = bool(data.get("is_conference"))
            client_message_id = data.get("client_message_id")
            user_message = add_chat_message("You", message, aid, source, is_conference, client_message_id)
            resp = self.handle_agent_message(AGENTS[aid], message)
            agent_message = add_chat_message(AGENTS[aid]["name"], resp, aid, source, is_conference)
            record_usage("ollama", aid, source, message, resp)
            self.send_json(200, {"response": resp, "provider": "ollama", "preferred_provider": ROLE_PROVIDERS.get(aid, "ollama"), "user_message": user_message, "agent_message": agent_message})
        elif parsed.path == "/instruction":
            if not SERVICE_ENABLED:
                self.send_json(503, {"error": "Agent server is paused"}); return
            text = (data.get("text") or "").strip()
            project_name = str(data.get("project_name") or "").strip()[:100]
            if not text:
                self.send_json(400, {"error": "No instruction text"}); return
            if data.get("async"):
                proj_id = str(datetime.now().timestamp())
                source = (data.get("source") or "web").lower()
                routing_mode = (data.get("routing_mode") or "smart").lower()
                initial = {
                    "id": proj_id, "ts": datetime.now().isoformat(), "text": text,
                    "name": project_name,
                    "analysis": "Julia is analyzing the instruction.", "workflow": "Planning workflow.",
                    "total": 0, "completed": 0, "percent": 0,
                    "status": "analyzing", "steps": [], "report": "", "source": source,
                    "routing_mode": routing_mode, "output_dir": PROJECTS_DIR
                }
                save_progress(proj_id, initial)
                worker = threading.Thread(target=run_instruction_async, args=(self, text, proj_id, source, routing_mode, project_name), daemon=True)
                worker.start()
                self.send_json(202, {"id": proj_id, "status": "analyzing"})
            else:
                self.send_json(200, run_instruction(self, text, project_name=project_name))
        elif parsed.path == "/open-project":
            folder = os.path.realpath(str(data.get("path") or ""))
            if not os.path.isdir(folder):
                self.send_json(400, {"error": "Project path must be an existing folder"}); return
            try:
                os.startfile(folder)
                self.send_json(200, {"ok": True})
            except Exception as e:
                self.send_json(500, {"error": str(e)})
        elif parsed.path == "/open-output":
            project_id = str(data.get("project_id") or "").strip()
            progress = get_progress(project_id) if project_id else None
            folder = (progress or {}).get("output_dir") or PROJECTS_DIR
            folder = os.path.realpath(folder)
            output_root = os.path.realpath(OUTPUT_DIR)
            try:
                contained = os.path.commonpath([folder, output_root]) == output_root
            except ValueError:
                contained = False
            if not contained:
                self.send_json(400, {"error": "Output folder must be inside the configured Agent Conference output directory"}); return
            try:
                os.makedirs(folder, exist_ok=True)
                os.startfile(folder)
                self.send_json(200, {"ok": True, "path": folder})
            except Exception as e:
                self.send_json(500, {"error": str(e)})
        elif parsed.path == "/notifications/read":
            mark_notifications_read(data.get("id"), data.get("agent_id"))
            self.send_json(200, {"ok": True})
        elif parsed.path == "/service/toggle":
            if not isinstance(data.get("enabled"), bool):
                self.send_json(400, {"error": "enabled must be a boolean"}); return
            SERVICE_ENABLED = data["enabled"]
            self.send_json(200, {"enabled": SERVICE_ENABLED})
        elif parsed.path == "/providers/heartbeat":
            provider = (self.headers.get("X-Agent-Conference-Client") or "").lower()
            if provider not in ("codex", "cline") or data.get("provider", provider).lower() != provider:
                self.send_json(403, {"error": "Provider identity mismatch"}); return
            provider_heartbeat(provider)
            self.send_json(200, {"provider": provider, "connected": provider in ("codex", "cline")})
        elif parsed.path == "/provider-tasks/complete":
            provider = (self.headers.get("X-Agent-Conference-Client") or "").lower()
            if provider not in ("codex", "cline") or data.get("provider", provider).lower() != provider:
                self.send_json(403, {"error": "Provider identity mismatch"}); return
            item = complete_provider_task(data.get("task_id", ""), provider, data.get("result", ""), data.get("usage"))
            if item:
                self.send_json(200, {"task": item})
            else:
                self.send_json(404, {"error": "Provider task not found"})
        elif parsed.path == "/approvals/resolve":
            decision = (data.get("decision") or "").lower()
            if decision not in ("approve", "deny"):
                self.send_json(400, {"error": "Decision must be approve or deny"}); return
            item = resolve_approval(str(data.get("id") or ""), decision)
            if item:
                self.send_json(200, {"approval": item})
            else:
                self.send_json(404, {"error": "Approval not found"})
        elif parsed.path == "/coach/config":
            config = coach_config()
            if "cline_token_budget" in data:
                config["cline_token_budget"] = max(0, int(data["cline_token_budget"]))
            save_json_file(COACH_CONFIG_PATH, config)
            self.send_json(200, {"config": config})
        elif parsed.path == "/chat-history/clear":
            save_json_file(CHAT_PATH, [])
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "Not found"})

    # ---- agent brain ----
    def handle_agent_message(self, agent, message):
        tool_name, tool_result = detect_tool(agent, message)
        aid = agent["id"] if "id" in agent else self.id_of(agent)
        if tool_result:
            add_memory(aid, "tool:" + (tool_name or "?"), tool_result[:1500])
            reply = ollama_chat(agent.get("model", "qwen2.5:3b"),
                                composed_system_prompt(aid, agent["system_prompt"] +
                                "\n\nA REAL tool just ran on the machine. Summarize only its REAL output faithfully. Never invent data."),
                                message + "\n\n" + tool_result)
            if not reply:
                reply = tool_result
            save_response_learning(aid, reply)
            return reply
        sys_prompt = composed_system_prompt(aid, agent["system_prompt"])
        reply = ollama_chat(agent.get("model", "qwen2.5:3b"), sys_prompt, message)
        if not reply:
            reply = self.fallback_response(agent, message)
        add_memory(aid, "chat", "User: " + message[:300] + " | Me: " + reply[:300])
        save_response_learning(aid, reply)
        # Detect questions and send notifications
        if is_question(reply):
            add_notification(aid, agent["name"], reply[:300], "question")
        else:
            add_notification(aid, agent["name"], reply[:300], "message")
        return reply

    def id_of(self, agent):
        for k, v in AGENTS.items():
            if v is agent:
                return k
        return "julia"

    def fallback_response(self, agent, message):
        return "[" + agent["name"] + "] Ollama not reachable, but I received: " + message[:100]

    def check_ollama(self):
        try:
            req = urllib.request.Request(OLLAMA_URL + "/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode()).get("models", []) != []
        except Exception:
            return False

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    # ---- static files ----
    def serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = path.lstrip("/")
        filepath = os.path.normpath(os.path.join(WEB_DIR, rel))
        try:
            contained = os.path.commonpath([os.path.realpath(filepath), os.path.realpath(WEB_DIR)]) == os.path.realpath(WEB_DIR)
        except ValueError:
            contained = False
        if not contained or not os.path.isfile(filepath):
            self.send_json(404, {"error": "Not found"}); return
        ctype = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        with open(filepath, "rb") as f:
            content = f.read()
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        pass

# ================= JULIA ORCHESTRATOR =================
INSTRUCTIONS_PATH = os.path.join(INSTRUCTIONS_DIR, "instructions.json")

ORCHESTRATOR_PROMPT = """You are Julia, the LEAD agent of a team.
Analyze the user's instruction, decide the workflow, and assign tasks.
Team:
- oreo: coding (creates code files, runs python)
- jessiejay: UI/UX design review
- mercedes: IT/network/backend/security (ping, ipconfig, netstat)
- abby: Ab, QA/testing/debugging (syntax checks)
Order steps sensibly (design -> code -> infra -> test).
Respond with ONLY valid JSON, no extra text:
{"analysis": "short analysis", "workflow": "short workflow description", "steps": [{"agent": "oreo", "task": "specific task"}]}
"""

def load_instructions():
    if os.path.exists(INSTRUCTIONS_PATH):
        try:
            with open(INSTRUCTIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_progress(proj_id, data):
    """Save project progress to file."""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    path = os.path.join(PROGRESS_DIR, proj_id + ".json")
    data["updated_at"] = datetime.now().isoformat()
    save_json_file(path, data)

def get_progress(proj_id):
    """Load project progress."""
    path = os.path.join(PROGRESS_DIR, proj_id + ".json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def list_progress():
    """List all project progress files."""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    result = []
    for f in os.listdir(PROGRESS_DIR):
        if f.endswith(".json"):
            data = load_json_file(os.path.join(PROGRESS_DIR, f), None)
            if isinstance(data, dict):
                result.append(data)
    return result

def save_instructions(items):
    os.makedirs(INSTRUCTIONS_DIR, exist_ok=True)
    backup_file(INSTRUCTIONS_PATH, "instructions")
    with open(INSTRUCTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(items[-100:], f, indent=2, ensure_ascii=False)

# ================= NOTIFICATIONS & QUESTIONS =================
NOTIFICATIONS_PATH = os.path.join(MEMORY_ROOT, "notifications.json")
_notifications_lock = NOTIFICATION_LOCK

def load_notifications():
    if os.path.exists(NOTIFICATIONS_PATH):
        try:
            with open(NOTIFICATIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_notifications(items):
    with _notifications_lock:
        os.makedirs(MEMORY_ROOT, exist_ok=True)
        with open(NOTIFICATIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(items[-200:], f, indent=2, ensure_ascii=False)

def add_notification(agent_id, agent_name, message, ntype="message"):
    """Add a notification. ntype: message, question, task_complete, error"""
    notif = {
        "id": str(datetime.now().timestamp() + hash(message) % 10000),
        "agent_id": agent_id,
        "agent_name": agent_name,
        "message": message[:500],
        "type": ntype,
        "read": False,
        "ts": datetime.now().isoformat()
    }
    with _notifications_lock:
        items = load_notifications()
        items.append(notif)
        save_notifications(items)
    return notif

def get_notifications(unread_only=False):
    items = load_notifications()
    if unread_only:
        items = [n for n in items if not n.get("read")]
    return items

def mark_notifications_read(notification_id=None, agent_id=None):
    with _notifications_lock:
        items = load_notifications()
        for n in items:
            if ((notification_id is None and agent_id is None) or
                    (notification_id is not None and str(n.get("id")) == str(notification_id)) or
                    (agent_id is not None and n.get("agent_id") == agent_id)):
                n["read"] = True
        save_notifications(items)

def is_question(text):
    """Detect if agent response is asking a question."""
    t = text.strip()
    if t.endswith("?"):
        return True
    question_starters = ["what ", "how ", "why ", "when ", "where ", "who ", "which ", "can you ", "could you ", "would you ", "do you ", "should ", "is there ", "are there ", "have you ", "tell me ", "clarify", "confirm"]
    tl = t.lower()
    for qs in question_starters:
        if tl.startswith(qs):
            return True
    return False

def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None

def run_instruction_async(handler, text, proj_id, source="web", routing_mode="smart", project_name=""):
    """Run an instruction in the background and always publish a terminal state."""
    try:
        run_instruction(handler, text, proj_id, source, routing_mode, project_name)
    except Exception as e:
        failed = get_progress(proj_id) or {
            "id": proj_id, "ts": datetime.now().isoformat(), "text": text,
            "analysis": "", "workflow": "", "total": 0, "completed": 0,
            "percent": 0, "steps": [], "report": ""
        }
        failed["status"] = "failed"
        failed["error"] = str(e)
        save_progress(proj_id, failed)
        threading.Thread(target=report_to_google_sheet, args=(failed.copy(),), daemon=True,
                         name="GoogleSheetFailedProjectReport").start()
        add_notification("julia", "Julia", "Instruction failed: " + str(e), "error")

def run_instruction(self, text, proj_id=None, source="web", routing_mode="smart", project_name=""):
    ts = datetime.now().isoformat()
    proj_id = proj_id or str(datetime.now().timestamp())
    progress_record = {
        "id": proj_id, "ts": ts, "text": text,
        "name": project_name,
        "analysis": "Julia is analyzing the instruction.", "workflow": "Planning workflow.",
        "total": 0, "completed": 0, "percent": 0,
        "status": "analyzing", "steps": [], "report": "", "source": source,
        "routing_mode": routing_mode, "output_dir": PROJECTS_DIR
    }
    save_progress(proj_id, progress_record)
    # 1. Julia analyzes and plans
    raw = ollama_chat("qwen2.5:3b", composed_system_prompt("julia", ORCHESTRATOR_PROMPT), text, temperature=0.3)
    plan = extract_json(raw) or {}
    analysis = plan.get("analysis", raw[:400] or "Analyzed instruction.")
    workflow = plan.get("workflow", "Linear execution by available agents.")
    steps = plan.get("steps", [])
    # sanitize steps
    clean = []
    for s in steps:
        if isinstance(s, dict) and s.get("task"):
            agent_id = "abby" if s.get("agent") == "ab" else s.get("agent")
            if agent_id in AGENTS:
                clean.append({"agent": agent_id, "task": str(s["task"])[:500]})
    if not clean:
        clean = [{"agent": "oreo", "task": text}]
    total = len(clean)
    # Save initial progress
    progress_record = {
        "id": proj_id, "ts": ts, "text": text,
        "name": project_name,
        "analysis": analysis, "workflow": workflow,
        "total": total, "completed": 0, "percent": 0,
        "status": "in_progress", "steps": [], "report": "", "source": source,
        "routing_mode": routing_mode, "output_dir": PROJECTS_DIR
    }
    save_progress(proj_id, progress_record)
    # 2. execute steps with progress tracking
    results = []
    for idx, s in enumerate(clean, 1):
        agent = AGENTS[s["agent"]]
        preferred = ROLE_PROVIDERS.get(s["agent"], "ollama")
        selected = "ollama" if routing_mode == "ollama" else (routing_mode if routing_mode in ("codex", "cline") else preferred)
        progress_record["current_agent"] = s["agent"]
        progress_record["current_task"] = s["task"]
        progress_record["preferred_provider"] = selected
        progress_record["execution_provider"] = "waiting:" + selected if selected in ("codex", "cline") else "ollama"
        save_progress(proj_id, progress_record)
        out = ""
        execution_provider = "ollama"
        connected = provider_snapshot().get(selected, {}).get("connected", False)
        if selected in ("codex", "cline") and connected:
            provider_task = create_provider_task(selected, s["agent"], s["task"], proj_id)
            out = wait_for_provider_task(provider_task["id"])
            if out:
                execution_provider = selected
        if not out:
            try:
                out = self.handle_agent_message(agent, "[TASK FROM JULIA] " + s["task"])
            except Exception as e:
                out = "Task failed: %s" % e
        results.append({"agent": s["agent"], "name": agent["name"], "task": s["task"], "result": out[:1500]})
        results[-1]["preferred_provider"] = selected
        results[-1]["execution_provider"] = execution_provider
        if execution_provider == "ollama":
            record_usage("ollama", s["agent"], source, s["task"], out, proj_id)
        add_memory(s["agent"], "instruction", "Task: " + s["task"][:300] + " -> " + out[:400])
        # Update progress
        progress_record["steps"].append({"agent": s["agent"], "task": s["task"], "result": out[:1000], "preferred_provider": selected, "execution_provider": execution_provider})
        progress_record["completed"] = idx
        progress_record["percent"] = int((idx / total) * 100)
        save_progress(proj_id, progress_record)
    # 3. Julia verifies and reports
    digest = "\n".join(["%s (%s): %s" % (r["name"], r["task"][:80], r["result"][:400]) for r in results])
    report = ollama_chat("qwen2.5:3b", composed_system_prompt("julia",
        "You are Julia, the LEAD agent. Verify the team's work against the original instruction and write a concise professional final report. Note anything incomplete and reject unsupported completion claims."),
        "Instruction: " + text + "\n\nTeam results:\n" + digest, temperature=0.4)
    report_missing = not bool(report)
    if report_missing:
        report = "FINAL STATUS: UNVERIFIED. Team steps reached terminal states, but Julia final-report generation was unavailable. Review step evidence before accepting completion."
    progress_record["report"] = report
    failure_markers = ("task failed:", "permission denied", "permission timed out",
                       "ollama not reachable", "tool denied", "runtime unavailable")
    failed_steps = [result for result in results if any(
        marker in result.get("result", "").lower() for marker in failure_markers)]
    progress_record["status"] = "failed" if failed_steps or report_missing else "completed"
    if failed_steps or report_missing:
        reasons = []
        if failed_steps:
            reasons.append("%d workflow step(s) failed or were blocked" % len(failed_steps))
        if report_missing:
            reasons.append("Julia final-report generation was unavailable")
        progress_record["error"] = "; ".join(reasons) + "; see evidence."
    progress_record["percent"] = 100
    progress_record["current_agent"] = None
    progress_record["current_task"] = None
    save_progress(proj_id, progress_record)
    threading.Thread(target=report_to_google_sheet, args=(progress_record.copy(),), daemon=True,
                     name="GoogleSheetProjectReport").start()
    record = {"id": proj_id, "ts": ts, "text": text,
              "analysis": analysis, "workflow": workflow,
              "steps": clean, "results": results, "report": report,
              "status": progress_record["status"], "error": progress_record.get("error", "")}
    items = load_instructions()
    items.append({k: record[k] for k in ("id", "ts", "text", "analysis", "workflow", "report")})
    save_instructions(items)
    add_memory("julia", "instruction", "Led instruction: " + text[:300] + " | Report: " + report[:400])
    save_response_learning("julia", report)
    return record

# ================= STARTUP =================
def run_server(port=PORT):
    preload_memories()
    os.makedirs(WORKSPACE, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', port), AgentHandler)
    server.daemon_threads = True
    threading.Thread(target=master_coach_loop, daemon=True, name="MasterCoach").start()
    threading.Thread(target=google_sheet_daily_loop, daemon=True, name="GoogleSheetDailyReport").start()
    print("Agent Server: http://localhost:%d" % port)
    print("Memory root:", MEMORY_ROOT)
    print("Agents:", ", ".join(a["name"] for a in AGENTS.values()))
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
        server.server_close()

if __name__ == "__main__":
    run_server()
