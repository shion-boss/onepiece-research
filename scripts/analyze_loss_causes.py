# -*- coding: utf-8 -*-
"""capture_learning_log の完全ログから hero デッキの「負け筋」を走査する。

⚠ setup_game は first_player で席順を入替えるので player_idx==0 は hero とは限らない。
必ず leader card_id で hero を識別する (= feedback_ab_harness_balance_player_index の分析側バグ)。

  .venv/bin/python scripts/analyze_loss_causes.py db/_analyst/ll_20new.jsonl OP15-058
"""
import sys, json
from collections import defaultdict, Counter

path = sys.argv[1]
HERO = sys.argv[2] if len(sys.argv) > 2 else "OP15-058"
recs = [json.loads(l) for l in open(path, encoding="utf-8")]

# 各 game で hero の player_idx を leader で特定
hidx = {}
for r in recs:
    if r.get("state") and r["game"] not in hidx:
        hidx[r["game"]] = 0 if r["state"]["players"][0]["leader"]["card_id"] == HERO else 1

def isH(r):
    return r["player_idx"] == hidx[r["game"]]

def won(g):
    for r in recs:
        if r["game"] == g and isH(r) and "y" in r:
            return r["y"] == 1
    return None

wins = {g for g in hidx if won(g)}
lost = set(hidx) - wins
print(f"=== {path} ({HERO}) ===")
print(f"hero 勝率: {len(wins)}/{len(hidx)} = {len(wins)/max(1,len(hidx))*100:.0f}%  負け={sorted(lost)}\n")

# --- 防御: killing blow の生存可否 + over/under/wasted ---
hdef = [r for r in recs if r.get("kind") == "defense" and isH(r)]
byg = defaultdict(list)
for r in hdef:
    byg[r["game"]].append(r)
surv_declined = 0; unsurv = 0
for g in sorted(lost):
    ds = byg.get(g, [])
    if not ds:
        continue
    kb = ds[-1]; gap = kb["atk_power"] - kb["target_power"]
    survivable = gap >= 0 and kb["def_counter_capacity"] > gap and not kb["blocked"]
    if kb["my_life"] <= 1:
        if survivable and kb["counter_spent"] == 0:
            surv_declined += 1
        elif not survivable:
            unsurv += 1
und = [r for r in hdef if r.get("under_defense")]
oc = [r for r in hdef if r.get("over_counter")]
wasted = [r for r in hdef if r["counter_spent"] > 0 and not r.get("nullified") and not r["blocked"]]
print(f"[防御] killing blow: 守れたのに自滅 {surv_declined} / 守れない {unsurv}")
print(f"       over_counter {len(oc)} / 無駄打ち {len(wasted)} / under_defense {len(und)} (life{dict(sorted(Counter(r['my_life'] for r in und).items()))})")

# --- 攻撃: 届かず効果も無い空振り / 打ち負け ---
hatk = [r for r in recs if isH(r) and r.get("kind") is None and r["action"] in ("AttackLeader", "AttackCharacter")]
face = [r for r in hatk if r["action"] == "AttackLeader"]
badtrade = 0
for r in [x for x in hatk if x["action"] == "AttackCharacter"]:
    st = r["state"]; me = st["players"][hidx[r["game"]]]; opp = st["players"][1 - hidx[r["game"]]]
    tid = r.get("action_detail", {}).get("target_iid"); aid = r.get("action_detail", {}).get("attacker_iid")
    tgt = next((c for c in opp["characters"] if c["instance_id"] == tid), None)
    atk = me["leader"] if me["leader"]["instance_id"] == aid else next((c for c in me["characters"] if c["instance_id"] == aid), None)
    if tgt and atk and atk["power"] < tgt["power"]:
        badtrade += 1
print(f"[攻撃] 総{len(hatk)} 顔{len(face)}/キャラ{len(hatk)-len(face)}(除去率{(len(hatk)-len(face))/max(1,len(hatk))*100:.0f}%)  打ち負け{badtrade}")

# --- 相手を養ってないか(相手の素受け率)+ 盤面成長 ---
odef = [r for r in recs if r.get("kind") == "defense" and not isH(r) and r["is_leader_attack"]]
took = sum(1 for r in odef if r["counter_spent"] == 0 and not r["blocked"])
print(f"[相手] hero顔攻撃{len(odef)}件 → 相手素受け(手札+1) {took} ({took/max(1,len(odef))*100:.0f}%)")
oboard = defaultdict(list)
for r in recs:
    if isH(r) and r.get("kind") is None:
        oboard[r["turn"]].append(len(r["state"]["players"][1 - hidx[r["game"]]]["characters"]))
print(f"[相手] 盤面(T別): " + " ".join(f"T{t}:{sum(oboard[t])/len(oboard[t]):.1f}" for t in sorted(oboard) if t <= 11))

# --- 負けの接戦度 ---
mn = defaultdict(lambda: 99)
for r in recs:
    if isH(r) and r.get("kind") is None:
        mn[r["game"]] = min(mn[r["game"]], r["opp_life"])
print(f"[接戦] 負けgameの相手最低ライフ: {[mn[g] for g in sorted(lost)]}")
