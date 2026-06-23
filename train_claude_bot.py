"""
claude-bot training script.

Runs headless games of Ticket to Ride (USA map) between claude-bot, chin-bot,
and fish-bot. Uses hill-climbing to tune claude-bot's scoring weights until it
consistently beats both opponents.

Usage:
    python train_claude_bot.py [--rounds 50] [--games-per-round 20] [--map usa]

Results are saved to claude_bot_weights.json and printed after each round.
"""

import sys, os, json, random, copy, argparse, time
sys.path.insert(0, os.path.dirname(__file__))

import game_logic as logic
import bot as bot_module

WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "claude_bot_weights.json")

# ── Initial weights ──────────────────────────────────────────────────────────
# Start between fish-bot (long-route heavy) and chin-bot (balanced)
DEFAULT_WEIGHTS = {
    "length_weights": {1: 0.3, 2: 0.4, 3: 0.8, 4: 1.2, 5: 2.2, 6: 4.0},
    "ticket_weight":  1.8,
    "chain_bonus":    1.0,
    "loco_slot_bias": 0.7,   # 0=never grab loco face-up, 1=always
    "ticket_draw_threshold": 1,  # draw more tickets if uncompleted <= this
}

# Mutation scale per parameter
_MUTATE = {
    "length_weights": 0.3,
    "ticket_weight":  0.4,
    "chain_bonus":    0.3,
    "loco_slot_bias": 0.2,
    "ticket_draw_threshold": 0,  # discrete, don't mutate continuously
}


# ── Claude-bot turn function (parametrized) ──────────────────────────────────

def _claude_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed, weights):
    from game_logic import is_path_connected
    from collections import defaultdict

    lw = weights["length_weights"]
    tw = weights["ticket_weight"]
    cb = weights["chain_bonus"]
    loco_bias = weights["loco_slot_bias"]

    scored = bot_module._score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights={int(k): v for k, v in lw.items()},
        ticket_weight=tw,
        chain_bonus=cb,
    )

    # Step 0: try to claim the best route
    if draw_step == 0:
        for rid, _ in sorted(scored.items(), key=lambda x: -x[1]):
            route = route_by_id.get(rid)
            if not route or str(rid) in claimed:
                continue
            cards = bot_module._can_claim(hand, route, trains)
            if cards:
                return "claim", {"route_id": rid, "cards": cards}

    # Step 0: draw more tickets if few uncompleted
    if draw_step == 0 and state.get("phase") == "main":
        uncompleted = sum(
            1 for tid in state["player_states"].get(pid, {}).get("tickets", [])
            if (t := ticket_by_id.get(tid))
            and not is_path_connected(state, pid, t["city1"], t["city2"])
        )
        threshold = int(weights.get("ticket_draw_threshold", 1))
        dest_key = "europe_dest_deck" if state.get("map") == "europe" else "dest_deck"
        if uncompleted <= threshold and len(state.get(dest_key, state.get("dest_deck", []))) >= 3:
            return "draw_tickets", {}

    # Grab face-up loco based on bias
    if draw_step == 0 and random.random() < loco_bias:
        for i, card in enumerate(face_up):
            if card == "loco":
                return "draw_face_up", {"slot": i}

    # Face-up needed color
    needed = bot_module._needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ── Headless game simulator ───────────────────────────────────────────────────

def _bot_action(state, pid, personality, weights=None):
    """Return (action, params) for any bot personality, including claude-bot."""
    route_by_id, ticket_by_id = bot_module._get_map_data(state)
    ps        = state["player_states"].get(pid, {})
    hand      = dict(ps.get("hand", {}))
    trains    = ps.get("trains", 45)
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]

    if personality == "claude_bot" and weights:
        return _claude_turn(state, pid, route_by_id, ticket_by_id,
                            hand, trains, draw_step, face_up, claimed, weights)

    fn = bot_module._DISPATCH.get(personality, bot_module._fish_turn)
    return fn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed)


def _safe_second_draw(state, pid, personality, weights):
    try:
        a2, p2 = _bot_action(state, pid, personality, weights)
    except Exception:
        a2 = "draw_blind"
        p2 = {}
    if a2 == "draw_face_up":
        r = logic.draw_face_up(state, pid, p2["slot"])
        if not r.get("ok"):
            logic.draw_blind(state, pid)
    else:
        logic.draw_blind(state, pid)


def _run_bot_turn(state, pid, personality, weights=None):
    """Execute one full bot turn (claim or two draws). Returns False if game ended."""
    if state.get("phase") not in ("initial_tickets", "main", "final_round"):
        return False

    # Clear any stuck pending tickets
    ps = state["player_states"].get(pid, {})
    if ps.get("pending_tickets"):
        pending = ps["pending_tickets"]
        keep = bot_module.bot_keep_initial_tickets(state, pid, pending,
                                                    personality if personality != "claude_bot" else "fish_bot")
        if not keep:
            keep = pending[:1]
        logic.keep_drawn_tickets(state, pid, keep)
        return True

    if state.get("phase") == "initial_tickets":
        ps = state["player_states"].get(pid, {})
        pending = ps.get("pending_tickets", [])
        if pending:
            keep = bot_module.bot_keep_initial_tickets(state, pid, pending,
                                                        personality if personality != "claude_bot" else "fish_bot")
            logic.keep_initial_tickets(state, pid, keep)
        return True

    # Pending tunnel
    if state.get("pending_tunnel") and state["pending_tunnel"].get("player_id") == pid:
        proceed, extra = bot_module.bot_resolve_tunnel(state, pid,
                                                        personality if personality != "claude_bot" else "fish_bot")
        logic.resolve_tunnel(state, pid, proceed=proceed, extra_cards=extra if proceed else None)
        return True

    draw_step = state.get("draw_step", 0)
    if draw_step == 1:
        logic.draw_blind(state, pid)
        return True

    try:
        action, params = _bot_action(state, pid, personality, weights)
    except Exception:
        action, params = "draw_blind", {}

    if action == "claim":
        result = logic.claim_route(state, pid, params["route_id"], params["cards"])
        if not result.get("ok"):
            if logic.draw_blind(state, pid).get("ok"):
                _safe_second_draw(state, pid, personality, weights)

    elif action == "draw_tickets":
        result = logic.draw_destination_tickets(state, pid)
        if result.get("ok"):
            fresh_ps = state["player_states"].get(pid, {})
            pending = fresh_ps.get("pending_tickets", [])
            keep = bot_module.bot_keep_initial_tickets(state, pid, pending,
                                                        personality if personality != "claude_bot" else "fish_bot")
            if not keep:
                keep = pending[:1]
            logic.keep_drawn_tickets(state, pid, keep)
        else:
            if logic.draw_blind(state, pid).get("ok"):
                _safe_second_draw(state, pid, personality, weights)

    elif action == "draw_face_up":
        result = logic.draw_face_up(state, pid, params["slot"])
        if result.get("ok"):
            _safe_second_draw(state, pid, personality, weights)
        else:
            if logic.draw_blind(state, pid).get("ok"):
                _safe_second_draw(state, pid, personality, weights)

    else:
        if logic.draw_blind(state, pid).get("ok"):
            _safe_second_draw(state, pid, personality, weights)

    return True


def simulate_game(bot_configs, map_variant="usa", max_turns=500):
    """
    bot_configs: list of {"pid": str, "name": str, "personality": str, "weights": dict|None}
    Returns dict of {pid: total_score} and the winner pid.
    """
    players = [
        {"id": int(cfg["pid"]), "name": cfg["name"],
         "color": ["red","blue","green","yellow","black"][i % 5],
         "turn_order": i}
        for i, cfg in enumerate(bot_configs)
    ]
    state = logic.init_game_state(players, map_variant)

    pid_to_cfg = {cfg["pid"]: cfg for cfg in bot_configs}

    for _ in range(max_turns):
        phase = state.get("phase")
        if phase not in ("initial_tickets", "main", "final_round"):
            break

        if phase == "initial_tickets":
            # Advance all players with pending tickets
            made_progress = False
            for pid, ps in state["player_states"].items():
                if ps.get("pending_tickets"):
                    cfg = pid_to_cfg[pid]
                    _run_bot_turn(state, pid, cfg["personality"], cfg.get("weights"))
                    made_progress = True
                    break
            if not made_progress:
                # All initial tickets kept, transition to main
                logic._advance_initial_tickets(state)
        else:
            cur_pid = state["current_player_id"]
            cfg = pid_to_cfg.get(cur_pid)
            if not cfg:
                break
            _run_bot_turn(state, cur_pid, cfg["personality"], cfg.get("weights"))

    scores = state.get("scores", {})
    if not scores:
        # Game didn't end normally; calculate manually
        for pid in pid_to_cfg:
            ps = state["player_states"].get(pid, {})
            scores[pid] = {"name": ps.get("name", pid), "total": ps.get("route_score", 0)}

    winner = max(scores, key=lambda p: scores[p].get("total", 0)) if scores else None
    return {pid: scores[pid].get("total", 0) for pid in scores}, winner


# ── Mutation ──────────────────────────────────────────────────────────────────

def mutate(weights):
    w = copy.deepcopy(weights)
    # Perturb length_weights
    for k in list(w["length_weights"].keys()):
        delta = random.gauss(0, _MUTATE["length_weights"])
        w["length_weights"][k] = max(0.01, w["length_weights"][k] + delta)
    # Perturb scalars
    for key in ("ticket_weight", "chain_bonus", "loco_slot_bias"):
        delta = random.gauss(0, _MUTATE[key])
        w[key] = max(0.0, w[key] + delta)
    w["loco_slot_bias"] = min(1.0, w["loco_slot_bias"])
    return w


# ── Training loop ──────────────────────────────────────────────────────────────

def run_training(rounds=40, games_per_round=20, map_variant="usa"):
    # Load existing weights if available
    if os.path.exists(WEIGHTS_FILE):
        with open(WEIGHTS_FILE) as f:
            weights = json.load(f)
        print(f"Loaded existing weights from {WEIGHTS_FILE}")
    else:
        weights = copy.deepcopy(DEFAULT_WEIGHTS)
        print("Starting with default weights")

    def eval_weights(w, n_games):
        wins = 0
        total_scores = []
        for _ in range(n_games):
            configs = [
                {"pid": "1", "name": "claude-bot", "personality": "claude_bot", "weights": w},
                {"pid": "2", "name": "chin-bot",   "personality": "chin_bot",   "weights": None},
                {"pid": "3", "name": "fish-bot",   "personality": "fish_bot",   "weights": None},
            ]
            random.shuffle(configs)
            # Reassign turn order after shuffle
            for i, c in enumerate(configs):
                c["pid"] = str(i + 1)
            # Find claude-bot's pid
            claude_pid = next(c["pid"] for c in configs if c["name"] == "claude-bot")
            scores, winner = simulate_game(configs, map_variant)
            claude_score = scores.get(claude_pid, 0)
            total_scores.append(claude_score)
            if winner == claude_pid:
                wins += 1
        avg = sum(total_scores) / max(len(total_scores), 1)
        return wins / n_games, avg

    print(f"\n{'='*60}")
    print(f"  claude-bot training: {rounds} rounds × {games_per_round} games ({map_variant})")
    print(f"  Opponents: chin-bot, fish-bot")
    print(f"{'='*60}\n")

    # Baseline eval
    print("Evaluating baseline weights...")
    base_wr, base_avg = eval_weights(weights, games_per_round)
    best_wr  = base_wr
    best_avg = base_avg
    print(f"Baseline → win rate: {base_wr:.1%}  avg score: {base_avg:.0f}\n")

    history = [{"round": 0, "win_rate": base_wr, "avg_score": base_avg, "improved": True}]

    for rnd in range(1, rounds + 1):
        t0 = time.time()
        candidate = mutate(weights)
        cand_wr, cand_avg = eval_weights(candidate, games_per_round)
        elapsed = time.time() - t0

        # Accept if better win rate, or same win rate but better avg score
        improved = cand_wr > best_wr or (cand_wr == best_wr and cand_avg > best_avg)
        if improved:
            weights  = candidate
            best_wr  = cand_wr
            best_avg = cand_avg
            marker   = " ✓ IMPROVED"
        else:
            marker = ""

        history.append({"round": rnd, "win_rate": cand_wr, "avg_score": cand_avg, "improved": improved})
        print(f"Round {rnd:3d}/{rounds}  win rate: {cand_wr:.1%}  avg score: {cand_avg:.0f}  ({elapsed:.1f}s){marker}")
        print(f"         best so far: {best_wr:.1%}  avg {best_avg:.0f}")

        # Save weights after each improvement
        if improved:
            with open(WEIGHTS_FILE, "w") as f:
                json.dump(weights, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  Training complete!")
    print(f"  Final win rate vs chin-bot + fish-bot: {best_wr:.1%}")
    print(f"  Avg score: {best_avg:.0f}")
    print(f"  Weights saved to: {WEIGHTS_FILE}")
    print(f"{'='*60}\n")

    print("Learned weights:")
    for k, v in weights.items():
        print(f"  {k}: {v}")

    return weights, history


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds",          type=int, default=40)
    parser.add_argument("--games-per-round", type=int, default=20)
    parser.add_argument("--map",             type=str, default="usa", choices=["usa", "europe"])
    args = parser.parse_args()

    run_training(rounds=args.rounds, games_per_round=args.games_per_round, map_variant=args.map)
