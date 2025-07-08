async function api(url, opts = {}) {
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
  await api('/dashboard/api/groups', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
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
  await api('/dashboard/api/accounts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
});

loadBots();
setInterval(loadBots, 5000);
