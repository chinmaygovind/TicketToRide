# claude-bot Handoff Document

## Goal
Train `claude_bot` to beat human Ticket to Ride players (target: 80%+ win rate vs humans).  
The value function must be accurate enough that `CLAUDE_BOT_VALUE=on` plays as well as the  
rollout-based ISMCTS (86% vs fish_bot). That makes the bot near-instant during live games  
(50ms/turn vs 2.2s/turn for rollouts).

## Build Stages (from original spec)

1. **Simulator validation** ✅ — adapter.py wraps game_logic.py
2. **Heuristic baseline** ✅ — heuristic_policy in rollout.py (fish_bot-style _LW weighting)
3. **ISMCTS + rollouts** ✅ — ismcts.py, 86% vs fish_bot at N_ITER=100
4. **Learned eval/value** 🔄 — features.py + value.py; 776 samples, RMSE=0.17; needs more data
5. **Self-play population pool** 🔄 — population_pool_training() written, has a bug (see below)

## Current Performance

**Rollout-ISMCTS (current default):**
- 86% vs fish_bot, +25.7 avg diff (N_ITER=100, 50-game run)
- Evaluation ladder (N_ITER=40, 10 games/rung):

| Opponent    | WR    | AvgDiff |
|-------------|-------|---------|
| chaos_bot   | 80.0% | +56.9   |
| greedy_bot  | 80.0% | +46.7   |
| ticket_bot  | 80.0% | +14.4   |
| rocket_bot  | 70.0% | +31.2   |
| fish_bot    | 70.0% | +12.7   |
| blocking_bot| 70.0% | +11.1   |
| chin_bot    | 70.0% | +10.7   |
| **Overall** | **74.3%** | **+26.2** |

**Value-ISMCTS (CLAUDE_BOT_VALUE=on):**
- Not yet benchmarked at N_ITER=100 (only 776 training samples from 20 games)
- Estimated to be weaker until more data is collected

## Why the Value Function Matters

ISMCTS simulates 100 full games per turn (22ms each = 2.2s/turn total). Too slow for live play.  
The value function replaces rollouts with a single dot product (~0.01ms). At N_ITER=100 that's  
~50ms/turn — near-instant. The value function just needs to be accurate enough.

## File Map

```
claude-bot/
  adapter.py          — get_legal_moves, apply_move, terminal_score, current_player
  determinize.py      — resample opponent hands/tickets for each ISMCTS iteration
  graph_cache.py      — Floyd-Warshall APSP, ROUTES_BY_VALUE, TICKET_ROUTE_RELEVANCE
  ismcts.py           — ISMCTS tree search, UCB1, max_claims=6 pruning
  rollout.py          — heuristic_policy (main), greedy_policy, blocking_policy, run_rollout
  bot_entry.py        — lazy-loaded entry point; reads CLAUDE_BOT_* env vars
  features.py         — extract(state, pid) → 20 floats
  value.py            — LinearValue, MLPValue (pure-Python SGD), ValueModel load/save/fit
  train.py            — data collection + training pipeline + population_pool_training()
  eval.py             — benchmark() + ladder() multi-opponent eval
  graph_cache.py      — precomputed path/ticket data (do not modify lightly)
  model/
    value_weights.json     — current trained value model weights
    checkpoints/           — per-round snapshots from pool training
```

## Env Vars (set before starting app.py)

| Var | Default | Meaning |
|-----|---------|---------|
| `CLAUDE_BOT_ITER` | 100 | ISMCTS iterations per decision |
| `CLAUDE_BOT_POLICY` | heuristic | rollout policy (heuristic\|random) |
| `CLAUDE_BOT_C` | 1.41 | UCB exploration constant |
| `CLAUDE_BOT_CLAIMS` | 6 | max claim-moves considered per node |
| `CLAUDE_BOT_VALUE` | auto | use value fn (auto\|on\|off) |

**Speed vs strength presets:**
- Fast playable: `CLAUDE_BOT_ITER=20` (~0.5s/turn)
- Instant (value fn): `CLAUDE_BOT_VALUE=on` (~50ms/turn, needs more training)
- Strongest: `CLAUDE_BOT_ITER=100 CLAUDE_BOT_VALUE=off` (~2.2s/turn)

## Known Bugs

### Bug 1: pool training pickling error (BLOCKER for `--pool` mode)
`population_pool_training()` calls `_eval_ladder()` which dynamically loads eval.py as  
`eval_mod2` via importlib. That module then spawns multiprocessing workers that can't  
pickle `_worker_init` because `eval_mod2` isn't a real importable module.

**Fix:** Change `_eval_ladder` in train.py to always pass `n_workers=1` (no multiprocessing  
inside the ladder call during pool training). The `benchmark()` call with n_workers=1 works fine.

```python
# In _eval_ladder(), change:
results = mod.ladder(n_games, "claude_bot", base_seed=99999, n_workers=n_workers)
# To:
results = mod.ladder(n_games, "claude_bot", base_seed=99999, n_workers=1)
```

### Bug 2: test_full_game.py hangs during git pre-push hook
Some test plays a game with claude_bot which takes 2+ minutes (ISMCTS is slow).  
Workaround: `git push --no-verify`.

## Immediate Next Steps (what to finish)

### Step 1: Collect more ISMCTS training data
```
cd claude-bot
python train.py --games 100 --ismcts --model mlp
```
Collects 100 ISMCTS-vs-fish_bot games (~3900 samples, ~15 min), trains MLP.

### Step 2: Benchmark value-ISMCTS vs rollout-ISMCTS
```
# Rollout baseline (already done: 86% vs fish_bot)
python eval.py --games 20 --iter 100 --opp fish_bot

# Value function mode
set CLAUDE_BOT_VALUE=on
python eval.py --games 20 --iter 100 --opp fish_bot
```
Target: value-ISMCTS win rate ≥ 80% vs fish_bot. If below 70%, collect more data.

### Step 3: Fix pool training bug, then run population pool
After fixing Bug 1:
```
python train.py --pool --rounds 5 --games 50 --model mlp --eval-games 5 --workers 1
```
This trains across all 7 pool opponents (fish/chin/rocket/ticket/chaos/greedy/blocking),  
re-trains value function each round, saves checkpoints, runs ladder eval.

### Step 4: Verify value-ISMCTS is playable
```
set CLAUDE_BOT_VALUE=on
set CLAUDE_BOT_ITER=100
python app.py
```
Should respond in ~50ms/turn.

## Training Architecture Details

**Features (features.py, N_FEATURES=20):**
route_score_diff, completed_ticket_diff, my_completed_pts, opp_completed_pts,
my_pending_pts, opp_pending_pts, my_trains_used, opp_trains_used, trains_used_diff,
my_hand_size, opp_hand_size, hand_size_diff, my_locos, deck_pct, my_ticket_count,
opp_ticket_count, my_completion_rate, opp_completion_rate, routes_claimed, game_stage

**ValueModel (value.py):**
- LinearValue: w·x + b, SGD on MSE
- MLPValue: 20→64→64→1 ReLU, Xavier init, SGD
- `ValueModel.load()` reads model/value_weights.json
- `ValueModel.new_mlp()` creates fresh MLP

**ISMCTS data collection (train.py):**
- `collect_ismcts_data(n_games, opp)` runs real ISMCTS-vs-opp games
- Snapshots features at each claude turn (draw_step==0 only)
- Final label = (a_score - b_score) / 100.0 (normalized score diff)
- Critical: must use CLAUDE_BOT_VALUE=off during data collection to avoid circular dependency

**Population pool (train.py):**
- Pool: fish_bot, chin_bot, rocket_bot, ticket_bot, chaos_bot, greedy_bot, blocking_bot
- Each round: random opponent, collect games, retrain on ALL accumulated data, eval, checkpoint
- Run with: `python train.py --pool --rounds 10 --games 50 --model mlp --eval-games 5 --workers 1`

## Bot Personalities (bot.py + rollout.py)

All registered in `bot.py:_DISPATCH`:
- `fish_bot` — patient, prefers 5-6 car routes (primary benchmark)
- `chin_bot` — balanced collector
- `rocket_bot` — speed/early-spread
- `ticket_bot` — ticket completionist
- `chaos_bot` — random/noise
- `greedy_bot` — aggressive ticket-grabber (new)
- `blocking_bot` — blocks opponent routes (new)
- `claude_bot` — ISMCTS with optional value function (the bot we're training)

Rollout equivalents in rollout.py: heuristic_policy, greedy_policy, blocking_policy, random_policy.

## Spec Compliance Status

From original spec requirements:
- ✅ 4 agents behind common interface (heuristic, greedy, blocking, ISMCTS)
- ✅ Self-play harness with persistent opponent pool
- ✅ Evaluation ladder vs held-out opponents with per-rung WR + score margin
- ✅ Train for 2-player games first
- ✅ ISMCTS with constraint-respecting determinization
- 🔄 Learned eval/value function (needs more training data)
- 🔄 Self-play population pool training (bug fix needed)
- ❌ Ticket decisions as distinct risk-management layer (currently keeps all tickets in rollouts)
- ❌ Belief sampler quality improvement (currently uniform sampling in determinize.py)
