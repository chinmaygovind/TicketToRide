/* ============================================================
   Ticket to Ride — Game Client
   ============================================================ */

const socket = io();
let gameState = null;
let pendingRouteId = null;

// ─── Transition tracking ──────────────────────────────────────────────────────
let prevCurrentPlayerId = null;
let prevPhase = null;
let lastKnownActionLogEntry = '';

// ─── Sound system ─────────────────────────────────────────────────────────────
let soundEnabled = true;
let _gameOverSoundPlayed = false;

// Map logical names → file paths
const SOUND_FILES = {
  your_turn:    '/static/sounds/your_turn.mp3',
  draw_card:    '/static/sounds/take_card.mp3',
  place_trains: '/static/sounds/place_train.mp3',
  win:          '/static/sounds/win.mp3',
  lose:         '/static/sounds/lose.mp3',
};

// Synth fallback (used for final_round fanfare which has no file)
let _audioCtx = null;
function _getAudioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
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
  if (SOUND_FILES[name]) {
    const a = new Audio(SOUND_FILES[name]);
    a.play().catch(() => {});
    return;
  }
  // Synth-only sounds
  if (name === 'final_round') {
    _synth(523, 0.18); setTimeout(() => _synth(659, 0.18), 200);
    setTimeout(() => _synth(784, 0.18), 400); setTimeout(() => _synth(1047, 0.5), 600);
  }
}

// ─── Music player ─────────────────────────────────────────────────────────────
let musicEnabled = true;
let _musicQueue = [];
let _musicIdx = 0;
const _musicAudio = new Audio();
_musicAudio.volume = 0.35;

function _initMusic() {
  if (!window.MUSIC_FILES || !MUSIC_FILES.length) return;
  // Shuffle
  _musicQueue = [...MUSIC_FILES].sort(() => Math.random() - 0.5);
  _musicIdx = 0;
  _musicAudio.addEventListener('ended', () => {
    _musicIdx = (_musicIdx + 1) % _musicQueue.length;
    _loadAndPlayTrack();
  });
  _loadAndPlayTrack();
}

function _loadAndPlayTrack() {
  if (!musicEnabled || !_musicQueue.length) return;
  _musicAudio.src = `/static/music/${_musicQueue[_musicIdx]}`;
  _musicAudio.play().catch(() => {}); // silently fails until user gesture
}

// Auto-start music on first user click (bypasses autoplay block)
document.addEventListener('click', function _musicAutostart() {
  if (musicEnabled && _musicAudio.paused && _musicQueue.length) {
    _musicAudio.play().catch(() => {});
  }
}, { once: true });

function toggleMusic() {
  musicEnabled = !musicEnabled;
  const btn = document.getElementById('music-toggle');
  if (btn) btn.classList.toggle('audio-off', !musicEnabled);
  if (musicEnabled) {
    _loadAndPlayTrack();
  } else {
    _musicAudio.pause();
  }
}

function toggleSound() {
  soundEnabled = !soundEnabled;
  const btn = document.getElementById('sound-toggle');
  if (btn) btn.classList.toggle('audio-off', !soundEnabled);
}

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

const CARD_ICON = {
  purple: '🟣', blue: '🔵', orange: '🟠', white: '⚪',
  green: '🟢', yellow: '🟡', black: '⚫', red: '🔴',
  locomotive: '🚂',
};
const CARD_BG = {
  purple:     'linear-gradient(135deg, #7c3aed, #4c1d95)',
  blue:       'linear-gradient(135deg, #2563eb, #1e3a8a)',
  orange:     'linear-gradient(135deg, #ea580c, #9a3412)',
  white:      'linear-gradient(135deg, #cbd5e1, #94a3b8)',
  green:      'linear-gradient(135deg, #16a34a, #14532d)',
  yellow:     'linear-gradient(135deg, #ca8a04, #713f12)',
  black:      'linear-gradient(135deg, #374151, #111827)',
  red:        'linear-gradient(135deg, #dc2626, #7f1d1d)',
  locomotive: 'linear-gradient(160deg, #ef4444 0%, #f97316 18%, #eab308 38%, #22c55e 58%, #3b82f6 78%, #8b5cf6 100%)',
};

// Player color hex map (should match server-side)
const PLAYER_HEX = {
  red: '#EF4444', blue: '#3B82F6', green: '#22C55E',
  yellow: '#EAB308', pink: '#EC4899', orange: '#F97316',
};

// ─── Socket setup ────────────────────────────────────────────────────────────

socket.on('connect', () => {
  socket.emit('register_session');
  socket.emit('join_game_room', { code: GAME_CODE });
});

socket.on('game_state', (state) => {
  // Detect your-turn transition before overwriting gameState
  if (gameState &&
      gameState.current_player_id !== MY_PLAYER_ID &&
      state.current_player_id === MY_PLAYER_ID &&
      (state.phase === 'main' || state.phase === 'final_round')) {
    playSound('your_turn');
    showToast('🎯 Your turn!', '#22c55e', 3000);
  }
  prevCurrentPlayerId = state.current_player_id;
  prevPhase = state.phase;
  lastKnownActionLogEntry = (state.action_log || []).slice(-1)[0] || '';
  gameState = state;
  renderAll();
});

socket.on('game_state_update', (state) => {
  if (!gameState) return;
  const oldCurrentPlayer = gameState.current_player_id;
  const oldPhase = gameState.phase;

  gameState.claimed_routes          = state.claimed_routes;
  gameState.face_up                 = state.face_up;
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
  // Merge public-only per-player fields without touching hand/tickets
  for (const pid of Object.keys(state.players)) {
    if (gameState.players[pid]) {
      gameState.players[pid].trains       = state.players[pid].trains;
      gameState.players[pid].route_score  = state.players[pid].route_score;
      gameState.players[pid].card_count   = state.players[pid].card_count;
      gameState.players[pid].ticket_count = state.players[pid].ticket_count;
    }
  }

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

  renderAll();
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
      animateCardToPlayerRow(pid, 'draw-blind-btn', 'locomotive');
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

function recalcBoardScale() {
  const img = document.getElementById('board-img');
  const container = document.getElementById('board-container');
  if (!img.naturalWidth) return;

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
  svg.setAttribute('viewBox', '0 0 1024 683');
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
      const dx = c2[0] - c1[0], dy = c2[1] - c1[1];
      const dist = Math.sqrt(dx*dx + dy*dy);
      const segW = (dist / route.length) * 0.78;
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
        rect.addEventListener('click', () => onRouteClick(route.id));
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
    }
  }

  // Draw city circles
  for (const [cityName, coords] of Object.entries(cities)) {
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', coords[0]);
    circle.setAttribute('cy', coords[1]);
    circle.setAttribute('r', 5);
    circle.setAttribute('fill', '#1a1512');
    circle.setAttribute('stroke', '#c8a84b');
    circle.setAttribute('stroke-width', 1.5);
    circle.classList.add('city-circle');
    circle.dataset.city = cityName;
    svg.appendChild(circle);

    const labelFontSize = 11;
    const [ldx, ldy] = LABEL_OFFSETS[cityName] || [0, 14];
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

window.addEventListener('resize', () => {
  recalcBoardScale();
  renderBoard();
});

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
    return `<div class="player-row ${isActive ? 'active-turn' : ''}" data-pid="${pid}">
      <div class="player-color-dot" style="background:${PLAYER_HEX[p.color]};box-shadow:0 0 5px ${PLAYER_HEX[p.color]};"></div>
      <span class="player-row-name">${escHtml(p.name)}${isMe ? ' <span style="color:var(--gold);font-size:0.65rem;">(you)</span>' : ''}</span>
      <span class="player-row-score">${p.route_score}</span>
      <span class="player-row-trains">🚂${p.trains}</span>
    </div>`;
  }).join('');
}

// ─── Face-up cards ───────────────────────────────────────────────────────────

function renderFaceUpCards() {
  if (!gameState) return;
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
  const colorOrder = ['red','blue','green','yellow','orange','purple','black','white','locomotive'];
  area.innerHTML = colorOrder
    .filter(c => hand[c] > 0)
    .map(c => `
      <div class="hand-card-chip" style="background:${CARD_BG[c]};"
           data-color="${c}">
        <span class="chip-icon">🚂</span>
        <span class="chip-count">${hand[c]}</span>
        <span class="chip-name">${c === 'locomotive' ? 'LOCO' : c.toUpperCase()}</span>
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
  me.tickets.forEach(tid => {
    const t = getTicketById(tid);
    if (!t) return;
    const completed = isTicketCompleted(t);
    const div = document.createElement('div');
    div.className = 'ticket-item' + (completed ? ' completed' : '');
    div.innerHTML = `
      <div class="ticket-cities">
        ${escHtml(t.city1)} <span style="color:var(--text-muted);">→</span> ${escHtml(t.city2)}
        ${completed ? '<span class="ticket-check">✓</span>' : ''}
      </div>
      <div class="ticket-points">${t.points} pts</div>`;
    div.addEventListener('mouseenter', () => highlightTicketCities(t.city1, t.city2, true));
    div.addEventListener('mouseleave', () => highlightTicketCities(t.city1, t.city2, false));
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
    bar.textContent = '🏁 Game over!';
    bar.style.color = 'var(--gold-light)';
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
    if (gameState.draw_step === 1) {
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
  if (!gameState) return;
  const isMyTurn = gameState.current_player_id === MY_PLAYER_ID;
  const drawingCards = gameState.draw_step > 0;
  const btn = document.getElementById('draw-tickets-btn');
  btn.disabled = !isMyTurn || drawingCards;
  btn.classList.toggle('active-turn', isMyTurn && !drawingCards);
  document.getElementById('dest-count').textContent = gameState.dest_deck_count || 0;

  const blindBtn = document.getElementById('draw-blind-btn');
  blindBtn.disabled = !isMyTurn;
  blindBtn.classList.toggle('active-turn', isMyTurn);
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
  const btn = document.getElementById('draw-blind-btn');
  animateCardToElement(btn, 'hand-cards', 'locomotive');
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
  const colorOrder = ['red','blue','green','yellow','orange','purple','black','white','locomotive'];
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
    playSound('place_trains');
    closeModal('claim-modal');
  };

  openModal('claim-modal');
}

document.getElementById('claim-cancel-btn').addEventListener('click', () => closeModal('claim-modal'));
document.querySelector('#claim-modal .modal-backdrop').addEventListener('click', () => closeModal('claim-modal'));

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
  const minKeep = isInitial ? 2 : 1;

  document.getElementById('ticket-modal-title').textContent =
    isInitial ? 'Choose Your Starting Tickets' : 'Keep Destination Tickets';
  document.getElementById('ticket-modal-desc').textContent =
    `Choose which tickets to keep (minimum ${minKeep}).`;

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
    return `<div class="score-row ${isWinner ? 'winner' : ''}">
      <div class="score-row-place">${['🥇','🥈','🥉','4','5'][i]}</div>
      <div style="flex:1">
        <div class="score-row-name">
          <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${PLAYER_HEX[s.color]};margin-right:6px;"></span>
          ${escHtml(s.name)}
        </div>
        <div class="score-row-detail">Routes: ${s.route_score} | Longest path: ${s.longest_path}${longestBonus} | Destinations: ${s.tickets && s.tickets.length ? (s.tickets.reduce((sum, t) => sum + t.delta, 0) >= 0 ? '+' : '') + s.tickets.reduce((sum, t) => sum + t.delta, 0) : 0}</div>
        <div class="score-row-detail">${formatTickets(s.tickets)}</div>
      </div>
      <div class="score-row-total">${s.total}</div>
    </div>`;
  }).join('');

  openModal('gameover-modal');
}

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

// Wire audio toggle buttons
document.getElementById('music-toggle').addEventListener('click', toggleMusic);
document.getElementById('sound-toggle').addEventListener('click', toggleSound);

// Kick off background music
_initMusic();
