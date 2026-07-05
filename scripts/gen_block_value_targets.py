"""塊(round)帰結 target 生成 — 単発 MC を捨て、 プランの帰結で value を訓練する第一歩。

docs/block_value_architecture.md Phase 1。 ExploitBeam self-play(=配備分布)を打ち、
各 target 手番頭 s_t に対し:
  - feat   : features(s_t, 0, v6=True)  (38dim)
  - mc     : 最終勝敗 z (0/1)            = 現状の単発 Monte Carlo ラベル(比較用)
  - v_self : 配備 value の P(win|s_t)     = 単発 static value 自身
  - v_next : 配備 value の P(win|s_{t+1}) = 1 round 後(=この塊①②③④を解決した後)の value
             (終局なら z)                = 塊の帰結(TD(1-round) bootstrap target)

塊帰結 target の狙い: Plan①(DON→攻撃) を打った s_t は s_{t+1} が良い盤面 → v_next 高、
Plan②(攻撃→DON無駄) を打った s_t は s_{t+1} が弱い盤面 → v_next 低。 単発 v_self や mc では
この「プランの帰結」が捉えられない。 v_next は配備 policy が実際に打った塊の帰結を測る。

まず target の質(mc vs v_next の分散・帰結相関)を analyze してから train_block_value に進む。

  .venv/bin/python scripts/gen_block_value_targets.py --deck cardrush_1454 \
      --opponents cardrush_1454 cardrush_1342 tcgportal_bonney tcgportal_calgara cardrush_1439 \
      --n-games 8 --out db/_analyst/blockval_cardrush_1454.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.core import Phase
from engine.exploit_beam_ai import ExploitBeamAI
from engine.gbm_value import features, gbm_score, SCALE

_REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(ROOT / "db" / "card_effects.json")


def _deck(slug):
    return make_deck_from_dict(
        json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8")), _REPO
    )


def _pwin(state, idx):
    """配備 value の P(win) を [0,1] で返す(未設定/失敗なら None)。"""
    s = gbm_score(state, idx)
    if s is None:
        return None
    return min(1.0, max(0.0, s / SCALE + 0.5))


_FEAT = "v6"  # main で --feat 設定(v6 / v11 / v12)
_MY_TEMP = 0.0  # 自分(target=idx0)の塊探索温度(>0=探索)。 相手は常に argmax(現最強)
_MY_GBM = None  # 自分(idx0)の value pkl 明示指定(= base v6 で打たせる等)。 None=auto-resolve


def _play(deck_t, deck_o, slug_t, slug_o, seed):
    """target=idx0 固定。 各 target 手番頭 s_t で (feat, v_self) を記録、
    塊帰結 v_next = 次 target 手番頭の P(win)(終局なら z) を後付けで解決。
    自分(idx0)= 温度探索(_MY_TEMP)、 相手(idx1)= argmax(=現最強、 塊を punish)。"""
    st = setup_game(deck_t, deck_o, rng=random.Random(seed),
                    first_player=seed % 2, effects_overlay=_OVERLAY)
    play_until_main(st)
    ais = [
        ExploitBeamAI(rng=random.Random(seed * 3 + 1), deck_analysis={"deck_slug": slug_t},
                      plan_temperature=_MY_TEMP, gbm_path=_MY_GBM),
        ExploitBeamAI(rng=random.Random(seed * 5 + 2), deck_analysis={"deck_slug": slug_o}),
    ]
    caps = []  # [(feat, v_self)] in target-turn order
    last_tp = None
    n = 0
    while not st.game_over and st.turn_number < 50 and n < 1500:
        cur = st.turn_player_idx
        if st.phase == Phase.MAIN and cur == 0 and cur != last_tp:  # target 手番頭のみ
            try:
                if _FEAT == "v12":
                    feat = features(st, 0, v12=True)
                elif _FEAT == "v11":
                    feat = features(st, 0, v11=True)
                else:
                    feat = features(st, 0, v6=True)
                caps.append((feat, _pwin(st, 0)))
            except Exception:
                pass
            last_tp = cur
        elif cur != 0:
            last_tp = cur
        try:
            play_one_action(st, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
    if not st.game_over:
        return []
    z = 1.0 if getattr(st, "winner", -1) == 0 else 0.0
    rows = []
    for i, (feat, v_self) in enumerate(caps):
        # 塊帰結: 次 target 手番頭の value。 無ければ(=最後の塊で決着)終局 z。
        v_next = caps[i + 1][1] if i + 1 < len(caps) else None
        if v_next is None:
            v_next = z
        rows.append({"feat": feat, "mc": z, "v_self": v_self, "v_next": v_next})
    return rows, z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--opponents", nargs="+", required=True)
    ap.add_argument("--n-games", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--value-path", default=None,
                    help="bootstrap 元 value pkl (既定 db/value_gbm_<deck>.pkl)")
    ap.add_argument("--feat", default="v6", choices=["v6", "v11", "v12"],
                    help="記録する特徴 (v11 = v6 + 防御-threat 3、 v12 = v11 + 中身バレ相手 4)")
    ap.add_argument("--seed-base", type=int, default=900,
                    help="対局 seed の基点 (= ラウンド毎に変えて新規対局を生成)")
    ap.add_argument("--my-temperature", type=float, default=0.0,
                    help="自分(idx0)の塊探索温度 (>0=探索して被覆↑、 相手は常に現最強argmax)")
    ap.add_argument("--my-gbm-path", default=None,
                    help="自分(idx0)の value pkl 明示指定 (= base v6 で打たせる等、 既定 auto-resolve)")
    a = ap.parse_args()
    global _FEAT, _MY_TEMP, _MY_GBM
    _FEAT = a.feat
    _MY_TEMP = a.my_temperature
    _MY_GBM = str(ROOT / a.my_gbm_path) if a.my_gbm_path else None

    vpath = a.value_path or str(ROOT / "db" / f"value_gbm_{a.deck}.pkl")
    if Path(vpath).exists():
        os.environ["ONEPIECE_GBM_VALUE_PATH"] = vpath
        print(f"[bootstrap value] {vpath}", flush=True)
    else:
        print(f"[bootstrap value] なし → v_self/v_next は board_eval 由来ではなく None フォールバック",
              flush=True)

    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    dt = _deck(a.deck)
    n_games = n_samp = 0
    n_win = 0
    with open(out, "w", encoding="utf-8") as f:
        for opp in a.opponents:
            do = _deck(opp)
            for i in range(a.n_games):
                res = _play(dt, do, a.deck, opp, a.seed_base + i)
                if not res:
                    continue
                rows, z = res
                for r in rows:
                    f.write(json.dumps(r) + "\n")
                    n_samp += 1
                f.flush()
                n_games += 1
                n_win += int(z)
                print(f"  {a.deck} vs {opp} seed{a.seed_base+i}: z={int(z)} (+{len(rows)} rounds)",
                      flush=True)
    print(f"\n[done] {n_games} games, {n_samp} round-samples, target 勝率={n_win/max(1,n_games)*100:.0f}% "
          f"-> {out}")


if __name__ == "__main__":
    main()
