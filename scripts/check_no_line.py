# -*- coding: utf-8 -*-
"""打倒カルガラ: 敗北は「予測の問題」か「no-line(勝ち筋なし)」か を切り分ける。

Crocodile が calgara に負けた試合で、 **死ぬ直前(自分の最後のターン終了時)に防御リソース
(手札の counter 合計 / 場の active blocker 数)を余らせていたか** を集計する。
- 余らせて死ぬ → 線は在った = 予測/value で拾える余地 (opponent model に意味)
- 空で死ぬ → no-line = どんな opponent model も無駄

  .venv/bin/python scripts/check_no_line.py --deck cardrush_1385 --n 40
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")
OV = load_effect_overlay(ROOT / "db" / "card_effects.json")
_CARDS = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
_CARDS = _CARDS if isinstance(_CARDS, list) else _CARDS.get("cards", [])
def _ctr(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


CID2CTR = {c["card_id"]: _ctr(c.get("counter")) for c in _CARDS}


def _ana(s):
    p = ROOT / "decks" / f"{s}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _mk(slug):
    return lambda rng, deck_analysis=None: ExploitBeamAI(
        rng=rng, deck_analysis={**(deck_analysis or {}), "deck_slug": slug})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", default="cardrush_1385")
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    # challenger = leader 名で player idx を特定 (run_matchup は先後を cell 内で振る)
    dC = DeckList.from_json(ROOT / "decks" / f"{a.deck}.json", REPO)
    dT = DeckList.from_json(ROOT / "decks" / f"{a.target}.json", REPO)
    ch_leader = REPO.get(json.loads((ROOT / "decks" / f"{a.deck}.json").read_text())["leader"]).name

    rep = run_matchup(dC, dT, n_games=a.n, seed=a.seed,
                      ai_factory_1=_mk(a.deck), ai_factory_2=_mk(a.target),
                      deck1_analysis=_ana(a.deck), deck2_analysis=_ana(a.target),
                      effects_overlay=OV, record_snapshots=True)

    last_ctr, last_blk, last_hand, death_life_tg = [], [], [], []
    losses = 0
    for g in rep.games:
        snaps = getattr(g, "snapshots", None) or []
        if not snaps:
            continue
        ci = 0 if ch_leader in str(snaps[0]["players"][0]["leader"].get("name", "")) else 1
        if getattr(g, "winner", -1) == ci:
            continue  # 勝った試合は skip
        losses += 1
        # challenger の最後のターン (= calgara の lethal 直前) の snapshot
        ch_turn_snaps = [s for s in snaps if s.get("turn_player_idx") == ci]
        if not ch_turn_snaps:
            continue
        s = ch_turn_snaps[-1]
        p = s["players"][ci]
        ctr = sum(CID2CTR.get(cid, 0) for cid in p.get("hand", []))
        blk = sum(1 for c in p.get("characters", [])
                  if "ブロッカー" in (c.get("keywords") or []) and not c.get("rested"))
        last_ctr.append(ctr)
        last_blk.append(blk)
        last_hand.append(p.get("hand_count", len(p.get("hand", []))))
        death_life_tg.append(snaps[-1]["players"][1 - ci]["life_count"])

    print(f"=== {a.deck} ({ch_leader}) が {a.target} に負けた {losses} 試合の"
          f" 死ぬ直前(自最終ターン終了)の防御リソース ===")
    if losses:
        print(f"  手札 counter 合計   : 平均 {statistics.mean(last_ctr):.0f}  "
              f"(中央 {int(statistics.median(last_ctr))}, 0枚率 {sum(1 for x in last_ctr if x==0)/losses:.0%})")
        print(f"  場の active blocker : 平均 {statistics.mean(last_blk):.1f}  "
              f"(0体率 {sum(1 for x in last_blk if x==0)/losses:.0%})")
        print(f"  手札枚数            : 平均 {statistics.mean(last_hand):.1f}")
        print(f"  死亡時の calgara 残ライフ: 平均 {statistics.mean(death_life_tg):.1f}")
        print()
        # ざっくり判定: counter≈1枚(<=2000)かつ blocker 0 が多数 → no-line 寄り
        starved = sum(1 for c, b in zip(last_ctr, last_blk) if c <= 2000 and b == 0)
        print(f"  → counter<=2000 かつ blocker 0 (= 防御枯渇/no-line 寄り): "
              f"{starved}/{losses} ({starved/losses:.0%})")
        rich = sum(1 for c, b in zip(last_ctr, last_blk) if c >= 4000 or b >= 2)
        print(f"  → counter>=4000 or blocker>=2 (= 防御を余らせて死亡/線あり寄り): "
              f"{rich}/{losses} ({rich/losses:.0%})")


if __name__ == "__main__":
    main()
