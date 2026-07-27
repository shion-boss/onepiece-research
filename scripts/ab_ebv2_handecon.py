# -*- coding: utf-8 -*-
"""baseline EBV2 vs 「相手手札削りモード」EBV2(= EBV2 + hand_economy)の観察 (2026-07-27)。

両者とも配備 EBV2(ExploitBeam + agnostic value)。 A 側だけ hand_economy(要求値+エンジン除去+
timing で相手手札経済を削る)を _hand_econ_w で ON。 = value(頭脳)は同一、 「相手手札を削る意識」
だけが違う。 観察:
  1. 勝率(削り意識で強くなるか)
  2. **相手手札をより低く抑えるか**(= モードが実際に効いているか): 各手番後の相手手札を集計し、
     A のターン後 vs B のターン後 で比較。 A < B なら「削りモードが実際に相手手札を削っている」。

  HE_SLUG=cardrush_1454 HE_W=3.0 HE_N=60 HE_WORKERS=10 .venv/bin/python scripts/ab_ebv2_handecon.py
"""
import sys, os, random, time, json
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, os.getcwd())
from engine.deck import CardRepository, make_deck_from_dict
from engine.effects import load_effect_overlay
from engine.game import setup_game, play_until_main
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI

REPO_ROOT = Path(os.getcwd())
_REPO = CardRepository.from_json(REPO_ROOT / "db" / "cards.json")
_OVERLAY = load_effect_overlay(REPO_ROOT / "db" / "card_effects.json")
SLUG = os.environ.get("HE_SLUG", "cardrush_1454")
W = float(os.environ.get("HE_W", "3.0"))


def _load():
    return make_deck_from_dict(
        json.loads((REPO_ROOT / "decks" / f"{SLUG}.json").read_text(encoding="utf-8")), _REPO)


def _ebv2(seed, hand_econ):
    ai = ExploitBeamAI(rng=random.Random(seed), beam_width=16, max_depth=10,
                       deck_analysis={"deck_slug": SLUG})
    if hand_econ:
        ai._hand_econ_w = W
    return ai


def _one(seed):
    a_idx = seed % 2            # A(削りモード)がどちら側か
    fp = (seed // 2) % 2
    state = setup_game(_load(), _load(), rng=random.Random(seed),
                       first_player=fp, effects_overlay=_OVERLAY)
    play_until_main(state)
    ais = [None, None]
    ais[a_idx] = _ebv2(seed * 5 + 1, hand_econ=True)     # A = 削りモード EBV2
    ais[1 - a_idx] = _ebv2(seed * 7 + 3, hand_econ=False)  # B = baseline EBV2
    a_opp_hand, b_opp_hand = [], []   # A/B のターン直後の相手手札
    n = 0
    while not state.game_over and state.turn_number < 50 and n < 1500:
        cur = state.turn_player_idx
        try:
            play_one_action(state, ais[cur], ais[1 - cur])
        except Exception:
            break
        n += 1
        # ターンが切り替わった瞬間 = 直前の手番プレイヤーの攻撃が終わった → 相手手札を記録
        if state.turn_player_idx != cur or state.game_over:
            opp_hand = len(state.players[1 - cur].hand)
            if cur == a_idx:
                a_opp_hand.append(opp_hand)
            else:
                b_opp_hand.append(opp_hand)
    if not state.game_over:
        return None
    w = getattr(state, "winner", -1)
    res = "A" if w == a_idx else ("B" if w == (1 - a_idx) else None)
    ma = sum(a_opp_hand) / max(1, len(a_opp_hand))
    mb = sum(b_opp_hand) / max(1, len(b_opp_hand))
    return (res, ma, mb)


def main():
    n = int(os.environ.get("HE_N", "60"))
    workers = int(os.environ.get("HE_WORKERS", "10"))
    seeds = list(range(6000, 6000 + n))
    t0 = time.time()
    print(f"[ebv2_handecon] {SLUG}  A(EBV2+削りモード w={W}) vs B(EBV2 baseline)  N={n}", flush=True)
    with mp.Pool(workers) as p:
        res = [r for r in p.map(_one, seeds) if r]
    a = sum(1 for r, _, _ in res if r == "A")
    b = sum(1 for r, _, _ in res if r == "B")
    wr = a / max(1, a + b) * 100
    mean_a = sum(ma for _, ma, _ in res) / max(1, len(res))   # 削りモードのターン後 相手手札
    mean_b = sum(mb for _, _, mb in res) / max(1, len(res))   # baseline のターン後 相手手札
    print(f"[ebv2_handecon] {SLUG}  A(削りモード) {a} - {b} B(baseline)  A_wr={wr:.1f}%", flush=True)
    print(f"  相手手札(低いほど削れてる): 削りモード後={mean_a:.2f}枚 / baseline後={mean_b:.2f}枚 "
          f"→ 差 {mean_b-mean_a:+.2f}枚 ({len(res)} games, {time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
