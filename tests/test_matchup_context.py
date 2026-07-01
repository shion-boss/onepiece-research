"""matchup context 層 (engine/matchup_context.py) のテスト。

A軸(自分 leader 使い方) + B軸(相手 belief 脅威) の統合サマリを、 mock state で検証。
実 artifact (opponent_deck_priors / leader_effect_profiles) をロードして実データで確認。
"""

from __future__ import annotations

from engine import matchup_context as mc


class _Card:
    def __init__(self, cid: str) -> None:
        self.card_id = cid


class _InPlay:
    def __init__(self, cid: str) -> None:
        self.card = _Card(cid)


class _Player:
    def __init__(self, leader_id: str) -> None:
        self.leader = _InPlay(leader_id)
        self.characters: list = []
        self.stages: list = []
        self.trash: list = []
        self.hand: list = []
        self.deck: list = []
        self.life: list = []
        self.known_hand_card_ids: list = []
        self.don_active = 0


class _State:
    def __init__(self, me_leader: str, opp_leader: str) -> None:
        self.players = [_Player(me_leader), _Player(opp_leader)]


# エネル(自分, engine_use_often) vs ドフラ(相手, belief にあり)
ENEL = "OP15-058"
DOFLA = "OP14-060"


def test_own_leader_plan():
    st = _State(ENEL, DOFLA)
    own = mc.own_leader_plan(st, 0)
    assert own["known"] is True
    assert own["primary_usage"] == "engine_use_often"
    assert own["when_decision"] is True
    assert own["usage_hint"]  # 非空


def test_opponent_threat_summary():
    st = _State(ENEL, DOFLA)
    opp = mc.opponent_threat_summary(st, 0)
    assert opp["known"] is True
    assert "ドフラ" in opp["leader_name"] or opp["leader_name"]  # 名前が引けている
    assert len(opp["top_threats"]) > 0
    # 脅威に prob と name が付く
    t0 = opp["top_threats"][0]
    assert 0.0 <= t0["prob"] <= 1.0
    assert opp["posterior_sharpened"] is False  # seen 無し


def test_posterior_sharpens_with_seen():
    st = _State(ENEL, DOFLA)
    # 相手が場に OP14-069 を出した = 確定観測
    st.players[1].characters.append(_InPlay("OP14-069"))
    opp = mc.opponent_threat_summary(st, 0)
    assert opp["n_seen"] >= 1
    assert opp["posterior_sharpened"] is True


def test_unknown_opponent_leader():
    st = _State(ENEL, "NONEXISTENT-999")
    opp = mc.opponent_threat_summary(st, 0)
    assert opp["known"] is False


def test_describe_and_format():
    st = _State(ENEL, DOFLA)
    ctx = mc.describe_matchup_context(st, 0)
    assert ctx["own"]["known"] and ctx["opponent"]["known"]
    text = mc.format_context_text(ctx)
    assert "[自分]" in text and "[相手]" in text
    assert text.strip()


def test_collect_seen_dedup_counts():
    st = _State(ENEL, DOFLA)
    st.players[1].characters.append(_InPlay("OP14-069"))
    st.players[1].trash.append(_Card("OP14-069"))
    seen = mc.collect_seen_opponent_cards(st, 1)
    assert seen["OP14-069"] == 2  # 場 + トラッシュ = 2 枚確定
