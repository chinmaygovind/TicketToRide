/* ============================================================
   Ticket to Ride — Game Client
   ============================================================ */

const socket = io();
let gameState = null;
let amHost = false;
let botPlayerIds = [];
let pendingRouteId = null;
let myChatName = IS_SPECTATOR ? SPECTATOR_NAME : '';

// ─── Transition tracking ──────────────────────────────────────────────────────
let prevCurrentPlayerId = null;
let prevPhase = null;
let lastKnownActionLogEntry = '';
let prevClaimedCount = 0;
let pendingBlindDraw = null; // hand snapshot taken before a blind draw, cleared after animation
let _sweepInProgress = false; // true while 3-loco sweep animation is running

// ─── Audio system (AudioContext-based for mobile compatibility) ───────────────
// Settings — persisted to localStorage
function _loadSetting(key, def) {
  const v = localStorage.getItem(key);
  return v === null ? def : v === 'true';
}
let soundEnabled        = _loadSetting('ttr_sounds', true);
let yourTurnSoundEnabled = _loadSetting('ttr_your_turn_sound', true);
let scoringVisible      = _loadSetting('ttr_scoring', true);
let _gameOverSoundPlayed = false;
let _gameOverDismissed = false;

let _audioCtx = null;
const _soundBuffers = {};   // pre-loaded decoded buffers
let _audioUnlocked = false;

const SOUND_FILES = {
  your_turn:    '/static/sounds/your_turn.mp3',
  draw_card:    '/static/sounds/take_card.mp3',
  place_trains: '/static/sounds/place_train.mp3',
  win:          '/static/sounds/win.mp3',
  lose:         '/static/sounds/lose.mp3',
};

function _getAudioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}

// Called once on first user gesture — resumes context and pre-loads all buffers
async function _unlockAudio() {
  if (_audioUnlocked) return;
  _audioUnlocked = true;
  try {
    const ctx = _getAudioCtx();
    if (ctx.state === 'suspended') await ctx.resume();
    for (const [name, url] of Object.entries(SOUND_FILES)) {
      try {
        const res = await fetch(url);
        const raw = await res.arrayBuffer();
        _soundBuffers[name] = await ctx.decodeAudioData(raw);
      } catch(e) {}
    }
  } catch(e) {}
}

function _synth(freq, dur, type = 'sine', vol = 0.2) {
  try {
    const ctx = _getAudioCtx();
    if (ctx.state === 'suspended') ctx.resume();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(vol, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
    osc.start(); osc.stop(ctx.currentTime + dur);
  } catch(e) {}
}

function playSound(name) {
  if (!soundEnabled) return;
  if (_soundBuffers[name]) {
    try {
      const ctx = _getAudioCtx();
      const src = ctx.createBufferSource();
      src.buffer = _soundBuffers[name];
      src.connect(ctx.destination);
      src.start();
    } catch(e) {}
    return;
  }
  // Synth-only sounds (no file)
  if (name === 'final_round') {
    _synth(523, 0.18); setTimeout(() => _synth(659, 0.18), 200);
    setTimeout(() => _synth(784, 0.18), 400); setTimeout(() => _synth(1047, 0.5), 600);
  }
}

// ─── Music player ─────────────────────────────────────────────────────────────
let musicEnabled = false;
let _musicQueue = [];
let _musicIdx = 0;
const _musicAudio = new Audio();
_musicAudio.volume = 0.35;

function _initMusic() {
  if (!window.MUSIC_FILES || !MUSIC_FILES.length) return;
  _musicQueue = [...MUSIC_FILES].sort(() => Math.random() - 0.5);
  _musicIdx = 0;
  _musicAudio.addEventListener('ended', () => {
    _musicIdx = (_musicIdx + 1) % _musicQueue.length;
    _loadAndPlayTrack();
  });
}

function _loadAndPlayTrack() {
  if (!musicEnabled || !_musicQueue.length) return;
  _musicAudio.src = `/static/music/${_musicQueue[_musicIdx]}`;
  _musicAudio.play().catch(() => {});
}

// First-click handler: unlock AudioContext and start music if it was enabled
document.addEventListener('click', function _firstGestureHandler() {
  _unlockAudio();
  if (musicEnabled && _musicQueue.length && !_musicAudio.src) {
    _loadAndPlayTrack();
  }
}, { once: true });

// ─── Toast notifications ──────────────────────────────────────────────────────
function showToast(msg, color = '#f59e0b', duration = 4000) {
  const t = document.createElement('div');
  t.className = 'game-toast';
  t.style.borderColor = color;
  t.style.color = color;
  t.textContent = msg;
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add('visible'));
  setTimeout(() => {
    t.classList.remove('visible');
    setTimeout(() => t.remove(), 500);
  }, duration);
}

// Card icon emoji map
// Per-city label offsets [dx, dy] from city dot center.
// Run scripts/label_debug.html to place labels, then paste the output here.
const LABEL_OFFSETS = {
  "Vancouver": [-26, -25],
  "Seattle": [42, -22],
  "Portland": [35, 18],
  "San Francisco": [70, 6],
  "Los Angeles": [-44, 10],
  "Las Vegas": [0, 14],
  "Salt Lake City": [-62, -18],
  "Helena": [6, -53],
  "Calgary": [-9, -24],
  "Winnipeg": [-50, -4],
  "Denver": [42, -20],
  "Omaha": [41, -2],
  "Duluth": [-36, -17],
  "Sault St. Marie": [-24, -43],
  "Kansas City": [-52, -18],
  "Chicago": [27, 9],
  "Saint Louis": [44, 4],
  "Oklahoma City": [-51, -30],
  "Dallas": [-33, -10],
  "Houston": [-47, 0],
  "Little Rock": [53, 5],
  "New Orleans": [4, 10],
  "Nashville": [44, -8],
  "Atlanta": [34, -10],
  "Raleigh": [44, -2],
  "Charleston": [47, -4],
  "Miami": [0, 14],
  "Washington": [44, 5],
  "Pittsburgh": [-48, -3],
  "New York": [45, 2],
  "Boston": [26, 3],
  "Montreal": [42, -17],
  "Toronto": [33, -17],
  "Santa Fe": [-44, -4],
  "Phoenix": [0, 14],
  "El Paso": [-13, 16]
};

// Europe city label offsets — generated by scripts/europe_debug.html
// All default to [0, 14] until refined with the debug tool
const EUROPE_LABEL_OFFSETS = {
  "Edinburgh": [-10, -18],
  "London": [-38, -3],
  "Amsterdam": [-38, -20],
  "Bruxelles": [-29, -23],
  "Dieppe": [-19, 8],
  "Brest": [-20, -6],
  "Paris": [-45, 6],
  "Pamplona": [-43, -21],
  "Madrid": [-29, -2],
  "Lisboa": [28, -4],
  "Cadiz": [0, -21],
  "Barcelona": [-2, 9],
  "Marseille": [8, 15],
  "Essen": [-10, 9],
  "Kobenhavn": [36, 7],
  "Frankfurt": [43, 10],
  "Zurich": [-20, -19],
  "Munchen": [33, -9],
  "Berlin": [-24, -31],
  "Wien": [-29, -14],
  "Venezia": [34, 6],
  "Roma": [-24, 4],
  "Brindisi": [22, -21],
  "Palermo": [-34, -5],
  "Stockholm": [-56, -11],
  "Danzic": [-18, 9],
  "Warszawa": [43, 0],
  "Riga": [25, 9],
  "Petrograd": [32, -15],
  "Wilno": [0, 14],
  "Smolensk": [-32, 4],
  "Moskva": [-29, -11],
  "Kharkov": [-28, -14],
  "Budapest": [39, -14],
  "Zagreb": [32, 2],
  "Sarajevo": [-37, -19],
  "Bucuresti": [40, 0],
  "Sofia": [0, 14],
  "Kyiv": [26, -15],
  "Sevastopol": [-41, -2],
  "Rostov": [-32, 5],
  "Sochi": [-30, 7],
  "Athina": [25, -18],
  "Constantinople": [54, -8],
  "Smyrna": [33, -15],
  "Angora": [-36, -2],
  "Erzurum": [-32, 4],
};

const CARD_ICON = {
  pink: '<span style="display:inline-block;width:0.75em;height:0.75em;border-radius:50%;background:#ec4899;vertical-align:middle;"></span>',
  blue: '🔵', orange: '🟠', white: '⚪',
  green: '🟢', yellow: '🟡', black: '⚫', red: '🔴',
  locomotive: '🚂',
};
const CARD_BG = {
  pink:       'linear-gradient(135deg, #db2777, #9d174d)',
  blue:       'linear-gradient(135deg, #2563eb, #1e3a8a)',
  orange:     'linear-gradient(135deg, #ea580c, #9a3412)',
  white:      'linear-gradient(135deg, #cbd5e1, #94a3b8)',
  green:      'linear-gradient(135deg, #16a34a, #14532d)',
  yellow:     'linear-gradient(135deg, #ca8a04, #713f12)',
  black:      'linear-gradient(135deg, #374151, #111827)',
  red:        'linear-gradient(135deg, #dc2626, #7f1d1d)',
  locomotive: 'linear-gradient(160deg, #ef4444 0%, #f97316 18%, #eab308 38%, #22c55e 58%, #3b82f6 78%, #8b5cf6 100%)',
  unknown:    'linear-gradient(135deg, #1e293b, #0f172a)',
};

// ─── Route graph for ticket path highlight ────────────────────────────────────

function buildRouteGraph() {
  const adj = {};
  for (const route of BOARD_DATA.routes) {
    const a = route.city1, b = route.city2;
    (adj[a] = adj[a] || []).push({ to: b, id: route.id });
    (adj[b] = adj[b] || []).push({ to: a, id: route.id });
  }
  return adj;
}
const ROUTE_GRAPH = buildRouteGraph();

function shortestPath(from, to) {
  const queue = [[from, []]];
  const visited = new Set([from]);
  while (queue.length) {
    const [city, path] = queue.shift();
    for (const edge of (ROUTE_GRAPH[city] || [])) {
      if (visited.has(edge.to)) continue;
      const newPath = [...path, edge.id];
      if (edge.to === to) return newPath;
      visited.add(edge.to);
      queue.push([edge.to, newPath]);
    }
  }
  return [];
}

function highlightPath(routeIds, on) {
  routeIds.forEach(id => {
    document.querySelectorAll(`[data-route-id="${id}"]`).forEach(el => {
      el.classList.toggle('path-highlight', on);
    });
  });
}

// Player color hex map (should match server-side)
const PLAYER_HEX = {
  red: '#EF4444', blue: '#3B82F6', green: '#22C55E',
  yellow: '#EAB308', pink: '#EC4899', orange: '#F97316',
};

// ─── Socket setup ────────────────────────────────────────────────────────────

socket.on('connect', () => {
  socket.emit('register_session');
  if (!IS_SPECTATOR) {
    socket.emit('join_game_room', { code: GAME_CODE });
  }
});

// ─── Spectator entry ──────────────────────────────────────────────────────────
if (IS_SPECTATOR) {
  document.body.classList.add('spectating');
  const modal = document.getElementById('spectator-modal');

  if (SPECTATOR_NAME) {
    // Logged-in user — skip modal, join immediately with their username
    if (modal) modal.classList.add('hidden');
    socket.emit('join_game_room', { code: GAME_CODE, spectator_name: SPECTATOR_NAME });
  } else {
    const input = document.getElementById('spectator-name-input');
    const btn   = document.getElementById('spectator-watch-btn');

    function joinAsSpectator() {
      const name = input.value.trim() || 'Spectator';
      modal.classList.add('hidden');
      socket.emit('join_game_room', { code: GAME_CODE, spectator_name: name });
    }

    btn.addEventListener('click', joinAsSpectator);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') joinAsSpectator(); });
    setTimeout(() => input.focus(), 100);
  }
}

socket.on('spectator_joined', (data) => {
  showToast(`👀 ${escHtml(data.name)} is spectating`, '#94a3b8', 3000);
});

socket.on('player_kicked', (data) => {
  if (String(data.player_id) === String(MY_PLAYER_ID)) {
    window.location.href = '/lobbies';
  }
});

// Kick button delegation (players panel re-renders so use delegation)
document.getElementById('players-panel').addEventListener('click', e => {
  const btn = e.target.closest('.kick-btn');
  if (!btn) return;
  socket.emit('kick_player', { code: GAME_CODE, player_id: parseInt(btn.dataset.pid) });
});

socket.on('game_state', (state) => {
  const newClaimedCount = Object.keys(state.claimed_routes || {}).length;
  // Detect your-turn transition before overwriting gameState
  if (gameState &&
      gameState.current_player_id !== MY_PLAYER_ID &&
      state.current_player_id === MY_PLAYER_ID &&
      (state.phase === 'main' || state.phase === 'final_round')) {
    if (yourTurnSoundEnabled) playSound('your_turn');
    showToast('🎯 Your turn!', '#22c55e', 3000);
  }
  // Play train placement sound only on a successful claim (routes count increased while it was my turn)
  if (gameState && prevCurrentPlayerId === MY_PLAYER_ID && newClaimedCount > prevClaimedCount) {
    playSound('place_trains');
  }
  prevClaimedCount = newClaimedCount;
  prevCurrentPlayerId = state.current_player_id;
  prevPhase = state.phase;
  lastKnownActionLogEntry = (state.action_log || []).slice(-1)[0] || '';

  // Animate my blind draw with the real card color now that the server has told us what it was
  if (pendingBlindDraw !== null) {
    const newHand = state.players?.[MY_PLAYER_ID]?.hand || {};
    let drawnColor = null;
    for (const [color, count] of Object.entries(newHand)) {
      if ((count || 0) > (pendingBlindDraw[color] || 0)) { drawnColor = color; break; }
    }
    const btn = document.getElementById('draw-blind-btn');
    animateCardToElement(btn, 'hand-cards', drawnColor || 'locomotive');
    pendingBlindDraw = null;
  }

  gameState = state;
  if (state.is_host !== undefined) amHost = state.is_host;
  if (state.bot_player_ids) botPlayerIds = state.bot_player_ids;
  if (!myChatName && MY_PLAYER_ID && state.players && state.players[MY_PLAYER_ID]) {
    myChatName = state.players[MY_PLAYER_ID].name;
  }
  renderAll();
});

socket.on('game_state_update', (state) => {
  if (!gameState) return;
  const oldCurrentPlayer = gameState.current_player_id;
  const oldPhase = gameState.phase;

  // Detect 3-loco sweep: all 5 face-up slots changed simultaneously
  const oldFaceUp = gameState.face_up ? [...gameState.face_up] : [];
  const newFaceUp = state.face_up || [];
  const numChanged = oldFaceUp.filter((c, i) => c !== newFaceUp[i]).length;
  const isSweep = numChanged >= 5 && oldFaceUp.length === 5;

  gameState.claimed_routes          = state.claimed_routes;
  // Hold off updating face_up if a sweep is about to animate
  if (!isSweep) gameState.face_up   = state.face_up;
  gameState.deck_count              = state.deck_count;
  gameState.dest_deck_count         = state.dest_deck_count;
  gameState.action_log              = state.action_log;
  gameState.phase                   = state.phase;
  gameState.current_player_id       = state.current_player_id;
  gameState.draw_step               = state.draw_step;
  gameState.scores                  = state.scores;
  gameState.winner_id               = state.winner_id;
  gameState.final_round_players_left = state.final_round_players_left;
  gameState.final_round_triggered_by = state.final_round_triggered_by;
  gameState.has_undo_snapshot = state.has_undo_snapshot;
  // Merge public-only per-player fields without touching hand/tickets
  for (const pid of Object.keys(state.players)) {
    if (gameState.players[pid]) {
      gameState.players[pid].trains        = state.players[pid].trains;
      gameState.players[pid].route_score   = state.players[pid].route_score;
      gameState.players[pid].card_count    = state.players[pid].card_count;
      gameState.players[pid].ticket_count  = state.players[pid].ticket_count;
      if (state.players[pid].station_count !== undefined) {
        gameState.players[pid].station_count = state.players[pid].station_count;
      }
    }
  }
  // Europe-specific top-level fields
  if (state.stations !== undefined) gameState.stations = state.stations;
  if ('pending_tunnel' in state) gameState.pending_tunnel = state.pending_tunnel;

  // Animate other players' draws from action log
  animateFromActionLog(gameState.action_log);

  // Detect transitions
  const newCurrentPlayer = gameState.current_player_id;
  const newPhase = gameState.phase;

  if (newPhase === 'final_round' && oldPhase !== 'final_round') {
    playSound('final_round');
    const triggeredBy = gameState.final_round_triggered_by;
    const triggerer = triggeredBy ? gameState.players[triggeredBy] : null;
    const name = triggerer ? triggerer.name : 'Someone';
    showToast(`⚠️ FINAL ROUND! ${name} has triggered the end. Everyone gets one last turn!`, '#f97316', 7000);
  }

  prevCurrentPlayerId = newCurrentPlayer;
  prevPhase = newPhase;

  if (isSweep) {
    // Block renderFaceUpCards during sweep so OLD cards stay in DOM with their
    // already-painted position — they become our animation "from" state.
    _sweepInProgress = true;
  }

  renderAll();

  if (isSweep) {
    const area = document.getElementById('face-up-cards');
    const cards = [...area.querySelectorAll('.train-card')];

    // Force a layout flush so the browser commits the current painted position
    // of each card before we apply transitions (getBoundingClientRect triggers reflow).
    cards.forEach(c => c.getBoundingClientRect());

    // Slide old cards out to the left
    cards.forEach((card, i) => {
      card.style.transition = `transform 0.28s ease ${i * 0.06}s, opacity 0.28s ease ${i * 0.06}s`;
      card.style.transform = 'translateX(-160px)';
      card.style.opacity = '0';
    });

    const exitDuration = 280 + (cards.length - 1) * 60 + 60;
    setTimeout(() => {
      gameState.face_up = newFaceUp;
      _sweepInProgress = false;
      renderFaceUpCards();

      // Slide new cards in from the right
      area.querySelectorAll('.train-card').forEach((card, i) => {
        card.style.transition = 'none';
        card.style.transform = 'translateX(80px)';
        card.style.opacity = '0';
        // Double rAF ensures browser paints the offset position before animating
        requestAnimationFrame(() => requestAnimationFrame(() => {
          card.style.transition = `transform 0.25s ease ${i * 0.05}s, opacity 0.25s ease ${i * 0.05}s`;
          card.style.transform = '';
          card.style.opacity = '';
        }));
      });
    }, exitDuration);
  }
});

socket.on('error', (data) => {
  showStatus('❌ ' + data.message, '#ef4444');
});

// ─── Card animations ──────────────────────────────────────────────────────────

function animateCardToElement(sourceEl, targetId, color) {
  if (!sourceEl) return;
  const sourceRect = sourceEl.getBoundingClientRect();
  const targetEl = document.getElementById(targetId);
  if (!targetEl) return;
  const targetRect = targetEl.getBoundingClientRect();

  const card = document.createElement('div');
  card.style.cssText = `
    position:fixed;left:${sourceRect.left}px;top:${sourceRect.top}px;
    width:${Math.max(sourceRect.width,28)}px;height:${Math.max(sourceRect.height,18)}px;
    background:${CARD_BG[color] || '#555'};border-radius:5px;
    pointer-events:none;z-index:9999;opacity:0.92;
    box-shadow:0 4px 14px rgba(0,0,0,0.55);
    transition:left .42s cubic-bezier(.25,.46,.45,.94),top .42s cubic-bezier(.25,.46,.45,.94),
               width .42s ease,height .42s ease,opacity .42s ease;`;
  document.body.appendChild(card);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    card.style.left    = (targetRect.left + 6) + 'px';
    card.style.top     = (targetRect.top  + 6) + 'px';
    card.style.width   = '26px';
    card.style.height  = '16px';
    card.style.opacity = '0';
  }));
  setTimeout(() => card.remove(), 600);
}

function animateCardToPlayerRow(playerId, sourceId, color) {
  const sourceEl = document.getElementById(sourceId);
  const targetRow = document.querySelector(`.player-row[data-pid="${playerId}"]`);
  if (!sourceEl || !targetRow) return;

  const sourceRect = sourceEl.getBoundingClientRect();
  const targetRect = targetRow.getBoundingClientRect();

  const card = document.createElement('div');
  card.style.cssText = `
    position:fixed;left:${sourceRect.left + sourceRect.width/2}px;top:${sourceRect.top + sourceRect.height/2}px;
    width:22px;height:14px;
    background:${CARD_BG[color] || '#555'};border-radius:4px;
    pointer-events:none;z-index:9999;opacity:0.85;
    box-shadow:0 3px 10px rgba(0,0,0,0.5);
    transition:left .38s cubic-bezier(.25,.46,.45,.94),top .38s cubic-bezier(.25,.46,.45,.94),opacity .38s ease;`;
  document.body.appendChild(card);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    card.style.left    = (targetRect.left + targetRect.width/2) + 'px';
    card.style.top     = (targetRect.top  + targetRect.height/2) + 'px';
    card.style.opacity = '0';
  }));
  setTimeout(() => {
    card.remove();
    // Flash the player row
    targetRow.classList.add('card-received');
    setTimeout(() => targetRow.classList.remove('card-received'), 500);
  }, 420);
}

function animateFromActionLog(log) {
  if (!log || log.length === 0 || !gameState) return;
  const latest = log[log.length - 1];
  if (latest === lastKnownActionLogEntry) return;
  lastKnownActionLogEntry = latest;

  for (const [pid, player] of Object.entries(gameState.players)) {
    if (pid === MY_PLAYER_ID) continue;
    const name = player.name;
    if (latest.startsWith(name + ' drew face-up ')) {
      const colorStr = latest.slice((name + ' drew face-up ').length).replace('.', '').trim();
      animateCardToPlayerRow(pid, 'face-up-cards', colorStr);
    } else if (latest.startsWith(name + ' drew a blind card')) {
      animateCardToPlayerRow(pid, 'draw-blind-btn', 'unknown');
    }
  }
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function renderAll() {
  if (!gameState) return;
  renderBoard();
  renderPlayersPanel();
  renderFaceUpCards();
  renderHand();
  renderTickets();
  renderActionLog();
  renderStatusBar();
  renderActionButtons();
  if (gameState.phase === 'ended') showGameOver();

  // Europe: tunnel pending for this player → show tunnel modal
  if (gameState.pending_tunnel && gameState.pending_tunnel.player_id === MY_PLAYER_ID) {
    const tunnelModal = document.getElementById('tunnel-modal');
    if (tunnelModal && tunnelModal.classList.contains('hidden')) {
      openTunnelModal(gameState.pending_tunnel);
    }
    return;
  }

  const ticketModal = document.getElementById('ticket-modal');
  if (!ticketModal.classList.contains('hidden')) {
    // If modal is open but pending tickets are gone (e.g. game_state_update raced ahead),
    // close it so the fresh game_state can cleanly re-evaluate.
    if (!hasPendingTickets()) closeModal('ticket-modal');
    return;
  }
  if (hasPendingTickets()) openInitialTicketsModal();
}

// ─── Board SVG ───────────────────────────────────────────────────────────────

let svgInitialized = false;
let boardScale = { x: 1, y: 1, imgX: 0, imgY: 0, imgW: 1024, imgH: 683 };
let stationPlacementMode = false; // Europe: true while player is clicking a city to place station
let stationPlacementCity = null;  // city chosen in placement mode

const MOBILE_BOARD_BASE = 900;  // board width in px at zoom level 1 on mobile
let mobileZoom = 1.0;

function recalcBoardScale() {
  const img = document.getElementById('board-img');
  const container = document.getElementById('board-container');
  if (!img.naturalWidth) return;

  if (window.innerWidth <= 768) {
    // Mobile: fixed-width scrollable board; JS sets img size explicitly
    const boardW = Math.round(MOBILE_BOARD_BASE * mobileZoom);
    const boardH = Math.round(boardW * (img.naturalHeight / img.naturalWidth));
    img.style.width  = boardW + 'px';
    img.style.height = boardH + 'px';
    boardScale = {
      x: boardW / img.naturalWidth,
      y: boardH / img.naturalHeight,
      imgX: 0, imgY: 0,
      imgW: boardW, imgH: boardH,
    };
    return;
  }

  // Desktop: fit-contain within container
  img.style.width  = '';
  img.style.height = '';
  const containerW = container.clientWidth;
  const containerH = container.clientHeight;
  const naturalW = img.naturalWidth;
  const naturalH = img.naturalHeight;

  const scale = Math.min(containerW / naturalW, containerH / naturalH);
  const rendW = naturalW * scale;
  const rendH = naturalH * scale;
  const offX = (containerW - rendW) / 2;
  const offY = (containerH - rendH) / 2;

  boardScale = { x: scale, y: scale, imgX: offX, imgY: offY, imgW: rendW, imgH: rendH };
}

function boardPx(naturalX, naturalY) {
  return {
    x: boardScale.imgX + naturalX * boardScale.x,
    y: boardScale.imgY + naturalY * boardScale.y,
  };
}

function renderBoard() {
  const img = document.getElementById('board-img');
  if (!img.naturalWidth) {
    img.onload = () => renderBoard();
    return;
  }
  recalcBoardScale();

  const svg = document.getElementById('board-svg');
  svg.innerHTML = '';

  // Set SVG viewBox and dimensions to match the board scaling
  const boardNatW = BOARD_DATA.board_w || 1024;
  const boardNatH = BOARD_DATA.board_h || 683;
  svg.setAttribute('viewBox', `0 0 ${boardNatW} ${boardNatH}`);
  svg.setAttribute('width', boardScale.imgW);
  svg.setAttribute('height', boardScale.imgH);
  svg.style.position = 'absolute';
  svg.style.left = boardScale.imgX + 'px';
  svg.style.top = boardScale.imgY + 'px';

  // Drop-shadow filter for claimed segments
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML = `
    <filter id="claimed-shadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="0" stdDeviation="2" flood-color="rgba(0,0,0,0.7)"/>
    </filter>
  `;
  svg.appendChild(defs);

  const cities = BOARD_DATA.cities;
  const routes = BOARD_DATA.routes;
  const claimed = gameState ? gameState.claimed_routes : {};
  const numPlayers = gameState ? gameState.turn_order.length : 6;

  // Draw routes
  for (const route of routes) {
    const c1 = cities[route.city1];
    const c2 = cities[route.city2];
    if (!c1 || !c2) continue;

    const segData = BOARD_DATA.route_segments && BOARD_DATA.route_segments[route.id];
    let segments;

    if (segData && segData.length === route.length) {
      const segW = 30;
      const segH = 8;
      segments = segData.map(([bx, by, segAngle]) => {
        return { x: bx - segW/2, y: by - segH/2, w: segW, h: segH, angle: segAngle, cx: bx, cy: by };
      });
    } else {
      segments = buildRouteSegments(c1, c2, route.length, route.side, route.color);
    }
    const claimedBy = claimed[String(route.id)];

    // In 2-3 player games, if the partner route in a double is claimed, this one is closed
    let isClosed = false;
    if (!claimedBy && route.double_group && numPlayers <= 3) {
      const partnerRoutes = routes.filter(r => r.double_group === route.double_group && r.id !== route.id);
      isClosed = partnerRoutes.some(pr => claimed[String(pr.id)]);
    }

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', seg.x);
      rect.setAttribute('y', seg.y);
      rect.setAttribute('width', seg.w);
      rect.setAttribute('height', seg.h);
      rect.setAttribute('transform', `rotate(${seg.angle}, ${seg.cx}, ${seg.cy})`);
      rect.setAttribute('rx', '2');

      rect.dataset.routeId = route.id;
      rect.addEventListener('mouseenter', () => highlightRoute(route.id));
      rect.addEventListener('mouseleave', () => unhighlightRoute(route.id));

      if (claimedBy) {
        const owner = gameState.players[claimedBy];
        const ownerColor = owner ? PLAYER_HEX[owner.color] : '#888';
        rect.setAttribute('fill', ownerColor);
        rect.setAttribute('stroke', 'rgba(255,255,255,0.75)');
        rect.setAttribute('stroke-width', '1.5');
        rect.setAttribute('filter', 'url(#claimed-shadow)');
        rect.classList.add('route-seg', 'claimed');
      } else if (isClosed) {
        rect.setAttribute('fill', '#2a2522');
        rect.setAttribute('fill-opacity', '0.7');
        rect.setAttribute('stroke', 'rgba(255,0,0,0.25)');
        rect.setAttribute('stroke-width', '1');
        rect.classList.add('route-seg', 'closed');
        // No click handler — closed
      } else {
        const routeColor = route.color === 'gray' ? '#9ca3af' : (BOARD_DATA.card_colors[route.color] || '#888');
        rect.setAttribute('fill', routeColor);
        rect.setAttribute('fill-opacity', '0.55');
        rect.setAttribute('stroke', 'rgba(255,255,255,0.3)');
        rect.setAttribute('stroke-width', '1');
        rect.classList.add('route-seg');
        if (!IS_SPECTATOR) rect.addEventListener('click', () => onRouteClick(route.id));
      }

      svg.appendChild(rect);

      if (claimedBy) {
        // Small center pip to distinguish claimed segments
        const pip = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        pip.setAttribute('cx', seg.cx);
        pip.setAttribute('cy', seg.cy);
        pip.setAttribute('r', '2');
        pip.setAttribute('fill', 'rgba(255,255,255,0.85)');
        pip.setAttribute('pointer-events', 'none');
        svg.appendChild(pip);
      }

      // Tunnel indicator: small diagonal hatch marks on each segment
      if (route.tunnel && !claimedBy && !isClosed) {
        const hatch = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        hatch.setAttribute('x1', seg.cx - 3);
        hatch.setAttribute('y1', seg.cy - 3);
        hatch.setAttribute('x2', seg.cx + 3);
        hatch.setAttribute('y2', seg.cy + 3);
        hatch.setAttribute('stroke', 'rgba(255,255,255,0.5)');
        hatch.setAttribute('stroke-width', '1.5');
        hatch.setAttribute('pointer-events', 'none');
        hatch.setAttribute('transform', `rotate(${seg.angle}, ${seg.cx}, ${seg.cy})`);
        svg.appendChild(hatch);
      }
    }

    // Ferry indicator: loco icon at midpoint of route
    if (route.ferry && !claimedBy && !isClosed && segments.length > 0) {
      const mid = segments[Math.floor(segments.length / 2)];
      const locoText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      locoText.setAttribute('x', mid.cx);
      locoText.setAttribute('y', mid.cy - 8);
      locoText.setAttribute('font-size', '9');
      locoText.setAttribute('fill', '#fff');
      locoText.setAttribute('stroke', '#1a1210');
      locoText.setAttribute('stroke-width', '2');
      locoText.setAttribute('paint-order', 'stroke');
      locoText.setAttribute('text-anchor', 'middle');
      locoText.setAttribute('dominant-baseline', 'middle');
      locoText.setAttribute('pointer-events', 'none');
      locoText.textContent = '🚂×' + route.ferry;
      svg.appendChild(locoText);
    }
  }

  // Build station lookup: city → player color
  const stationsByCity = {};
  if (gameState && gameState.stations) {
    for (const [pid, cityList] of Object.entries(gameState.stations)) {
      const owner = gameState.players[pid];
      for (const c of (cityList || [])) {
        stationsByCity[c] = owner ? PLAYER_HEX[owner.color] : '#888';
      }
    }
  }

  // Draw city circles
  for (const [cityName, coords] of Object.entries(cities)) {
    // Station marker (drawn under city dot)
    if (stationsByCity[cityName]) {
      const sColor = stationsByCity[cityName];
      const sRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      sRect.setAttribute('x', coords[0] - 7);
      sRect.setAttribute('y', coords[1] - 7);
      sRect.setAttribute('width', 14);
      sRect.setAttribute('height', 14);
      sRect.setAttribute('rx', 3);
      sRect.setAttribute('fill', sColor);
      sRect.setAttribute('stroke', '#fff');
      sRect.setAttribute('stroke-width', 1.5);
      sRect.setAttribute('opacity', '0.88');
      sRect.setAttribute('pointer-events', 'none');
      svg.appendChild(sRect);
    }

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', coords[0]);
    circle.setAttribute('cy', coords[1]);
    circle.setAttribute('r', 5);
    circle.setAttribute('fill', '#1a1512');
    circle.setAttribute('stroke', '#c8a84b');
    circle.setAttribute('stroke-width', 1.5);
    circle.classList.add('city-circle');
    circle.dataset.city = cityName;
    if (stationPlacementMode && !IS_SPECTATOR) {
      circle.style.cursor = 'crosshair';
      circle.addEventListener('click', (e) => {
        e.stopPropagation();
        onCityClickForStation(cityName);
      });
    }
    svg.appendChild(circle);

    const labelFontSize = 11;
    const offsetMap = BOARD_DATA.map === 'europe' ? EUROPE_LABEL_OFFSETS : LABEL_OFFSETS;
    const [ldx, ldy] = offsetMap[cityName] || [0, 14];
    const labelX = coords[0] + ldx;
    const labelY = coords[1] + ldy;
    // Semi-transparent pill behind label so text is readable over routes
    const estLabelW = cityName.length * 6.4;
    const labelBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    labelBg.setAttribute('x', labelX - estLabelW / 2 - 2);
    labelBg.setAttribute('y', labelY - 1);
    labelBg.setAttribute('width', estLabelW + 4);
    labelBg.setAttribute('height', labelFontSize + 3);
    labelBg.setAttribute('fill', 'rgba(10, 7, 4, 0.58)');
    labelBg.setAttribute('rx', '2');
    labelBg.style.pointerEvents = 'none';
    svg.appendChild(labelBg);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', labelX);
    text.setAttribute('y', labelY);
    text.setAttribute('font-size', labelFontSize);
    text.setAttribute('fill', '#f0e8d0');
    text.setAttribute('stroke', '#1a1210');
    text.setAttribute('stroke-width', '1.5');
    text.setAttribute('paint-order', 'stroke');
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'hanging');
    text.style.fontFamily = 'Cinzel, serif';
    text.style.pointerEvents = 'none';
    text.textContent = cityName;
    svg.appendChild(text);
  }
}

function buildRouteSegments(p1, p2, length, side, color) {
  // p1 and p2 are [x, y] arrays in board space (1024x683)
  const dx = p2[0] - p1[0];
  const dy = p2[1] - p1[1];
  const dist = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * 180 / Math.PI;

  const segW = (dist / length) * 0.78;
  const segH = 8;
  const gap = (dist / length) * 0.22;

  // Perpendicular offset for double routes
  const perpX = -dy / dist;
  const perpY = dx / dist;
  const offsetDist = side === 0 ? -4 : 4;
  const offX = perpX * offsetDist;
  const offY = perpY * offsetDist;

  const segments = [];
  for (let i = 0; i < length; i++) {
    const t = (i + 0.5) / length;
    const cx = p1[0] + dx * t + offX;
    const cy = p1[1] + dy * t + offY;
    segments.push({
      x: cx - segW / 2,
      y: cy - segH / 2,
      w: segW,
      h: segH,
      angle,
      cx,
      cy,
    });
  }
  return segments;
}

// ─── Players panel ───────────────────────────────────────────────────────────

function renderPlayersPanel() {
  const panel = document.getElementById('players-panel');
  if (!gameState) return;
  const order = gameState.turn_order;
  panel.innerHTML = order.map(pid => {
    const p = gameState.players[pid];
    if (!p) return '';
    const isActive = pid === gameState.current_player_id;
    const isMe = pid === MY_PLAYER_ID;
    const isBot = botPlayerIds.includes(pid);
    const canKick = amHost && !isMe && !IS_SPECTATOR;
    const stationBadge = '';
    return `<div class="player-row ${isActive ? 'active-turn' : ''}" data-pid="${pid}">
      <div class="player-color-dot" style="background:${PLAYER_HEX[p.color]};box-shadow:0 0 5px ${PLAYER_HEX[p.color]};"></div>
      <span class="player-row-name">${escHtml(p.name)}${isMe ? ' <span style="color:var(--gold);font-size:0.65rem;">(you)</span>' : ''}${isBot ? ' <span style="color:var(--text-muted);font-size:0.65rem;">(bot)</span>' : ''}${canKick ? ` <button class="kick-btn" data-pid="${pid}" title="Kick player">✕</button>` : ''}${stationBadge}</span>
      <span class="player-row-score">${p.route_score}</span>
      <span class="player-row-trains">🚂${p.trains}</span>
      <span class="player-row-tickets">🎫${p.ticket_count ?? 0}</span>
      <span class="player-card-count">🎴${p.card_count ?? '?'}</span>
    </div>`;
  }).join('');
}

// ─── Face-up cards ───────────────────────────────────────────────────────────

function renderFaceUpCards() {
  if (!gameState || _sweepInProgress) return;
  const area = document.getElementById('face-up-cards');
  const faceUp = gameState.face_up || [];
  area.innerHTML = faceUp.map((color, i) => {
    if (!color) return `<div class="train-card" style="background:#222;border-style:dashed;"></div>`;
    const label = color === 'locomotive' ? 'LOCO' : color.toUpperCase();
    return `<div class="train-card" style="background:${CARD_BG[color] || '#444'};"
                 data-slot="${i}" data-color="${color}" title="${color}">
              <span class="card-train-emoji">🚂</span>
              <div class="card-label">${label}</div>
            </div>`;
  }).join('');

  area.querySelectorAll('.train-card[data-slot]').forEach(card => {
    card.addEventListener('click', () => {
      const slot = parseInt(card.dataset.slot);
      onDrawFaceUp(slot, card);
    });
  });

  document.getElementById('deck-count').textContent = gameState.deck_count || 0;
}

// ─── Hand ────────────────────────────────────────────────────────────────────

function renderHand() {
  if (!gameState) return;
  const me = gameState.players[MY_PLAYER_ID];
  if (!me) return;
  const hand = me.hand || {};
  const area = document.getElementById('hand-cards');
  const colorOrder = ['red','blue','green','yellow','orange','pink','black','white','locomotive'];
  area.innerHTML = colorOrder
    .filter(c => hand[c] > 0)
    .map(c => `
      <div class="hand-card-chip" style="background:${CARD_BG[c]};"
           data-color="${c}">
        <span class="chip-icon">${CARD_ICON[c] ?? '🚂'}</span>
        <span class="chip-count">${hand[c]}</span>
        <span class="chip-name">${c === 'locomotive' ? 'LOCOMOTIVE' : c.toUpperCase()}</span>
      </div>`)
    .join('');
}

// ─── Tickets ─────────────────────────────────────────────────────────────────

function isTicketCompleted(ticket) {
  if (!gameState || !ticket) return false;
  const adj = {};
  for (const [ridStr, pid] of Object.entries(gameState.claimed_routes)) {
    if (pid !== MY_PLAYER_ID) continue;
    const route = BOARD_DATA.routes.find(r => r.id === parseInt(ridStr));
    if (!route) continue;
    (adj[route.city1] = adj[route.city1] || []).push(route.city2);
    (adj[route.city2] = adj[route.city2] || []).push(route.city1);
  }
  const visited = new Set();
  const queue = [ticket.city1];
  while (queue.length) {
    const city = queue.shift();
    if (city === ticket.city2) return true;
    if (visited.has(city)) continue;
    visited.add(city);
    for (const next of (adj[city] || [])) {
      if (!visited.has(next)) queue.push(next);
    }
  }
  return false;
}

function highlightTicketCities(city1, city2, on) {
  document.querySelectorAll('#board-svg .city-circle').forEach(c => {
    if (c.dataset.city === city1 || c.dataset.city === city2) {
      c.classList.toggle('city-highlight', on);
    }
  });
}

function renderTickets() {
  if (!gameState) return;
  const me = gameState.players[MY_PLAYER_ID];
  if (!me) return;
  const area = document.getElementById('tickets-panel');

  if (!me.tickets || me.tickets.length === 0) {
    area.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">No tickets yet.</div>';
    return;
  }

  area.innerHTML = '';
  // Sort: incomplete first, completed at the bottom
  const sorted = [...me.tickets].sort((a, b) => {
    const ta = getTicketById(a), tb = getTicketById(b);
    const ca = ta ? isTicketCompleted(ta) : false;
    const cb = tb ? isTicketCompleted(tb) : false;
    return ca - cb;
  });
  const longTicketId = me.long_ticket_id;
  sorted.forEach(tid => {
    const t = getTicketById(tid);
    if (!t) return;
    const completed = isTicketCompleted(t);
    const isLong = tid === longTicketId;
    const div = document.createElement('div');
    div.className = 'ticket-item' + (completed ? ' completed' : '') + (isLong ? ' long-ticket' : '');
    div.innerHTML = `
      <div class="ticket-cities">
        ${escHtml(t.city1)} <span style="color:var(--text-muted);">→</span> ${escHtml(t.city2)}
        ${completed ? '<span class="ticket-check">✓</span>' : ''}
      </div>
      <div class="ticket-points">${t.points} pts</div>`;
    const pathIds = shortestPath(t.city1, t.city2);
    div.addEventListener('mouseenter', () => {
      highlightTicketCities(t.city1, t.city2, true);
      highlightPath(pathIds, true);
    });
    div.addEventListener('mouseleave', () => {
      highlightTicketCities(t.city1, t.city2, false);
      highlightPath(pathIds, false);
    });
    area.appendChild(div);
  });
}

// ─── Action log ──────────────────────────────────────────────────────────────

function renderActionLog() {
  if (!gameState) return;
  const el = document.getElementById('action-log');
  const log = gameState.action_log || [];
  el.innerHTML = log.map(l => `<p>${escHtml(l)}</p>`).join('');
  el.scrollTop = el.scrollHeight;
  const label = document.getElementById('action-log-label');
  if (label && gameState.round_number) {
    label.textContent = `ACTION LOG — Round ${gameState.round_number}`;
  }
}

// ─── Status bar ──────────────────────────────────────────────────────────────

function renderStatusBar() {
  if (!gameState) return;
  const bar = document.getElementById('status-bar');
  const cur = gameState.players[gameState.current_player_id];
  const isMyTurn = gameState.current_player_id === MY_PLAYER_ID;
  const phase = gameState.phase;

  if (phase === 'initial_tickets') {
    const me = gameState.players[MY_PLAYER_ID];
    if (me && me.pending_tickets && me.pending_tickets.length > 0) {
      bar.textContent = '⬆ Choose your starting destination tickets (keep at least 2)';
      bar.style.color = '#f59e0b';
    } else {
      bar.textContent = `Waiting for players to choose tickets…`;
      bar.style.color = 'var(--text-muted)';
    }
    return;
  }

  if (phase === 'ended') {
    bar.innerHTML = '🏁 Game over! &nbsp;<button id="reopen-results-btn" style="background:none;border:1px solid var(--gold);border-radius:4px;color:var(--gold);font-family:\'Cinzel\',serif;font-size:0.7rem;letter-spacing:0.06em;padding:0.1rem 0.5rem;cursor:pointer;">View Results</button>';
    bar.style.color = 'var(--gold-light)';
    document.getElementById('reopen-results-btn').addEventListener('click', () => {
      _gameOverDismissed = false;
      showGameOver();
    });
    return;
  }

  if (phase === 'final_round') {
    if (isMyTurn) {
      bar.textContent = '⚠️ FINAL ROUND — Your last turn!';
      bar.style.color = '#f97316';
    } else {
      bar.textContent = `Final round — waiting for ${cur ? cur.name : '…'}`;
      bar.style.color = 'var(--text-muted)';
    }
    return;
  }

  if (isMyTurn) {
    if (stationPlacementMode) {
      bar.textContent = '🏙 Click a city on the board to place your station (Esc to cancel)';
      bar.style.color = '#f59e0b';
    } else if (gameState.draw_step === 1) {
      bar.textContent = '🃏 Draw your second card (or click deck)';
      bar.style.color = '#22c55e';
    } else {
      bar.textContent = '✅ Your turn — draw cards, claim a route, or draw tickets';
      bar.style.color = '#22c55e';
    }
  } else {
    bar.textContent = `⏳ Waiting for ${cur ? cur.name : '…'} to play…`;
    bar.style.color = 'var(--text-muted)';
  }
}

function renderActionButtons() {
  if (!gameState || IS_SPECTATOR) return;
  const isMyTurn = gameState.current_player_id === MY_PLAYER_ID;
  const drawingCards = gameState.draw_step > 0;
  const btn = document.getElementById('draw-tickets-btn');
  btn.disabled = !isMyTurn || drawingCards;
  btn.classList.toggle('active-turn', isMyTurn && !drawingCards);
  document.getElementById('dest-count').textContent = gameState.dest_deck_count || 0;

  const blindBtn = document.getElementById('draw-blind-btn');
  blindBtn.disabled = !isMyTurn;
  blindBtn.classList.toggle('active-turn', isMyTurn);

  // Europe: station placement button
  const stationBtn = document.getElementById('place-station-btn');
  if (stationBtn) {
    const me = gameState.players[MY_PLAYER_ID];
    const hasStations = me && (me.station_count > 0);
    const canPlaceStation = isMyTurn && !drawingCards && hasStations &&
      (gameState.phase === 'main' || gameState.phase === 'final_round') &&
      !gameState.pending_tunnel;
    stationBtn.disabled = !canPlaceStation;
    stationBtn.classList.toggle('active-turn', canPlaceStation);
    if (me && document.getElementById('station-count-badge')) {
      document.getElementById('station-count-badge').textContent = me.station_count ?? 3;
    }
    // If it's no longer our turn, cancel placement mode
    if (!isMyTurn && stationPlacementMode) exitStationPlacementMode();
  }

  // Undo button — visible when a snapshot exists, it's your turn, and no vote pending
  let undoBtn = document.getElementById('undo-action-btn');
  const hasUndo = gameState.has_undo_snapshot && isMyTurn &&
    (gameState.phase === 'main' || gameState.phase === 'final_round');
  if (hasUndo && !undoBtn) {
    undoBtn = document.createElement('button');
    undoBtn.id = 'undo-action-btn';
    undoBtn.className = 'action-btn';
    undoBtn.title = 'Request to undo last action (all players must approve)';
    undoBtn.textContent = '↩ Request Undo';
    undoBtn.addEventListener('click', () => socket.emit('request_undo', { code: GAME_CODE }));
    document.getElementById('draw-tickets-btn').parentElement.appendChild(undoBtn);
  } else if (!hasUndo && undoBtn) {
    undoBtn.remove();
  }
}

// ─── Actions ─────────────────────────────────────────────────────────────────

function onDrawFaceUp(slot, sourceEl) {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  if (gameState.phase !== 'main' && gameState.phase !== 'final_round') return;
  const color = gameState.face_up[slot];
  if (color && sourceEl) animateCardToElement(sourceEl, 'hand-cards', color);
  playSound('draw_card');
  socket.emit('draw_face_up', { code: GAME_CODE, slot });
}

document.getElementById('draw-blind-btn').addEventListener('click', () => {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  // Snapshot current hand so we can diff against the server's response to find the drawn color
  const me = gameState.players?.[MY_PLAYER_ID];
  pendingBlindDraw = { ...(me?.hand || {}) };
  playSound('draw_card');
  socket.emit('draw_blind', { code: GAME_CODE });
});

document.getElementById('draw-tickets-btn').addEventListener('click', () => {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  if (gameState.draw_step !== 0) return;
  socket.emit('draw_destination_tickets', { code: GAME_CODE });
});

// ─── Route hover highlight ────────────────────────────────────────────────────

function highlightRoute(routeId) {
  document.querySelectorAll(`[data-route-id="${routeId}"]`).forEach(el => {
    el.classList.add('route-hover');
  });
}

function unhighlightRoute(routeId) {
  document.querySelectorAll(`[data-route-id="${routeId}"]`).forEach(el => {
    el.classList.remove('route-hover');
  });
}

// ─── Route click → claim modal ───────────────────────────────────────────────

function onRouteClick(routeId) {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  if (gameState.draw_step !== 0) {
    showStatus('Finish drawing cards first.', '#f97316');
    return;
  }
  if (gameState.phase !== 'main' && gameState.phase !== 'final_round') return;
  if (gameState.claimed_routes[String(routeId)]) return;

  const route = BOARD_DATA.routes.find(r => r.id === routeId);
  if (!route) return;

  // Guard against closed double routes (2-3 player games)
  if (route.double_group && gameState.turn_order.length <= 3) {
    const partnerRoutes = BOARD_DATA.routes.filter(r => r.double_group === route.double_group && r.id !== route.id);
    if (partnerRoutes.some(pr => gameState.claimed_routes[String(pr.id)])) {
      showStatus('This route is closed in 2-3 player games.', '#ef4444');
      return;
    }
  }

  pendingRouteId = routeId;
  openClaimModal(route);
}

function openClaimModal(route) {
  const me = gameState.players[MY_PLAYER_ID];
  const hand = me ? me.hand : {};

  const info = document.getElementById('claim-info');
  info.innerHTML = `<strong>${escHtml(route.city1)}</strong> → <strong>${escHtml(route.city2)}</strong> &nbsp;|&nbsp;
    Length: <strong>${route.length}</strong> &nbsp;|&nbsp;
    Color: <strong style="color:${route.color === 'gray' ? '#9ca3af' : BOARD_DATA.card_colors[route.color]}">${route.color.toUpperCase()}</strong>`;

  // Fixed grid of all 9 card types so layout never shifts
  const selector = document.getElementById('card-selector');
  const colorOrder = ['red','blue','green','yellow','orange','pink','black','white','locomotive'];
  selector.innerHTML = '';
  let selectedCombo = {};

  function refreshSelector() {
    // Update each chip in-place to avoid DOM reorder / layout shift
    colorOrder.forEach(color => {
      const inHand = hand[color] || 0;
      const sel = selectedCombo[color] || 0;
      let chip = selector.querySelector(`.csel-chip[data-color="${color}"]`);
      if (!chip) {
        chip = document.createElement('div');
        chip.dataset.color = color;
        chip.className = 'csel-chip';
        chip.style.background = CARD_BG[color];
        chip.innerHTML = `<span class="csel-chip-count"></span><span class="csel-chip-name">${color === 'locomotive' ? 'LOCO' : color.toUpperCase()}</span>`;
        chip.addEventListener('click', () => {
          if (inHand === 0) return;
          const cur = selectedCombo[color] || 0;
          selectedCombo[color] = cur < inHand ? cur + 1 : 0;
          if (selectedCombo[color] === 0) delete selectedCombo[color];
          refreshSelector();
        });
        selector.appendChild(chip);
      }
      chip.querySelector('.csel-chip-count').textContent = `${sel}/${inHand}`;
      chip.classList.toggle('selected', sel > 0);
      chip.classList.toggle('empty', inHand === 0);
      chip.style.cursor = inHand > 0 ? 'pointer' : 'default';
    });
  }
  refreshSelector();

  // Confirm button
  document.getElementById('claim-confirm-btn').onclick = () => {
    socket.emit('claim_route', {
      code: GAME_CODE,
      route_id: pendingRouteId,
      cards: selectedCombo,
    });
    closeModal('claim-modal');
  };

  openModal('claim-modal');
}

document.getElementById('claim-cancel-btn').addEventListener('click', () => closeModal('claim-modal'));
document.querySelector('#claim-modal .modal-backdrop').addEventListener('click', () => closeModal('claim-modal'));

// ─── Tunnel modal (Europe) ────────────────────────────────────────────────────

function openTunnelModal(pt) {
  if (!pt) return;
  const route = BOARD_DATA.routes.find(r => r.id === pt.route_id);
  const routeLabel = route ? `${route.city1} → ${route.city2}` : 'tunnel route';

  document.getElementById('tunnel-modal-desc').textContent =
    `You're claiming the tunnel ${routeLabel}. Three cards were revealed:`;

  // Show revealed cards
  const revealedEl = document.getElementById('tunnel-revealed-cards');
  revealedEl.innerHTML = (pt.revealed || []).map(color => `
    <div class="train-card" style="background:${CARD_BG[color] || '#444'};width:54px;height:36px;font-size:0.7rem;display:inline-flex;flex-direction:column;align-items:center;justify-content:center;border-radius:6px;border:1px solid rgba(255,255,255,0.18);">
      <span>🚂</span>
      <div style="font-size:0.6rem;font-weight:600;">${color === 'locomotive' ? 'LOCO' : color.toUpperCase()}</div>
    </div>`).join('');

  const extraSection = document.getElementById('tunnel-extra-section');
  const proceedBtn = document.getElementById('tunnel-proceed-btn');
  let selectedExtra = {};

  if (pt.extra_cost === 0) {
    // No extra cost — proceed immediately or abort
    extraSection.classList.add('hidden');
    document.getElementById('tunnel-extra-desc').textContent = '';
    proceedBtn.disabled = false;
    proceedBtn.onclick = () => {
      socket.emit('resolve_tunnel', { code: GAME_CODE, proceed: true, extra_cards: {} });
      closeModal('tunnel-modal');
    };
  } else {
    // Show extra card selector
    extraSection.classList.remove('hidden');
    const colorLabel = pt.extra_color === 'locomotive' ? 'locomotive' : `${pt.extra_color} or locomotive`;
    document.getElementById('tunnel-extra-desc').textContent =
      `Pay ${pt.extra_cost} extra card(s) (${colorLabel}) to claim, or abort and lose your turn.`;

    const selector = document.getElementById('tunnel-extra-selector');
    selector.innerHTML = '';
    const me = gameState.players[MY_PLAYER_ID];
    const hand = me ? me.hand : {};

    // Only show eligible colors
    const eligibleColors = ['red','blue','green','yellow','orange','pink','black','white','locomotive']
      .filter(c => (c === pt.extra_color || c === 'locomotive') && (hand[c] || 0) > 0);

    function refreshExtraSelector() {
      eligibleColors.forEach(color => {
        const inHand = hand[color] || 0;
        const sel = selectedExtra[color] || 0;
        let chip = selector.querySelector(`.csel-chip[data-color="${color}"]`);
        if (!chip) {
          chip = document.createElement('div');
          chip.dataset.color = color;
          chip.className = 'csel-chip';
          chip.style.background = CARD_BG[color];
          chip.innerHTML = `<span class="csel-chip-count"></span><span class="csel-chip-name">${color === 'locomotive' ? 'LOCO' : color.toUpperCase()}</span>`;
          chip.addEventListener('click', () => {
            const cur = selectedExtra[color] || 0;
            selectedExtra[color] = cur < inHand ? cur + 1 : 0;
            if (selectedExtra[color] === 0) delete selectedExtra[color];
            refreshExtraSelector();
          });
          selector.appendChild(chip);
        }
        chip.querySelector('.csel-chip-count').textContent = `${sel}/${inHand}`;
        chip.classList.toggle('selected', sel > 0);
        chip.classList.toggle('empty', inHand === 0);
        const total = Object.values(selectedExtra).reduce((a, b) => a + b, 0);
        proceedBtn.disabled = total !== pt.extra_cost;
      });
    }
    if (eligibleColors.length === 0) {
      selector.innerHTML = '<p style="color:var(--text-muted);font-size:0.8rem;">No eligible cards to pay extra cost.</p>';
      proceedBtn.disabled = true;
    } else {
      refreshExtraSelector();
    }

    proceedBtn.onclick = () => {
      const total = Object.values(selectedExtra).reduce((a, b) => a + b, 0);
      if (total !== pt.extra_cost) return;
      socket.emit('resolve_tunnel', { code: GAME_CODE, proceed: true, extra_cards: selectedExtra });
      closeModal('tunnel-modal');
    };
  }

  openModal('tunnel-modal');
}

const tunnelAbortBtn = document.getElementById('tunnel-abort-btn');
if (tunnelAbortBtn) {
  tunnelAbortBtn.addEventListener('click', () => {
    socket.emit('resolve_tunnel', { code: GAME_CODE, proceed: false, extra_cards: {} });
    closeModal('tunnel-modal');
  });
}
document.querySelector('#tunnel-modal .modal-backdrop')?.addEventListener('click', () => {
  // Clicking backdrop = abort
  socket.emit('resolve_tunnel', { code: GAME_CODE, proceed: false, extra_cards: {} });
  closeModal('tunnel-modal');
});

// ─── Station placement mode (Europe) ─────────────────────────────────────────

function enterStationPlacementMode() {
  stationPlacementMode = true;
  stationPlacementCity = null;
  showStatus('🏙 Click a city on the board to place your station.', '#f59e0b');
  renderBoard(); // re-render so city circles get crosshair cursor
  const btn = document.getElementById('place-station-btn');
  if (btn) btn.classList.add('active');
}

function exitStationPlacementMode() {
  stationPlacementMode = false;
  stationPlacementCity = null;
  renderBoard();
  const btn = document.getElementById('place-station-btn');
  if (btn) btn.classList.remove('active');
}

function onCityClickForStation(cityName) {
  if (!stationPlacementMode) return;
  stationPlacementCity = cityName;
  openStationModal(cityName);
}

function openStationModal(cityName) {
  const me = gameState ? gameState.players[MY_PLAYER_ID] : null;
  if (!me) return;

  const stationsPlaced = (gameState.stations && gameState.stations[MY_PLAYER_ID])
    ? gameState.stations[MY_PLAYER_ID].length : 0;
  const cost = stationsPlaced + 1;

  document.getElementById('station-city-display').textContent = `City: ${cityName}`;
  document.getElementById('station-modal-desc').textContent =
    `Place station in ${cityName}. Cost: ${cost} card(s) of the same color.`;

  const hand = me.hand || {};
  const selector = document.getElementById('station-card-selector');
  selector.innerHTML = '';
  let selectedCards = {};

  const colorOrder = ['red','blue','green','yellow','orange','pink','black','white','locomotive'];

  function refreshStationSelector() {
    colorOrder.forEach(color => {
      const inHand = hand[color] || 0;
      if (inHand === 0) {
        const existing = selector.querySelector(`.csel-chip[data-color="${color}"]`);
        if (existing) existing.remove();
        return;
      }
      const sel = selectedCards[color] || 0;
      let chip = selector.querySelector(`.csel-chip[data-color="${color}"]`);
      if (!chip) {
        chip = document.createElement('div');
        chip.dataset.color = color;
        chip.className = 'csel-chip';
        chip.style.background = CARD_BG[color];
        chip.innerHTML = `<span class="csel-chip-count"></span><span class="csel-chip-name">${color === 'locomotive' ? 'LOCO' : color.toUpperCase()}</span>`;
        chip.addEventListener('click', () => {
          const cur = selectedCards[color] || 0;
          selectedCards[color] = cur < inHand ? cur + 1 : 0;
          if (selectedCards[color] === 0) delete selectedCards[color];
          refreshStationSelector();
        });
        selector.appendChild(chip);
      }
      chip.querySelector('.csel-chip-count').textContent = `${sel}/${inHand}`;
      chip.classList.toggle('selected', sel > 0);
      const total = Object.values(selectedCards).reduce((a, b) => a + b, 0);
      const confirmBtn = document.getElementById('station-confirm-btn');
      confirmBtn.disabled = total !== cost;
    });
    const total = Object.values(selectedCards).reduce((a, b) => a + b, 0);
    document.getElementById('station-confirm-btn').disabled = total !== cost;
  }
  refreshStationSelector();

  document.getElementById('station-confirm-btn').onclick = () => {
    socket.emit('place_station', { code: GAME_CODE, city: stationPlacementCity, cards: selectedCards });
    closeModal('station-modal');
    exitStationPlacementMode();
  };

  openModal('station-modal');
}

const stationCancelBtn = document.getElementById('station-cancel-btn');
if (stationCancelBtn) {
  stationCancelBtn.addEventListener('click', () => {
    closeModal('station-modal');
    exitStationPlacementMode();
  });
}
document.getElementById('station-backdrop')?.addEventListener('click', () => {
  closeModal('station-modal');
  exitStationPlacementMode();
});

const placeStationBtn = document.getElementById('place-station-btn');
if (placeStationBtn) {
  placeStationBtn.addEventListener('click', () => {
    if (!gameState || IS_SPECTATOR) return;
    if (stationPlacementMode) {
      exitStationPlacementMode();
    } else {
      enterStationPlacementMode();
    }
  });
}

// ─── Ticket selection modal ───────────────────────────────────────────────────

function hasPendingTickets() {
  if (!gameState) return false;
  const me = gameState.players[MY_PLAYER_ID];
  return me && me.pending_tickets && me.pending_tickets.length > 0;
}

function openInitialTicketsModal() {
  if (!gameState) return;
  const me = gameState.players[MY_PLAYER_ID];
  if (!me || !me.pending_tickets || me.pending_tickets.length === 0) return;

  const isInitial = gameState.phase === 'initial_tickets';
  const isEurope = BOARD_DATA.map === 'europe';
  const minKeep = isInitial ? 2 : 1;

  document.getElementById('ticket-modal-title').textContent =
    isInitial ? 'Choose Your Starting Tickets' : 'Keep Destination Tickets';

  let descText = `Choose which tickets to keep (minimum ${minKeep}).`;
  if (isInitial && isEurope && me.long_ticket_id) {
    const longT = getTicketById(me.long_ticket_id);
    const longName = longT ? `${longT.city1} → ${longT.city2} (${longT.points} pts)` : 'long ticket';
    descText = `Your long ticket has been auto-kept: ${longName}. Keep at least ${minKeep} of the 3 short tickets below.`;
  }
  document.getElementById('ticket-modal-desc').textContent = descText;

  const tickets = me.pending_tickets;
  let selected = new Set();  // default: none selected

  function refreshTicketChoices() {
    const choicesEl = document.getElementById('ticket-choices');
    choicesEl.innerHTML = tickets.map(t => `
      <label class="ticket-choice ${selected.has(t.id) ? 'selected' : ''}" data-id="${t.id}">
        <div class="ticket-choice-check">${selected.has(t.id) ? '✓' : ''}</div>
        <div class="ticket-choice-info">
          <div class="ticket-choice-route">${escHtml(t.city1)} <span>→</span> ${escHtml(t.city2)}</div>
        </div>
        <div class="ticket-choice-pts">${t.points} pts</div>
      </label>`).join('');

    choicesEl.querySelectorAll('.ticket-choice').forEach(el => {
      el.addEventListener('click', () => {
        const id = parseInt(el.dataset.id);
        if (selected.has(id)) {
          selected.delete(id);
        } else {
          selected.add(id);
        }
        refreshTicketChoices();
      });
    });
    const confirmBtn = document.getElementById('ticket-confirm-btn');
    confirmBtn.disabled = selected.size < minKeep;
    confirmBtn.style.opacity = selected.size < minKeep ? '0.45' : '1';
  }
  refreshTicketChoices();

  document.getElementById('ticket-confirm-btn').onclick = () => {
    const keepIds = [...selected];
    if (isInitial) {
      socket.emit('keep_initial_tickets', { code: GAME_CODE, keep_ids: keepIds });
    } else {
      socket.emit('keep_drawn_tickets', { code: GAME_CODE, keep_ids: keepIds });
    }
    closeModal('ticket-modal');
  };

  openModal('ticket-modal');
}

// (ticket modal opening handled in renderAll above)

// ─── Game over ────────────────────────────────────────────────────────────────

function showGameOver() {
  if (!gameState || !gameState.scores) return;
  if (!_gameOverSoundPlayed) {
    _gameOverSoundPlayed = true;
    playSound(gameState.winner_id === MY_PLAYER_ID ? 'win' : 'lose');
  }
  const scores = gameState.scores;
  const winnerId = gameState.winner_id;

  const sorted = Object.entries(scores).sort((a, b) => b[1].total - a[1].total);
  const finalEl = document.getElementById('final-scores');
  finalEl.innerHTML = sorted.map(([pid, s], i) => {
    const isWinner = pid === winnerId;
    const longestBonus = s.longest_path_bonus ? ` +10 🏆` : '';
    const stationBonus = s.station_bonus ? ` | Stations: +${s.station_bonus}` : '';
    return `<div class="score-row ${isWinner ? 'winner' : ''}">
      <div class="score-row-place">${['🥇','🥈','🥉','4','5'][i]}</div>
      <div style="flex:1">
        <div class="score-row-name">
          <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${PLAYER_HEX[s.color]};margin-right:6px;"></span>
          ${escHtml(s.name)}
        </div>
        <div class="score-row-detail">Routes: ${s.route_score} | Longest path: ${s.longest_path}${longestBonus} | Destinations: ${s.tickets && s.tickets.length ? (s.tickets.reduce((sum, t) => sum + t.delta, 0) >= 0 ? '+' : '') + s.tickets.reduce((sum, t) => sum + t.delta, 0) : 0}${stationBonus}</div>
        <div class="score-row-detail">${formatTickets(s.tickets)}</div>
      </div>
      <div class="score-row-total">${s.total}</div>
    </div>`;
  }).join('');

  // Inject rematch button for host (only once)
  const rematchContainer = document.getElementById('rematch-btn-container');
  if (rematchContainer && !rematchContainer.querySelector('.rematch-btn') &&
      !IS_SPECTATOR && gameState.players[MY_PLAYER_ID]?.is_host) {
    const btn = document.createElement('button');
    btn.className = 'btn-secondary rematch-btn';
    btn.textContent = '🔄 Rematch';
    btn.onclick = () => socket.emit('rematch', { code: GAME_CODE });
    rematchContainer.appendChild(btn);
  }

  if (!_gameOverDismissed) openModal('gameover-modal');
}

socket.on('rematch_created', data => {
  window.location.href = '/lobby/' + data.new_code;
});

document.getElementById('gameover-close-btn').addEventListener('click', () => {
  _gameOverDismissed = true;
  closeModal('gameover-modal');
});
document.getElementById('gameover-backdrop').addEventListener('click', () => {
  _gameOverDismissed = true;
  closeModal('gameover-modal');
});

function formatTickets(tickets) {
  if (!tickets || tickets.length === 0) return 'No tickets';
  return tickets.map(t => {
    const info = getTicketById(t.id);
    const sign = t.delta >= 0 ? '+' : '';
    return `${info ? info.city1 + '→' + info.city2 : '?'} (${sign}${t.delta})`;
  }).join(', ');
}

// ─── Modal helpers ────────────────────────────────────────────────────────────

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// ─── Utils ────────────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

let statusTimer = null;
function showStatus(msg, color = '#f59e0b') {
  const bar = document.getElementById('status-bar');
  const prev = bar.textContent;
  const prevColor = bar.style.color;
  bar.textContent = msg;
  bar.style.color = color;
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    bar.textContent = prev;
    bar.style.color = prevColor;
  }, 3000);
}

function getTicketById(id) {
  // Tickets are injected by the server via game state pending_tickets,
  // but we also need a static lookup. Build it from the first state we receive.
  if (!window._ticketCache) window._ticketCache = {};
  if (window._ticketCache[id]) return window._ticketCache[id];
  // Search in current pending_tickets
  if (gameState) {
    for (const pid of Object.keys(gameState.players)) {
      const p = gameState.players[pid];
      if (p.pending_tickets) {
        for (const t of p.pending_tickets) {
          if (t.id === id) { window._ticketCache[id] = t; return t; }
        }
      }
    }
  }
  return null;
}

// Expose tickets via a request so the client can look them up
socket.on('all_tickets', (tickets) => {
  window._ticketCache = window._ticketCache || {};
  tickets.forEach(t => { window._ticketCache[t.id] = t; });
});

// Handle ticket data from server (we'll populate it in the template too)
(function preloadTickets() {
  if (BOARD_DATA.tickets) {
    window._ticketCache = {};
    BOARD_DATA.tickets.forEach(t => { window._ticketCache[t.id] = t; });
  }
})();

// ─── Settings modal ───────────────────────────────────────────────────────────

function _applySettings() {
  document.getElementById('scoring-section').style.display = scoringVisible ? '' : 'none';
  const ticketsSection = document.getElementById('tickets-section');
  if (ticketsSection) {
    // When scoring reference is shown, shrink tickets to make room; when hidden, let them grow
    ticketsSection.style.maxHeight = scoringVisible ? '30vh' : '55vh';
  }
}

function openSettings() {
  const modal = document.getElementById('settings-modal');
  // Sync checkboxes to current state
  document.getElementById('set-your-turn-sound').checked = yourTurnSoundEnabled;
  document.getElementById('set-sounds').checked          = soundEnabled;
  document.getElementById('set-music').checked           = musicEnabled;
  document.getElementById('set-scoring').checked         = scoringVisible;
  modal.classList.remove('hidden');
}

function closeSettings() {
  document.getElementById('settings-modal').classList.add('hidden');
}

document.getElementById('settings-btn').addEventListener('click', openSettings);
document.getElementById('settings-backdrop').addEventListener('click', closeSettings);

document.getElementById('set-your-turn-sound').addEventListener('change', e => {
  yourTurnSoundEnabled = e.target.checked;
  localStorage.setItem('ttr_your_turn_sound', yourTurnSoundEnabled);
});

document.getElementById('set-sounds').addEventListener('change', e => {
  soundEnabled = e.target.checked;
  localStorage.setItem('ttr_sounds', soundEnabled);
});

document.getElementById('set-music').addEventListener('change', e => {
  musicEnabled = e.target.checked;
  localStorage.setItem('ttr_music', musicEnabled);
  if (musicEnabled) { _loadAndPlayTrack(); } else { _musicAudio.pause(); }
});

document.getElementById('set-scoring').addEventListener('change', e => {
  scoringVisible = e.target.checked;
  localStorage.setItem('ttr_scoring', scoringVisible);
  _applySettings();
});

// Apply persisted settings on load
_applySettings();
if (_loadSetting('ttr_music', false)) {
  musicEnabled = true;
}

// Kick off background music
_initMusic();

// ─── Chat ──────────────────────────────────────────────────────────────────────

(function initChat() {
  const panel        = document.getElementById('chat-panel');
  const messagesEl   = document.getElementById('chat-messages');
  const inputEl      = document.getElementById('chat-input');
  const sendBtn      = document.getElementById('chat-send-btn');
  const toggleBtn    = document.getElementById('chat-toggle-btn');
  const toggleHeader = document.getElementById('chat-toggle-header');
  const unreadEl     = document.getElementById('chat-unread');
  if (!panel) return;

  let collapsed     = false;
  let unreadCount   = 0;

  function setUnread(n) {
    unreadCount = n;
    if (n > 0) {
      unreadEl.textContent = n;
      unreadEl.classList.remove('hidden');
    } else {
      unreadEl.classList.add('hidden');
    }
  }

  function toggleCollapse() {
    collapsed = !collapsed;
    panel.classList.toggle('chat-collapsed', collapsed);
    toggleBtn.textContent = collapsed ? '+' : '−';
    if (!collapsed) {
      setUnread(0);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  }

  toggleHeader.addEventListener('click', toggleCollapse);

  function appendMsg(data, scrollImmediate) {
    const isMe = myChatName && data.name === myChatName;
    const div = document.createElement('div');
    div.className = 'chat-msg' + (isMe ? ' chat-mine' : '');
    div.innerHTML =
      `<span class="chat-msg-name">${escHtml(data.name)}:</span>` +
      `<span class="chat-msg-text">${escHtml(data.msg)}</span>`;
    messagesEl.appendChild(div);
    if (scrollImmediate) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function sendChat() {
    const msg = inputEl.value.trim();
    if (!msg) return;
    socket.emit('send_chat', { code: GAME_CODE, msg, spectator_name: SPECTATOR_NAME });
    inputEl.value = '';
  }

  sendBtn.addEventListener('click', sendChat);
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { sendChat(); e.preventDefault(); }
    e.stopPropagation(); // don't fire game keybinds while typing
  });

  socket.on('chat_history', (messages) => {
    messagesEl.innerHTML = '';
    messages.forEach(m => appendMsg(m, false));
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });

  socket.on('chat_message', (data) => {
    appendMsg(data, !collapsed);
    if (collapsed) setUnread(unreadCount + 1);
  });

  // Expose focus function for keybind (M key)
  window._focusChat = () => {
    if (window.innerWidth <= 768) {
      // Mobile: activate the chat tab
      document.getElementById('mobile-chat-tab')?.click();
    } else {
      if (collapsed) toggleCollapse();
    }
    setTimeout(() => inputEl.focus(), 30);
  };
})();

// ─── Undo vote handlers ───────────────────────────────────────────────────────

socket.on('undo_requested', data => {
  // If I'm the requester, just show a toast
  if (data.player_id && String(data.player_id) === String(MY_PLAYER_ID)) {
    showToast('↩ Undo request sent — waiting for others to approve.', '#f59e0b', 5000);
    return;
  }
  if (IS_SPECTATOR) return;
  document.getElementById('undo-vote-desc').textContent =
    `${escHtml(data.by)} wants to undo their last action. Do you approve?`;
  openModal('undo-vote-modal');
});

socket.on('undo_applied', () => {
  closeModal('undo-vote-modal');
  showToast('↩ Undo applied!', '#22c55e', 3000);
});

socket.on('undo_rejected', () => {
  closeModal('undo-vote-modal');
  showToast('↩ Undo declined.', '#ef4444', 3000);
});

document.getElementById('undo-approve-btn').addEventListener('click', () => {
  socket.emit('vote_undo', { code: GAME_CODE, approve: true });
  closeModal('undo-vote-modal');
});
document.getElementById('undo-reject-btn').addEventListener('click', () => {
  socket.emit('vote_undo', { code: GAME_CODE, approve: false });
  closeModal('undo-vote-modal');
});
document.getElementById('undo-vote-backdrop').addEventListener('click', () => {
  socket.emit('vote_undo', { code: GAME_CODE, approve: false });
  closeModal('undo-vote-modal');
});

// ─── Keyboard shortcuts ────────────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  // Escape — cancel station placement mode
  if (e.key === 'Escape' && stationPlacementMode) {
    exitStationPlacementMode();
    return;
  }

  // M — focus chat (even from within inputs)
  if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (!inInput) {
      e.preventDefault();
      if (window._focusChat) window._focusChat();
    }
    return;
  }

  // Ignore remaining shortcuts when typing or a modal is open
  const inInput = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
  if (inInput) return;
  const modalOpen = ['claim-modal','ticket-modal','settings-modal','undo-vote-modal','tunnel-modal','station-modal'].some(
    id => { const el = document.getElementById(id); return el && !el.classList.contains('hidden'); }
  );
  if (modalOpen) return;

  const myTurn = gameState &&
    gameState.current_player_id === MY_PLAYER_ID &&
    (gameState.phase === 'main' || gameState.phase === 'final_round');

  // D — blind draw (only on your turn)
  if ((e.key === 'd' || e.key === 'D') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (myTurn && !IS_SPECTATOR) {
      e.preventDefault();
      document.getElementById('draw-blind-btn').click();
    }
    return;
  }

  // T — draw destination tickets (only on your turn, not mid-draw)
  if ((e.key === 't' || e.key === 'T') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (myTurn && !IS_SPECTATOR && gameState.draw_step === 0) {
      e.preventDefault();
      document.getElementById('draw-tickets-btn').click();
    }
    return;
  }
});

// ─── Mobile: tab bar & board zoom ────────────────────────────────────────────

(function initMobile() {
  function isMobile() { return window.innerWidth <= 768; }

  // Tab bar — show left or right sidebar as a slide-up panel
  const tabs = document.querySelectorAll('.mobile-tab');
  const leftSidebar  = document.querySelector('.left-sidebar');
  const rightSidebar = document.querySelector('.right-sidebar');
  const chatPanel    = document.getElementById('chat-panel');

  function setMobileTab(panelName) {
    tabs.forEach(t => t.classList.toggle('active', t.dataset.panel === panelName));
    leftSidebar.classList.remove('mobile-open');
    rightSidebar.classList.remove('mobile-open');
    if (chatPanel) chatPanel.classList.remove('mobile-open');
    if (panelName === 'left')  leftSidebar.classList.add('mobile-open');
    if (panelName === 'right') rightSidebar.classList.add('mobile-open');
    if (panelName === 'chat' && chatPanel) {
      chatPanel.classList.add('mobile-open');
      // Clear unread badge when chat tab is opened
      const unreadEl = document.getElementById('chat-unread');
      if (unreadEl) unreadEl.classList.add('hidden');
      const mobileBadge = document.getElementById('mobile-chat-badge');
      if (mobileBadge) mobileBadge.classList.add('hidden');
      const messagesEl = document.getElementById('chat-messages');
      if (messagesEl) setTimeout(() => { messagesEl.scrollTop = messagesEl.scrollHeight; }, 30);
    }
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => setMobileTab(tab.dataset.panel));
  });

  // Show a red dot on the Chat tab when a new message arrives while it isn't active
  socket.on('chat_message', () => {
    if (!isMobile()) return;
    const chatTab = document.getElementById('mobile-chat-tab');
    if (!chatTab || chatTab.classList.contains('active')) return;
    let badge = document.getElementById('mobile-chat-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.id = 'mobile-chat-badge';
      badge.className = 'mobile-chat-badge';
      badge.textContent = '●';
      chatTab.querySelector('.mobile-tab-icon').appendChild(badge);
    }
    badge.classList.remove('hidden');
  });

  // Close mobile panel when tapping the board (outside the panel)
  document.getElementById('board-container').addEventListener('click', () => {
    if (isMobile()) setMobileTab('board');
  }, true);

  // Zoom buttons
  const zoomIn  = document.getElementById('zoom-in-btn');
  const zoomOut = document.getElementById('zoom-out-btn');
  if (zoomIn) {
    zoomIn.addEventListener('click', () => {
      mobileZoom = Math.min(mobileZoom + 0.25, 3.0);
      recalcBoardScale();
      renderBoard();
    });
  }
  if (zoomOut) {
    zoomOut.addEventListener('click', () => {
      mobileZoom = Math.max(mobileZoom - 0.25, 0.5);
      recalcBoardScale();
      renderBoard();
    });
  }

  // Re-run board scale recalc on resize (handles rotation, window resize)
  window.addEventListener('resize', () => {
    recalcBoardScale();
    renderBoard();
  });

  // Pinch-to-zoom on the board
  const boardContainer = document.getElementById('board-container');
  let lastPinchDist = null;
  boardContainer.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      lastPinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
    } else {
      lastPinchDist = null;
    }
  }, { passive: true });
  boardContainer.addEventListener('touchmove', e => {
    if (e.touches.length === 2 && lastPinchDist !== null) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      mobileZoom = Math.min(Math.max(mobileZoom * (dist / lastPinchDist), 0.5), 3.0);
      lastPinchDist = dist;
      recalcBoardScale();
      renderBoard();
    }
  }, { passive: true });
})();
