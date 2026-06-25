"""
Evaluation harness for claude_bot.

Runs headless 2-player games (claude_bot vs opponent) and reports:
  - win rate
  - mean score differential (my_score - opponent_score)
  - avg total score for each side

Usage:
    python eval.py                    # 100 games, claude vs fish
    python eval.py --games 200 --opp chin_bot
    python eval.py --games 50  --seed 42

Players alternate seat order every game to remove first-mover bias.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import multiprocessing

parser = argparse.ArgumentParser()
parser.add_argument("--games",   type=int, default=100)
parser.add_argument("--opp",     type=str, default="fish_bot",
                    help="Opponent personality, or 'ladder' to run full evaluation ladder")
parser.add_argument("--seed",    type=int, default=0)
parser.add_argument("--claude",  type=str, default="claude_bot")
parser.add_argument("--iter",    type=int, default=40,
                    help="ISMCTS iterations per decision (default 40 for benchmarking)")
parser.add_argument("--policy",  type=str, default="heuristic",
                    choices=["random", "heuristic"],
                    help="Rollout policy (heuristic=stronger, random=faster)")
parser.add_argument("--workers", type=int,
                    default=min(4, multiprocessing.cpu_count()),
                    help="Parallel worker processes for game simulation")
_args, _ = parser.parse_known_args()

# Set env vars BEFORE any bot import so bot_entry reads them at module load time
os.environ["CLAUDE_BOT_ITER"]   = str(_args.iter)
os.environ["CLAUDE_BOT_POLICY"] = _args.policy

import random
import time
from tqdm import tqdm
import game_logic as logic
import bot as bot_module

logic.longest_path = lambda state, pid: 0   # too slow for bulk eval


# ---------------------------------------------------------------------------
# Worker init — called once per process in the pool
# ---------------------------------------------------------------------------

def _worker_init(iter_val: str, policy_val: str):
    """Set env vars and warm up imports for each pool worker."""
    os.environ["CLAUDE_BOT_ITER"]   = iter_val
    os.environ["CLAUDE_BOT_POLICY"] = policy_val
    import game_logic as _gl
    _gl.longest_path = lambda state, pid: 0
    import bot as _b
    _b._load_claude_agent()   # warm up lazy import


# ---------------------------------------------------------------------------
# Headless 2-player game runner
# ---------------------------------------------------------------------------

def run_game(personality_a: str, personality_b: str, seed: int,
             snapshot_fn=None) -> dict:
    """
    Run one complete 2-player game.
    Returns {"a_score": int, "b_score": int, "winner": "a"|"b"|"tie", "turns": int}

    snapshot_fn: optional callable(state, pid) called at the start of each
    draw_step==0 turn for personality_a's pid ("1").  Used to collect training
    data from ISMCTS games without a second game-runner loop.
    """
    random.seed(seed)

    configs = [
        {"pid": "1", "name": "A", "personality": personality_a},
        {"pid": "2", "name": "B", "personality": personality_b},
    ]

    players = [
        {"id": int(c["pid"]), "name": c["name"],
         "color": ["red", "blue"][i], "turn_order": i}
        for i, c in enumerate(configs)
    ]
    state       = logic.init_game_state(players, "usa")
    pid_to_pers = {c["pid"]: c["personality"] for c in configs}
    route_by_id, ticket_by_id = bot_module._get_map_data(state)

    for _ in range(3000):
        phase = state.get("phase")
        if phase == "ended":
            break

        if phase == "initial_tickets":
            acted = False
            for pid, ps in state["player_states"].items():
                if ps.get("pending_tickets"):
                    keep = bot_module.bot_keep_initial_tickets(
                        state, pid, ps["pending_tickets"], pid_to_pers[pid]
                    )
                    if len(keep) < 2:
                        keep = list(ps["pending_tickets"][:2])
                    logic.keep_initial_tickets(state, pid, keep)
                    acted = True
                    break
            if not acted:
                logic._advance_initial_tickets(state)
            continue

        if phase not in ("main", "final_round"):
            break

        cur_pid = state["current_player_id"]
        pers    = pid_to_pers.get(cur_pid, "fish_bot")
        ps      = state["player_states"].get(cur_pid, {})

        if ps.get("pending_tickets"):
            keep = bot_module.bot_keep_initial_tickets(
                state, cur_pid, ps["pending_tickets"], pers
            )
            if not keep:
                keep = ps["pending_tickets"][:1]
            logic.keep_drawn_tickets(state, cur_pid, keep)
            continue

        ds = state.get("draw_step", 0)
        if ds == 1:
            if not logic.draw_blind(state, cur_pid).get("ok"):
                logic._next_turn(state)
            continue

        # Snapshot current state for training data collection (personality_a only)
        if snapshot_fn is not None and cur_pid == "1" and ds == 0:
            snapshot_fn(state, cur_pid)

        fn = bot_module._DISPATCH.get(pers, bot_module._fish_turn)
        h  = dict(ps.get("hand", {}))
        t  = ps.get("trains", 45)
        try:
            action, params = fn(state, cur_pid, route_by_id, ticket_by_id,
                                h, t, ds, state["face_up"], state["claimed_routes"])
        except Exception:
            action, params = "draw_blind", {}

        def _do2():
            ps2 = state["player_states"].get(cur_pid, {})
            h2  = dict(ps2.get("hand", {}))
            t2  = ps2.get("trains", 45)
            try:
                a2, p2 = fn(state, cur_pid, route_by_id, ticket_by_id,
                            h2, t2, 1, state["face_up"], state["claimed_routes"])
            except Exception:
                a2, p2 = "draw_blind", {}
            if a2 == "draw_face_up":
                if not logic.draw_face_up(state, cur_pid, p2.get("slot", 0)).get("ok"):
                    logic.draw_blind(state, cur_pid)
            else:
                logic.draw_blind(state, cur_pid)

        if action == "claim":
            r = logic.claim_route(state, cur_pid, params["route_id"], params["cards"])
            if not r.get("ok"):
                logic.draw_blind(state, cur_pid)
                if state.get("draw_step", 0) == 1:
                    logic.draw_blind(state, cur_pid)
        elif action == "draw_tickets":
            r = logic.draw_destination_tickets(state, cur_pid)
            if r.get("ok"):
                fp   = state["player_states"].get(cur_pid, {})
                pend = fp.get("pending_tickets", [])
                keep = bot_module.bot_keep_initial_tickets(state, cur_pid, pend, pers)
                if not keep and pend:
                    keep = [pend[0]]
                if keep:
                    logic.keep_drawn_tickets(state, cur_pid, keep)
            else:
                logic.draw_blind(state, cur_pid)
        elif action == "draw_face_up":
            r = logic.draw_face_up(state, cur_pid, params.get("slot", 0))
            if r.get("ok"):
                if state.get("draw_step", 0) == 1:
                    _do2()
            else:
                logic.draw_blind(state, cur_pid)
                if state.get("draw_step", 0) == 1:
                    logic.draw_blind(state, cur_pid)
        else:
            if logic.draw_blind(state, cur_pid).get("ok"):
                if state.get("draw_step", 0) == 1:
                    _do2()
            else:
                logic._next_turn(state)

    scores = state.get("scores", {})
    a_score = scores.get("1", {}).get("total", 0)
    b_score = scores.get("2", {}).get("total", 0)
    if a_score > b_score:
        winner = "a"
    elif b_score > a_score:
        winner = "b"
    else:
        winner = "tie"
    return {"a_score": a_score, "b_score": b_score,
            "winner": winner, "turns": state.get("turns_taken", 0)}


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def _run_one(args):
    """Worker function: (claude_pers, opp_pers, i, base_seed) -> (cs, os_, winner_is_claude)"""
    claude_pers, opp_pers, i, base_seed = args
    if i % 2 == 0:
        res = run_game(claude_pers, opp_pers, seed=base_seed + i)
        cs, os_ = res["a_score"], res["b_score"]
        w = res["winner"] == "a"
        l = res["winner"] == "b"
    else:
        res = run_game(opp_pers, claude_pers, seed=base_seed + i)
        cs, os_ = res["b_score"], res["a_score"]
        w = res["winner"] == "b"
        l = res["winner"] == "a"
    return cs, os_, w, l


def benchmark(n_games: int, claude_pers: str, opp_pers: str, base_seed: int,
              n_workers: int = 1) -> dict:
    wins, losses, ties = 0, 0, 0
    diffs, claude_scores, opp_scores = [], [], []
    tasks = [(claude_pers, opp_pers, i, base_seed) for i in range(n_games)]

    desc    = f"{claude_pers} vs {opp_pers}"
    bar_fmt = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]{postfix}"

    t0 = time.time()

    with tqdm(total=n_games, desc=desc, unit="game", bar_format=bar_fmt,
              dynamic_ncols=True) as pbar:

        def _handle(cs, os_, w, l):
            nonlocal wins, losses, ties
            if w:   wins   += 1
            elif l: losses += 1
            else:   ties   += 1
            diff = cs - os_
            diffs.append(diff)
            claude_scores.append(cs)
            opp_scores.append(os_)
            done    = wins + losses + ties
            wr      = wins / done
            avg     = sum(diffs) / done
            outcome = "W" if w else ("L" if l else "T")
            pbar.set_postfix_str(
                f"{outcome}  claude={cs} opp={os_} diff={diff:+d} | "
                f"W/L/T {wins}/{losses}/{ties}  wr={wr:.0%}  avg={avg:+.1f}",
                refresh=False,
            )
            pbar.update(1)

        if n_workers > 1:
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(
                processes=n_workers,
                initializer=_worker_init,
                initargs=(str(_args.iter), _args.policy),
            ) as pool:
                for cs, os_, w, l in pool.imap_unordered(_run_one, tasks, chunksize=1):
                    _handle(cs, os_, w, l)
        else:
            for task in tasks:
                cs, os_, w, l = _run_one(task)
                _handle(cs, os_, w, l)

    elapsed = time.time() - t0
    return {
        "n_games":      n_games,
        "claude_pers":  claude_pers,
        "opp_pers":     opp_pers,
        "wins":         wins,
        "losses":       losses,
        "ties":         ties,
        "win_rate":     wins / n_games,
        "mean_diff":    sum(diffs)         / n_games,
        "mean_claude":  sum(claude_scores) / n_games,
        "mean_opp":     sum(opp_scores)    / n_games,
        "elapsed_s":    elapsed,
    }


def print_report(r: dict):
    sep = "=" * 58
    print(sep)
    print(f"  {r['claude_pers']} vs {r['opp_pers']}  ({r['n_games']} games)")
    print(sep)
    print(f"  Wins / Losses / Ties : {r['wins']} / {r['losses']} / {r['ties']}")
    print(f"  Win rate             : {r['win_rate']:.1%}")
    print(f"  Mean score diff      : {r['mean_diff']:+.1f}  (claude - opp)")
    print(f"  Mean claude score    : {r['mean_claude']:.1f}")
    print(f"  Mean opp score       : {r['mean_opp']:.1f}")
    print(f"  Elapsed              : {r['elapsed_s']:.1f}s "
          f"({r['elapsed_s']/r['n_games']*1000:.0f}ms/game wall-clock)")
    print(sep)


# ---------------------------------------------------------------------------
# Evaluation ladder — run vs all standard opponents, report table
# ---------------------------------------------------------------------------

# The held-out ladder opponents: never trained against, diverse styles.
# Ordered from weakest to strongest expected.
LADDER_RUNGS = [
    "chaos_bot",      # random noise / nearly random
    "greedy_bot",     # aggressive ticket-grabber
    "blocking_bot",   # blocker variant
    "rocket_bot",     # speed / early-spread
    "ticket_bot",     # ticket completionist
    "chin_bot",       # balanced collector
    "fish_bot",       # patient long-route (primary benchmark)
]


def ladder(n_games: int, claude_pers: str = "claude_bot", base_seed: int = 0,
           n_workers: int = 1) -> list:
    """
    Run claude_pers vs every rung in LADDER_RUNGS.
    Returns list of result dicts (one per rung), best-to-worst by win_rate.
    Flags regression if win_rate < 0.50 against any rung.
    """
    results = []
    sep = "=" * 58
    print(sep)
    print(f"  Evaluation Ladder  --  {claude_pers}  ({n_games} games/rung)")
    print(sep)
    print(f"  {'Opponent':<14}  {'W/L/T':>9}  {'WR':>6}  {'AvgDiff':>8}  {'ClaudeAvg':>10}")
    print(f"  {'-'*14}  {'-'*9}  {'-'*6}  {'-'*8}  {'-'*10}")

    for opp in LADDER_RUNGS:
        r = benchmark(n_games, claude_pers, opp, base_seed, n_workers)
        wlt = f"{r['wins']}/{r['losses']}/{r['ties']}"
        flag = "  <<REGRESSION" if r["win_rate"] < 0.50 else ""
        print(f"  {opp:<14}  {wlt:>9}  {r['win_rate']:>5.1%}  "
              f"{r['mean_diff']:>+8.1f}  {r['mean_claude']:>10.1f}{flag}")
        results.append(r)

    overall_wr = sum(r["wins"] for r in results) / (n_games * len(LADDER_RUNGS))
    overall_diff = sum(r["mean_diff"] for r in results) / len(LADDER_RUNGS)
    print(sep)
    print(f"  Overall WR: {overall_wr:.1%}  |  Mean diff across rungs: {overall_diff:+.1f}")
    print(sep)
    return results


def ladder_score(results: list) -> float:
    """Single scalar: mean win_rate across all rungs. Used for checkpoint selection."""
    if not results:
        return 0.0
    return sum(r["win_rate"] for r in results) / len(results)


if __name__ == "__main__":
    multiprocessing.freeze_support()   # required for Windows spawn
    args = parser.parse_args()
    if args.opp == "ladder":
        ladder(args.games, args.claude, args.seed, args.workers)
    else:
        r = benchmark(args.games, args.claude, args.opp, args.seed, args.workers)
        print_report(r)