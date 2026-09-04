#!/usr/bin/env python3
"""Julia's Google Sheets reporter. Never logs credential values."""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime


SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")
CREDENTIALS_PATH = os.path.abspath(os.path.expanduser(os.environ.get(
    "GOOGLE_OAUTH_CREDENTIALS_PATH", "~/AI-Agent-Conference/credentials.json")))
OUTPUT_ROOT = os.path.abspath(os.path.expanduser(os.environ.get(
    "AGENT_CONFERENCE_OUTPUT_DIR", "~/AI-Agent-Conference/output")))
CONFIG_PATH = os.path.join(OUTPUT_ROOT, "google_sheet_report_config.json")
STATE_PATH = os.path.join(OUTPUT_ROOT, "google_sheet_report_state.json")
LOG_PATH = os.path.join(OUTPUT_ROOT, "google_sheet_report_log.json")
API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
HEADERS = [
    "Timestamp", "Report Type", "Project ID", "Project Name", "Status",
    "Progress", "Source", "Routing / Providers", "Output Folder", "Summary", "Risks / Errors"
]
REPORT_LOCK = threading.RLock()


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _save(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    os.replace(temporary, path)


def config():
    value = {
        "enabled": bool(SPREADSHEET_ID),
        "spreadsheet_id": SPREADSHEET_ID,
        "credentials_path": CREDENTIALS_PATH,
        "daily_hour": 18,
        "daily_minute": 0,
        "project_sheets": {}
    }
    value.update(_load(CONFIG_PATH, {}))
    return value


def _access_token():
    settings = config()
    credentials = _load(settings["credentials_path"], {})
    required = ("refresh_token", "client_id", "client_secret")
    if not all(credentials.get(key) for key in required):
        raise RuntimeError("Google OAuth credentials are incomplete")
    body = urllib.parse.urlencode({
        "client_id": credentials["client_id"],
        "client_secret": credentials["client_secret"],
        "refresh_token": credentials["refresh_token"],
        "grant_type": "refresh_token"
    }).encode("utf-8")
    request = urllib.request.Request(
        credentials.get("token_uri", "https://oauth2.googleapis.com/token"),
        data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token = json.loads(response.read().decode("utf-8")).get("access_token")
    except urllib.error.HTTPError as error:
        raise RuntimeError("Google OAuth refresh failed with HTTP %s" % error.code) from error
    if not token:
        raise RuntimeError("Google OAuth refresh returned no access token")
    return token


def _api(path="", method="GET", payload=None, query=None):
    settings = config()
    spreadsheet_id = settings["spreadsheet_id"]
    if not spreadsheet_id:
        raise RuntimeError("Set GOOGLE_SHEETS_SPREADSHEET_ID or configure spreadsheet_id")
    url = API_ROOT + "/" + urllib.parse.quote(spreadsheet_id, safe="") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + _access_token(),
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError("Google Sheets API HTTP %s%s" % (error.code, ": " + detail if detail else "")) from error


def metadata():
    return _api(query={"fields": "properties.title,sheets.properties(sheetId,title,index)"})


def safe_title(name):
    title = re.sub(r"[\[\]:*?/\\]", "-", str(name or "Untitled Project"))
    title = re.sub(r"\s+", " ", title).strip(" '\t\r\n") or "Untitled Project"
    return title[:100]


def _unique_title(preferred, existing):
    preferred = safe_title(preferred)
    if preferred not in existing:
        return preferred
    index = 2
    while True:
        suffix = " (%d)" % index
        candidate = preferred[:100 - len(suffix)] + suffix
        if candidate not in existing:
            return candidate
        index += 1


def ensure_project_sheet(project_key, project_name):
    settings = config()
    mappings = settings.setdefault("project_sheets", {})
    if project_key in mappings:
        return mappings[project_key]
    book = metadata()
    sheets = book.get("sheets", [])
    existing = {item["properties"]["title"] for item in sheets}
    title = _unique_title(project_name, existing)
    sheet1 = next((item for item in sheets if item["properties"]["title"].casefold() == "sheet1"), None)
    requests = []
    if not mappings and sheet1:
        title = safe_title(project_name)
        if title in existing and title != "Sheet1":
            title = _unique_title(project_name, existing)
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": sheet1["properties"]["sheetId"], "title": title},
            "fields": "title"
        }})
    else:
        requests.append({"addSheet": {"properties": {"title": title}}})
    _api(":batchUpdate", "POST", {"requests": requests})
    mappings[project_key] = title
    _save(CONFIG_PATH, settings)
    _ensure_headers(title)
    return title


def ensure_named_sheet(title):
    title = safe_title(title)
    existing = {item["properties"]["title"] for item in metadata().get("sheets", [])}
    if title not in existing:
        _api(":batchUpdate", "POST", {"requests": [{"addSheet": {"properties": {"title": title}}}]})
    _ensure_headers(title)
    return title


def _range(title, cells="A:K"):
    return "'" + title.replace("'", "''") + "'!" + cells


def _ensure_headers(title):
    result = _api("/values/" + urllib.parse.quote(_range(title, "A1:K1"), safe=""))
    if not result.get("values"):
        _api("/values/" + urllib.parse.quote(_range(title, "A1:K1"), safe=""), "PUT",
             {"values": [HEADERS]}, {"valueInputOption": "RAW"})


def append_row(title, row):
    return _api("/values/" + urllib.parse.quote(_range(title), safe="") + ":append", "POST",
                {"values": [row]}, {"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"})


def project_name(record):
    explicit = str(record.get("name") or "").strip()
    if explicit:
        return explicit
    first_line = str(record.get("text") or "Untitled Project").strip().splitlines()[0]
    return first_line[:80] or "Untitled Project"


def project_row(record, report_type="project_completion"):
    steps = record.get("steps", [])
    providers = ", ".join(sorted({str(step.get("execution_provider", "unknown")) for step in steps})) or str(record.get("routing_mode", "unknown"))
    risks = record.get("error") or ("; ".join(str(step.get("result", ""))[:160] for step in steps if str(step.get("result", "")).lower().startswith("task failed")))
    return [
        datetime.now().isoformat(), report_type, record.get("id", ""), project_name(record),
        record.get("status", "unknown"), record.get("percent", 0), record.get("source", "unknown"),
        providers, record.get("output_dir", ""), str(record.get("report") or record.get("analysis") or "")[:5000],
        str(risks or "")[:2000]
    ]


def write_project_report(record, report_type="project_completion"):
    key = str(record.get("id") or safe_title(project_name(record)))
    title = ensure_project_sheet(key, project_name(record))
    append_row(title, project_row(record, report_type))
    _log({"status": "written", "type": report_type, "project_id": key, "sheet": title})
    return {"ok": True, "sheet": title, "project_id": key}


def write_project_report_once(record):
    """Write one completion report per project ID, even across restarts."""
    with REPORT_LOCK:
        key = str(record.get("id") or safe_title(project_name(record)))
        state = _load(STATE_PATH, {})
        reported = state.setdefault("reported_project_completions", {})
        if key in reported:
            return {"ok": True, "skipped": True, "sheet": reported[key], "project_id": key}
        result = write_project_report(record, "project_completion")
        reported[key] = result["sheet"]
        state["last_project_report"] = datetime.now().isoformat()
        _save(STATE_PATH, state)
        return result


def write_daily_summary(summary):
    title = ensure_named_sheet("Daily Summary")
    row = [
        datetime.now().isoformat(), "daily_summary", "", "All Projects", summary.get("status", "summary"),
        summary.get("completed", 0), "system", summary.get("providers", ""), OUTPUT_ROOT,
        summary.get("summary", ""), summary.get("risks", "")
    ]
    append_row(title, row)
    _log({"status": "written", "type": "daily_summary", "sheet": title})
    return {"ok": True, "sheet": title}


def conference_daily_summary():
    progress_dir = os.path.join(OUTPUT_ROOT, "progress")
    projects = []
    if os.path.isdir(progress_dir):
        for filename in os.listdir(progress_dir):
            if filename.endswith(".json"):
                projects.append(_load(os.path.join(progress_dir, filename), {}))
    completed = sum(item.get("status") == "completed" for item in projects)
    active = sum(item.get("status") not in ("completed", "failed") for item in projects)
    failed = sum(item.get("status") == "failed" for item in projects)
    provider_state = _load(os.path.join(OUTPUT_ROOT, "providers.json"), {})
    connected = [name for name, value in provider_state.items() if value.get("connected")]
    coach = _load(os.path.join(OUTPUT_ROOT, "coach_state.json"), {})
    stalled = coach.get("stalled_projects", [])
    return {
        "status": "attention" if failed or stalled else "healthy",
        "completed": completed,
        "providers": ", ".join(connected) or "No external MCP heartbeat; Ollama status checked by server",
        "summary": "%d total projects; %d completed; %d active; %d failed." % (len(projects), completed, active, failed),
        "risks": "Stalled projects: " + ", ".join(stalled) if stalled else ""
    }


def write_daily_summary_once(day=None):
    with REPORT_LOCK:
        day = day or datetime.now().strftime("%Y-%m-%d")
        state = _load(STATE_PATH, {})
        if state.get("last_daily_report") == day:
            return {"ok": True, "skipped": True, "sheet": "Daily Summary", "date": day}
        result = write_daily_summary(conference_daily_summary())
        state = _load(STATE_PATH, {})
        state["last_daily_report"] = day
        state["last_daily_report_at"] = datetime.now().isoformat()
        _save(STATE_PATH, state)
        result["date"] = day
        return result


def backfill_completed_projects():
    progress_dir = os.path.join(OUTPUT_ROOT, "progress")
    results = []
    if not os.path.isdir(progress_dir):
        return results
    records = []
    for filename in os.listdir(progress_dir):
        if filename.endswith(".json"):
            record = _load(os.path.join(progress_dir, filename), {})
            if record.get("status") == "completed":
                records.append(record)
    records.sort(key=lambda item: item.get("ts", ""))
    for record in records:
        results.append(write_project_report_once(record))
    return results


def _log(entry):
    entry = dict(entry)
    entry["ts"] = datetime.now().isoformat()
    values = _load(LOG_PATH, [])
    values.append(entry)
    _save(LOG_PATH, values[-1000:])


def current_status_record():
    progress_dir = os.path.join(OUTPUT_ROOT, "progress")
    projects = []
    if os.path.isdir(progress_dir):
        for filename in os.listdir(progress_dir):
            if filename.endswith(".json"):
                projects.append(_load(os.path.join(progress_dir, filename), {}))
    completed = sum(item.get("status") == "completed" for item in projects)
    active = sum(item.get("status") not in ("completed", "failed") for item in projects)
    failed = sum(item.get("status") == "failed" for item in projects)
    providers = _load(os.path.join(OUTPUT_ROOT, "providers.json"), {})
    coach = _load(os.path.join(OUTPUT_ROOT, "coach_state.json"), {})
    summary = "Current Agent Conference status: %d projects; %d completed; %d active; %d failed. Visible agents: Oreo, JessieJay, Mercedes, Ab, Julia. Hidden Master Coach: %s." % (
        len(projects), completed, active, failed, coach.get("status", "unknown")
    )
    connected = ", ".join(name for name, value in providers.items() if value.get("connected")) or "Ollama/local server"
    return {
        "id": "ai-agent-conference-current-status", "name": "AI Agent Conference",
        "text": "AI Agent Conference", "status": "monitoring", "percent": 100,
        "source": "system", "routing_mode": "hybrid", "output_dir": OUTPUT_ROOT,
        "steps": [{"execution_provider": connected}], "report": summary,
        "error": "Stalled projects: " + ", ".join(coach.get("stalled_projects", [])) if coach.get("stalled_projects") else ""
    }


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "metadata"
    if command == "metadata":
        book = metadata()
        print(json.dumps({"title": book.get("properties", {}).get("title"),
                          "sheets": [item["properties"]["title"] for item in book.get("sheets", [])]}))
    elif command == "current-status":
        print(json.dumps(write_project_report(current_status_record(), "current_status")))
    elif command == "backfill":
        print(json.dumps(backfill_completed_projects()))
    elif command == "daily":
        print(json.dumps(write_daily_summary_once()))
    else:
        raise SystemExit("Unknown command")