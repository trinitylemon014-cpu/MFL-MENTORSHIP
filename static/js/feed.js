// ─── Empower Mentorship – Feed JS ─────────────────────────────────────────────
// Includes:
//   • Feature 3 — Persistent post likes + "who liked" modal
//   • Feature 4 — Persistent comment likes, who liked comments,
//                 Instagram-style nested replies

// ── Helpers ────────────────────────────────────────────────────────────────────

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text || '';
  return d.innerHTML;
}

// Alias used by inline onclick= attributes in feed.html
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}

function csrf() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

// ── Init ────────────────────────────────────────────────────────────────────────

function initFeed() {
  // Build post emoji grid
  const grid = document.getElementById('postEmojiGrid');
  if (grid) {
    const emojis = [
      '😊','😂','❤️','👍','🙏','🔥','✅','💪','🎉','😍',
      '🤔','😢','😎','🌟','💯','👀','🙌','💡','📚','✨',
      '🚀','🎯','💬','👋','😄','🤩','💝','🎓','📝','⚡',
    ];
    emojis.forEach(e => {
      const span = document.createElement('span');
      span.className = 'emoji-item';
      span.textContent = e;
      span.onclick = () => {
        const inp = document.getElementById('postContent');
        if (inp) { inp.value += e; inp.focus(); }
      };
      grid.appendChild(span);
    });
  }
}

// ── Image preview (legacy post creator helper) ──────────────────────────────────

function previewImage(input) {
  const wrap = document.getElementById('imagePreviewWrap');
  const img  = document.getElementById('imagePreview');
  if (input.files && input.files[0]) {
    const reader = new FileReader();
    reader.onload = e => {
      img.src = e.target.result;
      wrap.classList.remove('hidden');
    };
    reader.readAsDataURL(input.files[0]);
  }
}

function clearImage() {
  document.getElementById('imageInput').value = '';
  document.getElementById('imagePreview').src = '';
  document.getElementById('imagePreviewWrap').classList.add('hidden');
}

// ══ FEATURE 3 — POST LIKES (persistent + "who liked" modal) ════════════════════

// Internal cache for the likes modal search
let _likesListCache = [];

/**
 * Toggle a post like.
 * Works with the feed.html heart button:
 *   onclick="likePost(this.dataset.pid, this)"
 */
async function likePost(postId, btn) {
  if (!btn) btn = document.getElementById('lb-' + postId);
  btn.classList.toggle('liked');
  const liked = btn.classList.contains('liked');
  btn.querySelector('i').className = liked ? 'fa-solid fa-heart' : 'fa-regular fa-heart';

  // Update count display
  const lc = document.getElementById('lc-' + postId);
  if (lc) {
    const n  = parseInt(lc.textContent) || 0;
    const nn = n + (liked ? 1 : -1);
    lc.textContent = nn === 1 ? '1 like' : nn > 1 ? `${nn} likes` : '';
    lc.style.cursor = nn > 0 ? 'pointer' : 'default';
  }

  // Heart pop animation (works with both old and new markup)
  btn.style.transform = 'scale(1.3)';
  setTimeout(() => (btn.style.transform = ''), 200);

  try {
    await fetch(`/post/${postId}/like`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
    });
  } catch (e) { console.error('likePost error:', e); }
}

/**
 * Fetch the list of people who liked a post and open the modal.
 * Called by clicking the like-count div in feed.html.
 */
async function showPostLikes(postId) {
  try {
    const res  = await fetch(`/post/${postId}/likes`);
    const data = await res.json();
    if (!data.ok) return;
    const title =
      data.likes.length === 1 ? '1 Like' :
      data.likes.length >  1 ? `${data.likes.length} Likes` : 'Likes';
    _openLikesModal(data.likes, title);
  } catch (e) { console.error('showPostLikes error:', e); }
}

/**
 * Render and open the shared "who liked" bottom-sheet modal.
 * @param {Array}  list   — array of { name, avatar } objects
 * @param {string} title  — modal header text
 */
function _openLikesModal(list, title) {
  const modal      = document.getElementById('likesModal');
  const titleEl    = document.getElementById('likesModalTitle');
  const listEl     = document.getElementById('likesModalList');
  const searchWrap = document.getElementById('likesSearchWrap');
  const searchInp  = document.getElementById('likesSearchInput');
  if (!modal) return;

  titleEl.textContent  = title;
  _likesListCache      = list;
  if (searchInp)  searchInp.value = '';
  // Show search only when the list is long enough to need it
  if (searchWrap) searchWrap.style.display = list.length > 6 ? 'block' : 'none';

  _renderLikesList(list, listEl);
  openModal('likesModal');
}

/**
 * Render the list of likers into a container element.
 */
function _renderLikesList(list, container) {
  if (!container) return;
  container.innerHTML = '';

  if (!list || !list.length) {
    container.innerHTML =
      '<div style="text-align:center;padding:28px 20px;color:var(--faint);">' +
      '<i class="fa-regular fa-heart" style="font-size:2rem;display:block;margin-bottom:10px;"></i>' +
      'No likes yet</div>';
    return;
  }

  list.forEach(lk => {
    const item = document.createElement('div');
    item.className = 'likes-list-item';

    const avHtml = lk.avatar
      ? `<img src="/static/${esc(lk.avatar)}"
              style="width:40px;height:40px;border-radius:50%;object-fit:cover;
                     border:1px solid var(--border);flex-shrink:0;">`
      : `<div style="width:40px;height:40px;border-radius:50%;
                     background:var(--story-gradient);color:#fff;
                     display:flex;align-items:center;justify-content:center;
                     font-weight:700;font-size:15px;flex-shrink:0;">
           ${esc((lk.name || '?')[0].toUpperCase())}
         </div>`;

    item.innerHTML =
      avHtml +
      `<span style="font-size:14px;font-weight:500;color:var(--text);flex:1;">
         ${esc(lk.name || 'Unknown')}
       </span>` +
      `<i class="fa-solid fa-heart" style="color:var(--red);font-size:14px;"></i>`;

    container.appendChild(item);
  });
}

/**
 * Filter the likes list by name (called from the search input).
 */
function filterLikesList(query) {
  const listEl = document.getElementById('likesModalList');
  const q = query.trim().toLowerCase();
  const filtered = q
    ? _likesListCache.filter(lk => (lk.name || '').toLowerCase().includes(q))
    : _likesListCache;
  _renderLikesList(filtered, listEl);
}

// ══ FEATURE 4A — COMMENT LIKE (persistent) ═════════════════════════════════════

/**
 * Toggle a like on a comment.
 * Button markup:
 *   <button class="cm-btn" data-cid="<id>" data-pid="<postId>"
 *           onclick="toggleCommentLike(this)">
 */
async function toggleCommentLike(btn) {
  const cid = btn.dataset.cid;
  const pid = btn.dataset.pid;
  if (!cid || !pid) return;

  try {
    const res  = await fetch(`/post/${pid}/comment/${cid}/like`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
    });
    const data = await res.json();
    if (!data.ok) return;

    // Update heart icon
    btn.classList.toggle('liked', data.liked);
    const icon = btn.querySelector('i');
    if (icon) {
      icon.className  = data.liked ? 'fa-solid fa-heart' : 'fa-regular fa-heart';
      icon.style.color = data.liked ? 'var(--red)' : '';
    }

    // Update / wire count span
    const countEl = btn.querySelector('.cl-count');
    if (countEl) {
      countEl.textContent = data.count > 0 ? data.count : '';
      if (data.count > 0) {
        countEl.style.cursor          = 'pointer';
        countEl.style.textDecoration  = 'underline';
        countEl.onclick = e => showCommentLikes(e, cid, pid);
      } else {
        countEl.style.cursor         = '';
        countEl.style.textDecoration = '';
        countEl.onclick              = null;
      }
    }
  } catch (e) { console.error('toggleCommentLike error:', e); }
}

// ══ FEATURE 4B — WHO LIKED A COMMENT ═══════════════════════════════════════════

/**
 * Fetch and display who liked a specific comment.
 */
async function showCommentLikes(e, cid, pid) {
  if (e) { e.stopPropagation(); e.preventDefault(); }
  try {
    const res  = await fetch(`/post/${pid}/comment/${cid}/likes`);
    const data = await res.json();
    if (!data.ok) return;
    const title =
      data.likes.length === 1 ? '1 Comment Like' :
      data.likes.length >  1 ? `${data.likes.length} Comment Likes` : 'Comment Likes';
    _openLikesModal(data.likes, title);
  } catch (e) { console.error('showCommentLikes error:', e); }
}

// ══ FEATURE 4C — NESTED COMMENT REPLIES ════════════════════════════════════════

/**
 * Show the inline reply input under a specific comment.
 * Button markup:
 *   <button class="cm-btn" data-cid="<parentId>" data-author="<name>"
 *           data-pid="<postId>" onclick="showReplyInput(this)">Reply</button>
 */
function showReplyInput(btn) {
  const cid    = btn.dataset.cid;
  const author = btn.dataset.author;

  // Close all other open reply inputs first
  document.querySelectorAll('.reply-input-wrap').forEach(w => {
    w.style.display = 'none';
  });

  const wrap = document.getElementById('ri-' + cid);
  if (wrap) {
    wrap.style.display = 'block';
    const inp = document.getElementById('rii-' + cid);
    if (inp) {
      inp.placeholder = `Reply to ${author}…`;
      inp.focus();
    }
  }
}

/**
 * Submit a reply to a comment.
 * @param {number|string} parentCid — the comment being replied to
 * @param {number}        pid       — the post ID
 */
async function submitReply(parentCid, pid) {
  const inp = document.getElementById('rii-' + parentCid);
  if (!inp) return;
  const text = inp.value.trim();
  if (!text) { inp.focus(); return; }
  inp.value = '';

  // Get current user info from the appData div written by feed.html
  const D     = document.getElementById('appData');
  const ME    = D ? D.dataset.me : '';
  const ME_AV = D ? D.dataset.av : '';

  try {
    const res  = await fetch(`/post/${pid}/comment`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
      },
      body: JSON.stringify({ comment: text, parent_id: parentCid }),
    });
    const data = await res.json();
    if (data.error) { showToast('Could not post reply', 'error'); return; }

    // Build reply DOM element
    const avHtml = ME_AV
      ? `<div class="comment-av" style="width:24px;height:24px;font-size:9px;min-width:24px;">
           <img src="/static/${esc(ME_AV)}" alt="">
         </div>`
      : `<div class="comment-av" style="width:24px;height:24px;font-size:9px;min-width:24px;">
           ${esc((ME || '?')[0].toUpperCase())}
         </div>`;

    const realCid = data.id || ('tmp-' + Date.now());
    const replyEl = document.createElement('div');
    replyEl.className = 'comment-row reply-row';
    replyEl.id = 'cr-' + realCid;
    replyEl.innerHTML = `
      ${avHtml}
      <div style="flex:1;min-width:0;">
        <div class="comment-bubble" style="border-radius:0 10px 10px 10px;">
          <strong>${esc(ME || 'You')}</strong>
          <span>${esc(text)}</span>
          <span class="ct">Just now</span>
        </div>
        <div class="comment-mini">
          <button class="cm-btn"
                  id="clb-${realCid}"
                  data-cid="${realCid}"
                  data-pid="${pid}"
                  onclick="toggleCommentLike(this)">
            <i class="fa-regular fa-heart"></i>
            <span class="cl-count"></span>
          </button>
          <button class="cm-btn"
                  data-cid="${parentCid}"
                  data-author="${esc(ME || 'You')}"
                  data-pid="${pid}"
                  onclick="showReplyInput(this)">Reply</button>
        </div>
      </div>`;

    // Find or create the replies container for this parent comment
    let repliesEl = document.getElementById('rl-' + parentCid);
    if (!repliesEl) {
      repliesEl = document.createElement('div');
      repliesEl.className = 'replies-list';
      repliesEl.id = 'rl-' + parentCid;
      const riWrap = document.getElementById('ri-' + parentCid);
      if (riWrap) riWrap.parentNode.insertBefore(repliesEl, riWrap);
    }
    repliesEl.appendChild(replyEl);
    replyEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    // Hide the reply input box after submitting
    const wrap = document.getElementById('ri-' + parentCid);
    if (wrap) wrap.style.display = 'none';

    showToast('Reply posted ✓', 'success');
  } catch (e) {
    showToast('Network error', 'error');
    console.error('submitReply error:', e);
  }
}

// ══ COMMENTS ════════════════════════════════════════════════════════════════════

/**
 * Open / close a post's comment section.
 * Used by the comment icon button: onclick="openComments(this.dataset.pid)"
 */
function openComments(pid) {
  const cw = document.getElementById('cw-' + pid);
  if (!cw) return;
  const hidden = cw.style.display === 'none' || !cw.style.display;
  cw.style.display = hidden ? 'block' : 'none';
  if (hidden) document.getElementById('ci-' + pid)?.focus();
}

// Legacy alias used by some older onclick= attributes
function toggleComments(postId) { openComments(postId); }

/**
 * Submit a top-level comment on a post.
 * Optimistically appends the comment, then patches IDs after the server responds.
 */
async function submitComment(pid) {
  const inp  = document.getElementById('ci-' + pid);
  const text = inp.value.trim();
  if (!text) { inp.focus(); return; }
  inp.value = '';

  const D     = document.getElementById('appData');
  const ME    = D ? D.dataset.me : '';
  const ME_AV = D ? D.dataset.av : '';

  const list   = document.getElementById('cl-' + pid);
  const avHtml = ME_AV
    ? `<div class="comment-av"><img src="/static/${esc(ME_AV)}" alt=""></div>`
    : `<div class="comment-av">${esc((ME || '?')[0].toUpperCase())}</div>`;

  const tmpId = 'tmp-' + Date.now();
  const newRow = document.createElement('div');
  newRow.className = 'comment-row';
  newRow.id = 'cr-' + tmpId;
  newRow.innerHTML = `
    ${avHtml}
    <div style="flex:1;min-width:0;">
      <div class="comment-bubble">
        <strong>${esc(ME || 'You')}</strong>
        <span>${esc(text)}</span>
        <span class="ct">Just now</span>
      </div>
      <div class="comment-mini">
        <button class="cm-btn"
                id="clb-${tmpId}"
                data-cid="${tmpId}"
                data-pid="${pid}"
                onclick="toggleCommentLike(this)">
          <i class="fa-regular fa-heart"></i>
          <span class="cl-count"></span>
        </button>
        <button class="cm-btn"
                data-cid="${tmpId}"
                data-author="${esc(ME || 'You')}"
                data-pid="${pid}"
                onclick="showReplyInput(this)">Reply</button>
      </div>
      <div class="reply-input-wrap" id="ri-${tmpId}" style="display:none;">
        <div class="reply-inner">
          <input type="text" class="comment-input"
                 id="rii-${tmpId}"
                 placeholder="Reply…"
                 onkeydown="if(event.key==='Enter') submitReply('${tmpId}', ${pid})">
          <button class="comment-send"
                  onclick="submitReply('${tmpId}', ${pid})">
            <i class="fa-solid fa-paper-plane"></i>
          </button>
          <button class="comment-send" style="color:var(--faint);"
                  onclick="document.getElementById('ri-${tmpId}').style.display='none'">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
      </div>
      <div class="replies-list" id="rl-${tmpId}"></div>
    </div>`;

  list.appendChild(newRow);
  newRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const res  = await fetch(`/post/${pid}/comment`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
      },
      body: JSON.stringify({ comment: text }),
    });
    const data = await res.json();
    if (data.error) return;

    // Patch all temp IDs → real server-assigned comment ID
    if (data.id) {
      const realId = data.id;
      newRow.id = 'cr-' + realId;

      ['clb', 'ri', 'rii', 'rl'].forEach(prefix => {
        const el = newRow.querySelector(`#${prefix}-${tmpId}`);
        if (el) {
          el.id = `${prefix}-${realId}`;
          if (el.dataset && el.dataset.cid) el.dataset.cid = realId;
        }
      });

      // Fix all onclick= / onkeydown= strings that reference the tmp ID
      newRow.querySelectorAll('[onclick]').forEach(el => {
        const oc = el.getAttribute('onclick');
        if (oc && oc.includes(tmpId))
          el.setAttribute('onclick', oc.replace(new RegExp(tmpId, 'g'), realId));
      });
      newRow.querySelectorAll('[onkeydown]').forEach(el => {
        const ok = el.getAttribute('onkeydown');
        if (ok && ok.includes(tmpId))
          el.setAttribute('onkeydown', ok.replace(new RegExp(tmpId, 'g'), realId));
      });
    }
  } catch (e) { console.error('submitComment error:', e); }
}

// ── Save (bookmark) ─────────────────────────────────────────────────────────────

async function savePost(pid, btn) {
  if (!btn) btn = document.getElementById('sb-' + pid);
  btn.classList.toggle('saved');
  const saved = btn.classList.contains('saved');
  btn.querySelector('i').className = saved ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark';
  showToast(saved ? 'Post saved ✓' : 'Post unsaved', saved ? 'success' : '');
  try {
    await fetch(`/post/${pid}/save`, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
    });
  } catch (e) { console.error('savePost error:', e); }
}

// ── Toast helper ────────────────────────────────────────────────────────────────
// Works with the #toast element defined in feed.html.
// Exposed as both showToast() and toast() for compatibility.

function showToast(msg, type) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.style.background =
    type === 'error'   ? '#ed4956' :
    type === 'success' ? '#00c853' : '#0a0a0a';
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), 2600);
}

// Alias so existing inline calls using toast() still work
const toast = showToast;

// ── Modal helpers ───────────────────────────────────────────────────────────────

function openModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.add('open'); document.body.style.overflow = 'hidden'; }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) { el.classList.remove('open'); document.body.style.overflow = ''; }
}

function closeBdrop(e, id) {
  if (e.target === document.getElementById(id)) closeModal(id);
}

// ── Expose everything globally ──────────────────────────────────────────────────
// All functions used by onclick= attributes must be on window.

Object.assign(window, {
  // Init
  initFeed,

  // Image preview
  previewImage,
  clearImage,

  // Post likes
  likePost,
  showPostLikes,
  filterLikesList,

  // Save
  savePost,

  // Comments
  openComments,
  toggleComments,
  submitComment,

  // Comment likes
  toggleCommentLike,
  showCommentLikes,

  // Replies
  showReplyInput,
  submitReply,

  // Utilities
  escapeHtml,
  esc,
  csrf,
  showToast,
  toast,
  openModal,
  closeModal,
  closeBdrop,
});