let botCache = [];

async function fetchBots() {
  const res = await fetch('/bots').catch(() => null);
  if (!res) return;
  botCache = await res.json();
  const tbody = document.querySelector('#botTable tbody');
  tbody.innerHTML = '';
  botCache.forEach(bot => {
    const row = document.createElement('tr');
    row.innerHTML =
      `<td>${bot.id}</td>` +
      `<td>${bot.channel}</td>` +
      `<td>${bot.message}</td>` +
      `<td>${bot.interval}</td>` +
      `<td>${bot.group || ''}</td>` +
      `<td>${bot.active ? '✅' : '❌'}</td>` +
      `<td>` +
      `<button onclick="sendNow(${bot.id})">Send</button> ` +
      `<button onclick="toggleBot(${bot.id})">Toggle</button> ` +
      `<button onclick="openEdit(${bot.id})">Edit</button> ` +
      `<button onclick="deleteBot(${bot.id})">Delete</button> ` +
      `<button onclick="viewLogs(${bot.id})">Logs</button> ` +
      `<button onclick="startGroup('${bot.group}')">Start group</button>` +
      `</td>`;
    tbody.appendChild(row);
  });
}

async function fetchLogs() {
  const res = await fetch('/logs').catch(() => null);
  if (!res) return;
  const logs = await res.json();
  const tbody = document.querySelector('#logTable tbody');
  tbody.innerHTML = '';
  logs.forEach(log => {
    const row = document.createElement('tr');
    row.innerHTML = `<td>${log.timestamp}</td><td>${log.channel}</td><td>${log.message}</td>`;
    tbody.appendChild(row);
  });
}

async function viewLogs(id) {
  const res = await fetch(`/bots/${id}/logs`).catch(() => null);
  if (!res) return;
  const logs = await res.json();
  const tbody = document.querySelector('#logTable tbody');
  tbody.innerHTML = '';
  logs.forEach(log => {
    const row = document.createElement('tr');
    row.innerHTML = `<td>${log.timestamp}</td><td>${log.channel}</td><td>${log.message}</td>`;
    tbody.appendChild(row);
  });
}

async function sendNow(id) {
  await fetch(`/bots/${id}/send`, {method: 'POST'}).catch(() => null);
  fetchLogs();
}

async function startGroup(name) {
  if (!name) return;
  await fetch(`/start_group/${encodeURIComponent(name)}`, {method: 'POST'}).catch(() => null);
  fetchLogs();
}

async function startAll() {
  await fetch('/start_all', {method: 'POST'}).catch(() => null);
  fetchLogs();
}

async function toggleBot(id) {
  await fetch(`/bots/${id}/toggle`, {method: 'POST'}).catch(() => null);
  fetchBots();
}

async function deleteBot(id) {
  await fetch(`/bots/${id}`, {method: 'DELETE'}).catch(() => null);
  fetchBots();
}

function openEdit(id) {
  fetch(`/bots/${id}`)
    .then(res => res.json())
    .then(bot => {
      document.getElementById('edit-id').value = bot.id;
      document.getElementById('edit-channel').value = bot.channel;
      document.getElementById('edit-message').value = bot.message;
      document.getElementById('edit-interval').value = bot.interval;
      document.getElementById('edit-token').value = bot.token;
      document.getElementById('edit-group').value = bot.group || '';
      document.getElementById('edit-active').checked = bot.active;
      document.getElementById('editDialog').showModal();
    })
    .catch(() => null);
}

function closeEdit() {
  document.getElementById('editDialog').close();
}

document.getElementById('botForm').addEventListener('submit', async e => {
  e.preventDefault();
  const data = {
    channel: document.getElementById('channel').value,
    message: document.getElementById('message').value,
    interval: parseInt(document.getElementById('interval').value, 10),
    token: document.getElementById('token').value,
    group: document.getElementById('group').value,
    active: document.getElementById('active').checked
  };
  await fetch('/bots', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}).catch(() => null);
  e.target.reset();
  fetchBots();
});

document.getElementById('editForm').addEventListener('submit', async e => {
  e.preventDefault();
  const id = document.getElementById('edit-id').value;
  const data = {
    channel: document.getElementById('edit-channel').value,
    message: document.getElementById('edit-message').value,
    interval: parseInt(document.getElementById('edit-interval').value, 10),
    token: document.getElementById('edit-token').value,
    group: document.getElementById('edit-group').value,
    active: document.getElementById('edit-active').checked
  };
  await fetch(`/bots/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}).catch(() => null);
  closeEdit();
  fetchBots();
});

fetchBots();
fetchLogs();
setInterval(fetchLogs, 5000);
setInterval(fetchBots, 5000);
