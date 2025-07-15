const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const spinner = document.getElementById('spinner');
let chart;

function showSpinner() { spinner.classList.remove('hidden'); }
function hideSpinner() { spinner.classList.add('hidden'); }

async function api(url, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, {'X-CSRFToken': csrfToken});
  showSpinner();
  const res = await fetch(url, opts).catch(() => null);
  hideSpinner();
  if (!res) return null;
  return res.json();
}

function openModal(id) { document.getElementById(id).showModal(); }
function closeModal(id) { document.getElementById(id).close(); }
function closeCmd() { document.getElementById('cmdDialog').close(); }

async function loadGroups() {
  const q = document.getElementById('groupSearch').value;
  const url = '/dashboard/api/groups?search=' + encodeURIComponent(q);
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
  const url = '/dashboard/api/accounts?search=' + encodeURIComponent(q);
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
  const url = '/dashboard/api/bots?search=' + encodeURIComponent(q);
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
document.getElementById('groupSearch').addEventListener('input', loadGroups);
document.getElementById('accountSearch').addEventListener('input', loadAccounts);
document.getElementById('botSearch').addEventListener('input', loadBots);

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
  if (res && res.error) alert(res.error); else { loadGroups(); closeModal('groupModal'); }
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
  if (res && res.error) alert(res.error); else { loadAccounts(); closeModal('accountModal'); }
});

document.getElementById('cmdForm').addEventListener('submit', async e => {
  e.preventDefault();
  const id = document.getElementById('cmd-id').value;
  const cmd = document.getElementById('cmd-type').value;
  const args = document.getElementById('cmd-args').value;
  await api(`/dashboard/api/bots/${id}/command`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cmd: cmd, args: {message: args}})
  });
  closeCmd();
  fetchLogs(id);
});

if (Notification && Notification.permission !== 'granted') { Notification.requestPermission(); }

const socket = io();
['bot_started','bot_finished','bot_error','status'].forEach(evt => {
  socket.on(evt, () => { loadBots(); refreshStats(); });
});

loadGroups();
loadAccounts();
loadBots();
refreshStats();

window.addEventListener('load', () => {
  if (!navigator.onLine) document.getElementById('offlineBanner').classList.remove('hidden');
});
