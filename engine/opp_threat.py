"""相手カード identity を見た攻撃対象の decision-層ボーナス (2026-07-22、 path (A))。

ohtsuki: 「相手のカードを区別して戦うようにしたい。 リーダーを攻撃するかキャラを攻撃するかを
検討する時、 そのキャラが何なのか・リーダーが誰なのかを見て判断してほしい (目をつぶって
戦っている印象)」。

value(盤面採点)を駒認識にする路線は null 確定(v14/residual)。 効くのは **決定の点で** カードを
区別する形(除去優先度 27f762d、 Enel lethal と同型)。 これは beam の action_bonus (ONEPIECE_OPPCARD_W)
として乗る per-action ボーナス — value 特徴でなく argmax を直接動かす。

- AttackCharacter: 相手キャラの脅威度を + → 拘束脅威(9ミホーク/8クロコ/4ペローナ)・除去・エンジンを
  優先して攻撃/除去。 = 「そのキャラが何なのか」を見る。
- AttackLeader: 相手リーダーが durable/回復なら chip を軽く - (詰め圏 opp_life≤2 では罰さない)。
  = 「リーダーが誰なのか」を見て、 回復相手を無駄に削らない。

⚠ 既定 OFF (ONEPIECE_OPPCARD_W=0)。 挙動検証後に per-AI (_oppcard_w) / deck_ai_config で ON。
"""
from __future__ import annotations
from typing import Optional

_KEY_THREATS: Optional[frozenset] = None


def _base_id(cid: str) -> str:
    return cid.split("_")[0] if cid else cid


def _key_threat_ids() -> frozenset:
    """pros02_matchup_facts で fact_type=key_threat に名指しされた card_id 集合 (= プロが
    『最優先で除去/警戒』と言った脅威。 9ミホーク OP14-119 / 8クロコ OP14-120 / 4ペローナ 等)。"""
    global _KEY_THREATS
    if _KEY_THREATS is None:
        ids: set = set()
        try:
            from . import card_knowledge as CK
            pm = CK._pros_matchup()
            for lid, rec in pm.items():
                if lid == "_meta":
                    continue
                for f in rec.get("facts", []):
                    if f.get("fact_type") in ("key_threat", "board_wipe") and f.get("card_id"):
                        ids.add(_base_id(f["card_id"]))
        except Exception:
            pass
        _KEY_THREATS = frozenset(ids)
    return _KEY_THREATS


def _char_threat(cid: str) -> float:
    """相手キャラ(cid)を『対処すべき度』の raw score ~[0,1]。 pros02 key_threat 最優先、
    さもなくば効果ラベル(除去/無効/拘束/エンジン)で判定。"""
    if not cid:
        return 0.0
    if _base_id(cid) in _key_threat_ids():
        return 1.0                       # プロが名指しした脅威 = 最優先
    try:
        from . import card_labels as CL
        labels = set(CL.labels_for_card(cid) or CL.labels_for_card(_base_id(cid)))
    except Exception:
        labels = set()
    if labels & {"removal", "negate"}:
        return 0.6                       # 除去/無効化 = 放置すると自盤面が崩れる
    if labels & {"keyword_grant", "tempo_rest"}:
        return 0.5                       # 拘束/レスト系
    if labels & {"draw", "search", "play_accel", "ramp_don", "recursion"}:
        return 0.45                      # ドロー/サーチ/展開エンジン = 放置で差が開く
    if labels:
        return 0.2                       # 何か効果はある = バニラよりは対処価値
    return 0.0


def _leader_durability(lid: str) -> float:
    """相手リーダー(lid)の耐久度 ~[0,1]。 回復(エネル黄=機構保証)や pros が『実効ライフ厚い』と
    言うリーダーで高い → その分 chip(顔削り)の価値を下げる。"""
    if not lid:
        return 0.0
    try:
        from . import card_knowledge as CK
        if CK.opp_invalidates_life_pressure(lid):
            return 1.0                   # 機構的回復 (0→1、 エネル黄)
        facts = CK.matchup_facts_for(lid)
        dur = sum(1 for f in facts if f.get("fact_type") in ("effective_life", "recovery"))
        return min(1.0, 0.5 * dur)
    except Exception:
        return 0.0


def attack_target_bonus(cur_state, action, me_idx: int) -> float:
    """相手カードを見た攻撃対象の raw bonus ~[-1,+1] (beam の action_bonus 形式、 W でスケール)。"""
    from .game import AttackCharacter, AttackLeader
    opp = cur_state.players[1 - me_idx]
    if isinstance(action, AttackCharacter):
        tgt = next((c for c in getattr(opp, "characters", [])
                    if c.instance_id == action.target_iid), None)
        if tgt is None:
            return 0.0
        cid = getattr(getattr(tgt, "card", None), "card_id", None)
        return _char_threat(cid)
    if isinstance(action, AttackLeader):
        # 詰め圏 (opp_life ≤ 2) では chip がリーサル前進なので罰さない。
        _ol = getattr(opp, "life", [])
        opp_life = len(_ol) if isinstance(_ol, (list, tuple)) else int(_ol or 0)
        if opp_life <= 2:
            return 0.0
        lid = getattr(getattr(opp.leader, "card", None), "card_id", None)
        return -0.5 * _leader_durability(lid)
    return 0.0


# === 防御側: 「どのカードを守るべきか」 (2026-07-24、 path A の対称形) ===================
# ohtsuki:「どのカードを除去したら良くなったかとか、 どのカードを攻撃されたときに守るべきか」。
# 攻撃側 (attack_target_bonus) が「相手のどの駒を叩くか」を決定層で区別するのに対し、 こちらは
# 「自分のどの駒を残すか」。 value(compute_score) は失った駒をパワー/枚数でしか見ないので、
# 効果持ち (除去/エンジン/拘束) を失う損を区別できない = 同じ盲目。
# 守る価値は「対処すべき度」と同じ尺度で測れる (相手にとって厄介な駒 = 自分にとって残す価値)。


def self_char_value(cid: str) -> float:
    """自分のキャラ(cid)を『残す価値』 raw score ~[0,1] (= _char_threat の自陣版)。"""
    return _char_threat(cid)


def defense_loss_bonus(before_ids: list, after_ids: list) -> float:
    """守備の結果 **失った自キャラ** の identity 価値の合計を負で返す (raw ~[-1,0])。

    before/after = 防御 sim の前後の自キャラ card_id 列。 攻撃対象が生き残ったか (守れたか)
    と、 ブロッカーが討ち死にしたか の両方が 1 つの差分に乗る = 「守るべき駒を守り、
    捨ててよい駒で受ける」 を決定層で表現できる。"""
    from collections import Counter
    lost = Counter(before_ids) - Counter(after_ids)
    if not lost:
        return 0.0
    return -sum(self_char_value(cid) * n for cid, n in lost.items())
