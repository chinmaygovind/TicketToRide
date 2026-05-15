"""
Full game logic for Ticket to Ride (North America).
All state lives in a single dict that is serialized to the DB as JSON.
"""

import random
from collections import defaultdict, deque
from game_data import (
    ROUTES, ROUTE_BY_ID, DESTINATION_TICKETS, TICKET_BY_ID,
    CARD_COUNTS, ROUTE_SCORING, DOUBLE_ROUTE_GROUPS, PLAYER_COLORS,
)


# ---------------------------------------------------------------------------
# State initialization
# ---------------------------------------------------------------------------

def build_deck() -> list[str]:
    deck = []
    for color, count in CARD_COUNTS.items():
        deck.extend([color] * count)
    random.shuffle(deck)
    return deck


def init_game_state(players: list[dict]) -> dict:
    """
    players: list of {id, name, color, turn_order}
    Returns the full game state dict.
    """
    deck = build_deck()
    face_up: list[str] = []
    for _ in range(5):
        face_up.append(deck.pop())
    face_up = _maybe_replace_three_locos(face_up, deck)

    dest_deck = list(range(1, len(DESTINATION_TICKETS) + 1))
    random.shuffle(dest_deck)

    player_states: dict[str, dict] = {}
    for p in players:
        hand: dict[str, int] = {}
        for _ in range(4):
            c = deck.pop()
            hand[c] = hand.get(c, 0) + 1
        player_states[str(p["id"])] = {
            "name": p["name"],
            "color": p["color"],
            "turn_order": p["turn_order"],
            "hand": hand,             # {color: count}
            "tickets": [],            # kept destination ticket IDs
            "trains": 45,
            "route_score": 0,
            "pending_tickets": [],    # drawn but not yet kept/returned
        }

    # Deal initial 3 destination tickets to each player (they must keep >=2)
    for p in players:
        pid = str(p["id"])
        drawn = [dest_deck.pop() for _ in range(3)]
        player_states[pid]["pending_tickets"] = drawn

    turn_order = sorted(players, key=lambda x: x["turn_order"])
    current_player_id = str(turn_order[0]["id"])

    return {
        "deck": deck,
        "face_up": face_up,
        "discard": [],
        "dest_deck": dest_deck,
        "claimed_routes": {},         # {route_id_str: player_id_str}
        "player_states": player_states,
        "current_player_id": current_player_id,
        "turn_order": [str(p["id"]) for p in turn_order],
        "phase": "initial_tickets",   # initial_tickets | main | final_round | ended
        "final_round_players_left": [],  # players who still get their last turn
        "draw_step": 0,               # 0 = haven't drawn yet, 1 = drew first card
        "action_log": [],
        "winner_id": None,
        "scores": {},
    }


def _maybe_replace_three_locos(face_up: list[str], deck: list[str]) -> list[str]:
    """If 3+ locomotives are face-up, discard all five and draw five new ones."""
    while face_up.count("locomotive") >= 3:
        deck.extend(face_up)
        random.shuffle(deck)
        face_up = [deck.pop() for _ in range(5)]
    return face_up


def _ensure_deck(state: dict):
    """Reshuffle discard into deck if deck is empty."""
    if not state["deck"] and state["discard"]:
        state["deck"] = state["discard"][:]
        random.shuffle(state["deck"])
        state["discard"] = []


# ---------------------------------------------------------------------------
# Initial ticket selection
# ---------------------------------------------------------------------------

def keep_initial_tickets(state: dict, player_id: str, keep_ids: list[int]) -> dict:
    ps = state["player_states"][player_id]
    pending = ps["pending_tickets"]
    if len(keep_ids) < 2:
        return {"ok": False, "error": "Must keep at least 2 destination tickets."}
    if not all(k in pending for k in keep_ids):
        return {"ok": False, "error": "Invalid ticket selection."}

    ps["tickets"].extend(keep_ids)
    returned = [t for t in pending if t not in keep_ids]
    state["dest_deck"] = returned + state["dest_deck"]
    ps["pending_tickets"] = []

    # Advance to next player for initial ticket phase
    _advance_initial_tickets(state)
    return {"ok": True}


def _advance_initial_tickets(state: dict):
    """Move to next player for initial ticket selection; when all done, start main game."""
    all_done = all(
        len(ps["pending_tickets"]) == 0
        for ps in state["player_states"].values()
    )
    if all_done:
        state["phase"] = "main"
        state["draw_step"] = 0
        state["current_player_id"] = state["turn_order"][0]
    else:
        # Advance to next player who still has pending tickets
        order = state["turn_order"]
        cur = state["current_player_id"]
        idx = order.index(cur)
        for i in range(1, len(order) + 1):
            nxt = order[(idx + i) % len(order)]
            if state["player_states"][nxt]["pending_tickets"]:
                state["current_player_id"] = nxt
                return


# ---------------------------------------------------------------------------
# Draw Train Car Cards
# ---------------------------------------------------------------------------

def draw_face_up(state: dict, player_id: str, slot: int) -> dict:
    """Draw a specific face-up card (slot 0-4). Returns error dict on failure."""
    if state["phase"] not in ("main", "final_round"):
        return {"ok": False, "error": "Not main game phase."}
    if state["current_player_id"] != player_id:
        return {"ok": False, "error": "Not your turn."}

    card = state["face_up"][slot]
    if card == "locomotive" and state["draw_step"] == 1:
        return {"ok": False, "error": "Cannot take a locomotive as the second card."}

    ps = state["player_states"][player_id]
    ps["hand"][card] = ps["hand"].get(card, 0) + 1
    _log(state, f"{ps['name']} drew face-up {card}.")

    # Replace drawn card
    _ensure_deck(state)
    if state["deck"]:
        state["face_up"][slot] = state["deck"].pop()
    else:
        state["face_up"][slot] = None
    state["face_up"] = _maybe_replace_three_locos(
        [c for c in state["face_up"] if c is not None], state["deck"]
    )
    # Re-pad to 5 slots
    while len(state["face_up"]) < 5:
        state["face_up"].append(None)

    if card == "locomotive":
        # Locomotive face-up counts as both draws
        state["draw_step"] = 0
        _end_draw_action(state, player_id)
    else:
        state["draw_step"] += 1
        if state["draw_step"] >= 2:
            state["draw_step"] = 0
            _end_draw_action(state, player_id)

    return {"ok": True, "card": card}


def draw_blind(state: dict, player_id: str) -> dict:
    """Draw blindly from the top of the deck."""
    if state["phase"] not in ("main", "final_round"):
        return {"ok": False, "error": "Not main game phase."}
    if state["current_player_id"] != player_id:
        return {"ok": False, "error": "Not your turn."}
    _ensure_deck(state)
    if not state["deck"]:
        return {"ok": False, "error": "No cards left to draw."}

    card = state["deck"].pop()
    ps = state["player_states"][player_id]
    ps["hand"][card] = ps["hand"].get(card, 0) + 1
    _log(state, f"{ps['name']} drew a blind card.")

    state["draw_step"] += 1
    if state["draw_step"] >= 2:
        state["draw_step"] = 0
        _end_draw_action(state, player_id)

    return {"ok": True, "card": card}


def _end_draw_action(state: dict, player_id: str):
    _next_turn(state)


# ---------------------------------------------------------------------------
# Claim a Route
# ---------------------------------------------------------------------------

def claim_route(state: dict, player_id: str, route_id: int, cards_to_use: dict) -> dict:
    """
    cards_to_use: {color: count} — the cards the player wants to spend.
    Locomotives are wildcards.
    """
    if state["phase"] not in ("main", "final_round"):
        return {"ok": False, "error": "Not main game phase."}
    if state["current_player_id"] != player_id:
        return {"ok": False, "error": "Not your turn."}
    if state["draw_step"] != 0:
        return {"ok": False, "error": "You are in the middle of drawing cards."}

    route = ROUTE_BY_ID.get(route_id)
    if not route:
        return {"ok": False, "error": "Invalid route."}

    route_id_str = str(route_id)
    if route_id_str in state["claimed_routes"]:
        return {"ok": False, "error": "Route already claimed."}

    # Check double-route restriction
    if route["double_group"]:
        group_ids = DOUBLE_ROUTE_GROUPS[route["double_group"]]
        other_ids = [rid for rid in group_ids if rid != route_id]
        num_players = len(state["turn_order"])
        for oid in other_ids:
            oid_str = str(oid)
            if oid_str in state["claimed_routes"]:
                if num_players <= 3:
                    return {"ok": False, "error": "Only one double-route allowed in 2-3 player games."}
                if state["claimed_routes"][oid_str] == player_id:
                    return {"ok": False, "error": "You already own the other side of this route."}

    ps = state["player_states"][player_id]
    required_length = route["length"]
    route_color = route["color"]

    # Validate cards_to_use
    total_cards = sum(cards_to_use.values())
    if total_cards != required_length:
        return {"ok": False, "error": f"Need exactly {required_length} cards."}

    loco_count = cards_to_use.get("locomotive", 0)
    non_loco = {c: n for c, n in cards_to_use.items() if c != "locomotive"}

    if route_color == "gray":
        # Gray route: all non-loco cards must be the same color
        if len(non_loco) > 1:
            return {"ok": False, "error": "Gray routes require cards of a single color plus locomotives."}
    else:
        # Specific color route: non-loco cards must match route color
        for c in non_loco:
            if c != route_color:
                return {"ok": False, "error": f"Route requires {route_color} cards."}

    # Check player has the cards
    hand = ps["hand"]
    for color, count in cards_to_use.items():
        if hand.get(color, 0) < count:
            return {"ok": False, "error": f"Not enough {color} cards."}

    # Check train count
    if ps["trains"] < required_length:
        return {"ok": False, "error": "Not enough trains."}

    # Apply: remove cards, place trains, record claim
    for color, count in cards_to_use.items():
        hand[color] -= count
        if hand[color] == 0:
            del hand[color]
    state["discard"].extend(_expand_cards(cards_to_use))

    ps["trains"] -= required_length
    points = ROUTE_SCORING[required_length]
    ps["route_score"] += points
    state["claimed_routes"][route_id_str] = player_id
    _log(state, f"{ps['name']} claimed {route['city1']}–{route['city2']} (+{points} pts).")

    # Check end game trigger
    if ps["trains"] <= 2:
        _trigger_final_round(state, player_id)
    else:
        _next_turn(state)

    return {"ok": True, "points": points}


def _expand_cards(cards: dict) -> list:
    result = []
    for color, count in cards.items():
        result.extend([color] * count)
    return result


# ---------------------------------------------------------------------------
# Draw Destination Tickets
# ---------------------------------------------------------------------------

def draw_destination_tickets(state: dict, player_id: str) -> dict:
    if state["phase"] != "main":
        return {"ok": False, "error": "Not main game phase."}
    if state["current_player_id"] != player_id:
        return {"ok": False, "error": "Not your turn."}
    if state["draw_step"] != 0:
        return {"ok": False, "error": "You are in the middle of drawing cards."}

    if not state["dest_deck"]:
        return {"ok": False, "error": "No destination tickets left."}

    ps = state["player_states"][player_id]
    available = min(3, len(state["dest_deck"]))
    drawn = state["dest_deck"][:available]
    state["dest_deck"] = state["dest_deck"][available:]
    ps["pending_tickets"] = drawn

    return {"ok": True, "tickets": [TICKET_BY_ID[t] for t in drawn]}


def keep_drawn_tickets(state: dict, player_id: str, keep_ids: list[int]) -> dict:
    if state["current_player_id"] != player_id:
        return {"ok": False, "error": "Not your turn."}

    ps = state["player_states"][player_id]
    pending = ps["pending_tickets"]
    if not pending:
        return {"ok": False, "error": "No pending tickets."}
    if len(keep_ids) < 1:
        return {"ok": False, "error": "Must keep at least 1 ticket."}
    if not all(k in pending for k in keep_ids):
        return {"ok": False, "error": "Invalid ticket selection."}

    ps["tickets"].extend(keep_ids)
    returned = [t for t in pending if t not in keep_ids]
    state["dest_deck"].extend(returned)
    ps["pending_tickets"] = []
    _log(state, f"{ps['name']} drew destination tickets.")
    _next_turn(state)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Turn management
# ---------------------------------------------------------------------------

def _next_turn(state: dict):
    order = state["turn_order"]
    cur = state["current_player_id"]
    idx = order.index(cur)
    nxt = order[(idx + 1) % len(order)]

    if state["phase"] == "final_round":
        remaining = state["final_round_players_left"]
        if cur in remaining:
            remaining.remove(cur)
        if not remaining:
            _end_game(state)
            return

    state["current_player_id"] = nxt
    state["draw_step"] = 0


def _trigger_final_round(state: dict, triggering_player_id: str):
    """Set up the final round — every player (including trigger) gets one last turn."""
    state["phase"] = "final_round"
    order = state["turn_order"]
    idx = order.index(triggering_player_id)
    # Players after the triggering player still get one turn
    remaining = [order[(idx + i + 1) % len(order)] for i in range(len(order) - 1)]
    state["final_round_players_left"] = remaining

    cur = state["current_player_id"]
    state["current_player_id"] = order[(idx + 1) % len(order)]
    state["draw_step"] = 0

    if not remaining:
        _end_game(state)


# ---------------------------------------------------------------------------
# End game and scoring
# ---------------------------------------------------------------------------

def _end_game(state: dict):
    state["phase"] = "ended"
    scores = {}
    for pid, ps in state["player_states"].items():
        total = ps["route_score"]
        ticket_details = []
        for tid in ps["tickets"]:
            ticket = TICKET_BY_ID[tid]
            completed = is_path_connected(state, pid, ticket["city1"], ticket["city2"])
            delta = ticket["points"] if completed else -ticket["points"]
            total += delta
            ticket_details.append({"id": tid, "completed": completed, "delta": delta})
        scores[pid] = {
            "name": ps["name"],
            "color": ps["color"],
            "route_score": ps["route_score"],
            "tickets": ticket_details,
            "longest_path": 0,
            "total": total,
        }

    # Longest path bonus
    max_path = 0
    for pid in state["player_states"]:
        lp = longest_path(state, pid)
        scores[pid]["longest_path"] = lp
        if lp > max_path:
            max_path = lp

    winners_of_longest = [pid for pid in scores if scores[pid]["longest_path"] == max_path]
    for pid in winners_of_longest:
        scores[pid]["total"] += 10
        scores[pid]["longest_path_bonus"] = True

    state["scores"] = scores

    # Determine winner
    sorted_players = sorted(scores.items(), key=lambda x: (
        x[1]["total"],
        len([t for t in state["player_states"][x[0]]["tickets"]]),
        x[1]["longest_path"],
    ), reverse=True)
    state["winner_id"] = sorted_players[0][0]
    _log(state, f"Game ended! Winner: {scores[state['winner_id']]['name']}")


# ---------------------------------------------------------------------------
# Graph algorithms
# ---------------------------------------------------------------------------

def _build_player_graph(state: dict, player_id: str) -> dict[str, set[str]]:
    """Return adjacency list of routes owned by player_id."""
    graph: dict[str, set[str]] = defaultdict(set)
    for route_id_str, pid in state["claimed_routes"].items():
        if pid == player_id:
            route = ROUTE_BY_ID[int(route_id_str)]
            graph[route["city1"]].add(route["city2"])
            graph[route["city2"]].add(route["city1"])
    return graph


def is_path_connected(state: dict, player_id: str, city1: str, city2: str) -> bool:
    """BFS to check if city1 and city2 are connected in the player's network."""
    graph = _build_player_graph(state, player_id)
    if city1 not in graph:
        return False
    visited = set()
    queue = deque([city1])
    while queue:
        node = queue.popleft()
        if node == city2:
            return True
        if node in visited:
            continue
        visited.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)
    return False


def longest_path(state: dict, player_id: str) -> int:
    """DFS with backtracking to find the longest continuous path in the player's network."""
    # Build edge list (each route segment = 1 edge of a given length)
    edges: list[tuple[str, str, int]] = []
    edge_set: set[int] = set()  # used route IDs
    for route_id_str, pid in state["claimed_routes"].items():
        if pid == player_id:
            route = ROUTE_BY_ID[int(route_id_str)]
            edges.append((route["city1"], route["city2"], route["length"]))

    if not edges:
        return 0

    # Build adjacency with edge indices
    adj: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for i, (c1, c2, length) in enumerate(edges):
        adj[c1].append((c2, i, length))
        adj[c2].append((c1, i, length))

    cities = set()
    for c1, c2, _ in edges:
        cities.add(c1)
        cities.add(c2)

    best = [0]

    def dfs(city: str, used: set[int], current_length: int):
        best[0] = max(best[0], current_length)
        for neighbor, edge_idx, length in adj[city]:
            if edge_idx not in used:
                used.add(edge_idx)
                dfs(neighbor, used, current_length + length)
                used.remove(edge_idx)

    for start in cities:
        dfs(start, set(), 0)

    return best[0]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _log(state: dict, msg: str):
    state["action_log"].append(msg)
    if len(state["action_log"]) > 100:
        state["action_log"] = state["action_log"][-100:]


def get_public_state(state: dict, viewer_id: str) -> dict:
    """Return the game state suitable for sending to a specific player."""
    players_public = {}
    for pid, ps in state["player_states"].items():
        players_public[pid] = {
            "name": ps["name"],
            "color": ps["color"],
            "turn_order": ps["turn_order"],
            "trains": ps["trains"],
            "route_score": ps["route_score"],
            "ticket_count": len(ps["tickets"]),
            "card_count": sum(ps["hand"].values()),
            "hand": ps["hand"] if pid == viewer_id else {},
            "tickets": ps["tickets"] if pid == viewer_id else [],
            "pending_tickets": (
                [TICKET_BY_ID[t] for t in ps["pending_tickets"]]
                if pid == viewer_id else []
            ),
        }

    return {
        "phase": state["phase"],
        "face_up": state["face_up"],
        "deck_count": len(state["deck"]),
        "dest_deck_count": len(state["dest_deck"]),
        "claimed_routes": state["claimed_routes"],
        "current_player_id": state["current_player_id"],
        "turn_order": state["turn_order"],
        "draw_step": state["draw_step"],
        "players": players_public,
        "action_log": state["action_log"][-10:],
        "scores": state.get("scores", {}),
        "winner_id": state.get("winner_id"),
        "final_round_players_left": state.get("final_round_players_left", []),
    }
