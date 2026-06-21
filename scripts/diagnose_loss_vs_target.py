# -*- coding: utf-8 -*-
"""対1位デッキ改善ループの「敗因調査」エンジン (ohtsuki: 負けた要因の調査と仮説検証を繰り返す)。

あるデッキ (challenger) が target (= 環境#1、 既定カルガラ) に**どう負けているか**を、
logged self-play から分類する。 ループ手順:
  1. gauntlet.py で対#1勝率を測る (= どのデッキが負けてるか)
  2. ⭐このスクリプトで負けデッキの**支配的な敗因パターン**を特定
  3. 仮説を立てて修正 → gauntlet で A/B
  4. 次の敗因へ反復

敗因の分類軸 (= 仮説の出発点):
  - bleed/守備失敗: ライフを毎ターン垂れ流し、 #1 のライフはまだ高い (= 一度も詰めてない)
                     → 守備 (choose_defense) / ライフ価値の eval
  - 惜敗/攻め不足:   #1 を瀕死 (≤2) まで追ったが負け → リーサル/攻撃テンポ
  - 盤面維持失敗:    敗北時に自分の盤面が空 (= 展開できない/除去され続け) → 盤面 eval / 除去耐性
  - 速攻負け:        ~8 ターン以下で決着 → 序盤の守り/展開が間に合っていない
  - 長期負け:        ~12 ターン以上で resource 負け → 終盤の手札/勝ち筋

  .venv/bin/python scripts/diagnose_loss_vs_target.py --deck cardrush_1342 --target tcgportal_calgara --n 20
"""
import argparse, json, statistics
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.deck import DeckList, CardRepository
from engine.harness import run_matchup
from engine.exploit_beam_ai import ExploitBeamAI

REPO = CardRepository.from_json(ROOT / "db" / "cards.json")


def _ana(slug):
    p = ROOT / "decks" / f"{slug}.analysis.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _leader_name(slug):
    d = json.loads((ROOT / "decks" / f"{slug}.json").read_text(encoding="utf-8"))
    lid = d.get("leader") or d.get("leader_id")
    return REPO.get(lid).name


def diagnose(deck, target, n, seed):
    dC = DeckList.from_json(ROOT / "decks" / f"{deck}.json", REPO)
    dT = DeckList.from_json(ROOT / "decks" / f"{target}.json", REPO)
    ch_leader = _leader_name(deck)

    def a1(rng, da=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(da or {}), "deck_slug": deck})

    def a2(rng, da=None):
        return ExploitBeamAI(rng=rng, deck_analysis={**(da or {}), "deck_slug": target})

    rep = run_matchup(dC, dT, n_games=n, seed=seed, ai_factory_1=a1, ai_factory_2=a2,
                      deck1_analysis=_ana(deck), deck2_analysis=_ana(target),
                      record_snapshots=True)
    patt = Counter()
    detail = []
    losses = 0
    for g in rep.games:
        snaps = getattr(g, "snapshots", None) or []
        if not snaps:
            continue
        # challenger player idx = leader 名一致 (first_player 推測に頼らない)
        ci = 0 if ch_leader in str(snaps[0]["players"][0]["leader"].get("name", "")) else 1
        traj = []
        for s in snaps:
            x = s["players"][ci]["life_count"]
            if not traj or traj[-1] != x:
                traj.append(x)
        end = snaps[-1]
        ch_life = end["players"][ci]["life_count"]
        tg_life = end["players"][1 - ci]["life_count"]
        ch_field = len(end["players"][ci].get("characters", []))
        # challenger が負けたゲームのみ分類 (= 自ライフ0 で決着、 winner != ci)
        won = (getattr(g, "winner", -1) == ci)
        if won:
            continue
        losses += 1
        # 敗因分類
        if tg_life >= 4:
            patt["①守備失敗/bleed (#1ライフ高=一度も詰めてない)"] += 1
        elif tg_life <= 2:
            patt["②惜敗/攻め不足 (#1を瀕死まで追って負け)"] += 1
        else:
            patt["③中間 (#1ライフ3)"] += 1
        if ch_field == 0:
            patt["(併発)盤面0で敗北 (展開/盤面維持失敗)"] += 1
        if g.turns <= 8:
            patt["(併発)速攻負け (≤8T)"] += 1
        elif g.turns >= 12:
            patt["(併発)長期/resource負け (≥12T)"] += 1
        detail.append((g.turns, traj, tg_life, ch_field))
    print(f"=== {deck} ({ch_leader}) vs {target} の敗因調査: {rep.deck1_winrate:.0%} "
          f"({rep.deck1_wins}-{rep.deck2_wins}-{rep.draws}), 敗北 {losses} 件 ===")
    if losses:
        print(f"  決着ターン中央値: {int(statistics.median([d[0] for d in detail]))}")
        print(f"  敗北時の #1 残ライフ平均: {statistics.mean([d[2] for d in detail]):.1f} "
              f"(高い=こちらが詰められてない=守備/eval問題)")
        print(f"  敗北時の自盤面数平均: {statistics.mean([d[3] for d in detail]):.1f}")
        print("  --- 敗因パターン ---")
        for k, v in patt.most_common():
            print(f"    {v:>3}/{losses}  {k}")
        print("  --- 自ライフ推移サンプル (最大5件) ---")
        for t, tr, tgl, chf in detail[:5]:
            print(f"    {t}T: 自life {tr}  → 敗北時 #1life={tgl} 自盤面={chf}")
    return patt, detail


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--target", default="tcgportal_calgara")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    diagnose(a.deck, a.target, a.n, a.seed)
