const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const spinner = document.getElementById('spinner');
const redisBanner = document.getElementById('redisBanner');
let chart;

function loadQueue() {
  return JSON.parse(localStorage.getItem('syncQueue') || '[]');
}

function saveQueue(q) {
  localStorage.setItem('syncQueue', JSON.stringify(q));
}

function showSpinner() { spinner.classList.remove('hidden'); }
function hideSpinner() { spinner.classList.add('hidden'); }

async function checkRedis() {
  const res = await fetch('/dashboard/api/status').catch(() => null);
  if (!res || !res.ok) return;
  const data = await res.json();
  if (data.redis_online) redisBanner.classList.add('hidden');
  else redisBanner.classList.remove('hidden');
}

function getAccess() {
  return localStorage.getItem('accessToken');
}

async function refreshToken() {
  const refresh = localStorage.getItem('refreshToken');
  if (!refresh) return null;
  const res = await fetch('/auth/refresh', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + refresh }
  }).catch(() => null);
  if (!res || !res.ok) return null;
  const data = await res.json();
  localStorage.setItem('accessToken', data.access_token);
  return data.access_token;
}

async function api(url, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, {
    'X-CSRFToken': csrfToken,
    'Authorization': 'Bearer ' + getAccess()
  });
  showSpinner();
  let res = await fetch(url, opts).catch(() => null);
  if (res && res.status === 401) {
    const newTok = await refreshToken();
    if (newTok) {
      opts.headers['Authorization'] = 'Bearer ' + newTok;
      res = await fetch(url, opts).catch(() => null);
    }
  }
  hideSpinner();
  if (!res) return null;
  return res.json();
}


function openModal(id) { document.getElementById(id).showModal(); }
function closeModal(id) { document.getElementById(id).close(); }
function closeCmd() { document.getElementById('cmdDialog').close(); }

async function syncPull() {
  const res = await api('/sync/pull');
  if (!res) return;
  res.events.forEach(evt => {
    if (evt.entity === 'group') loadGroups();
    if (evt.entity === 'account') loadAccounts();
    if (evt.entity === 'bot') loadBots();
  });
}

async function syncPush() {
  if (!navigator.onLine) return;
  const queue = loadQueue();
  if (queue.length === 0) return;
  const res = await api('/sync/push', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(queue)
  });
  if (res) saveQueue([]);
}

async function loadGroups() {
  const q = document.getElementById('groupSearch').value;
  const url = q ? '/dashboard/api/groups?search=' + encodeURIComponent(q) : '/dashboard/api/groups';
  const data = await api(url);
  if (!data) return;
  const groups = data.items || data;
  const list = document.getElementById('groupList');
  list.innerHTML = '';
  groups.forEach(g => {
    const li = document.createElement('li');
    li.textContent = `${g.name} (${g.target})`;
    list.appendChild(li);
  });
}

async function loadAccounts() {
  const q = document.getElementById('accountSearch').value;
  const url = q ? '/dashboard/api/accounts?search=' + encodeURIComponent(q) : '/dashboard/api/accounts';
  const data = await api(url);
  if (!data) return;
  const accs = data.items || data;
  const table = document.getElementById('accountTable');
  table.innerHTML = '<tr><th>ID</th><th>User</th><th>Group</th></tr>';
  accs.forEach(a => {
    const row = document.createElement('tr');
    row.innerHTML = `<td class="border px-2">${a.id}</td><td class="border px-2">${a.username}</td><td class="border px-2">${a.group_id}</td>`;
    table.appendChild(row);
  });
}

async function loadBots() {
  const q = document.getElementById('botSearch').value;
  const url = q ? '/dashboard/api/bots?search=' + encodeURIComponent(q) : '/dashboard/api/bots';
  const data = await api(url);
  if (!data) return;
  const bots = data.items || data;
  const container = document.getElementById('bots');
  container.innerHTML = '';
  bots.forEach(b => {
    const div = document.createElement('div');
    let color = 'bg-red-200';
    if (b.status === 'online') color = 'bg-green-200';
    else if (b.status === 'queued') color = 'bg-yellow-200';
    div.className = `${color} p-2`;
    div.innerHTML = `ID ${b.id} (${b.username}) - ${b.status} <button onclick="openCmd(${b.id})" class="bg-blue-500 text-white px-1">Cmd</button> <button onclick="fetchLogs(${b.id})" class="text-sm underline">Logs</button>`;
    container.appendChild(div);
  });
}

async function refreshStats() {
  const stats = await api('/dashboard/api/stats');
  if (!stats) return;
  if (!chart) {
    const ctx = document.getElementById('chart');
    chart = new Chart(ctx, {
      type: 'bar',
      data: { labels: ['Runs', 'Errors'], datasets: [{ data: [stats.runs, stats.errors], backgroundColor: ['#4ade80','#f87171'] }] },
      options: { plugins: { legend: { display: false } } }
    });
  } else {
    chart.data.datasets[0].data = [stats.runs, stats.errors];
    chart.update();
  }
}

async function startScheduler() {
  await api('/dashboard/api/scheduler/start', {method: 'POST'});
}

async function fetchLogs(id) {
  const logs = await api(`/dashboard/api/bots/${id}/logs`);
  if (!logs) return;
  document.getElementById('logBox').textContent = logs.join('\n');
}

document.getElementById('addGroupBtn').addEventListener('click', () => openModal('groupModal'));
document.getElementById('addAccountBtn').addEventListener('click', () => openModal('accountModal'));
let groupTimer, accountTimer, botTimer;
document.getElementById('groupSearch').addEventListener('input', () => {
  clearTimeout(groupTimer);
  groupTimer = setTimeout(loadGroups, 300);
});
document.getElementById('accountSearch').addEventListener('input', () => {
  clearTimeout(accountTimer);
  accountTimer = setTimeout(loadAccounts, 300);
});
document.getElementById('botSearch').addEventListener('input', () => {
  clearTimeout(botTimer);
  botTimer = setTimeout(loadBots, 300);
});

document.getElementById('groupForm').addEventListener('submit', async e => {
  e.preventDefault();
  const data = {
    name: document.getElementById('g-name').value,
    target: document.getElementById('g-target').value,
    interval: parseInt(document.getElementById('g-interval').value, 10)
  };
  const res = await api('/dashboard/api/groups', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if (!res) {
    const q = loadQueue();
    q.push({entity: 'group', action: 'create', payload: data, timestamp: new Date().toISOString()});
    saveQueue(q);
    alert('Queued offline');
  } else if (res.error) {
    alert(res.error);
  } else {
    loadGroups();
    closeModal('groupModal');
    syncPush();
  }
});

document.getElementById('accountForm').addEventListener('submit', async e => {
  e.preventDefault();
  const data = {
    username: document.getElementById('a-user').value,
    password: document.getElementById('a-pass').value,
    proxy: document.getElementById('a-proxy').value,
    messages_file: document.getElementById('a-msg').value,
    group_id: parseInt(document.getElementById('a-group').value, 10)
  };
  const res = await api('/dashboard/api/accounts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  if (!res) {
    const q = loadQueue();
    q.push({entity: 'account', action: 'create', payload: data, timestamp: new Date().toISOString()});
    saveQueue(q);
    alert('Queued offline');
  } else if (res.error) {
    alert(res.error);
  } else {
    loadAccounts();
    closeModal('accountModal');
    syncPush();
  }
});

document.getElementById('cmdForm').addEventListener('submit', async e => {
  e.preventDefault();
  const id = document.getElementById('cmd-id').value;
  const cmd = document.getElementById('cmd-type').value;
  const args = document.getElementById('cmd-args').value;
  const payload = {cmd: cmd, args: {message: args}};
  const res = await api(`/dashboard/api/bots/${id}/command`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (!res) {
    const q = loadQueue();
    q.push({entity: 'bot', action: cmd, payload: {id: id, args: args}, timestamp: new Date().toISOString()});
    saveQueue(q);
    alert('Queued offline');
  }
  closeCmd();
  fetchLogs(id);
  syncPush();
});

if (Notification && Notification.permission !== 'granted') { Notification.requestPermission(); }

const socket = io();
['bot_started','bot_stopped','bot_error','status'].forEach(evt => {
  socket.on(evt, () => { loadBots(); refreshStats(); });
});
socket.on('redis_status', () => checkRedis());
socket.on('sync_event', syncPull);
socket.on('connect', () => { syncPull(); syncPush(); checkRedis(); });

loadGroups();
loadAccounts();
loadBots();
refreshStats();
syncPull();
syncPush();
checkRedis();
setInterval(checkRedis, 10000);

window.addEventListener('load', () => {
  if (!navigator.onLine) document.getElementById('offlineBanner').classList.remove('hidden');
});
