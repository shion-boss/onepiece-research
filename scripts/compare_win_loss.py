# -*- coding: utf-8 -*-
"""席固定ログで hero の 勝ち vs 負け を多軸比較 → 席交絡なしの「勝ち筋/負け筋」を抽出。

  .venv/bin/python scripts/compare_win_loss.py db/_analyst/ll_enel_first.jsonl OP15-058
"""
import sys, json
from collections import defaultdict

path = sys.argv[1]
HERO = sys.argv[2] if len(sys.argv) > 2 else "OP15-058"
recs = [json.loads(l) for l in open(path, encoding="utf-8")]
raw = json.load(open("db/cards.json"))
CTR = {c["card_id"]: (int(c["counter"]) if str(c.get("counter", "")).isdigit() else 0)
       for c in (raw if isinstance(raw, list) else raw["cards"])}

hidx = {}
for r in recs:
    if r.get("state") and r["game"] not in hidx:
        hidx[r["game"]] = 0 if r["state"]["players"][0]["leader"]["card_id"] == HERO else 1
def isH(r): return r["player_idx"] == hidx[r["game"]]
def won(g):
    for r in recs:
        if r["game"] == g and isH(r) and "y" in r:
            return r["y"] == 1
wins = {g for g in hidx if won(g)}; lost = set(hidx) - wins
print(f"=== {path} ({HERO}) ===")
print(f"勝ち {len(wins)} / 負け {len(lost)} (計{len(hidx)}, 勝率{len(wins)/max(1,len(hidx))*100:.0f}%)\n")

def per_game_metrics(g):
    gr = [r for r in recs if r["game"] == g]
    hm = [r for r in gr if isH(r) and r.get("kind") is None]
    hturns = sorted({r["turn"] for r in hm})
    early = set(hturns[:3])
    m = {}
    m["face_atk"] = sum(1 for r in hm if r["action"] == "AttackLeader")
    m["char_atk"] = sum(1 for r in hm if r["action"] == "AttackCharacter")
    m["early_face"] = sum(1 for r in hm if r["action"] == "AttackLeader" and r["turn"] in early)
    m["play_char"] = sum(1 for r in hm if r["action"] == "PlayCharacter")
    m["activate"] = sum(1 for r in hm if r["action"] == "ActivateMain")
    # ボニーが ≤1 に達した最初のターン
    le1 = [r["turn"] for r in hm if r["opp_life"] <= 1]
    m["opp_le1_turn"] = min(le1) if le1 else 99
    m["turns_opp_le1"] = len(set(le1))
    # 相手素受け(=養った)回数
    odef = [r for r in gr if not isH(r) and r.get("kind") == "defense" and r["is_leader_attack"]]
    m["opp_took"] = sum(1 for r in odef if r["counter_spent"] == 0 and not r["blocked"])
    # hero が counter を切った総量
    hdef = [r for r in gr if isH(r) and r.get("kind") == "defense"]
    m["my_counter_spent"] = sum(r["counter_spent"] for r in hdef)
    # 中盤(T5-8)の自盤面キャラ数平均、 相手盤面キャラ数平均
    mid = [r for r in hm if 5 <= r["turn"] <= 8]
    if mid:
        m["my_board_mid"] = sum(len(r["state"]["players"][hidx[g]]["characters"]) for r in mid) / len(mid)
        m["opp_board_mid"] = sum(len(r["state"]["players"][1 - hidx[g]]["characters"]) for r in mid) / len(mid)
    else:
        m["my_board_mid"] = m["opp_board_mid"] = 0
    # 自ライフの最終、 相手ライフの最低
    m["opp_min_life"] = min((r["opp_life"] for r in hm), default=9)
    m["my_min_life"] = min((r["my_life"] for r in hm), default=9)
    return m

keys = ["face_atk", "char_atk", "early_face", "play_char", "activate", "opp_le1_turn",
        "turns_opp_le1", "opp_took", "my_counter_spent", "my_board_mid", "opp_board_mid",
        "opp_min_life", "my_min_life"]
def avg(games, k):
    v = [per_game_metrics(g)[k] for g in games]
    return sum(v) / max(1, len(v))
print(f"{'metric':18} {'勝ち':>8} {'負け':>8} {'Δ(勝-負)':>10}")
for k in keys:
    w, l = avg(wins, k), avg(lost, k)
    print(f"{k:18} {w:8.2f} {l:8.2f} {w-l:+10.2f}")
