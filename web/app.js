const SERVER = '';
const GROUP_TRIGGERS = ["everyone", "all", "guys", "team", "all of you", "hey all", "hi all", "hello all", "hi guys", "hello guys", "hey guys", "folks", "everybody"];

let agents = [];
let messages = [];
let tasks = [];
let projects = [];
let instructions = [];
let currentTab = 'conference';
let selectedAgentId = null;
let serviceEnabled = true;
let pendingInstructionProjectId = null;
let routingMode = localStorage.getItem('ac_routing_mode') || 'smart';
let providerData = { providers: {}, usage: {} };
let approvals = [];
let chatClearedAt = localStorage.getItem('ac_chat_cleared_at') || '';
const projectHandles = new Map();

const $ = (id) => document.getElementById(id);

/* ---------- Server helpers ---------- */
async function api(path, opts = {}, method = 'GET') {
  const res = await fetch(SERVER + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...opts
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ('Request failed: ' + res.status));
  return data;
}

/* ---------- State persistence (localStorage) ---------- */
function loadState() {
  try {
    agents = JSON.parse(localStorage.getItem('ac_agents') || '[]');
    messages = JSON.parse(localStorage.getItem('ac_messages') || '[]');
    tasks = JSON.parse(localStorage.getItem('ac_tasks') || '[]');
    projects = JSON.parse(localStorage.getItem('ac_projects') || '[]');
    instructions = JSON.parse(localStorage.getItem('ac_instructions') || '[]');
    workstationItems = JSON.parse(localStorage.getItem('ac_workstation') || '[]');
    outputItems = JSON.parse(localStorage.getItem('ac_output') || '[]');
  } catch (e) {}
}
function saveState() {
  localStorage.setItem('ac_agents', JSON.stringify(agents));
  localStorage.setItem('ac_messages', JSON.stringify(messages));
  localStorage.setItem('ac_tasks', JSON.stringify(tasks));
  localStorage.setItem('ac_projects', JSON.stringify(projects));
  localStorage.setItem('ac_instructions', JSON.stringify(instructions));
  localStorage.setItem('ac_workstation', JSON.stringify(workstationItems));
  localStorage.setItem('ac_output', JSON.stringify(outputItems));
}

/* ---------- Init ---------- */
async function init() {
  loadState();
  await refreshServerStatus();
  await loadAgentsFromServer();
  renderAgents();
  renderMessages();
  renderProjects();
  renderTasks();
  renderWorkstation();
  renderOutput();

  $('addAgentBtn').onclick = addAgent;
  $('addProjectBtn').onclick = addProject;
  $('importBtn').onclick = importProject;
  $('clearBtn').onclick = clearChat;
  $('addTaskBtn').onclick = addTaskPrompt;
  $('notifBell').onclick = toggleNotifPanel;
  $('notifClear').onclick = markAllNotificationsRead;
  $('clearWorkstation').onclick = clearWorkstation;
  $('clearOutput').onclick = clearOutput;
  initRightTabs();
  initResizeHandles();
  initProjectImport();
  $('serverToggle').onchange = toggleServerService;
  $('routingMode').value = routingMode;
  $('routingMode').onchange = function() {
    routingMode = this.value;
    localStorage.setItem('ac_routing_mode', routingMode);
    renderProviders();
  };
  $('usageSummary').onclick = function() {
    const events = (providerData.usage && providerData.usage.events) || [];
    const recent = events.slice(-12).reverse().map(function(e) {
      return (e.ts || '').slice(0, 16).replace('T', ' ') + ' · ' + e.provider + ' · ' + e.agent + ' · ~' +
        ((e.input_tokens_estimated || 0) + (e.output_tokens_estimated || 0)) + ' tokens';
    });
    alert('Provider usage (estimated)\n\n' + (recent.join('\n') || 'No usage recorded yet.'));
  };
  $('closeWorkstationModal').onclick = closeWorkstationWindow;
  $('workstationModal').onclick = function(e) { if (e.target === this) closeWorkstationWindow(); };
  $('sendBtn').onclick = sendMessage;
  $('messageInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.tab));
  loadNotifications();
  loadApprovals();
  syncChatHistory();
  syncServerProjects();
  loadProviders();
  setInterval(loadNotifications, 5000);
  setInterval(loadApprovals, 3000);
  setInterval(syncChatHistory, 3000);
  setInterval(syncServerProjects, 3000);
  setInterval(loadProviders, 5000);
  setInterval(refreshServerStatus, 10000);
}

/* ---------- Server status ---------- */
async function refreshServerStatus() {
  try {
    const data = await api('/health');
    serviceEnabled = data.service_enabled !== false;
    setServer(true, serviceEnabled);
  }
  catch (e) { setServer(false); }
}
function setServer(reachable, enabled) {
  const active = reachable && enabled;
  $('serverDot').style.background = active ? '#3ecf8e' : (reachable ? '#ffc107' : '#e94560');
  $('serverText').textContent = active ? 'Server Online' : (reachable ? 'Server Paused' : 'Server Offline');
  $('serverToggle').checked = active;
  $('serverToggle').disabled = !reachable;
}

async function toggleServerService() {
  const toggle = $('serverToggle');
  toggle.disabled = true;
  try {
    const data = await api('/service/toggle', {
      method: 'POST', body: JSON.stringify({ enabled: toggle.checked })
    }, 'POST');
    serviceEnabled = data.enabled;
    setServer(true, serviceEnabled);
  } catch (e) {
    setServer(false);
  }
}

async function loadProviders() {
  try {
    providerData = await api('/providers');
    renderProviders();
    renderAgents();
  } catch (e) {}
}

function renderProviders() {
  const labels = { codex: 'Codex', cline: 'VS Cline', ollama: 'Ollama' };
  $('providerStates').innerHTML = ['codex', 'cline', 'ollama'].map(function(id) {
    const connected = providerData.providers && providerData.providers[id] && providerData.providers[id].connected;
    return '<span class="provider-chip ' + (connected ? 'online' : 'offline') + '"><i></i>' + labels[id] + '</span>';
  }).join('');
  const totals = (providerData.usage && providerData.usage.totals) || {};
  const summary = Object.keys(totals).map(function(id) {
    const item = totals[id];
    const reported = (item.input_tokens_reported || 0) + (item.output_tokens_reported || 0);
    const estimated = (item.input_tokens_estimated || 0) + (item.output_tokens_estimated || 0);
    return id + ': ' + item.requests + ' req / ' + (reported ? reported.toLocaleString() : '~' + estimated.toLocaleString()) + ' tokens';
  }).join(' · ');
  $('usageSummary').textContent = summary ? 'Usage · ' + summary : 'Usage · no requests';
  $('usageSummary').title = 'Token figures are estimated unless a provider reports exact usage.';
}

/* ---------- Agents ---------- */
async function loadAgentsFromServer() {
  try {
    const data = await api('/agents');
    const serverAgents = data.agents || [];
    const localIds = new Set(agents.map(a => a.id));
    for (const sa of serverAgents) {
      if (!localIds.has(sa.id)) agents.push(sa);
    }
    for (const a of agents) a.status = 'connected';
    saveState();
  } catch (e) {}
}
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderAgents() {
  const list = $('agentsList');
  if (!agents.length) {
    list.innerHTML = '<div class="empty-msg">No agents yet<br>Click + to add</div>';
    return;
  }
  list.innerHTML = agents.map(a => {
    const sel = selectedAgentId === a.id ? ' selected' : '';
    const sc = a.status === 'connected' ? '#3ecf8e' : '#ffc107';
    const av = a.avatar || { emoji: '\uD83D\uDC15', bg: '#3f4147', breed: a.type || 'Agent' };
    const unread = notifications.filter(function(n) { return !n.read && n.agent_id === a.id; }).length;
    const workStatus = a.workStatus === 'working' ? 'working' : 'idle';
    const provider = (providerData.routing && providerData.routing[a.id]) || 'ollama';
    return '<div class="agent-card' + sel + '" data-id="' + a.id + '" onclick="selectAgent(\'' + a.id + '\')">' +
      '<div class="agent-row">' +
      '<span class="avatar" style="background:' + av.bg + '" title="' + esc(av.breed || '') + '">' + av.emoji + '</span>' +
      '<span style="flex:1">' +
      '<div style="display:flex;align-items:center;gap:6px"><span class="status-dot ' + workStatus + '"></span><span class="name">' + esc(a.name) + '</span>' +
      (unread ? '<span class="agent-notif-badge">' + unread + '</span>' : '') + '</div>' +
      '<div class="type">' + esc(a.type) + '</div>' +
      '<div class="agent-card-meta"><span class="agent-work-status ' + workStatus + '">' + workStatus + '</span>' +
      '<span class="agent-provider">' + esc(provider === 'cline' ? 'VS Cline' : (provider === 'codex' ? 'Codex' : 'Ollama')) + '</span></div>' +
      '</span>' +
      '<button class="agent-del" onclick="event.stopPropagation();deleteAgent(\'' + a.id + '\')" title="Delete">×</button>' +
      '</div>' +
      '</div>';
  }).join('');
}

function selectAgent(id) {
  selectedAgentId = id;
  currentTab = 'agent';
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  markAgentNotificationsRead(id);
  renderAgents();
  updateChatHeader();
  renderMessages();
}

async function syncChatHistory() {
  try {
    const data = await api('/chat-history');
    const known = new Set(messages.map(function(m) { return String(m.serverId || m.id); }));
    (data.messages || []).forEach(function(item) {
      if (known.has(String(item.id))) return;
      messages.push({
        id: 'server-' + item.id, serverId: item.id, sender: item.sender,
        content: item.content, timestamp: item.ts, isConference: !!item.is_conference,
        targetAgentId: item.is_conference ? null : item.agent_id, source: item.source || 'web',
        severity: item.severity || 'normal'
      });
      known.add(String(item.id));
    });
    saveState();
    renderMessages();
  } catch (e) {}
}

function deleteAgent(id) {
  if (!confirm('Delete this agent?')) return;
  agents = agents.filter(a => a.id !== id);
  if (selectedAgentId === id) selectedAgentId = null;
  saveState();
  renderAgents();
  renderMessages();
}

function addAgent() {
  const name = prompt('Agent name:');
  if (!name) return;
  const type = prompt('Agent type:');
  if (!type) return;
  const endpoint = prompt('Endpoint URL:', 'http://localhost:8766');
  agents.push({ id: name.toLowerCase().replace(/\s+/g, '_'), name: name, type: type, endpoint: endpoint, status: 'connected' });
  saveState();
  renderAgents();
}

function switchTab(tab) {
  currentTab = tab;
  if (tab === 'conference' || tab === 'tasks') selectedAgentId = null;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  updateChatHeader();
  renderMessages();
}

function updateChatHeader() {
  if (currentTab === 'conference') $('chatTitle').textContent = 'Conference Chat - All Agents';
  else if (currentTab === 'tasks') $('chatTitle').textContent = 'Task List';
  else if (currentTab === 'agent' && selectedAgentId) {
    const a = agents.find(x => x.id === selectedAgentId);
    $('chatTitle').textContent = 'Chat with ' + (a ? a.name : 'Agent');
  } else $('chatTitle').textContent = 'Select an agent to chat';
}

async function clearChat() {
  if (!confirm('Clear all messages?')) return;
  messages = [];
  chatClearedAt = new Date().toISOString();
  localStorage.setItem('ac_chat_cleared_at', chatClearedAt);
  saveState();
  renderMessages();
  try {
    await api('/chat-history/clear', { method: 'POST', body: JSON.stringify({}) }, 'POST');
  } catch (e) {
    alert('Local chat cleared, but server history could not be cleared: ' + e.message);
  }
}

function sendMessage() {
  const input = $('messageInput');
  const content = input.value.trim();
  if (!content) return;
  if (currentTab === 'agent' && !selectedAgentId) { alert('Select an agent first'); return; }
  if (currentTab === 'tasks') switchTab('conference');

  const userMessage = {
    id: Date.now() + '',
    sender: 'You',
    content: content,
    timestamp: new Date().toISOString(),
    isConference: currentTab === 'conference',
    targetAgentId: currentTab === 'agent' ? selectedAgentId : null
  };
  messages.push(userMessage);
  input.value = '';
  saveState();
  renderMessages();
  simulateResponses(content, userMessage);
}

function getAgentsToReply(message) {
  const ml = message.toLowerCase();
  if (GROUP_TRIGGERS.some(function(t) { return ml.includes(t); })) return agents;
  return agents.filter(function(a) { return ml.includes(a.name.toLowerCase()); });
}

async function simulateResponses(content, userMessage) {
  let targets = [];
  if (currentTab === 'conference') {
    targets = getAgentsToReply(content);
  } else if (selectedAgentId) {
    const a = agents.find(function(x) { return x.id === selectedAgentId; });
    if (a) targets = [a];
  }
  for (const agent of targets) {
    setAgentWorkStatus(agent.id, 'working');
    const workItem = addWorkstationItem(agent.name, 'Responding to: ' + content.slice(0, 120), 'running');
    const response = await callAgent(agent, content, userMessage);
    const resp = response.response;
    if (response.user_message) userMessage.serverId = response.user_message.id;
    messages.push({
      id: Date.now() + Math.random(),
      serverId: response.agent_message ? response.agent_message.id : null,
      sender: agent.name,
      content: resp,
      timestamp: new Date().toISOString(),
      isConference: currentTab === 'conference',
      targetAgentId: currentTab === 'agent' ? agent.id : null
    });
    saveState();
    renderMessages();
    // Populate Work Station and Output panels
    parseAgentResponse(agent.name, resp, workItem);
    setAgentWorkStatus(agent.id, 'idle');
  }
}

function setAgentWorkStatus(agentId, status) {
  const agent = agents.find(function(a) { return a.id === agentId; });
  if (agent) agent.workStatus = status;
  renderAgents();
}

async function callAgent(agent, message, userMessage) {
  try {
    const data = await api('/chat/' + agent.id, { method: 'POST', body: JSON.stringify({
      message: message, source: 'web', is_conference: currentTab === 'conference',
      client_message_id: 'web-' + userMessage.id
    }) }, 'POST');
    return data;
  } catch (e) {
    return { response: '[' + agent.name + '] ' + e.message };
  }
}

function renderMessages() {
  const box = $('messages');
  if (currentTab === 'tasks') { renderTasksPanel(); return; }
  let filtered = messages;
  if (currentTab === 'agent' && selectedAgentId) {
    filtered = messages.filter(function(m) { return !m.isConference && m.targetAgentId === selectedAgentId; });
  } else if (currentTab === 'conference') {
    filtered = messages.filter(function(m) { return m.isConference; });
  }
  if (!filtered.length) {
    box.innerHTML = '<div class="empty-chat">No messages yet<br><br>Click an agent for a direct chat<br>or use Conference for the whole team</div>';
    return;
  }
  box.innerHTML = filtered.map(function(m) {
    const isUser = m.sender === 'You';
    const isSystem = m.sender === 'System';
    const cls = isUser ? 'user' : (isSystem ? 'system' : 'agent');
    const source = m.source && m.source !== 'web' ? '<span class="message-source">' + esc(m.source) + '</span>' : '';
    const sender = isUser ? source : '<span class="sender">' + esc(m.sender) + source + '</span>';
    return '<div class="msg ' + cls + '">' + sender + esc(m.content) + '</div>';
  }).join('');
  box.scrollTop = box.scrollHeight;
}

/* ---------- Tasks ---------- */
function renderTasksPanel() {
  const box = $('messages');
  if (!tasks.length) {
    box.innerHTML = '<div class="empty-chat">No tasks yet</div>';
    return;
  }
  box.innerHTML = tasks.map(function(t) {
    const done = t.status === 'done';
    const checkColor = done ? '#3ecf8e' : '#7a8194';
    return '<div class="msg agent" style="display:flex;align-items:center;gap:10px;">' +
      '<button class="p-btn" onclick="toggleTask(\'' + t.id + '\')" style="font-size:18px;color:' + checkColor + '">' + (done ? '\u2714' : '\u25CB') + '</button>' +
      '<span style="flex:1">' + esc(t.text) + '</span>' +
      '<span style="font-size:11px;color:#7a8194">' + esc(t.agent) + '</span>' +
      '<button class="p-btn" onclick="deleteTask(\'' + t.id + '\')">×</button>' +
      '</div>';
  }).join('');
}

function addTaskPrompt() {
  const text = prompt('Task description:');
  if (!text) return;
  const a = agents.find(function(x) { return x.id === selectedAgentId; });
  tasks.push({ id: Date.now() + '', text: text, status: 'pending', agent: a ? a.name : 'Unassigned', created: new Date().toISOString() });
  saveState();
  renderTasksPanel();
}

function toggleTask(id) {
  const t = tasks.find(function(x) { return x.id === id; });
  if (t) { t.status = t.status === 'done' ? 'pending' : 'done'; saveState(); renderTasksPanel(); }
}

function deleteTask(id) {
  tasks = tasks.filter(function(x) { return x.id !== id; });
  saveState();
  renderTasksPanel();
}

function renderTasks() { renderTasksPanel(); }

/* ---------- Projects ---------- */
function renderProjects() {
  const list = $('projectsList');
  if (!projects.length) {
    list.innerHTML = '<div class="empty-msg">No projects<br>Open or drop a folder to begin</div>';
    return;
  }
  list.innerHTML = projects.map(function(p) {
    const percent = Math.max(0, Math.min(100, Number(p.percent) || 0));
    const status = p.status || 'idle';
    const completed = status === 'completed' || percent >= 100;
    const instructionName = p.instructionName || 'Add instruction file';
    return '<div class="project-card ' + esc(status) + '" data-project-id="' + p.id + '">' +
      '<div class="pname">' + esc(p.name) + '</div>' +
      '<div class="ppath">' + esc(p.sourceLabel || p.path || 'Folder selected') + '</div>' +
      '<div class="pmeta">' +
      '<span class="pstatus">● ' + esc(status) + '</span>' +
      '<button class="p-btn open" onclick="openProject(\'' + p.id + '\')">Open</button>' +
      '<button class="p-btn" onclick="deleteProject(\'' + p.id + '\')">Remove</button>' +
      '</div>' +
      '<div class="project-progress-head"><span>Progress</span><strong>' + percent + '%</strong></div>' +
      '<div class="project-progress"><span style="width:' + percent + '%"></span></div>' +
      '<button class="instruction-file" onclick="chooseInstructionFile(\'' + p.id + '\')">📄 ' + esc(instructionName) + '</button>' +
      (p.instructionContent ? '<div class="instruction-preview">' + esc(p.instructionContent.slice(0, 120)) + '</div>' : '') +
      (completed
        ? '<button class="btn-start project-start open-output" onclick="openProjectOutput(\'' + p.id + '\')">📂 Open Output</button>'
        : '<button class="btn-start project-start" onclick="startProject(\'' + p.id + '\')" ' +
          (!p.instructionContent || status === 'working' ? 'disabled' : '') + '>' + (status === 'working' ? 'Working...' : 'Start Project') + '</button>') +
      '</div>';
  }).join('');
}

async function syncServerProjects() {
  try {
    const data = await api('/progress');
    (data.progress || []).forEach(function(rec) {
      let project = projects.find(function(p) { return p.progressId === rec.id; });
      if (!project) {
        project = {
          id: 'server-' + rec.id,
          progressId: rec.id,
          name: (rec.text || 'Julia project').split(/\r?\n/)[0].slice(0, 60),
          sourceLabel: 'Julia / ' + (rec.source === 'cline' ? 'VS Cline' : (rec.source === 'codex' ? 'Codex' : 'Web UI')) + ' project',
          instructionName: (rec.source === 'cline' ? 'Cline' : (rec.source === 'codex' ? 'Codex' : 'Web')) + ' instruction',
          instructionContent: rec.text || '',
          created: rec.ts || new Date().toISOString(),
          serverProject: true,
          syncedSteps: 0,
          percent: 0,
          status: 'working'
        };
        projects.push(project);
      }
      project.percent = Number(rec.percent) || 0;
      project.outputDir = rec.output_dir || 'Configured project output folder';
      project.status = rec.status === 'completed' ? 'completed' : (rec.status === 'failed' ? 'failed' : 'working');
      const steps = rec.steps || [];
      for (let index = project.syncedSteps || 0; index < steps.length; index++) {
        const step = steps[index];
        const syncKey = rec.id + ':' + index;
        if (workstationItems.some(function(item) { return item.syncKey === syncKey; })) continue;
        const name = agentName(step.agent);
        const result = step.result || 'Task completed.';
        addWorkstationItem(name, step.task || 'Agent task', result.indexOf('Task failed:') === 0 ? 'error' : 'done', syncKey);
        addOutput(name, result, result.indexOf('Task failed:') === 0 ? 'error' : 'result', syncKey);
      }
      project.syncedSteps = steps.length;
      if (rec.report && !project.reportSynced) {
        project.report = rec.report;
        project.reportSynced = true;
        const reportKey = rec.id + ':report';
        if (!outputItems.some(function(item) { return item.syncKey === reportKey; })) {
          addOutput('Julia', rec.report, 'report', reportKey);
        }
      }
    });
    saveState();
    renderProjects();
  } catch (e) {}
}

function addImportedProject(name, sourceLabel, handle, instructionFile) {
  const project = {
    id: Date.now() + Math.random() + '', name: name || 'Imported project',
    sourceLabel: sourceLabel || 'Browser import', created: new Date().toISOString(),
    status: 'idle', percent: 0
  };
  projects.push(project);
  if (handle) projectHandles.set(project.id, handle);
  if (instructionFile) attachInstruction(project, instructionFile);
  saveState();
  renderProjects();
  return project;
}

async function addProject() { return importProject(); }

async function importProject() {
  if (window.showDirectoryPicker) {
    try {
      const handle = await window.showDirectoryPicker({ mode: 'read' });
      addImportedProject(handle.name, 'Local folder', handle);
      return;
    } catch (e) {
      if (e.name === 'AbortError') return;
    }
  }
  $('folderInput').click();
}

function importFolderFiles(files) {
  if (!files || !files.length) return;
  const first = files[0];
  const relative = first.webkitRelativePath || first.name;
  const name = relative.split('/')[0] || first.name;
  addImportedProject(name, files.length + ' imported item' + (files.length === 1 ? '' : 's'));
}

function initProjectImport() {
  $('folderInput').onchange = function() { importFolderFiles(Array.from(this.files || [])); this.value = ''; };
  $('instructionInput').onchange = function() {
    const project = projects.find(function(p) { return p.id === pendingInstructionProjectId; });
    if (project && this.files && this.files[0]) attachInstruction(project, this.files[0]);
    this.value = '';
  };
  const zone = $('projectDropZone');
  ['dragenter', 'dragover'].forEach(function(type) {
    zone.addEventListener(type, function(e) { e.preventDefault(); zone.classList.add('dragging'); });
  });
  ['dragleave', 'drop'].forEach(function(type) {
    zone.addEventListener(type, function(e) { e.preventDefault(); zone.classList.remove('dragging'); });
  });
  zone.addEventListener('drop', async function(e) {
    const items = Array.from(e.dataTransfer.items || []);
    if (items[0] && items[0].getAsFileSystemHandle) {
      const handle = await items[0].getAsFileSystemHandle();
      if (handle) {
        const project = addImportedProject(handle.name, handle.kind === 'directory' ? 'Dropped folder' : 'Dropped file', handle);
        if (handle.kind === 'file') attachInstruction(project, await handle.getFile());
        return;
      }
    }
    importFolderFiles(Array.from(e.dataTransfer.files || []));
  });
}

function chooseInstructionFile(projectId) {
  pendingInstructionProjectId = projectId;
  $('instructionInput').click();
}

async function attachInstruction(project, file) {
  try {
    project.instructionName = file.name;
    project.instructionContent = await file.text();
    project.status = 'ready';
    saveState();
    renderProjects();
  } catch (e) { alert('Could not read the instruction file.'); }
}

async function openProject(id) {
  const p = projects.find(function(x) { return x.id === id; });
  if (!p) return;
  const handle = projectHandles.get(id);
  if (handle) {
    try {
      if (handle.requestPermission) await handle.requestPermission({ mode: 'read' });
      alert(p.name + ' is connected to the selected ' + handle.kind + '.');
      return;
    } catch (e) {}
  }
  if (!p.path) { alert('This browser session no longer has the original folder handle. Use Open Folder to reconnect it.'); return; }
  try {
    await api('/open-project', { method: 'POST', body: JSON.stringify({ path: p.path }) }, 'POST');
  } catch (e) { alert('Could not open folder'); }
}

async function openProjectOutput(id) {
  const project = projects.find(function(p) { return p.id === id; });
  if (!project) return;
  try {
    await api('/open-output', {
      method: 'POST', body: JSON.stringify({ project_id: project.progressId || '' })
    }, 'POST');
  } catch (e) {
    alert('Could not open the output folder: ' + e.message);
  }
}

function deleteProject(id) {
  if (!confirm('Remove project from list?')) return;
  projects = projects.filter(function(x) { return x.id !== id; });
  saveState();
  renderProjects();
}

/* ---------- Make functions global for inline handlers ---------- */
window.selectAgent = selectAgent;
window.deleteAgent = deleteAgent;
window.toggleTask = toggleTask;
window.deleteTask = deleteTask;
window.openProject = openProject;
window.openProjectOutput = openProjectOutput;
window.deleteProject = deleteProject;
window.chooseInstructionFile = chooseInstructionFile;
window.startProject = startProject;
window.addTaskPrompt = addTaskPrompt;

document.addEventListener('DOMContentLoaded', init);

function agentName(id) {
  const a = agents.find(function(x) { return x.id === id; });
  return a ? a.name : id;
}


/* ---------- Notifications ---------- */
let notifications = [];

async function loadNotifications() {
  try {
    const data = await api('/notifications');
    notifications = data.notifications || [];
    notifications.forEach(function(n) {
      if (chatClearedAt && n.ts && n.ts <= chatClearedAt) return;
      const exists = messages.some(function(m) {
        return m.notificationId === n.id || (m.sender === n.agent_name &&
          (m.content === n.message || m.content.indexOf(n.message) === 0 || n.message.indexOf(m.content) === 0));
      });
      if (!exists && n.agent_id) {
        messages.push({
          id: 'notification-' + n.id, notificationId: n.id, sender: n.agent_name || agentName(n.agent_id),
          content: n.message, timestamp: n.ts, isConference: false, targetAgentId: n.agent_id,
          source: n.source || 'agent'
        });
      }
    });
    saveState();
    renderNotifications();
    updateNotifBadge();
    renderAgents();
  } catch (e) {}
}

async function loadApprovals() {
  try {
    const data = await api('/approvals');
    approvals = data.approvals || [];
    renderApprovals();
  } catch (e) {}
}

function renderApprovals() {
  const list = $('checkpointList');
  if (!list) return;
  const pending = approvals.filter(function(item) { return item.status === 'pending'; });
  if (!pending.length) {
    list.innerHTML = '<div class="checkpoint-empty">No pending permission requests</div>';
    return;
  }
  list.innerHTML = pending.slice().reverse().map(function(item) {
    return '<div class="checkpoint-item">' +
      '<div class="checkpoint-agent">' + esc(item.agent_name) + ' · ' + esc(item.tool) + '</div>' +
      '<div class="checkpoint-path">' + esc(item.path || item.message) + '</div>' +
      '<div class="checkpoint-actions"><button class="approve" onclick="resolveCheckpoint(\'' + item.id + '\',true)">Approve</button>' +
      '<button class="deny" onclick="resolveCheckpoint(\'' + item.id + '\',false)">Deny</button></div></div>';
  }).join('');
}

async function resolveCheckpoint(id, approve) {
  const item = approvals.find(function(entry) { return entry.id === id; });
  if (item) item.status = approve ? 'approved' : 'denied';
  renderApprovals();
  try {
    await api('/approvals/resolve', {
      method: 'POST', body: JSON.stringify({ id: id, decision: approve ? 'approve' : 'deny' })
    }, 'POST');
  } catch (e) { alert('Could not update the checkpoint: ' + e.message); }
  loadApprovals();
}

function renderNotifications() {
  const list = document.getElementById('notifList');
  if (!list) return;
  if (!notifications.length) {
    list.innerHTML = '<div class="notif-empty">No notifications</div>';
    return;
  }
  list.innerHTML = notifications.slice().reverse().map(function(n) {
    const unread = n.read ? '' : ' unread';
    const isQ = n.type === 'question' ? ' question' : '';
    return '<div class="notif-item' + unread + isQ + '" onclick="openNotif(\'' + n.id + '\')">' +
      '<div class="nagent">' + esc(n.agent_name || n.agent_id) + '</div>' +
      '<div class="ntext">' + esc(n.message) + '</div>' +
      '<div class="ntype">' + esc(n.type || 'message') + '</div>' +
      '</div>';
  }).join('');
}

function updateNotifBadge() {
  const badge = document.getElementById('notifBadge');
  if (!badge) return;
  const unread = notifications.filter(function(n) { return !n.read; }).length;
  badge.textContent = unread;
  badge.classList.toggle('show', unread > 0);
}

async function openNotif(id) {
  const n = notifications.find(function(x) { return x.id === id; });
  if (n) {
    n.read = true;
    renderNotifications();
    updateNotifBadge();
    renderAgents();
    try {
      await api('/notifications/read', { method: 'POST', body: JSON.stringify({ id: id }) }, 'POST');
    } catch (e) {}
    alert(n.agent_name + ' says:\n\n' + n.message);
  }
}

async function markAllNotificationsRead() {
  notifications.forEach(function(n) { n.read = true; });
  renderNotifications();
  updateNotifBadge();
  renderAgents();
  try {
    await api('/notifications/read', { method: 'POST', body: JSON.stringify({}) }, 'POST');
  } catch (e) {}
}

async function markAgentNotificationsRead(agentId) {
  const unread = notifications.some(function(n) { return n.agent_id === agentId && !n.read; });
  if (!unread) return;
  notifications.forEach(function(n) { if (n.agent_id === agentId) n.read = true; });
  updateNotifBadge();
  renderAgents();
  try {
    await api('/notifications/read', { method: 'POST', body: JSON.stringify({ agent_id: agentId }) }, 'POST');
  } catch (e) {}
}

async function toggleNotifPanel() {
  const panel = document.getElementById('notifPanel');
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) await markAllNotificationsRead();
}

/* ---------- Progress Tracking ---------- */
let activeProgress = null;
let progressTimer = null;

function updateProgressUI(proj) {
  if (!proj) return;
  agents.forEach(function(a) {
    a.workStatus = (a.id === 'julia' || a.id === proj.current_agent) && proj.status !== 'completed' && proj.status !== 'failed' ? 'working' : 'idle';
  });
  const project = projects.find(function(p) { return p.progressId === proj.id; });
  if (project) {
    project.percent = proj.percent || 0;
    project.status = proj.status === 'completed' ? 'completed' : (proj.status === 'failed' ? 'failed' : 'working');
    saveState();
    renderProjects();
  }
  renderAgents();
}

function startProgressPolling(projId, onComplete) {
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = setInterval(async function() {
    try {
      const data = await api('/progress/' + projId);
      activeProgress = data;
      updateProgressUI(data);
      if (data.status === 'completed') {
        clearInterval(progressTimer);
        progressTimer = null;
        loadNotifications();
        if (onComplete) onComplete(data);
      } else if (data.status === 'failed') {
        clearInterval(progressTimer);
        progressTimer = null;
        if (onComplete) onComplete(data);
      }
    } catch (e) {}
  }, 2000);
}

async function startProject(projectId) {
  const project = projects.find(function(p) { return p.id === projectId; });
  if (!project || !project.instructionContent) { alert('Add an instruction file first.'); return; }
  const instr = { id: project.id, text: project.instructionContent, status: 'running', ts: new Date().toISOString(), projectId: project.id };

  project.status = 'working';
  project.percent = 0;
  agents.forEach(function(a) { a.workStatus = a.id === 'julia' ? 'working' : 'idle'; });
  saveState();
  renderProjects();
  renderAgents();

  // Show in chat
  messages.push({ id: Date.now() + 'u', sender: 'You', content: instr.text, timestamp: new Date().toISOString(), isConference: true });
  messages.push({ id: Date.now() + 'w', sender: 'Julia', content: 'Analyzing instruction and coordinating the team...', timestamp: new Date().toISOString(), isConference: true });
  saveState();
  renderMessages();
  switchTab('conference');

  try {
    const resp = await fetch(SERVER + '/instruction', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: instr.text, project_name: project.name, async: true, source: 'web', routing_mode: routingMode })
    });
    const rec = await resp.json();
    if (rec.error) {
      messages = messages.filter(function(m) { return !(m.sender === 'Julia' && m.content.indexOf('Analyzing instruction') === 0); });
      messages.push({ id: Date.now() + 'e', sender: 'System', content: 'Instruction failed: ' + rec.error, timestamp: new Date().toISOString(), isConference: true });
      instr.status = 'failed';
    } else {
      activeProgress = { id: rec.id, text: instr.text, percent: 0, status: 'analyzing' };
      project.progressId = rec.id;
      saveState();
      updateProgressUI(activeProgress);
      startProgressPolling(rec.id, function(result) { completeProject(instr, result); });
    }
    saveState();
    renderProjects();
    renderMessages();
    loadNotifications();
  } catch (e) {
    messages.push({ id: Date.now() + 'e', sender: 'System', content: 'Instruction failed: ' + e, timestamp: new Date().toISOString(), isConference: true });
    instr.status = 'failed';
    project.status = 'failed';
    agents.forEach(function(a) { a.workStatus = 'idle'; });
    saveState();
    renderProjects();
    renderAgents();
    renderMessages();
  }
}

function completeProject(instr, rec) {
  const project = projects.find(function(p) { return p.id === instr.projectId; });
  messages = messages.filter(function(m) { return !(m.sender === 'Julia' && m.content.indexOf('Analyzing instruction') === 0); });
  if (rec.status === 'failed') {
    instr.status = 'failed';
    if (project) { project.status = 'failed'; project.percent = rec.percent || 0; }
    messages.push({ id: Date.now() + 'e', sender: 'System', content: 'Instruction failed: ' + (rec.error || 'Unknown error'), timestamp: new Date().toISOString(), isConference: true });
  } else {
    instr.status = 'completed';
    if (project) { project.status = 'completed'; project.percent = 100; project.report = rec.report; }
    instr.analysis = rec.analysis;
    instr.workflow = rec.workflow;
    instr.report = rec.report;
    messages.push({ id: Date.now() + 'a', sender: 'Julia', content: 'ANALYSIS: ' + rec.analysis + '\n\nWORKFLOW: ' + rec.workflow, timestamp: rec.ts, isConference: true });
    (rec.steps || []).forEach(function(s, idx) {
      const name = agentName(s.agent);
      const result = s.result || '(no result)';
      const syncKey = rec.id + ':' + idx;
      messages.push({ id: Date.now() + 's' + idx, sender: name, content: 'TASK: ' + s.task + '\n\n' + result, timestamp: new Date().toISOString(), isConference: true });
      if (!workstationItems.some(function(item) { return item.syncKey === syncKey; })) {
        addWorkstationItem(name, s.task, result.indexOf('Task failed:') === 0 ? 'error' : 'done', syncKey);
      }
      if (!outputItems.some(function(item) { return item.syncKey === syncKey; })) {
        addOutput(name, result, 'result', syncKey);
      }
    });
    messages.push({ id: Date.now() + 'r', sender: 'Julia', content: 'FINAL REPORT:\n' + rec.report, timestamp: new Date().toISOString(), isConference: true });
    const reportKey = rec.id + ':report';
    if (!outputItems.some(function(item) { return item.syncKey === reportKey; })) {
      addOutput('Julia', rec.report, 'report', reportKey);
    }
  }
  saveState();
  agents.forEach(function(a) { a.workStatus = 'idle'; });
  renderProjects();
  renderAgents();
  renderMessages();
  loadNotifications();
}

/* ---------- Parse agent response for Work Station & Output ---------- */
function parseAgentResponse(agentName, resp, workItem) {
  if (!resp) return;
  const toolMarkers = ['[Real file created:', '[Real run of', '[Real output from', '[Output of', '[Real', '[tool'];
  const isTool = toolMarkers.some(function(m) { return resp.indexOf(m) >= 0; });
  
  if (isTool) {
    if (workItem) workItem.action = 'Tool executed';
    addOutput(agentName, resp, 'tool');
  }
  if (workItem) {
    workItem.detail = resp;
    workItem.status = resp.indexOf('Server not connected') >= 0 ? 'error' : 'done';
  } else {
    addWorkstationItem(agentName, resp.slice(0, 120), 'done');
  }
  saveState();
  renderWorkstation();
}

/* ---------- Global exports for inline handlers ---------- */
window.startProject = startProject;
window.openNotif = openNotif;
window.resolveCheckpoint = resolveCheckpoint;
window.startProgressPolling = startProgressPolling;

/* ---------- Right panel tabs ---------- */
function initRightTabs() {
  document.querySelectorAll('.right-tab').forEach(function(tab) {
    tab.onclick = function() {
      var name = tab.dataset.righttab;
      document.querySelectorAll('.right-tab').forEach(function(t) { t.classList.remove('active'); });
      tab.classList.add('active');
      document.querySelectorAll('.right-content').forEach(function(c) { c.classList.add('hidden'); });
      var target = document.getElementById('tab-' + name);
      if (target) target.classList.remove('hidden');
    };
  });
}

/* ---------- Resize handles ---------- */
function initResizeHandles() {
  var leftHandle = document.getElementById('leftResize');
  var rightHandle = document.getElementById('rightResize');
  var agentsPanel = document.getElementById('agentsPanel');
  var rightPanel = document.getElementById('rightPanel');

  function makeResizer(handle, panel, isLeft) {
    var startX, startW;
    handle.addEventListener('mousedown', function(e) {
      startX = e.clientX;
      startW = panel.offsetWidth;
      handle.classList.add('active');
      document.addEventListener('mousemove', onDrag);
      document.addEventListener('mouseup', stopDrag);
      e.preventDefault();
    });
    function onDrag(e) {
      var dx = isLeft ? e.clientX - startX : startX - e.clientX;
      var newW = Math.max(180, Math.min(500, startW + dx));
      panel.style.width = newW + 'px';
    }
    function stopDrag() {
      handle.classList.remove('active');
      document.removeEventListener('mousemove', onDrag);
      document.removeEventListener('mouseup', stopDrag);
    }
  }
  if (leftHandle && agentsPanel) makeResizer(leftHandle, agentsPanel, true);
  if (rightHandle && rightPanel) makeResizer(rightHandle, rightPanel, false);
}

/* ---------- Work Station ---------- */
let workstationItems = [];

function addWorkstationItem(agent, action, status, syncKey) {
  var item = { id: Date.now() + Math.random(), agent: agent, action: action, detail: action, status: status || 'running', syncKey: syncKey || null, ts: new Date().toISOString() };
  workstationItems.push(item);
  if (workstationItems.length > 100) workstationItems = workstationItems.slice(-100);
  saveState();
  renderWorkstation();
  return item;
}

function renderWorkstation() {
  var list = document.getElementById('workstationList');
  if (!list) return;
  if (!workstationItems.length) {
    list.innerHTML = '<div class="empty-msg">No active work</div>';
    return;
  }
  list.innerHTML = workstationItems.slice().reverse().map(function(item) {
    var cls = item.status === 'done' ? 'done' : (item.status === 'error' ? 'error' : '');
    return '<div class="ws-item ' + cls + '" onclick="openWorkstationWindow(\'' + item.id + '\')" title="Open activity window">' +
      '<div class="ws-agent">' + esc(item.agent) + '</div>' +
      '<div class="ws-action">' + esc(item.action) + '</div>' +
      '<div class="ws-time">' + (item.ts || '').slice(11, 19) + ' · ' + esc(item.status) + ' · Click for details</div>' +
      '</div>';
  }).join('');
}

function openWorkstationWindow(id) {
  const item = workstationItems.find(function(x) { return String(x.id) === String(id); });
  if (!item) return;
  $('workstationModalTitle').textContent = item.action || 'Agent activity';
  $('workstationModalAgent').textContent = item.agent + ' · ' + new Date(item.ts).toLocaleString();
  $('workstationModalStatus').textContent = item.status === 'running' ? '● Working now' : (item.status === 'error' ? '● Error' : '● Completed');
  $('workstationModalStatus').className = 'window-status ' + item.status;
  const related = outputItems.filter(function(out) { return out.agent === item.agent; }).slice(-5);
  $('workstationModalContent').textContent = item.detail || item.action || 'No additional details.';
  if (related.length) {
    $('workstationModalContent').textContent += '\n\nRecent output\n─────────────\n' + related.map(function(out) { return out.content; }).join('\n\n');
  }
  $('workstationModal').classList.remove('hidden');
}

function closeWorkstationWindow() {
  $('workstationModal').classList.add('hidden');
}

function clearWorkstation() {
  workstationItems = [];
  saveState();
  renderWorkstation();
}

/* ---------- Output panel ---------- */
let outputItems = [];

function addOutput(agent, content, type, syncKey) {
  var item = { id: Date.now() + Math.random(), agent: agent, content: content, type: type || 'tool', syncKey: syncKey || null, ts: new Date().toISOString() };
  outputItems.push(item);
  if (outputItems.length > 200) outputItems = outputItems.slice(-200);
  saveState();
  renderOutput();
}

function renderOutput() {
  var list = document.getElementById('outputList');
  if (!list) return;
  if (!outputItems.length) {
    list.innerHTML = '<div class="empty-msg">No output yet</div>';
    return;
  }
  list.innerHTML = outputItems.slice().reverse().map(function(item) {
    return '<div class="output-item ' + (item.type || 'tool') + '">' +
      '<div class="out-agent">' + esc(item.agent) + ' @ ' + (item.ts || '').slice(11, 19) + '</div>' +
      '<div class="out-content">' + esc(item.content) + '</div>' +
      '</div>';
  }).join('');
}

function clearOutput() {
  outputItems = [];
  saveState();
  renderOutput();
}

/* ---------- Global exports ---------- */
window.addWorkstationItem = addWorkstationItem;
window.addOutput = addOutput;
window.clearWorkstation = clearWorkstation;
window.clearOutput = clearOutput;
window.openWorkstationWindow = openWorkstationWindow;
window.initRightTabs = initRightTabs;
window.initResizeHandles = initResizeHandles;
