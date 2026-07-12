// ─── Empower Mentorship – Chat JS ─────────────────────────────────────────────
//
//  FIX: Removed `let socket` declaration and `socket = io()` call.
//  The global `socket` is created once in base.html.
//  Redeclaring it here caused:
//    SyntaxError: Identifier 'socket' has already been declared
//  Which crashed the entire script before initChat could be defined,
//  which caused:
//    ReferenceError: initChat is not defined
//  Which meant the sidebar never loaded contacts.
// ─────────────────────────────────────────────────────────────────────────────

// NOTE: `socket` is NOT declared here — it comes from base.html

function initChat(role, uid, peerType, peerId, room, meName, meAvatar, peerName, peerAvatar) {
  // `socket` is the global from base.html — just use it directly

  socket.on('connect', function () {
    socket.emit('join', { room: room });
  });

  // If already connected (page loaded after socket connected), join now
  if (socket.connected) {
    socket.emit('join', { room: room });
  }

  socket.on('new_message', function (data) {
    var isMe = data.sender_type === role && data.sender_id === uid;
    appendMessage(data, isMe, peerName, peerAvatar, meName, meAvatar);
    scrollBottom();
  });

  scrollBottom();
  var inp = document.getElementById('msgInput');
  if (inp) inp.focus();
}

function initGroupChat(role, uid, groupId, meName, meAvatar) {
  socket.on('connect', function () {
    socket.emit('join', { room: 'group_' + groupId });
  });

  if (socket.connected) {
    socket.emit('join', { room: 'group_' + groupId });
  }

  socket.on('new_group_message', function (data) {
    var isMe = data.sender_type === role && data.sender_id === uid;
    appendGroupMessage(data, isMe, meName, meAvatar);
    scrollBottom();
  });

  scrollBottom();
  var inp = document.getElementById('msgInput');
  if (inp) inp.focus();
}

function appendMessage(data, isMe, peerName, peerAvatar, meName, meAvatar) {
  var container = document.getElementById('chatMessages');
  if (!container) return;
  var wrapper = document.createElement('div');
  wrapper.className = 'msg-wrapper ' + (isMe ? 'me' : 'them');

  var avatarName = isMe ? meName : peerName;
  var avatarSrc  = isMe ? meAvatar : peerAvatar;
  var avatarHTML = avatarSrc
    ? '<img src="/static/' + avatarSrc + '" class="msg-avatar" alt="">'
    : '<div class="msg-avatar">' + ((avatarName || '?')[0].toUpperCase()) + '</div>';

  wrapper.innerHTML =
    avatarHTML +
    '<div class="msg-bubble ' + (isMe ? 'me' : 'them') + '">' +
      escapeHtml(data.text) +
      '<div class="msg-time">' +
        data.time +
        (isMe ? ' <i class="fa-solid fa-check-double" style="color:rgba(0,0,0,0.4);font-size:.65rem;"></i>' : '') +
      '</div>' +
    '</div>';

  container.appendChild(wrapper);
}

function appendGroupMessage(data, isMe, meName, meAvatar) {
  var container = document.getElementById('chatMessages');
  if (!container) return;
  var wrapper = document.createElement('div');
  wrapper.className = 'msg-wrapper ' + (isMe ? 'me' : 'them');

  var avatarSrc  = isMe ? meAvatar : (data.avatar || '');
  var avatarName = isMe ? meName   : (data.name   || '?');
  var avatarHTML = avatarSrc
    ? '<img src="/static/' + avatarSrc + '" class="msg-avatar" alt="">'
    : '<div class="msg-avatar">' + ((avatarName || '?')[0].toUpperCase()) + '</div>';

  wrapper.innerHTML =
    avatarHTML +
    '<div class="msg-bubble ' + (isMe ? 'me' : 'them') + '">' +
      (!isMe ? '<div class="msg-name">' + escapeHtml(data.name || '') + '</div>' : '') +
      escapeHtml(data.text) +
      '<div class="msg-time">' + data.time + '</div>' +
    '</div>';

  container.appendChild(wrapper);
}

function sendMessage() {
  if (!socket) return;
  var inp  = document.getElementById('msgInput');
  var text = inp.value.trim();
  if (!text) return;
  socket.emit('send_message', {
    peer_type: window.PEER_TYPE,
    peer_id:   window.PEER_ID,
    text:      text,
    room:      window.ROOM
  });
  inp.value = '';
  inp.style.height = 'auto';
  inp.focus();
}

function sendGroupMessage() {
  if (!socket) return;
  var inp  = document.getElementById('msgInput');
  var text = inp.value.trim();
  if (!text) return;
  socket.emit('send_group_message', {
    group_id: window.GROUP_ID,
    text:     text
  });
  inp.value = '';
  inp.style.height = 'auto';
  inp.focus();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
  autoResize(e.target);
}

function handleGroupKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendGroupMessage();
  }
  autoResize(e.target);
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function scrollBottom() {
  var el = document.getElementById('chatMessages');
  if (el) el.scrollTop = el.scrollHeight;
}

function escapeHtml(text) {
  var d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

document.addEventListener('DOMContentLoaded', function () {
  var inp = document.getElementById('msgInput');
  if (inp) {
    inp.addEventListener('input', function () { autoResize(inp); });
    scrollBottom();
  }
});