// ─── Empower / MFL – WebRTC Voice Calls  ────────────────────────────────────
//
//  Call record flow
//  ──────────────────
//  Ended call  : caller POSTs to /api/call-record (status=ended)
//                socket emits call_ended → both sides see "Voice call · duration"
//
//  No-answer   : after 30 s _onTimeout fires:
//                caller shows "No answer" bubble + saves record
//                socket emits call_missed_notify → receiver's personal room
//                receiver's chat.html JS inserts "Missed voice call" bubble + saves record
//
//  Declined    : receiver declines → call_declined fires on caller
//                caller saves "declined" record, receiver saves "missed" record
//                (receiver explicitly chose to decline, so they need no notification)
//
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

// ── State ─────────────────────────────────────────────────
var _pc           = null;
var _localStream  = null;
var _callTimer    = null;
var _callSeconds  = 0;
var _isMuted      = false;
var _isSpeaker    = false;
var _callActive   = false;
var _noAnswerTout = null;
var _currentCall  = {};
var _callStartTime  = null;   // when outgoing call was initiated / incoming ring started
var _callConnectTime = null;  // when both sides were connected

var DEFAULT_ICE_SERVERS = [
  { urls: 'stun:stun.l.google.com:19302'  },
  { urls: 'stun:stun1.l.google.com:19302' },
  { urls: 'stun:stun2.l.google.com:19302' }
];

var RTC_CONFIG = {
  iceServers: (window.RTC_ICE_SERVERS && window.RTC_ICE_SERVERS.length)
    ? window.RTC_ICE_SERVERS
    : DEFAULT_ICE_SERVERS
};

function getRtcSocket() {
  if (typeof socket !== 'undefined' && socket) return socket;
  console.error('[WebRTC] Global socket missing');
  return null;
}
function _joinRoom(r) { var s = getRtcSocket(); if (s) s.emit('join', { room: r }); }

// ── Formatting helpers ────────────────────────────────────
function _fmtDur(secs) {
  var m = String(Math.floor(secs / 60)).padStart(2, '0');
  var s = String(secs % 60).padStart(2, '0');
  return m + ':' + s;
}
function _fmtTime(d) {
  if (!d) d = new Date();
  return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

// ════════════════════════════════════════════════════════
//  OUTGOING CALL
// ════════════════════════════════════════════════════════
function initiateCall(peerType, peerId, peerName, peerAvatar) {
  if (_callActive) { console.warn('[WebRTC] Call already in progress'); return; }
  var s = getRtcSocket(); if (!s) return;

  var myRole   = CURRENT_ROLE;
  var myId     = CURRENT_ID;
  var myName   = CURRENT_NAME;
  var myAvatar = CURRENT_AVATAR;

  var lo       = Math.min(myId, parseInt(peerId));
  var hi       = Math.max(myId, parseInt(peerId));
  var callRoom = 'call_' + lo + '_' + hi;
  var targetRoom = 'user_' + peerType + '_' + peerId;
  var callerRoom = 'user_' + myRole   + '_' + myId;

  _callStartTime = new Date();
  _callConnectTime = null;
  _currentCall   = { peerType, peerId, peerName, peerAvatar, role:'caller', room:callRoom, callerRoom };
  _callActive    = true;

  _joinRoom(callRoom);
  _showOverlay({ label:'Calling', name:peerName, avatar:peerAvatar, status:'Ringing…', actions:_btnCalling() });

  s.emit('call_request', {
    target_room:   targetRoom,
    caller_room:   callerRoom,
    call_room:     callRoom,
    caller_name:   myName,
    caller_type:   myRole,
    caller_id:     myId,
    caller_avatar: myAvatar,
  });

  _noAnswerTout = setTimeout(function () { _onTimeout(peerType, peerId); }, 30000);

  s.once('call_accepted', function () {
    clearTimeout(_noAnswerTout);
    _callConnectTime = new Date();
    _setStatus('Connecting…');
    _startLocalStream(function () {
      _setStatus('Connected');
      _showTimer();
      _setActions(_btnConnected());
      _startTimer();
      _createOffer(callRoom);
    });
  });

  s.once('call_declined', function () {
    clearTimeout(_noAnswerTout);
    // Save caller's record
    _saveCallRecord(_currentCall.peerType, _currentCall.peerId, 'declined', 0);
    // Also save receiver's "missed" record on their behalf via socket
    s.emit('call_missed_notify', {
      target_room:   'user_' + _currentCall.peerType + '_' + _currentCall.peerId,
      caller_type:   CURRENT_ROLE,
      caller_id:     CURRENT_ID,
      caller_name:   CURRENT_NAME,
      caller_avatar: CURRENT_AVATAR,
      called_at:     _fmtTime(_callStartTime),
      status:        'declined',
    });
    _endOverlay('Call declined');
  });

  _setupSignalListeners(s, callRoom);
}

function _onTimeout(peerType, peerId) {
  var s    = getRtcSocket();
  var room = _currentCall.room;
  if (s && room) s.emit('call_ended', { room: room });

  // Save no-answer record for caller
  _saveCallRecord(peerType, peerId, 'no_answer', 0);

  // Notify receiver they have a missed call
  if (s) {
    s.emit('call_missed_notify', {
      target_room:   'user_' + peerType + '_' + peerId,
      caller_type:   CURRENT_ROLE,
      caller_id:     CURRENT_ID,
      caller_name:   CURRENT_NAME,
      caller_avatar: CURRENT_AVATAR || '',
      called_at:     _fmtTime(_callStartTime),
      status:        'missed',
    });
  }

  _endOverlay('No answer');
  _fullCleanup();
}

// ════════════════════════════════════════════════════════
//  INCOMING CALL
// ════════════════════════════════════════════════════════
function setupIncomingCallListener() {
  var s = getRtcSocket(); if (!s) return;
  s.off('incoming_call');
  s.on('incoming_call', function (data) {
    if (_callActive) { s.emit('call_declined', { caller_room: data.caller_room }); return; }
    _callStartTime = new Date();
    _currentCall   = {
      peerName: data.caller_name, peerAvatar: data.caller_avatar || '',
      peerType: data.caller_type, peerId: data.caller_id,
      role: 'receiver', room: data.call_room, callerRoom: data.caller_room
    };
    _showOverlay({ label:'Incoming Voice Call', name:data.caller_name, avatar:data.caller_avatar||'', status:'Incoming call…', actions:_btnIncoming() });
    _playRingtone();
  });
}

// ════════════════════════════════════════════════════════
//  ACCEPT / DECLINE / END
// ════════════════════════════════════════════════════════
function acceptCall() {
  _stopRingtone();
  var s = getRtcSocket(); if (!s) return;
  _callActive      = true;
  _callConnectTime = new Date();
  _joinRoom(_currentCall.room);
  s.emit('call_accepted', { caller_room: _currentCall.callerRoom });
  _setLabel('Voice Call');
  _setStatus('Connecting…');
  _showTimer();
  _setActions(_btnConnected());
  _startLocalStream(function () { _setStatus('Connected'); _startTimer(); _setupSignalListeners(s, _currentCall.room); });
}

function declineCall() {
  _stopRingtone();
  var s = getRtcSocket();
  if (s) s.emit('call_declined', { caller_room: _currentCall.callerRoom });
  // Receiver explicitly declined — they know it; no bubble needed for them.
  // Save a "missed" record for their own chat history so they can see they missed it.
  _saveCallRecord(_currentCall.peerType, _currentCall.peerId, 'missed', 0);
  _callActive  = false;
  _currentCall = {};
  hideCallOverlay();
}

function endCall() {
  if (!_callActive) return;
  _stopRingtone();
  clearTimeout(_noAnswerTout);
  var s    = getRtcSocket();
  var room = _currentCall.room;
  var dur  = _callSeconds;
  if (s && room) s.emit('call_ended', { room: room });
  if (s) { s.off('call_accepted'); s.off('call_declined'); }
  // Save record for this side — the other side saves their own via call_ended handler
  _saveCallRecord(_currentCall.peerType, _currentCall.peerId, 'ended', dur);
  _fullCleanup();
  _endOverlay('Call ended · ' + _fmtDur(dur));
}

function toggleMute() {
  if (!_localStream) return;
  _isMuted = !_isMuted;
  _localStream.getAudioTracks().forEach(function (t) { t.enabled = !_isMuted; });
  _refreshConnectedBtns();
}
function toggleSpeaker() {
  _isSpeaker = !_isSpeaker;
  var ra = document.getElementById('remoteAudio');
  if (ra && ra.setSinkId) ra.setSinkId(_isSpeaker ? 'default' : '').catch(function(){});
  _refreshConnectedBtns();
}

// ════════════════════════════════════════════════════════
//  CALL RECORD PERSISTENCE  (save to DB)
// ════════════════════════════════════════════════════════
function _saveCallRecord(receiverType, receiverId, status, durationSecs) {
  fetch('/api/call-record', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({
      receiver_type:  receiverType,
      receiver_id:    receiverId,
      status:         status,
      duration_secs:  durationSecs || 0,
    }),
  }).catch(function(e){ console.warn('[CallRecord save error]', e); });
}

// ════════════════════════════════════════════════════════
//  CALL BUBBLE (DOM insert, called after endCall / timeout)
// ════════════════════════════════════════════════════════
/**
 * Appends a call-record bubble to #chatMessages.
 * @param {string}  status   – 'ended' | 'missed' | 'no_answer' | 'declined'
 * @param {number}  durSecs  – duration in seconds (0 for missed/declined)
 * @param {string}  calledAt – "HH:MM" string of when the call was placed
 * @param {boolean} isMe     – true = caller's bubble (right-aligned), false = receiver's
 * @param {string}  [id]     – optional data-id for the wrapper
 */
function _appendCallBubble(status, durSecs, calledAt, isMe, id) {
  var chatMessages = document.getElementById('chatMessages');
  if (!chatMessages) return;
  var typing = document.getElementById('typingIndicator');

  var isMissed  = (status === 'missed' || status === 'no_answer' || status === 'declined');
  var iconClass = isMissed ? 'crb-icon--missed' : 'crb-icon--ended';
  var color     = isMissed ? '#f44336' : '#00a884';

  var title, meta;
  switch (status) {
    case 'ended':
      title = 'Voice call';
      meta  = 'Duration ' + _fmtDur(durSecs || 0) + ' · Called ' + (calledAt || _fmtTime(_callStartTime));
      break;
    case 'no_answer':
      title = isMe ? 'No answer' : 'Missed voice call';
      meta  = 'Called ' + (calledAt || _fmtTime(_callStartTime));
      break;
    case 'declined':
      title = isMe ? 'Call declined' : 'Missed voice call';
      meta  = 'Called ' + (calledAt || _fmtTime(_callStartTime));
      break;
    case 'missed':
    default:
      title = isMe ? 'No answer' : 'Missed voice call';
      meta  = 'Called ' + (calledAt || _fmtTime(_callStartTime));
      break;
  }

  var endTime = _fmtTime(new Date());

  var wrap = document.createElement('div');
  wrap.className   = 'msg-wrapper ' + (isMe ? 'me' : 'them');
  wrap.dataset.id  = id || '';
  wrap.dataset.kind = 'call';

  wrap.innerHTML =
    '<div class="call-record-bubble ' + (isMissed ? 'crb-missed' : 'crb-ended') + '">' +
      '<div class="crb-phone-wrap ' + iconClass + '">' +
        // Pure CSS phone shape — no icon font needed
        '<div class="crb-phone-svg"></div>' +
      '</div>' +
      '<div class="crb-body">' +
        '<div class="crb-title">' + title + '</div>' +
        '<div class="crb-meta">' + meta + '</div>' +
      '</div>' +
      '<div class="crb-time">' + endTime + '</div>' +
    '</div>';

  if (typing && typing.parentNode === chatMessages) {
    chatMessages.insertBefore(wrap, typing);
  } else {
    chatMessages.appendChild(wrap);
  }
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ════════════════════════════════════════════════════════
//  WEBRTC CORE
// ════════════════════════════════════════════════════════
function _startLocalStream(cb) {
  navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    .then(function (stream) {
      _localStream = stream;
      var la = document.getElementById('localAudio'); if (la) la.srcObject = stream;
      if (cb) cb();
    })
    .catch(function (err) {
      console.error('[WebRTC] Mic error:', err);
      _setStatus('⚠ Microphone access denied');
      _setActions(_btnEndOnly());
    });
}

function _setupSignalListeners(s, room) {
  s.off('webrtc_offer'); s.off('webrtc_answer'); s.off('webrtc_ice'); s.off('call_ended');
  s.on('webrtc_offer', function (data) {
    if (!_pc) _createPeerConn(s, room);
    _pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
      .then(function () { return _pc.createAnswer(); })
      .then(function (ans) { return _pc.setLocalDescription(ans); })
      .then(function () { s.emit('webrtc_answer', { room: room, sdp: _pc.localDescription }); })
      .catch(function (e) { console.error('[WebRTC] Answer:', e); });
  });
  s.on('webrtc_answer', function (data) {
    if (_pc) _pc.setRemoteDescription(new RTCSessionDescription(data.sdp)).catch(function(){});
  });
  s.on('webrtc_ice', function (data) {
    if (_pc && data.candidate) _pc.addIceCandidate(new RTCIceCandidate(data.candidate)).catch(function(){});
  });
  s.on('call_ended', function () {
    if (!_callActive) return;
    var dur  = _callSeconds;
    var side = _currentCall.role;
    // Save own record
    _saveCallRecord(_currentCall.peerType, _currentCall.peerId, 'ended', dur);
    // Show bubble
    _appendCallBubble('ended', dur, _fmtTime(_callStartTime), side === 'caller');
    _fullCleanup();
    _endOverlay('Call ended · ' + _fmtDur(dur));
  });
}

function _createPeerConn(s, room) {
  _pc = new RTCPeerConnection(RTC_CONFIG);
  if (_localStream) _localStream.getTracks().forEach(function (t) { _pc.addTrack(t, _localStream); });
  _pc.ontrack = function (e) { var ra = document.getElementById('remoteAudio'); if (ra) ra.srcObject = e.streams[0]; };
  _pc.onicecandidate = function (e) { if (e.candidate) getRtcSocket().emit('webrtc_ice', { room: room, candidate: e.candidate }); };
  _pc.oniceconnectionstatechange = function () {
    var st = _pc ? _pc.iceConnectionState : '';
    if (st === 'connected' || st === 'completed') _setStatus('Connected');
    else if (st === 'checking') _setStatus('Connecting…');
    else if (st === 'disconnected') _setStatus('⚠ Reconnecting…');
    else if ((st === 'failed' || st === 'closed') && _callActive) {
      var dur = _callSeconds; _fullCleanup(); _endOverlay('Call ended · ' + _fmtDur(dur));
    }
  };
}

function _createOffer(room) {
  var s = getRtcSocket(); _createPeerConn(s, room);
  _pc.createOffer()
    .then(function (o) { return _pc.setLocalDescription(o); })
    .then(function () { s.emit('webrtc_offer', { room: room, sdp: _pc.localDescription }); })
    .catch(function (e) { console.error('[WebRTC] Offer:', e); });
}

function _fullCleanup() {
  _callActive = false; _stopTimer(); _stopRingtone(); clearTimeout(_noAnswerTout);
  if (_pc) { _pc.oniceconnectionstatechange=null; _pc.ontrack=null; _pc.onicecandidate=null; _pc.close(); _pc=null; }
  if (_localStream) { _localStream.getTracks().forEach(function(t){t.stop();}); _localStream=null; }
  var la=document.getElementById('localAudio'); var ra=document.getElementById('remoteAudio');
  if(la)la.srcObject=null; if(ra)ra.srcObject=null;
  _isMuted=false; _isSpeaker=false;
  var s=getRtcSocket();
  if(s){s.off('webrtc_offer');s.off('webrtc_answer');s.off('webrtc_ice');s.off('call_ended');s.off('call_accepted');s.off('call_declined');}
  _currentCall={};
}

// ════════════════════════════════════════════════════════
//  TIMER & RINGTONE
// ════════════════════════════════════════════════════════
function _startTimer() {
  _callSeconds=0;
  _callTimer=setInterval(function(){
    _callSeconds++;
    var el=document.getElementById('callTimer');
    if(el)el.textContent=_fmtDur(_callSeconds);
  },1000);
}
function _stopTimer(){ clearInterval(_callTimer); _callTimer=null; }

var _audioCtx=null,_ringIv=null;
function _playRingtone(){
  try{
    _audioCtx=new(window.AudioContext||window.webkitAudioContext)();
    var count=0;
    _ringIv=setInterval(function(){
      if(++count>50){_stopRingtone();return;}
      var osc=_audioCtx.createOscillator();var gain=_audioCtx.createGain();
      osc.connect(gain);gain.connect(_audioCtx.destination);
      osc.frequency.setValueAtTime(440,_audioCtx.currentTime);
      osc.frequency.setValueAtTime(480,_audioCtx.currentTime+.22);
      gain.gain.setValueAtTime(.35,_audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(.001,_audioCtx.currentTime+.75);
      osc.start(_audioCtx.currentTime);osc.stop(_audioCtx.currentTime+.75);
    },1300);
  }catch(e){}
}
function _stopRingtone(){
  clearInterval(_ringIv);_ringIv=null;
  if(_audioCtx){try{_audioCtx.close();}catch(e){}_audioCtx=null;}
}

// ════════════════════════════════════════════════════════
//  OVERLAY
// ════════════════════════════════════════════════════════
function _showOverlay(opts){
  var overlay=document.getElementById('callOverlay'); if(!overlay)return;
  var lbl=document.getElementById('callLabel'); if(lbl)lbl.textContent=opts.label||'Voice Call';
  var wrap=document.getElementById('callAvatarWrap');
  if(wrap)wrap.innerHTML=opts.avatar?'<img src="/static/'+opts.avatar+'" alt="">':'<div class="call-avatar-ph">'+(opts.name||'?')[0].toUpperCase()+'</div>';
  var nameEl=document.getElementById('callName'); if(nameEl)nameEl.textContent=opts.name||'';
  _setStatus(opts.status||'');
  var timerEl=document.getElementById('callTimer'); if(timerEl){timerEl.textContent='00:00';timerEl.classList.add('hidden');}
  _setActions(opts.actions||'');
  overlay.classList.add('active');
}
function _endOverlay(msg){
  _setLabel('Voice Call'); _setStatus(msg); _setActions('');
  var timerEl=document.getElementById('callTimer'); if(timerEl)timerEl.classList.add('hidden');
  setTimeout(hideCallOverlay,2500);
}
function hideCallOverlay(){ var o=document.getElementById('callOverlay'); if(o)o.classList.remove('active'); }
function _setLabel(t) { var e=document.getElementById('callLabel');   if(e)e.textContent=t; }
function _setStatus(t){ var e=document.getElementById('callStatus');  if(e)e.textContent=t; }
function _setActions(h){ var e=document.getElementById('callActions'); if(e)e.innerHTML=h; }
function _showTimer()  { var e=document.getElementById('callTimer');   if(e)e.classList.remove('hidden'); }

// ════════════════════════════════════════════════════════
//  BUTTON BUILDERS
// ════════════════════════════════════════════════════════
function _btnIncoming(){ return _wrap('decline','declineCall()','fa-phone-slash','Decline')+_wrap('accept','acceptCall()','fa-phone','Accept'); }
function _btnCalling() { return _wrap('end','endCall()','fa-phone-slash','Cancel'); }
function _btnConnected(){
  var mc='call-btn mute'+(_isMuted?' muted':''), mi=_isMuted?'fa-microphone-slash':'fa-microphone';
  var sc='call-btn speaker'+(_isSpeaker?' active':'');
  return '<div class="call-action-wrap"><button class="'+mc+'" id="muteCallBtn" onclick="toggleMute()"><i class="fa-solid '+mi+'"></i></button><span>'+(_isMuted?'Unmute':'Mute')+'</span></div>'+
         '<div class="call-action-wrap"><button class="call-btn end" onclick="endCall()"><i class="fa-solid fa-phone-slash"></i></button><span>End</span></div>'+
         '<div class="call-action-wrap"><button class="'+sc+'" id="speakerCallBtn" onclick="toggleSpeaker()"><i class="fa-solid fa-volume-high"></i></button><span>'+(_isSpeaker?'Earpiece':'Speaker')+'</span></div>';
}
function _btnEndOnly(){ return _wrap('end','endCall()','fa-phone-slash','End'); }
function _wrap(cls,fn,icon,label){
  return '<div class="call-action-wrap"><button class="call-btn '+cls+'" onclick="'+fn+'"><i class="fa-solid '+icon+'"></i></button><span>'+label+'</span></div>';
}
function _refreshConnectedBtns(){
  var mb=document.getElementById('muteCallBtn');
  if(mb){mb.className='call-btn mute'+(_isMuted?' muted':'');mb.innerHTML='<i class="fa-solid '+(_isMuted?'fa-microphone-slash':'fa-microphone')+'"></i>';if(mb.nextElementSibling)mb.nextElementSibling.textContent=_isMuted?'Unmute':'Mute';}
  var sb=document.getElementById('speakerCallBtn');
  if(sb){sb.className='call-btn speaker'+(_isSpeaker?' active':'');if(sb.nextElementSibling)sb.nextElementSibling.textContent=_isSpeaker?'Earpiece':'Speaker';}
}

// Legacy — kept so base.html _insertCallRecord references still work if any
function _insertCallRecord(type, duration) {
  var isMe = true;
  _appendCallBubble(type, _callSeconds, _fmtTime(_callStartTime), isMe);
}