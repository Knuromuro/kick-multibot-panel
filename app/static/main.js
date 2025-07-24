const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const spinner = document.getElementById('spinner');
const redisBanner = document.getElementById('redisBanner');
const toastBox = document.getElementById('toast');
let chart;
let logTimer = null;

function loadQueue() {
  return JSON.parse(localStorage.getItem('syncQueue') || '[]');
}

function saveQueue(q) {
  localStorage.setItem('syncQueue', JSON.stringify(q));
}

function showSpinner() { spinner.classList.remove('hidden'); }
function hideSpinner() { spinner.classList.add('hidden'); }
function showToast(msg, ok = true) {
  toastBox.textContent = msg;
  toastBox.classList.remove('hidden');
  toastBox.classList.toggle('bg-red-500', !ok);
  toastBox.classList.toggle('bg-green-500', ok);
  setTimeout(() => toastBox.classList.add('hidden'), 3000);
}

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
function openCmd(id) {
  document.getElementById('cmd-id').value = id;
  document.getElementById('cmdDialog').showModal();
}

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
  const q = document.getElementById('groupSearch').value.trim();
  const url = q.length > 1 ? '/dashboard/api/groups?search=' + encodeURIComponent(q) : '/dashboard/api/groups';
  const data = await api(url);
  if (!data) return;
  const groups = data.items || data;
  const list = document.getElementById('groupList');
  list.innerHTML = '';
  if (!groups.length) {
    list.innerHTML = '<li class="text-gray-500 text-sm">No groups created yet</li>';
    return;
  }
  groups.forEach(g => {
    const li = document.createElement('li');
    li.className = 'mb-1';
    li.innerHTML = `<div class="font-semibold">${g.name} (${g.target})</div>`;
    if (g.bots && g.bots.length) {
      const ul = document.createElement('ul');
      ul.className = 'pl-4 list-disc';
      g.bots.forEach(b => {
        const bi = document.createElement('li');
        bi.textContent = `${b.username} (#${b.id})`;
        ul.appendChild(bi);
      });
      li.appendChild(ul);
    }
    list.appendChild(li);
  });
}

async function loadAccounts() {
  const q = document.getElementById('accountSearch').value.trim();
  const url = q.length > 1 ? '/dashboard/api/accounts?search=' + encodeURIComponent(q) : '/dashboard/api/accounts';
  const data = await api(url);
  if (!data) return;
  const accs = data.items || data;
  const table = document.getElementById('accountTable');
  table.innerHTML = '<tr><th>ID</th><th>User</th><th>Group</th></tr>';
  if (!accs.length) {
    const row = document.createElement('tr');
    row.innerHTML = '<td class="border px-2 text-center" colspan="3">No accounts</td>';
    table.appendChild(row);
    return;
  }
  accs.forEach(a => {
    const row = document.createElement('tr');
    row.innerHTML = `<td class="border px-2">${a.id}</td><td class="border px-2">${a.username}</td><td class="border px-2">${a.group_id}</td>`;
    table.appendChild(row);
  });
}

async function loadBots() {
  const q = document.getElementById('botSearch').value.trim();
  const url = q.length > 1 ? '/dashboard/api/bots?search=' + encodeURIComponent(q) : '/dashboard/api/bots';
  const data = await api(url);
  if (!data) return;
  const bots = data.items || data;
  const table = document.getElementById('botTable');
  table.innerHTML = '<tr><th>ID</th><th>User</th><th>Status</th><th>Actions</th></tr>';
  if (!bots.length) {
    const row = document.createElement('tr');
    row.innerHTML = '<td class="border px-2 text-center" colspan="4">No bots created yet</td>';
    table.appendChild(row);
    return;
  }
  bots.forEach(b => {
    const row = document.createElement('tr');
    const badge = b.status === 'online'
      ? '<span class="bg-green-500 text-white px-2 py-0.5 rounded">running</span>'
      : '<span class="bg-red-500 text-white px-2 py-0.5 rounded">stopped</span>';
    row.innerHTML =
      `<td class="border px-2">${b.id}</td>` +
      `<td class="border px-2">${b.username}</td>` +
      `<td class="border px-2 text-center">${badge}</td>` +
      `<td class="border px-2 space-x-1">` +
        `<button onclick="startBot(${b.id})" class="bg-green-600 text-white px-2 py-1 text-xs rounded">Start</button>` +
        `<button onclick="stopBot(${b.id})" class="bg-red-600 text-white px-2 py-1 text-xs rounded">Stop</button>` +
        `<button onclick="openCmd(${b.id})" class="bg-blue-500 text-white px-2 py-1 text-xs rounded">Cmd</button>` +
        `<button onclick="fetchLogs(${b.id})" class="underline text-xs">Logs</button>` +
      `</td>`;
    table.appendChild(row);
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

async function startBot(id) {
  const res = await api(`/dashboard/api/bots/${id}/start`, {method: 'POST'});
  if (res && res.pid) showToast('Bot started');
  loadBots();
}

async function stopBot(id) {
  const res = await api(`/dashboard/api/bots/${id}/stop`, {method: 'POST'});
  if (res && res.stopped) showToast('Bot stopped');
  loadBots();
}

async function fetchLogs(id) {
  if (logTimer) clearInterval(logTimer);
  async function load() {
    const lines = await api(`/dashboard/api/bots/${id}/logs`);
    if (lines) {
      const box = document.getElementById('logBox');
      box.textContent = lines.join('\n');
      box.scrollTop = box.scrollHeight;
    }
  }
  await load();
  logTimer = setInterval(load, 3000);
}

document.getElementById('addGroupBtn').addEventListener('click', () => openModal('groupModal'));
document.getElementById('addAccountBtn').addEventListener('click', () => openModal('accountModal'));
let groupTimer, accountTimer, botTimer;
document.getElementById('groupSearch').addEventListener('input', () => {
  clearTimeout(groupTimer);
  groupTimer = setTimeout(() => {
    const q = document.getElementById('groupSearch').value.trim();
    if (q.length === 0 || q.length > 1) loadGroups();
  }, 300);
});
document.getElementById('accountSearch').addEventListener('input', () => {
  clearTimeout(accountTimer);
  accountTimer = setTimeout(() => {
    const q = document.getElementById('accountSearch').value.trim();
    if (q.length === 0 || q.length > 1) loadAccounts();
  }, 300);
});
document.getElementById('botSearch').addEventListener('input', () => {
  clearTimeout(botTimer);
  botTimer = setTimeout(() => {
    const q = document.getElementById('botSearch').value.trim();
    if (q.length === 0 || q.length > 1) loadBots();
  }, 300);
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
    showToast('Queued offline', true);
  } else if (res.error) {
    showToast(res.error, false);
  } else {
    loadGroups();
    closeModal('groupModal');
    syncPush();
    showToast('Group created');
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
    showToast('Queued offline', true);
  } else if (res.error) {
    showToast(res.error, false);
  } else {
    loadAccounts();
    loadBots();
    closeModal('accountModal');
    syncPush();
    showToast('Account created');
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
    showToast('Queued offline', true);
  } else if (res && res.status === 'ok') {
    showToast('Command queued');
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

window.addEventListener('load', () => {
  loadGroups();
  loadAccounts();
  loadBots();
  refreshStats();
  syncPull();
  syncPush();
  checkRedis();
  setInterval(checkRedis, 10000);
  if (!navigator.onLine) document.getElementById('offlineBanner').classList.remove('hidden');
});
