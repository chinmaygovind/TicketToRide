/* ============================================================
   Ticket to Ride — Game Client
   ============================================================ */

const socket = io();
let gameState = null;
let pendingRouteId = null;

// Card icon emoji map
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
  locomotive: 'linear-gradient(135deg, #d97706, #92400e)',
};

// Player color hex map (should match server-side)
const PLAYER_HEX = {
  blue: '#3B82F6', red: '#EF4444', green: '#22C55E',
  yellow: '#EAB308', black: '#6B7280',
};

// ─── Socket setup ────────────────────────────────────────────────────────────

socket.on('connect', () => {
  socket.emit('register_session');
  socket.emit('join_game_room', { code: GAME_CODE });
});

socket.on('game_state', (state) => {
  gameState = state;
  renderAll();
});

socket.on('game_state_update', (state) => {
  if (!gameState) return;
  gameState.claimed_routes    = state.claimed_routes;
  gameState.face_up           = state.face_up;
  gameState.deck_count        = state.deck_count;
  gameState.dest_deck_count   = state.dest_deck_count;
  gameState.action_log        = state.action_log;
  gameState.phase             = state.phase;
  gameState.current_player_id = state.current_player_id;
  gameState.draw_step         = state.draw_step;
  gameState.scores            = state.scores;
  gameState.winner_id         = state.winner_id;
  // Merge public-only per-player fields without touching hand/tickets
  for (const pid of Object.keys(state.players)) {
    if (gameState.players[pid]) {
      gameState.players[pid].trains       = state.players[pid].trains;
      gameState.players[pid].route_score  = state.players[pid].route_score;
      gameState.players[pid].card_count   = state.players[pid].card_count;
      gameState.players[pid].ticket_count = state.players[pid].ticket_count;
    }
  }
  renderAll();
});

socket.on('error', (data) => {
  showStatus('❌ ' + data.message, '#ef4444');
});

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
  if (!ticketModal.classList.contains('hidden')) return; // don't reset if already open
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

  const cities = BOARD_DATA.cities;
  const routes = BOARD_DATA.routes;
  const claimed = gameState ? gameState.claimed_routes : {};

  // Draw routes
  for (const route of routes) {
    const c1 = cities[route.city1];
    const c2 = cities[route.city2];
    if (!c1 || !c2) continue;

    const p1 = boardPx(c1[0], c1[1]);
    const p2 = boardPx(c2[0], c2[1]);

    const segData = BOARD_DATA.route_segments && BOARD_DATA.route_segments[route.id];
    let segments;
    if (segData && segData.length === route.length) {
      const dx = p2.x - p1.x, dy = p2.y - p1.y, dist = Math.sqrt(dx*dx + dy*dy);
      const angle = Math.atan2(dy, dx) * 180 / Math.PI;
      const segW = (dist / route.length) * 0.78;
      const segH = 8 * boardScale.x;
      segments = segData.map(([bx, by]) => {
        const p = boardPx(bx, by);
        return { x: p.x - segW/2, y: p.y - segH/2, w: segW, h: segH, angle, cx: p.x, cy: p.y };
      });
    } else {
      segments = buildRouteSegments(p1, p2, route.length, route.side, route.color);
    }
    const claimedBy = claimed[String(route.id)];

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', seg.x);
      rect.setAttribute('y', seg.y);
      rect.setAttribute('width', seg.w);
      rect.setAttribute('height', seg.h);
      rect.setAttribute('transform', `rotate(${seg.angle}, ${seg.cx}, ${seg.cy})`);
      rect.setAttribute('rx', '2');

      if (claimedBy) {
        const owner = gameState.players[claimedBy];
        const ownerColor = owner ? PLAYER_HEX[owner.color] : '#888';
        rect.setAttribute('fill', ownerColor);
        rect.setAttribute('stroke', 'rgba(0,0,0,0.4)');
        rect.setAttribute('stroke-width', '1');
        rect.classList.add('route-seg', 'claimed');
      } else {
        const routeColor = route.color === 'gray' ? '#9ca3af' : (BOARD_DATA.card_colors[route.color] || '#888');
        rect.setAttribute('fill', routeColor);
        rect.setAttribute('fill-opacity', '0.55');
        rect.setAttribute('stroke', 'rgba(255,255,255,0.3)');
        rect.setAttribute('stroke-width', '1');
        rect.classList.add('route-seg');
        rect.dataset.routeId = route.id;
        rect.addEventListener('click', () => onRouteClick(route.id));
      }

      svg.appendChild(rect);
    }
  }

  // Draw city circles
  for (const [cityName, coords] of Object.entries(cities)) {
    const p = boardPx(coords[0], coords[1]);
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', p.x);
    circle.setAttribute('cy', p.y);
    circle.setAttribute('r', 5 * boardScale.x);
    circle.setAttribute('fill', '#1a1512');
    circle.setAttribute('stroke', '#c8a84b');
    circle.setAttribute('stroke-width', 1.5);
    circle.classList.add('city-circle');
    svg.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', p.x);
    text.setAttribute('y', p.y + 10 * boardScale.y);
    text.setAttribute('font-size', Math.max(6, 7 * boardScale.x));
    text.setAttribute('fill', '#ffffff');
    text.setAttribute('stroke', '#000');
    text.setAttribute('stroke-width', '2');
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
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * 180 / Math.PI;

  const segW = (dist / length) * 0.78;
  const segH = 8 * boardScale.x;
  const gap = (dist / length) * 0.22;

  // Perpendicular offset for double routes
  const perpX = -dy / dist;
  const perpY = dx / dist;
  const offsetDist = side === 0 ? -4 * boardScale.x : 4 * boardScale.x;
  const offX = perpX * offsetDist;
  const offY = perpY * offsetDist;

  const segments = [];
  for (let i = 0; i < length; i++) {
    const t = (i + 0.5) / length;
    const cx = p1.x + dx * t + offX;
    const cy = p1.y + dy * t + offY;
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
    return `<div class="player-row ${isActive ? 'active-turn' : ''}">
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
    return `<div class="train-card" style="background:${CARD_BG[color] || '#444'};"
                 data-slot="${i}" onclick="onDrawFaceUp(${i})" title="${color}">
              <div class="card-label">${color.toUpperCase()}</div>
            </div>`;
  }).join('');

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
        <span class="chip-count">${hand[c]}</span>
        <span class="chip-name">${c.toUpperCase()}</span>
      </div>`)
    .join('');
}

// ─── Tickets ─────────────────────────────────────────────────────────────────

function renderTickets() {
  if (!gameState) return;
  const me = gameState.players[MY_PLAYER_ID];
  if (!me) return;
  const area = document.getElementById('tickets-panel');
  const ticketsData = BOARD_DATA.tickets || [];

  if (!me.tickets || me.tickets.length === 0) {
    area.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">No tickets yet.</div>';
    return;
  }

  area.innerHTML = me.tickets.map(tid => {
    const t = getTicketById(tid);
    if (!t) return '';
    return `<div class="ticket-item">
      <div class="ticket-cities">${escHtml(t.city1)} <span style="color:var(--text-muted);">→</span> ${escHtml(t.city2)}</div>
      <div class="ticket-points">${t.points} pts</div>
    </div>`;
  }).join('');
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

function onDrawFaceUp(slot) {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  if (gameState.phase !== 'main' && gameState.phase !== 'final_round') return;
  socket.emit('draw_face_up', { code: GAME_CODE, slot });
}

document.getElementById('draw-blind-btn').addEventListener('click', () => {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  socket.emit('draw_blind', { code: GAME_CODE });
});

document.getElementById('draw-tickets-btn').addEventListener('click', () => {
  if (!gameState) return;
  if (gameState.current_player_id !== MY_PLAYER_ID) return;
  if (gameState.draw_step !== 0) return;
  socket.emit('draw_destination_tickets', { code: GAME_CODE });
});

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

  // Build card selector
  const selector = document.getElementById('card-selector');
  const colorOrder = ['red','blue','green','yellow','orange','purple','black','white','locomotive'];
  const available = colorOrder.filter(c => hand[c] > 0);

  selector.innerHTML = '';
  let selectedCombo = {};

  function refreshSelector() {
    selector.innerHTML = '';
    available.forEach(color => {
      const chip = document.createElement('div');
      chip.className = 'csel-chip' + (selectedCombo[color] ? ' selected' : '');
      chip.style.background = CARD_BG[color];
      chip.innerHTML = `
        <span class="csel-chip-count">${selectedCombo[color] || 0} / ${hand[color]}</span>
        <span class="csel-chip-name">${color.toUpperCase()}</span>`;
      chip.addEventListener('click', () => {
        // Increment selected count, cycling: 0→1→…→hand[color]→0
        const cur = selectedCombo[color] || 0;
        if (cur < hand[color]) {
          selectedCombo[color] = cur + 1;
        } else {
          selectedCombo[color] = 0;
        }
        if (selectedCombo[color] === 0) delete selectedCombo[color];
        refreshSelector();
      });
      selector.appendChild(chip);
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
  let selected = new Set(tickets.map(t => t.id));  // default: keep all

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
          if (selected.size > minKeep) selected.delete(id);
        } else {
          selected.add(id);
        }
        refreshTicketChoices();
      });
    });
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
        <div class="score-row-detail">Routes: ${s.route_score} | Longest path: ${s.longest_path}${longestBonus}</div>
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
  // Tickets embedded via the board data
  if (BOARD_DATA.tickets) {
    window._ticketCache = {};
    BOARD_DATA.tickets.forEach(t => { window._ticketCache[t.id] = t; });
  }
})();
