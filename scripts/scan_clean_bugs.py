# -*- coding: utf-8 -*-
"""完全ログから matchup-agnostic な「クリーンなバグ」(客観的失着)を両プレイヤー分走査。

対象 (勝敗/席/デッキに依らず客観的に誤りと言えるもの):
- self_destruct_at_lethal : 素通し=敗北 (life<dmg) なのに 生存できる counter/block を切らず被弾
- over_counter            : 生存に必要な量より 2000+ 多く counter を切った
- wasted_counter          : counter を切ったが 止められず被弾 (= 閾値未達の無駄打ち)
- unreachable_no_effect   : 宣言時 atk < target かつ on_attack 効果無し (= 空タップ) ※要 overlay
- bad_trade              : キャラ攻撃で attacker.power < target.power (= 自キャラKOされ相手残存)

  .venv/bin/python scripts/scan_clean_bugs.py db/_analyst/ll_croc_dofla.jsonl
"""
import sys, json
from collections import Counter

import glob as _glob
paths = []
for a in sys.argv[1:]:
    paths.extend(sorted(_glob.glob(a)) if ("*" in a) else [a])
if not paths:
    print("usage: scan_clean_bugs.py <log.jsonl> [more.jsonl ...]"); sys.exit(1)
# 複数ログを game id が衝突しないよう file 単位で offset して結合
recs = []
_off = 0
for p in paths:
    fr = [json.loads(l) for l in open(p, encoding="utf-8")]
    gmax = max((r.get("game", 0) for r in fr), default=0)
    for r in fr:
        if "game" in r:
            r["game"] = r["game"] + _off
    recs += fr
    _off += gmax + 1
ov = json.load(open("db/card_effects.json"))
raw = json.load(open("db/cards.json"))
CARDS = {c["card_id"]: c for c in (raw if isinstance(raw, list) else raw["cards"])}


def has_on_attack(cid):
    e = ov.get(cid)
    if isinstance(e, list):
        return any(isinstance(x, dict) and "attack" in str(x.get("when", "")) for x in e)
    return False


bugs = Counter()
examples = {}
def note(kind, g, t, pidx, desc):
    bugs[kind] += 1
    examples.setdefault(kind, (g, t, pidx, desc))

# 防御 (self_destruct / over_counter / wasted_counter)
for r in recs:
    if r.get("kind") == "defense":
        atk = r["atk_power"]; tgt = r["target_power"]; cs = r["counter_spent"]
        cap = r["def_counter_capacity"]; life = r["my_life"]; blocked = r["blocked"]
        gap = atk - tgt
        nullified = r.get("nullified")
        # self_destruct: life 0 の leader 攻撃で 生存可能 (cap>gap) なのに 素受け
        if r["is_leader_attack"] and life == 0 and not blocked and cs == 0 and gap >= 0 and cap > gap:
            note("self_destruct_at_lethal", r["game"], r["turn"], r["player_idx"],
                 f"atk{atk}→L{tgt} 容量{cap} で守れたのに0で被弾=敗北")
        if not blocked and cs > 0 and nullified and (tgt + cs - 1000) > atk:
            note("over_counter", r["game"], r["turn"], r["player_idx"], f"atk{atk}→L{tgt} counter{cs}(必要{gap+1000})")
        if not blocked and cs > 0 and not nullified:
            note("wasted_counter", r["game"], r["turn"], r["player_idx"], f"atk{atk}→L{tgt} counter{cs}切るも被弾")
    # 攻撃 (unreachable_no_effect / bad_trade)
    if r.get("kind") is None and r.get("action") in ("AttackLeader", "AttackCharacter"):
        st = r.get("state"); ad = r.get("action_detail", {})
        if not st:
            continue
        me = st["players"][r["player_idx"]]; opp = st["players"][1 - r["player_idx"]]
        aid = ad.get("attacker_iid")
        atkc = me["leader"] if me["leader"]["instance_id"] == aid else next((c for c in me["characters"] if c["instance_id"] == aid), None)
        if not atkc:
            continue
        if r["action"] == "AttackLeader":
            if atkc["power"] < opp["leader"]["power"] and not has_on_attack(atkc["card_id"]):
                note("unreachable_no_effect", r["game"], r["turn"], r["player_idx"],
                     f"{atkc['card_id']}({atkc['power']})→L{opp['leader']['power']} 届かず効果無")
        else:
            tid = ad.get("target_iid")
            tgtc = next((c for c in opp["characters"] if c["instance_id"] == tid), None)
            if tgtc and atkc["power"] < tgtc["power"] and not has_on_attack(atkc["card_id"]):
                note("bad_trade", r["game"], r["turn"], r["player_idx"],
                     f"{atkc['card_id']}({atkc['power']})→{tgtc['card_id']}({tgtc['power']}) 打ち負け")

ng = len({r["game"] for r in recs if "game" in r})
print(f"=== {len(paths)} log / {ng} game クリーンなバグ走査 ===")
if not bugs:
    print("  検出ゼロ")
for k, v in bugs.most_common():
    g, t, p, d = examples[k]
    print(f"  {k}: {v}件  例) game{g} T{t} p{p}: {d}")
