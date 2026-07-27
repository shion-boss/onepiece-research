"""hand_economy = 相手の手札経済を因果モデルで評価する決定層 (2026-07-27、 ohtsuki insight)。

ohtsuki の指摘: AI は「どの行動が相手手札を減らすか / いつ効率的か / 手札を増やすエンジンの除去」を
理解していない。 pressure bonus は crude greedy sim の削り量を報酬化しただけで、 削りの因果を理解して
いなかった (= neutral)。 ここでは **カード知識(sig)+ 要求値(compute_demand_value)+ timing(相手
ライフ leverage)で解析的に** 相手手札経済への効果を評価する (sim の greedy 相手モデルに依存しない)。

3 成分 (plan-level、 beam の action_bonus 形式で W スケール):
  (1) 要求値 drain: リーダー攻撃の 要求値(= ceil((atk-opp_leader)/1000)) × ライフ leverage
      (低ライフ=相手が受けられない=カウンター強要=手札を割く)。 = 「いつ攻めると手札が減るか」。
  (2) engine 除去: 相手の search/draw エンジン(sig lbl_search/lbl_draw)へのキャラ攻撃を高評価。
      = counter で守れば手札-1、 KO で見捨てれば **将来の手札増(サーチ/ドロー)を止める**。
      = 「手札を増やすサーチを除去することも手札を減らすため大切」(ohtsuki)。
  (3) timing: 上記を相手ライフ leverage で重み付け。
"""
from __future__ import annotations

from math import ceil
from typing import Any


def _attacker_power(state: Any, me_idx: int, attacker_iid: int) -> int:
    me = state.players[me_idx]
    if getattr(me.leader, "instance_id", None) == attacker_iid:
        return me.leader.power
    for c in me.characters:
        if c.instance_id == attacker_iid:
            return c.power
    return 0


def _hand_engine_score(cid: str) -> float:
    """相手キャラ cid が手札生成エンジン(search/draw)か = 除去で将来手札を止める価値 ~[0, ~2]。"""
    if not cid:
        return 0.0
    try:
        from .card_sig import for_card
        s = for_card(cid)
        return float(s.get("lbl_search", 0.0)) + float(s.get("lbl_draw", 0.0))
    except Exception:
        return 0.0


def hand_economy_value(state: Any, plan: list, me_idx: int) -> float:
    """plan の「相手手札経済への効果」raw 値 (>0 = 相手手札を削る/増やさせない)。 W でスケール。"""
    try:
        from .game import AttackLeader, AttackCharacter
    except Exception:
        return 0.0
    opp = state.players[1 - me_idx]
    opp_life = len(getattr(opp, "life", []) or [])
    opp_leader_power = getattr(opp.leader, "power", 0)
    # ライフ leverage: 低ライフ=受けられない=カウンター強要=手札減。 [0,1]: life<=1→1.0, life>=6→0.0。
    leverage = max(0.0, min(1.0, (6.0 - opp_life) / 5.0))
    total = 0.0
    for a in plan:
        if isinstance(a, AttackLeader):
            atk = _attacker_power(state, me_idx, getattr(a, "attacker_iid", -1))
            demand = ceil(max(0, atk - opp_leader_power) / 1000.0)   # 要求値 (counter 単位)
            # 手札を割かせる期待 = 要求値 × leverage (低ライフほど確実にカウンター強要)。
            total += demand * leverage
        elif isinstance(a, AttackCharacter):
            tgt = next((c for c in getattr(opp, "characters", [])
                        if c.instance_id == getattr(a, "target_iid", -1)), None)
            if tgt is None:
                continue
            cid = getattr(getattr(tgt, "card", None), "card_id", None)
            # キャラ攻撃 = 「counter(手札-1) or KO(盤面/エンジン除去)」の二択強要 = base。
            v = 0.5
            # search/draw エンジン除去は将来の手札増を止める → 追加価値。
            v += 1.5 * _hand_engine_score(cid)
            total += v
    return total
