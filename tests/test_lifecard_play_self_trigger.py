"""ライフカードの play_self (「このカードを登場させる」) トリガー回帰テスト。

bug: play_self トリガーは taken が life→limbo でどの zone にも無いため play_self が
card を見つけられず no-op → _resolve_life_taken が fired&not-kept で trash 送りにし、
本来 登場すべき カード (ラン OP14-114 / マーガレット OP14-113 等) が dead だった。
fix: play_self トリガーなら taken を事前に trash 先頭へ置き play_self が pop→場 できる
様にし、 消費されたら trash/hand しない。
"""
import random
from pathlib import Path

from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import setup_game, _resolve_life_taken


def _repo():
    return CardRepository.from_json(Path("db/cards.json"))


def _overlay():
    return load_effect_overlay(Path("db/card_effects.json"))


def _mk_state(leader_id, main_id, overlay):
    repo = _repo()
    leader = repo.get(leader_id)
    main = [repo.get(main_id)] * 50
    d1 = DeckList(name="t1", leader=leader, main=list(main))
    d2 = DeckList(name="t2", leader=leader, main=list(main))
    return repo, setup_game(
        d1, d2, rng=random.Random(0), first_player=0, effects_overlay=overlay
    )


def test_lifecard_play_self_trigger_summons_to_board():
    """九蛇リーダーが ラン をライフから受け→トリガー発動 → ラン が 場 に 登場 (trash でない)。"""
    overlay = _overlay()
    # OP14-041 ボア・ハンコック = features 王下七武海/九蛇海賊団
    repo, state = _mk_state("OP14-041", "OP01-013", overlay)
    me, opp = state.players[0], state.players[1]
    taken = repo.get("OP14-114")  # ラン (trigger: 自リーダーが九蛇なら登場)

    chars_before = len(opp.characters)
    _resolve_life_taken(state, me, opp, taken, use_trigger=True)

    # 場 に 1 体 増えた (= ラン 登場) かつ taken は trash に無い
    assert len(opp.characters) == chars_before + 1
    assert any(ip.card is taken for ip in opp.characters), "taken ラン が 場 に居ない"
    assert taken not in opp.trash, "登場した ラン を trash 送りにしている (bug)"
    assert taken not in opp.hand


def test_lifecard_play_self_trigger_declined_goes_to_hand():
    """トリガー見送り → ラン は 手札 へ (場 へ 登場 しない)。"""
    overlay = _overlay()
    repo, state = _mk_state("OP14-041", "OP01-013", overlay)
    me, opp = state.players[0], state.players[1]
    taken = repo.get("OP14-114")

    chars_before = len(opp.characters)
    _resolve_life_taken(state, me, opp, taken, use_trigger=False)

    assert len(opp.characters) == chars_before
    assert taken in opp.hand
    assert taken not in opp.trash


def test_lifecard_play_self_trigger_condition_unmet_goes_to_hand():
    """非九蛇リーダーでは ラン の トリガー条件 不成立 → 発動 せず 手札 へ (trash でない)。"""
    overlay = _overlay()
    # OP01-001 = ルフィ (九蛇海賊団 を 持たない)
    repo, state = _mk_state("OP01-001", "OP01-013", overlay)
    me, opp = state.players[0], state.players[1]
    taken = repo.get("OP14-114")

    chars_before = len(opp.characters)
    _resolve_life_taken(state, me, opp, taken, use_trigger=True)

    assert len(opp.characters) == chars_before
    assert taken in opp.hand
    assert taken not in opp.trash
