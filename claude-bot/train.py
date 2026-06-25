"""
Self-play training for claude_bot value function.

Stage 5 in the build plan:
  1. Run N 2-player self-play games (heuristic policy for speed)
  2. At every turn, record (features, final_score_diff) pairs
  3. Train value.py model on collected pairs
  4. Save weights → loaded automatically by bot_entry.py

Usage
-----
    python train.py                          # 200 games, linear model
    python train.py --games 500 --model mlp
    python train.py --games 200 --eval 20   # also benchmark after training

Population pool (rounds)
------------------------
    python train.py --rounds 5 --games 100  # 5 rounds of 100 games each,
                                             # re-training after each round
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import random
import copy
import time
import json

import game_logic as logic
import bot as bot_module

from features import extract
from value import ValueModel, _MODEL_DIR
from rollout import heuristic_policy
from adapter import apply_move, is_terminal, terminal_score, current_player

logic.longest_path = lambda state, pid: 0   # skip for speed during training

# Data directory for training files
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


# ---------------------------------------------------------------------------
# Data collection — one game → list of (features, final_score) pairs
# ---------------------------------------------------------------------------

def _collect_game(seed: int, sample_every: int = 3) -> list:
    """
    Play one full game with heuristic_policy for both players.
    Every `sample_every` turns, snapshot features for pid "1".
    Returns list of (features, final_score_diff_for_pid_1).
    """
    random.seed(seed)
    players = [
        {"id": 1, "name": "A", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "B", "color": "blue", "turn_order": 1},
    ]
    state = logic.init_game_state(players, "usa")
    route_by_id, ticket_by_id = bot_module._get_map_data(state)

    # Initial ticket phase
    for pid in ["1", "2"]:
        ps = state["player_states"][pid]
        pend = ps.get("pending_tickets", [])
        if pend:
            logic.keep_initial_tickets(state, pid, pend[:2])
    while state.get("phase") == "initial_tickets":
        logic._advance_initial_tickets(state)

    snapshots = []  # (features_at_turn_t, ...)
    turns = 0

    for _ in range(3000):
        if is_terminal(state):
            break
        phase = state.get("phase")
        if phase not in ("main", "final_round"):
            break

        cur = current_player(state)
        if not cur:
            break

        ps = state["player_states"].get(cur, {})
        if ps.get("pending_tickets"):
            pend = ps["pending_tickets"]
            res = logic.keep_drawn_tickets(state, cur, pend)
            if not res.get("ok") and pend:
                logic.keep_drawn_tickets(state, cur, pend[:1])
            continue

        # Snapshot from pid "1"'s perspective every few turns
        if turns % sample_every == 0:
            snapshots.append(extract(state, "1"))

        action, params = heuristic_policy(state, cur)
        apply_move(state, cur, action, params)
        turns += 1

    final = terminal_score(state, "1")   # score_diff for pid "1"
    return [(feat, final) for feat in snapshots]


def collect_data(n_games: int, sample_every: int = 3) -> tuple:
    """Returns (X, y) where X is list of feature lists, y is list of floats."""
    X, y = [], []
    t0 = time.time()
    for i in range(n_games):
        pairs = _collect_game(seed=i, sample_every=sample_every)
        for feat, score in pairs:
            X.append(feat)
            y.append(score)
        if (i + 1) % 20 == 0 or i == n_games - 1:
            elapsed = time.time() - t0
            print(f"  collected {i+1}/{n_games} games  "
                  f"({len(X)} samples, {elapsed:.1f}s)")
    return X, y


# ---------------------------------------------------------------------------
# ISMCTS-game data collection (correct training distribution)
# ---------------------------------------------------------------------------

_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "training_data.json")


def collect_ismcts_data(n_games: int, opp: str = "fish_bot",
                        n_iter: int = 20) -> tuple:
    """
    Run ISMCTS-vs-opp games and collect (features, final_score) pairs.
    Saves to disk after every game so progress survives a kill.
    n_iter controls ISMCTS depth during data collection (lower = faster games).
    """
    import importlib.util as _ilu

    _eval_path = os.path.join(os.path.dirname(__file__), "eval.py")
    spec = _ilu.spec_from_file_location("eval_mod", _eval_path)
    eval_mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(eval_mod)
    os.environ["CLAUDE_BOT_VALUE"] = "off"
    os.environ["CLAUDE_BOT_ITER"] = str(n_iter)  # override for fast data collection

    # Load existing data so we can resume or accumulate
    os.makedirs(os.path.dirname(_DATA_FILE), exist_ok=True)
    if os.path.exists(_DATA_FILE):
        with open(_DATA_FILE) as f:
            saved = json.load(f)
        X, y = saved["X"], saved["y"]
        start_seed = saved.get("n_games", 0)
        print(f"  Resuming: loaded {len(X)} existing samples (from {start_seed} games)", flush=True)
    else:
        X, y = [], []
        start_seed = 0

    t0 = time.time()
    for i in range(n_games):
        seed = start_seed + i
        snapshots = []

        def _snap(state, pid, _buf=snapshots):
            _buf.append(extract(state, pid))

        result = eval_mod.run_game("claude_bot", opp, seed=seed, snapshot_fn=_snap)
        final_diff = (result["a_score"] - result["b_score"]) / 100.0

        for feat in snapshots:
            X.append(feat)
            y.append(final_diff)

        # Save to disk after every game so a kill loses at most 1 game
        with open(_DATA_FILE, "w") as f:
            json.dump({"X": X, "y": y, "n_games": start_seed + i + 1}, f)

        elapsed = time.time() - t0
        rate = (i + 1) / elapsed
        remaining = (n_games - i - 1) / rate if rate > 0 else 0
        print(f"  game {i+1}/{n_games}  samples={len(X)}  "
              f"{elapsed:.0f}s elapsed  ~{remaining:.0f}s left", flush=True)

    return X, y


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(n_games: int = 200, model_type: str = "linear",
          sample_every: int = 3, use_ismcts: bool = False,
          n_iter: int = 20) -> ValueModel:
    if use_ismcts:
        print(f"\n=== Collecting ISMCTS data ({n_games} games, iter={n_iter}) ===", flush=True)
        X, y = collect_ismcts_data(n_games, n_iter=n_iter)
    else:
        print(f"\n=== Collecting data ({n_games} games, sample every {sample_every} turns) ===", flush=True)
        X, y = collect_data(n_games, sample_every)
    print(f"  Total samples: {len(X)}", flush=True)

    print(f"\n=== Training {model_type} value model ===", flush=True)
    if model_type == "mlp":
        model = ValueModel.new_mlp()
        model.fit(X, y, lr=0.005, epochs=100)
    else:
        model = ValueModel()
        model.fit(X, y, lr=0.005, epochs=500)

    train_mse = model.mse(X, y)
    print(f"  Train MSE: {train_mse:.4f}  (RMSE: {train_mse**0.5:.4f})", flush=True)

    model.save()
    print(f"  Saved to claude-bot/model/value_weights.json", flush=True)
    return model


# ---------------------------------------------------------------------------
# Optional post-training benchmark (calls eval.py benchmark())
# ---------------------------------------------------------------------------

def _run_eval(n_eval_games: int):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "eval_mod",
            os.path.join(os.path.dirname(__file__), "eval.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        r = mod.benchmark(n_eval_games, "claude_bot", "fish_bot", base_seed=9999,
                          n_workers=1)
        mod.print_report(r)
    except Exception as exc:
        print(f"  (eval failed: {exc})")


# ---------------------------------------------------------------------------
# Stage 5: Population pool self-play training
# ---------------------------------------------------------------------------

# The diverse pool of opponents to train against (from bot.py _DISPATCH)
_POOL = [
    "fish_bot",      # patient long-route heuristic (primary benchmark)
    "chin_bot",      # balanced collector
    "rocket_bot",    # speed / early-spread
    "ticket_bot",    # ticket completionist
    "chaos_bot",     # noise / random
    "greedy_bot",    # aggressive ticket-grabber
    "blocking_bot",  # blocker variant
]

# Checkpoint directory
_CKPT_DIR = os.path.join(_MODEL_DIR, "checkpoints")


def _save_checkpoint(round_num: int):
    """Copy current value_weights.json to checkpoints/round_NNN.json."""
    os.makedirs(_CKPT_DIR, exist_ok=True)
    src = os.path.join(_MODEL_DIR, "value_weights.json")
    if not os.path.exists(src):
        return
    import shutil
    dst = os.path.join(_CKPT_DIR, f"round_{round_num:03d}.json")
    shutil.copy(src, dst)
    print(f"  Checkpoint saved: {dst}")


def _eval_ladder(n_games: int, n_workers: int = 1) -> float:
    """Run evaluation ladder; return mean win rate across all rungs."""
    import importlib.util as _ilu
    _eval_path = os.path.join(os.path.dirname(__file__), "eval.py")
    spec = _ilu.spec_from_file_location("eval_mod2", _eval_path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Force n_workers=1: dynamically-loaded module can't be pickled for spawn workers
    results = mod.ladder(n_games, "claude_bot", base_seed=99999, n_workers=1)
    return mod.ladder_score(results)


def population_pool_training(
    rounds: int = 10,
    games_per_round: int = 50,
    model_type: str = "linear",
    eval_games: int = 10,
    n_workers: int = 1,
):
    """
    Stage 5 self-play training.

    Each round:
    1. Pick a random opponent from the pool.
    2. Collect games_per_round ISMCTS games vs that opponent.
    3. Retrain value model on ALL accumulated data so far.
    4. Evaluate on the held-out ladder.
    5. If ladder score improves, save checkpoint.
    6. Periodically inject a past checkpoint into the pool (diversity).
    """
    print(f"\n{'='*60}")
    print(f"  Stage 5: Population Pool Training")
    print(f"  {rounds} rounds x {games_per_round} games | pool: {_POOL}")
    print(f"{'='*60}\n")

    all_X: list = []
    all_y: list = []
    best_score: float = 0.0
    pool = list(_POOL)   # mutable copy; may gain checkpoint opponents

    for rnd in range(1, rounds + 1):
        opp = random.choice(pool)
        print(f"\n--- Round {rnd}/{rounds}: vs {opp} ---")

        # Collect data vs chosen pool member
        X, y = collect_ismcts_data(games_per_round, opp=opp)
        all_X.extend(X)
        all_y.extend(y)
        print(f"  Accumulated samples: {len(all_X)}")

        # Retrain on ALL accumulated data
        print(f"  Training {model_type} model on {len(all_X)} samples...")
        if model_type == "mlp":
            model = ValueModel.new_mlp()
            model.fit(all_X, all_y, lr=0.005, epochs=100)
        else:
            model = ValueModel()
            model.fit(all_X, all_y, lr=0.005, epochs=500)
        train_mse = model.mse(all_X, all_y)
        print(f"  Train MSE: {train_mse:.4f}")
        model.save()

        # Evaluate on held-out ladder
        print(f"\n  Evaluating on ladder ({eval_games} games/rung)...")
        score = _eval_ladder(eval_games, n_workers)

        print(f"\n  Ladder score: {score:.3f}  (best so far: {best_score:.3f})")
        _save_checkpoint(rnd)

        if score > best_score:
            best_score = score
            print(f"  ** New best! ({score:.3f}) **")
        else:
            print(f"  No improvement this round.")

    print(f"\n{'='*60}")
    print(f"  Training complete. Best ladder score: {best_score:.3f}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="claude_bot value function trainer")
    parser.add_argument("--games",          type=int, default=200,
                        help="Games to collect per training run / per pool round")
    parser.add_argument("--model",          type=str, default="linear",
                        choices=["linear", "mlp"])
    parser.add_argument("--rounds",         type=int, default=1,
                        help="Stage 5 population-pool training rounds")
    parser.add_argument("--sample-every",   type=int, default=3,
                        help="Snapshot features every N turns (heuristic mode only)")
    parser.add_argument("--ismcts",         action="store_true",
                        help="Collect training data from ISMCTS games (correct distribution)")
    parser.add_argument("--iter",           type=int, default=20,
                        help="ISMCTS iterations per decision during data collection (lower=faster)")
    parser.add_argument("--pool",           action="store_true",
                        help="Run Stage 5 population pool training (implies --ismcts, --rounds>1)")
    parser.add_argument("--eval-games",     type=int, default=10,
                        help="Games per rung on the evaluation ladder (--pool mode)")
    parser.add_argument("--workers",        type=int, default=1,
                        help="Parallel workers for ladder evaluation")
    parser.add_argument("--eval",           type=int, default=0,
                        help="If >0, run N eval games vs fish_bot after training")
    args = parser.parse_args()

    if args.pool:
        population_pool_training(
            rounds=max(args.rounds, 3),
            games_per_round=args.games,
            model_type=args.model,
            eval_games=args.eval_games,
            n_workers=args.workers,
        )
    elif args.rounds > 1:
        # Simple repeated training without pool selection
        for rnd in range(1, args.rounds + 1):
            print(f"\n--- Round {rnd}/{args.rounds} ---")
            train(args.games, args.model, getattr(args, "sample_every", 3),
                  use_ismcts=args.ismcts)
    else:
        model = train(args.games, args.model, getattr(args, "sample_every", 3),
                      use_ismcts=args.ismcts, n_iter=args.iter)

    if args.eval > 0:
        print(f"\n=== Post-training eval ({args.eval} games vs fish_bot) ===")
        _run_eval(args.eval)
