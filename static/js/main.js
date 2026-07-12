// ─── Empower Mentorship – Main JS ────────────────────────────────────────────

const EMOJIS = ['😊','😂','❤️','👍','🙏','🔥','✅','💪','🎉','😍',
                '🤔','😢','😎','🌟','💯','👀','🙌','💡','📚','✨',
                '🚀','🎯','💬','👋','😄','🤩','💝','🎓','📝','⚡'];

// ─── Auto-dismiss alerts ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(a => {
      a.style.opacity = '0';
      a.style.transition = 'opacity .4s';
      setTimeout(() => a.remove(), 400);
    });
  }, 4000);
});

// ─── Emoji Panel (generic) ────────────────────────────────────────────────────
function buildEmojiGrid(gridId, targetId) {
  const grid = document.getElementById(gridId);
  if (!grid) return;
  grid.innerHTML = '';
  EMOJIS.forEach(e => {
    const span = document.createElement('span');
    span.className = 'emoji-item';
    span.textContent = e;
    span.onclick = () => {
      const inp = document.getElementById(targetId);
      if (!inp) return;
      const pos = inp.selectionStart || inp.value.length;
      inp.value = inp.value.slice(0, pos) + e + inp.value.slice(pos);
      inp.focus();
    };
    grid.appendChild(span);
  });
}

function toggleEmoji() {
  const panel = document.getElementById('emojiPanel');
  if (!panel) return;
  const open = panel.classList.toggle('open');
  if (open) buildEmojiGrid('emojiGrid', 'msgInput');
  document.addEventListener('click', closeEmojiOutside, { once: true });
}

function closeEmojiOutside(e) {
  const panel = document.getElementById('emojiPanel');
  if (panel && !panel.contains(e.target) && !e.target.closest('.emoji-btn')) {
    panel.classList.remove('open');
  }
}

// ─── Feed emoji ───────────────────────────────────────────────────────────────
function togglePostEmoji() {
  const panel = document.getElementById('postEmojiPanel');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    buildEmojiGrid('postEmojiGrid', 'postContent');
  }
}

// ─── Auto-resize textarea ─────────────────────────────────────────────────────
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// ─── Heartbeat ────────────────────────────────────────────────────────────────
// Sends a 'heartbeat' socket event every 30 s so the server keeps last_seen
// fresh and the user stays "online" accurately.
// base.html already creates `window.socket` and joins the personal room.
document.addEventListener('DOMContentLoaded', function () {
  if (typeof socket === 'undefined') return;  // not logged in

  function sendHeartbeat() {
    if (socket.connected) socket.emit('heartbeat');
  }

  // First beat shortly after connect settles
  setTimeout(sendHeartbeat, 2000);
  // Recurring beats
  setInterval(sendHeartbeat, 30000);
  // Re-beat after a reconnect
  socket.on('reconnect', sendHeartbeat);
});

// ─── Presence helpers (used by chat.html & mentors.html) ─────────────────────

/**
 * Flip one sidebar dot on/off.
 * Dot elements are given id="dot_<role>_<uid>"  e.g.  dot_mentor_3
 */
function setContactOnline(role, uid, isOnline) {
  const dot = document.getElementById('dot_' + role + '_' + uid);
  if (dot) dot.classList.toggle('visible', !!isOnline);
}

/**
 * Update the chat-header subtitle (<p id="peerStatus">).
 */
function updateChatHeaderStatus(isOnline, label) {
  const el = document.getElementById('peerStatus');
  if (!el) return;
  el.textContent = label || (isOnline ? 'online' : 'last seen recently');
  el.className   = isOnline ? 'online' : '';
}

/**
 * POST /api/online-status/bulk to refresh ALL sidebar dots at once.
 * Pass the contacts array that was returned by /api/contacts.
 * Also updates the chat-header if the current peer is in the list.
 */
async function refreshPresenceBulk(contacts) {
  if (!contacts || !contacts.length) return;
  try {
    const users = contacts.map(function (c) {
      return { type: c.peer_type, id: c.peer_id };
    });
    const res  = await fetch('/api/online-status/bulk', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ users: users }),
    });
    const data = await res.json();
    if (!data.ok) return;

    Object.entries(data.statuses).forEach(function ([key, val]) {
      // key looks like "mentor_3" or "student_7"
      const parts = key.split('_');
      const role  = parts[0];
      const uid   = parts[1];

      // Update dot in sidebar
      setContactOnline(role, uid, val.online);

      // Update chat header if this is the active peer
      if (typeof window.PEER_TYPE !== 'undefined' &&
          role === window.PEER_TYPE &&
          String(uid) === String(window.PEER_ID)) {
        updateChatHeaderStatus(val.online, val.label);
      }
    });
  } catch (_) {
    // Network hiccup — silently ignore, will retry on next interval
  }
}