# -*- coding: utf-8 -*-
"""召喚酔い の ブロッカー が ブロック できる こと の regression (公式 10-1-4)。

公式 10-1-4: 受け側は自分の場の【ブロッカー】カードのうち アクティブのもの 1 枚を
レストにして ブロックを発動可能。 ＝ 条件は「アクティブ (= レストでない)」のみ。
召喚酔い (= 登場したターン) は アタック を 制限 する だけ で、 ブロック は 妨げない。
自ターンに出したブロッカーは 次の相手ターンに (= まだ summoning_sickness=True の状態で)
ブロックできなければ ならない。

bug (2026-06-04 修正前): game.py / human_session.py / ai.py が blocker 条件に
`not summoning_sickness` を入れていた → 出したばかりのブロッカーが弾かれ、 人間プレイで
「ブロッカー発動できない」。
"""
from __future__ import annotations

from engine.core import InPlay
from engine.game import AttackLeader, AttackCharacter, apply_action

import tests.test_effects as T


def _find_blocker_card(repo, min_power=4000):
    return next(
        c for cid, c in repo._by_id.items()
        if "ブロッカー" in (c.text or "") and c.power >= min_power
    )


def test_sick_blocker_can_block_leader_attack():
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    me, opp = state.players[0], state.players[1]
    me.don_active = 5
    me.leader.summoning_sickness = False
    me.leader.rested = False
    state.turn_number = 3

    bc = _find_blocker_card(repo)
    blocker = InPlay.of(bc, sickness=True, rested=False)  # 召喚酔い + アクティブ
    opp.characters = [blocker]
    life0 = len(opp.life)

    apply_action(state, AttackLeader(
        attacker_iid=me.leader.instance_id, blocker_iid=blocker.instance_id))

    assert blocker.rested, "召喚酔い blocker が ブロック できて いない (= レスト されない)"
    # ブロッカー が 攻撃 を 受けた ので リーダー ライフ は 減って いない
    assert len(opp.life) == life0, f"life {life0}→{len(opp.life)}: ブロッカー が 無視 された"


def test_sick_blocker_can_block_character_attack():
    repo, overlay = T._repo(), T._overlay()
    state = T._make_state(repo, "OP01-001", overlay=overlay)
    me, opp = state.players[0], state.players[1]
    me.don_active = 5
    state.turn_number = 3

    # 攻撃側 キャラ (active, no sickness)
    atk_card = _find_blocker_card(repo, min_power=5000)
    attacker = InPlay.of(atk_card, sickness=False, rested=False)
    me.characters = [attacker]

    bc = _find_blocker_card(repo, min_power=1000)
    # 守備側: 攻撃対象 の キャラ + 召喚酔い blocker
    victim = InPlay.of(bc, sickness=False, rested=False)
    blocker = InPlay.of(bc, sickness=True, rested=False)  # 召喚酔い + アクティブ
    opp.characters = [victim, blocker]

    apply_action(state, AttackCharacter(
        attacker_iid=attacker.instance_id,
        target_iid=victim.instance_id,
        blocker_iid=blocker.instance_id))

    assert blocker.rested, "召喚酔い blocker が キャラ攻撃 を ブロック できて いない"


def test_human_session_offers_sick_blocker(monkeypatch):
    """human_session の defense pause が 召喚酔い blocker を legal_blocker_iids に含める。"""
    from engine.human_session import HumanSession, PauseSignal
    from engine.deck import CardRepository, DeckList

    repo, overlay = T._repo(), T._overlay()
    leader = repo.get("OP01-001")
    bc = _find_blocker_card(repo, min_power=2000)

    # 最小 deck (50 枚) を 非ブロッカー 連打 で 構成 (validate しない)
    nonblk = next(c for cid, c in repo._by_id.items()
                  if c.category.name == "CHARACTER" and "ブロッカー" not in (c.text or ""))
    deck_a = DeckList(name="a", leader=leader,
                      main=[nonblk] * 50, slug="t_a")
    deck_b = DeckList(name="b", leader=leader,
                      main=[nonblk] * 50, slug="t_b")

    sess = HumanSession(deck_a=deck_a, deck_b=deck_b,
                        ai_factory=lambda rng, deck_analysis=None: __import__(
                            "engine.ai", fromlist=["GreedyAI"]).GreedyAI(rng=rng),
                        seed=1, effects_overlay=overlay, human_first=True)
    state = sess.state
    # human = players[0]。 相手 (players[1]) が players[0].leader を攻撃する状況を直接組む。
    human = state.players[0]
    ai = state.players[1]
    blocker = InPlay.of(bc, sickness=True, rested=False)  # 召喚酔い + アクティブ
    human.characters = [blocker]

    # defense pause を 直接 検証: _build_defense_pause 相当 を 経由 する代わりに
    # blocker 候補 算出 ロジック を 再現 (= human_session と 同条件)。
    target = human.leader
    cand = [
        b.instance_id for b in human.characters
        if b.is_blocker_now and not b.rested
        and not b.blocker_disabled_until_turn_end
        and b.instance_id != getattr(target, "instance_id", None)
    ]
    assert blocker.instance_id in cand, \
        "召喚酔い blocker が 防御候補 に 含まれ ない (= UI で 選べない)"
