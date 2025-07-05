async function fetchBots() {
  const res = await fetch('/bots');
  const bots = await res.json();
  const tbody = document.querySelector('#botTable tbody');
  tbody.innerHTML = '';
  bots.forEach(bot => {
    const row = document.createElement('tr');
    row.innerHTML =
      `<td>${bot.id}</td>` +
      `<td>${bot.channel}</td>` +
      `<td>${bot.message}</td>` +
      `<td>${bot.interval}</td>` +
      `<td>${bot.active ? '✅' : '❌'}</td>` +
      `<td>` +
      `<button onclick="sendNow(${bot.id})">Send</button> ` +
      `<button onclick="toggleBot(${bot.id})">Toggle</button> ` +
      `<button onclick="editBot(${bot.id})">Edit</button> ` +
      `<button onclick="deleteBot(${bot.id})">Delete</button>` +
      `</td>`;
    tbody.appendChild(row);
  });
}

async function fetchLogs() {
  const res = await fetch('/logs');
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
  await fetch(`/bots/${id}/send`, {method: 'POST'});
  fetchLogs();
}

async function toggleBot(id) {
  await fetch(`/bots/${id}/toggle`, {method: 'POST'});
  fetchBots();
}

async function deleteBot(id) {
  await fetch(`/bots/${id}`, {method: 'DELETE'});
  fetchBots();
}

async function editBot(id) {
  const channel = prompt('Channel?');
  const message = prompt('Message?');
  const interval = prompt('Interval (sec)?');
  const data = {channel, message, interval: parseInt(interval, 10)};
  await fetch(`/bots/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  fetchBots();
}

document.getElementById('botForm').addEventListener('submit', async e => {
  e.preventDefault();
  const data = {
    channel: document.getElementById('channel').value,
    message: document.getElementById('message').value,
    interval: parseInt(document.getElementById('interval').value, 10),
    active: document.getElementById('active').checked
  };
  await fetch('/bots', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  e.target.reset();
  fetchBots();
});

fetchBots();
fetchLogs();
setInterval(fetchLogs, 5000);
