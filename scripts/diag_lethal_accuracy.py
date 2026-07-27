# -*- coding: utf-8 -*-
"""リーサル計算器の精度診断 (2026-07-27、 ohtsuki「精度どんな感じ?」)。

配備 EBV2(per-attack + delta)がリーサルを宣言(発火)した時、 実際にそのターンに勝てたかを突合:
  - misfire率 = 発火したのに相手が生存(そのターンに勝てなかった)割合
  - calibration = 予測 p_lethal のバケツ別 実成功率(予測 0.7 → 実際 ~0.7 なら calibrated)
_compute_lethal_action の ONEPIECE_LETHAL_DIAG フックが (turn, player, p_lethal) を記録。

  DIAG_SLUG=cardrush_1454 DIAG_N=200 DIAG_WORKERS=12 .venv/bin/python scripts/diag_lethal_accuracy.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

os.environ["ONEPIECE_LETHAL_DIAG"] = "1"
sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
import engine.ai as _AI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("DIAG_SLUG", "cardrush_1454")


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _ebv2(seed):
    return ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                         deck_analysis={"deck_slug": SLUG})


def _one(seed):
    _AI._LETHAL_DIAG_LOG.clear()
    fp = seed % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [_ebv2(seed * 5 + 1), _ebv2(seed * 7 + 3)]
    n = 0
    while not state.game_over and state.turn_number < 60 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not state.game_over:
        return None
    winner = getattr(state, "winner", -1)
    end_turn = state.turn_number
    # (turn, player) 単位に dedup (発火は attach+attack で複数回) → 最大 p_lethal を採用
    fires = {}
    for (t, p, pw) in list(_AI._LETHAL_DIAG_LOG):
        key = (t, p)
        fires[key] = max(fires.get(key, 0.0), pw)
    # 各発火の成功 = そのターンにその player が勝った
    out = []
    for (t, p), pw in fires.items():
        success = (t == end_turn and winner == p)
        out.append((pw, success))
    return out


def main():
    n = int(os.environ.get("DIAG_N", "200"))
    workers = int(os.environ.get("DIAG_WORKERS", "12"))
    seeds = list(range(9000, 9000 + n))
    t0 = time.time()
    print(f"[diag_lethal_acc] {SLUG}  EBV2(per-attack+delta)  N={n} games", flush=True)
    with mp.Pool(workers) as p:
        res = [r for r in p.map(_one, seeds) if r]
    fires = [f for game in res for f in game]
    if not fires:
        print("  リーサル発火 0 (= 発火頻度が低い、 N を増やすか閾値確認)", flush=True)
        return
    n_fire = len(fires)
    n_success = sum(1 for pw, s in fires if s)
    print(f"  リーサル発火 {n_fire} 回 ({len(res)} games, {time.time()-t0:.0f}s)", flush=True)
    print(f"  ✅ 成功率 = {n_success/n_fire*100:.0f}%  /  ⚠ misfire率(発火→相手生存) = "
          f"{(n_fire-n_success)/n_fire*100:.0f}%", flush=True)
    # calibration: p_lethal バケツ別 実成功率
    buckets = defaultdict(lambda: [0, 0])   # bucket -> [success, total]
    for pw, s in fires:
        b = min(9, int(pw * 10)) / 10.0   # 0.0,0.1,...,0.9
        buckets[b][1] += 1
        if s:
            buckets[b][0] += 1
    print("  calibration (予測 p_lethal → 実成功率):", flush=True)
    for b in sorted(buckets):
        suc, tot = buckets[b]
        print(f"    予測 {b:.1f}-{b+0.1:.1f}: 実 {suc/tot*100:3.0f}%  (n={tot})", flush=True)


if __name__ == "__main__":
    main()
