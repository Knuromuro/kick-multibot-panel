const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

async function api(url, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, {'X-CSRFToken': csrfToken});
  const res = await fetch(url, opts).catch(() => null);
  if (!res) return null;
  return res.json();
}

async function loadBots() {
  const bots = await api('/dashboard/api/bots');
  if (!bots) return;
  const container = document.getElementById('bots');
  container.innerHTML = '';
  bots.forEach(b => {
    const div = document.createElement('div');
    div.className = 'border p-2';
    div.innerHTML = `ID ${b.id} (${b.username}) - ${b.status} ` +
      `<button onclick="openCmd(${b.id})" class="bg-blue-500 text-white px-1">Cmd</button>`;
    container.appendChild(div);
  });
}

async function loadGroups() {
  const groups = await api('/dashboard/api/groups');
  if (!groups) return;
  const table = document.getElementById('groupTable');
  table.innerHTML = '<tr><th>ID</th><th>Name</th><th>Target</th><th>Interval</th></tr>';
  groups.forEach(g => {
    const row = document.createElement('tr');
    row.innerHTML = `<td class="border px-2">${g.id}</td><td class="border px-2">${g.name}</td><td class="border px-2">${g.target}</td><td class="border px-2">${g.interval}</td>`;
    table.appendChild(row);
  });
}

async function loadAccounts() {
  const accs = await api('/dashboard/api/accounts');
  if (!accs) return;
  const table = document.getElementById('accountTable');
  table.innerHTML = '<tr><th>ID</th><th>User</th><th>Group</th></tr>';
  accs.forEach(a => {
    const row = document.createElement('tr');
    row.innerHTML = `<td class="border px-2">${a.id}</td><td class="border px-2">${a.username}</td><td class="border px-2">${a.group_id}</td>`;
    table.appendChild(row);
  });
}

async function startScheduler() {
  await api('/dashboard/api/scheduler/start', {method: 'POST'});
}

function openCmd(id) {
  document.getElementById('cmd-id').value = id;
  document.getElementById('cmdDialog').showModal();
}

function closeCmd() {
  document.getElementById('cmdDialog').close();
}

async function fetchLogs(id) {
  const logs = await api(`/dashboard/api/bots/${id}/logs`);
  if (!logs) return;
  document.getElementById('logBox').textContent = logs.join('\n');
}

// Forms

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

// TODO: simple forms for groups and accounts (not fully implemented)

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
  if (res && res.error) {
    alert(res.error);
  } else {
    loadGroups();
    e.target.reset();
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
  if (res && res.error) {
    alert(res.error);
  } else {
    loadAccounts();
    e.target.reset();
  }
});

if (Notification && Notification.permission !== 'granted') {
  Notification.requestPermission();
}

const socket = io();
socket.on('status', data => {
  loadBots();
  loadGroups();
  loadAccounts();
  if (data.message && Notification.permission === 'granted') {
    new Notification(data.message);
  }
});

loadBots();
loadGroups();
loadAccounts();
