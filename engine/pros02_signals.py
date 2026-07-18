"""pros_02 由来の per-deck signal を beam 採点に変換する消費層。

signals は deck_analysis['pros02_signals'] (= db/note_pros02/applied/<slug>.json overlay 由来、
gitignore、 有料note非コミット、 harness._merge_pros02_overlay が runtime 注入)。
scripts/note_pros02_apply.py:_derive_signals が Claude蒸留 JSON から抽出する。

beam-only 規律 (= concept_prior / play_prior と同じ): plan 選別スコアにのみ加算し、
post-opp 最終 value (calibrated) には足さない (= prior であって value bias でない)。
呼び出し側 (plan_search) が `_W_PROS02 * raw * scale` でスケールする。

signal 種:
- protect_card_ids: 盤面に残す/優先展開したい key card。 play を加点 + leaf で生存数を加点。
- attack_count_priority: 攻撃 action を加点 (= 攻撃回数で相手カウンターを枯らす pros_02 原則)。
- avoid_overpump: opp leader +2000 を超えるキャラへの追加 DON 付与を減点 (= 過剰打点の無駄)。
"""
from __future__ import annotations

from .game import AttachDonToCharacter, AttackCharacter, AttackLeader, PlayCharacter


# debug 発火カウンタ (= 検証用、 ONEPIECE_PROS02_DEBUG=1 の時のみ計上)
import os as _os
_STATS = {"action_calls": 0, "action_nonzero": 0, "leaf_calls": 0, "leaf_nonzero": 0}


def get_signals(deck_analysis) -> dict | None:
    if isinstance(deck_analysis, dict):
        s = deck_analysis.get("pros02_signals")
        if isinstance(s, dict):
            return s
    return None


def action_bonus(cur_state, action, me_idx: int, sig: dict) -> float:
    """per-action の raw signal (概ね [-1, +1])。 呼び出し側で W*scale。"""
    b = 0.0
    protect = sig.get("protect_card_ids") or []
    # (1) 守る/キー カードの展開を優先 (= 盤面に置く)
    if protect and isinstance(action, PlayCharacter):
        cid = getattr(getattr(action, "card", None), "card_id", None)
        if cid in protect:
            b += 1.0
    # (2) 攻撃回数を評価 (race / 圧をかける)
    if sig.get("attack_count_priority") and isinstance(action, (AttackLeader, AttackCharacter)):
        b += 1.0
    # (3) 過剰パンプ penalty (opp leader +2000 を超えるキャラへの追加付与は無駄)
    if sig.get("avoid_overpump") and isinstance(action, AttachDonToCharacter):
        me = cur_state.players[me_idx]
        opp = cur_state.players[1 - me_idx]
        tgt = next((c for c in me.characters if c.instance_id == action.target_iid), None)
        if tgt is not None:
            opp_leader_pow = opp.leader.power if getattr(opp, "leader", None) else 5000
            if int(tgt.power) >= int(opp_leader_pow) + 2000:
                b -= 1.0
    if _os.environ.get("ONEPIECE_PROS02_DEBUG") == "1":
        _STATS["action_calls"] += 1
        if b:
            _STATS["action_nonzero"] += 1
    return b


def leaf_bonus(cur_state, me_idx: int, sig: dict) -> float:
    """leaf state の raw signal: 守るカードが自盤面に生存している数。"""
    protect = sig.get("protect_card_ids") or []
    if not protect:
        return 0.0
    me = cur_state.players[me_idx]
    return float(sum(1 for c in me.characters
                     if getattr(c.card, "card_id", None) in protect))
