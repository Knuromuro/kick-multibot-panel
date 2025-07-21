const socket = io();

socket.on('bot_started', data => {
  const li = document.querySelector(`li[data-id='${data.id}']`);
  if (li) li.classList.add('bg-green-100');
});

socket.on('bot_stopped', data => {
  const li = document.querySelector(`li[data-id='${data.id}']`);
  if (li) li.classList.remove('bg-green-100');
});

socket.on('bot_error', data => {
  alert('Bot error: ' + data.error);
});

function addGroup(name) {
  fetch('/dashboard/api/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  }).then(r => r.json()).then(g => {
    const ul = document.getElementById('group-list');
    const li = document.createElement('li');
    li.textContent = g.name;
    ul.appendChild(li);
  }).catch(err => alert(err));
}

document.getElementById('add-group').addEventListener('click', () => {
  const name = prompt('Group name?');
  if (name) addGroup(name);
});

document.querySelectorAll('.start-bot').forEach(btn => {
  btn.addEventListener('click', () => {
    const id = btn.parentElement.getAttribute('data-id');
    fetch(`/dashboard/api/bots/${id}/start`, {method:'POST'});
  });
});
