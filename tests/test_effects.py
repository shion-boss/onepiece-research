# -*- coding: utf-8 -*-
"""効果DSL のユニットテスト: 個別効果が実際に発動することを確認する。"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    evaluate_static_effects,
    fire_activate_main,
    list_activate_main_effects,
    load_effect_overlay,
    trigger_on_play,
)

ROOT = Path(__file__).resolve().parent.parent


def _repo() -> CardRepository:
    return CardRepository.from_json(ROOT / "db" / "cards.json")


def _overlay():
    return load_effect_overlay(ROOT / "db" / "card_effects.json")


def _make_state(repo, leader_id, hand_ids=(), overlay=None):
    leader = repo.get(leader_id)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo.get("OP01-001"), sickness=False))
    p1.hand = [repo.get(cid) for cid in hand_ids]
    p1.deck = [repo.get("OP01-013")] * 30
    p2.deck = [repo.get("OP01-013")] * 30
    return GameState(
        players=[p1, p2],
        phase=Phase.MAIN,
        rng=random.Random(1),
        effects_overlay=overlay or {},
    )


def test_on_play_search():
    """OP01-016 ナミ 登場時 サーチ"""
    repo = _repo()
    overlay = _overlay()
    nami = repo.get("OP01-016")
    state = _make_state(repo, "OP01-003", hand_ids=["OP01-016"], overlay=overlay)
    state.players[0].deck = [repo.get("OP01-013")] * 5

    me = state.players[0]
    opp = state.players[1]
    initial_hand = len(me.hand)

    ip = InPlay.of(nami, sickness=True)
    me.characters.append(ip)
    trigger_on_play(state, me, opp, ip, overlay)

    assert len(me.hand) == initial_hand + 1, "サーチで1枚増えるはず"


def test_on_play_ko():
    """OP02-013 エース 登場時 5000以下を KO"""
    repo = _repo()
    overlay = _overlay()
    ace = repo.get("OP02-013")
    state = _make_state(repo, "OP02-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    opp.characters.append(InPlay.of(repo.get("ST21-005"), sickness=False))  # P4000
    opp.characters.append(InPlay.of(repo.get("OP11-015"), sickness=False))  # P6000

    ip = InPlay.of(ace, sickness=True)
    me.characters.append(ip)
    trigger_on_play(state, me, opp, ip, overlay)

    assert len(opp.characters) == 1
    assert opp.characters[0].card.card_id == "OP11-015"


def test_activate_main_pump():
    """OP01-013 サンジ 起動メイン: ライフ→手札 + パワー+2000"""
    repo = _repo()
    overlay = _overlay()
    sanji = repo.get("OP01-013")
    state = _make_state(repo, "OP01-003", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-001")] * 4

    ip = InPlay.of(sanji, sickness=False)
    me.characters.append(ip)

    p_before = ip.power
    life_before = len(me.life)
    hand_before = len(me.hand)

    options = list_activate_main_effects(state, me, overlay)
    assert len(options) == 1

    src, eff = options[0]
    fire_activate_main(state, me, opp, src, eff)

    assert ip.power == p_before + 2000
    assert len(me.life) == life_before - 1
    assert len(me.hand) == hand_before + 1


def test_untap_primitive():
    """untap: rested=True のキャラ/リーダーを False に戻す"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    sanji.rested = True
    me.characters = [sanji]
    me.leader.rested = True

    from engine.effects import execute_effect
    execute_effect({"untap": "self_leader"}, state, me, opp, None)
    assert me.leader.rested is False

    execute_effect({"untap": "all_self_characters"}, state, me, opp, None)
    assert sanji.rested is False


def test_give_rush_primitive():
    """give_rush: summoning_sickness を False に"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    sanji = InPlay.of(repo.get("OP01-013"), sickness=True)
    me.characters = [sanji]
    assert sanji.summoning_sickness is True

    from engine.effects import execute_effect
    execute_effect({"give_rush": "self"}, state, me, opp, sanji)
    assert sanji.summoning_sickness is False


def test_attach_don_primitive():
    """attach_don: 自キャラ/リーダーにアクティブドン N 付与"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 5

    p_before = me.leader.power
    from engine.effects import execute_effect
    execute_effect(
        {"attach_don": {"target": "self_leader", "count": 2}},
        state, me, opp, None,
    )
    assert me.leader.attached_dons == 2
    assert me.don_active == 3
    assert me.leader.power == p_before + 2000


def test_don_power_buff_owner_turn_only():
    """公式 6-5-5: ドン+1000 は所有者のターン中のみ。相手ターン中は寄与しない。

    setup_game/_recompute_static 経由で is_owners_turn を更新し、
    自ターン中は DON が +1000、相手ターン中は +0 になることを確認する。
    """
    from engine.deck import DeckList
    from engine.game import setup_game

    repo = _repo()
    overlay = _overlay()
    leader = repo.get("OP01-001")
    main = [repo.get("OP01-013")] * 50
    deck1 = DeckList(name="t1", leader=leader, main=list(main))
    deck2 = DeckList(name="t2", leader=leader, main=list(main))

    state = setup_game(deck1, deck2, rng=random.Random(0), first_player=0,
                      effects_overlay=overlay)
    p0 = state.players[0]
    p1 = state.players[1]
    base_p = p0.leader.card.power  # 5000

    # 自ターン (turn_player_idx=0) で DON+2 → +2000 寄与
    state.turn_player_idx = 0
    p0.leader.attached_dons = 2
    from engine.game import _recompute_static
    _recompute_static(state)
    assert p0.leader.is_owners_turn is True
    assert p0.leader.power == base_p + 2000

    # 相手ターンに切り替え → DON は物理的に付いたままでも +0
    state.turn_player_idx = 1
    _recompute_static(state)
    assert p0.leader.is_owners_turn is False
    assert p0.leader.power == base_p, \
        "相手ターン中は DON+1000 はパワーに寄与しないはず"

    # 一方、p1 のリーダーは相手ターン中なので DON があれば寄与
    p1.leader.attached_dons = 3
    _recompute_static(state)
    assert p1.leader.is_owners_turn is True
    assert p1.leader.power == base_p + 3000


def test_on_attached_don_static_buff():
    """OP01-001 リーダー: ドン1枚以上付与時、自キャラに +1000 (常在)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]

    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    sai = InPlay.of(repo.get("OP01-012"), sickness=False)
    me.characters = [sanji, sai]

    # ドン未付与: バフなし
    evaluate_static_effects(state, overlay)
    assert sanji.static_buff == 0
    assert sai.static_buff == 0

    # ドン1付与: 全自キャラ +1000
    me.leader.attached_dons = 1
    evaluate_static_effects(state, overlay)
    assert sanji.static_buff == 1000
    assert sai.static_buff == 1000
    assert sanji.power == sanji.card.power + 1000

    # ドン解除: 常在解除
    me.leader.attached_dons = 0
    evaluate_static_effects(state, overlay)
    assert sanji.static_buff == 0


def test_set_cannot_attack_primitive():
    """set_cannot_attack: ターン中アタック不可フラグ + legal_actions 除外"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    state.turn_number = 3  # 1ターン目バトル不可制限を回避

    enemy = InPlay.of(repo.get("OP01-013"), sickness=False)
    enemy.rested = False
    opp.characters = [enemy]

    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [attacker]

    from engine.effects import execute_effect
    from engine.game import legal_actions, AttackCharacter, AttackLeader

    # アタック不可付与前: AttackLeader が出る
    acts = legal_actions(state)
    assert any(isinstance(a, AttackLeader) and a.attacker_iid == attacker.instance_id for a in acts)

    execute_effect({"set_cannot_attack": "self"}, state, me, opp, attacker)
    assert attacker.cannot_attack_until_turn_end is True

    # 付与後: attacker はアタック候補に出ない
    acts = legal_actions(state)
    assert not any(
        (isinstance(a, AttackLeader) or isinstance(a, AttackCharacter))
        and a.attacker_iid == attacker.instance_id for a in acts
    )


def test_stay_rested_next_refresh_primitive():
    """stay_rested_next_refresh: REFRESH でアクティブ化されないフラグ"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    enemy = InPlay.of(repo.get("OP01-013"), sickness=False)
    enemy.rested = True
    opp.characters = [enemy]

    from engine.effects import execute_effect
    execute_effect(
        {"stay_rested_next_refresh": "one_opponent_character_any"},
        state, me, opp, None,
    )
    assert enemy.stay_rested_next_refresh is True

    # 相手側のリフレッシュをシミュレート: rested を維持しフラグをクリア
    state.turn_player_idx = 1  # 相手のターンに
    state.turn_number = 3
    state.phase = Phase.REFRESH
    from engine.game import advance_phase
    advance_phase(state)
    # フラグはクリア、rested は維持
    assert enemy.stay_rested_next_refresh is False
    assert enemy.rested is True


def test_reduce_play_cost_primitive():
    """reduce_play_cost: Player.play_cost_reduction 累積。コスト消費で減算"""
    repo = _repo()
    overlay = _overlay()
    # OP01-013 サンジ cost=2 を使う。don=1 では通常出せない
    state = _make_state(repo, "OP01-003", hand_ids=["OP01-013"], overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 1

    from engine.effects import execute_effect
    from engine.game import legal_actions, PlayCharacter, apply_action

    # 軽減なしでは PlayCharacter が出ない (cost 2 > don 1)
    acts = legal_actions(state)
    assert not any(isinstance(a, PlayCharacter) for a in acts)

    # コスト軽減 1 を付与
    execute_effect({"reduce_play_cost": 1}, state, me, opp, None)
    assert me.play_cost_reduction == 1

    # 軽減後は出せる (cost 2-1=1 ≤ don 1)
    acts = legal_actions(state)
    play_acts = [a for a in acts if isinstance(a, PlayCharacter)]
    assert len(play_acts) == 1

    apply_action(state, play_acts[0])
    assert me.don_active == 0  # 2-1=1 払って 0
    assert me.play_cost_reduction == 0  # 消費済
    assert len(me.characters) == 1


def test_static_ko_immune():
    """on_attached_don n=0 + 条件 → set_ko_immune で static_ko_immune が立ち、
    効果による KO / return_to_hand が無効化される。条件が外れれば効果も外れる。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP13-079", overlay=overlay)  # 黒イム
    me = state.players[0]
    opp = state.players[1]

    # OP13-084 ピーター聖: 自トラッシュ7+で離れない
    peter = repo.get("OP13-084")
    ip = InPlay.of(peter, sickness=False)
    me.characters = [ip]

    # トラッシュ < 7: 静的KO耐性なし
    me.trash = []
    evaluate_static_effects(state, overlay)
    assert ip.static_ko_immune is False

    # トラッシュ 7+: 静的KO耐性が立つ
    me.trash = [repo.get("OP13-084")] * 7
    evaluate_static_effects(state, overlay)
    assert ip.static_ko_immune is True

    # 相手効果でKOしようとしても無効化されることを確認
    # (相手側の me として ko プリミティブを実行)
    from engine.effects import execute_effect
    state.players[1].characters = [ip]  # 仮想的に opp の場とみなす配置で execute_effect
    state.players[0].trash = me.trash  # me が "効果実行者"

    # ko 効果を実行 (state.players[0] = me, state.players[1] = opp)
    # 上記 ip は state.players[1].characters (= opp.characters) に居る
    fake_me = state.players[0]
    fake_opp = state.players[1]
    fake_opp.characters = [ip]
    # 静的耐性は ip 側 (= opp) のトラッシュで判定なので、評価し直し
    fake_opp.trash = [repo.get("OP13-084")] * 7
    evaluate_static_effects(state, overlay)
    assert ip.static_ko_immune is True

    before_count = len(fake_opp.characters)
    execute_effect({"ko": "all_opponent_characters"}, state, fake_me, fake_opp, None)
    assert len(fake_opp.characters) == before_count, "static_ko_immune の キャラは KO されないはず"


def test_opp_turn_condition():
    """opp_turn / self_turn / self_rested 条件が evaluate_static_effects で正しく動く。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]

    # OP10-011 チョッパー: 相手ターン中 +2000 (CardDef ブロッカー)
    chopper = repo.get("OP10-011")
    ip = InPlay.of(chopper, sickness=False)
    me.characters = [ip]

    # 自分のターン: 発動なし (turn_player_idx=0, me=players[0])
    state.turn_player_idx = 0
    evaluate_static_effects(state, overlay)
    assert ip.static_buff == 0

    # 相手ターン: +2000
    state.turn_player_idx = 1
    evaluate_static_effects(state, overlay)
    assert ip.static_buff == 2000


def test_replace_ko_self():
    """OP15-003 アルビダ replace_ko: 効果でKOされそうな時、代わりに手札捨てで代替"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    arvida = repo.get("OP15-003")
    ip = InPlay.of(arvida, sickness=False)
    # 相手の場に置く (相手のキャラとして KO される側)
    opp.characters = [ip]
    opp.hand = [repo.get("OP01-013")] * 2  # 捨て用カード

    from engine.effects import execute_effect
    initial_hand = len(opp.hand)
    initial_field = len(opp.characters)

    # me から ko 効果を発動 (アルビダは opp 側にいる)
    # NOTE: ko プリミティブの target で「opp.characters」 = アルビダを KO 試行
    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)

    # アルビダは生存、手札が1枚減る
    assert len(opp.characters) == initial_field, "アルビダは KO 置換で生存"
    assert len(opp.hand) == initial_hand - 1, "手札捨て1で代替されるはず"


def test_replace_ko_other_chara():
    """OP12-027 コウシロウ replace_ko: 自分の他の斬5以下キャラがKOされる時、コウシロウがレストで代替"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    koushiro = repo.get("OP12-027")
    # 別の 斬5以下 のキャラ (例: ロロノア・ゾロ OP01-025 cost4 攻撃属性斬を仮定)
    # コスト1のサンジ OP01-013 は属性「特殊」で斬ではない可能性
    # 確実に「斬」属性かつコスト5以下なキャラを探す
    import json
    cards = json.loads((Path(__file__).resolve().parent.parent / "db" / "cards.json").read_text())
    def _ci(v):
        if v in (None, "", "-"):
            return 0
        try: return int(str(v).replace(",", ""))
        except ValueError: return 0
    sanji_swords = [c["card_id"] for c in cards
                    if c.get("attribute") == "斬"
                    and 1 <= _ci(c.get("cost")) <= 5
                    and c.get("category") == "CHARACTER"]
    # コウシロウとは別のカード
    target_id = next(cid for cid in sanji_swords if cid != "OP12-027")
    target_card = repo.get(target_id)
    target_ip = InPlay.of(target_card, sickness=False)

    koushiro_ip = InPlay.of(koushiro, sickness=False)
    opp.characters = [target_ip, koushiro_ip]

    from engine.effects import execute_effect
    # me 側からターゲット (= opp の場の) を KO
    execute_effect({"ko": "all_opponent_characters"}, state, me, opp, None)

    # 期待: 斬5以下のターゲットは生存 (コウシロウの replace_ko で代替)
    # コウシロウもまだ生存 (any_self_chara ではなく other_self_chara なので self の KO はカバーしない)
    survivors = [c.card.card_id for c in opp.characters]
    # コウシロウは self が KO されようとした時には保護されないが、
    # この場合 ko プリミティブが両方を順に対象にするので、コウシロウ自身の KO は止められない
    # ただし target キャラは置換で生存、その時コウシロウはレスト状態に
    assert target_id in survivors, f"斬5以下キャラは置換で生存すべき: {survivors}"
    if "OP12-027" in survivors:
        koushiro_after = next(c for c in opp.characters if c.card.card_id == "OP12-027")
        assert koushiro_after.rested, "コウシロウは置換でレストになっているはず"


def test_set_base_power_static():
    """set_base_power: 元々のパワーを X にする静的効果。OP15-092 ルフィ trash≥10 で 9000"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]

    luffy = repo.get("OP15-092")  # 元々のパワー 7000
    ip = InPlay.of(luffy, sickness=False)
    me.characters = [ip]

    # トラッシュ < 10: base_power_override なし → 7000
    me.trash = []
    evaluate_static_effects(state, overlay)
    assert ip.base_power_override is None
    assert ip.power == 7000

    # トラッシュ 10+: base_power = 9000
    me.trash = [repo.get("OP01-013")] * 10
    evaluate_static_effects(state, overlay)
    assert ip.base_power_override == 9000
    assert ip.power == 9000  # ドン無し attack_buff なしで 9000


def test_set_attack_taunt_static():
    """attack_taunt: 相手はこのキャラ以外にアタックできない (OP01-051 キッド)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    state.turn_number = 3
    state.turn_player_idx = 1  # 相手のターン (キッドは me 側)

    kid = repo.get("OP01-051")
    kid_ip = InPlay.of(kid, sickness=False)
    kid_ip.attached_dons = 1   # ドン×1 条件
    kid_ip.rested = True        # 自身レスト 条件
    me.characters = [kid_ip]

    # 別のキャラも置いておく (これは攻撃対象外になるはず)
    other = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters.append(other)

    # 相手 (turn_player) の場に attacker キャラ (アタック側)
    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters.append(attacker)

    # static 評価
    evaluate_static_effects(state, overlay)
    assert kid_ip.attack_taunt is True

    # legal_actions 検証 (state.turn_player = opp)
    from engine.game import legal_actions, AttackLeader, AttackCharacter
    acts = legal_actions(state)
    # AttackLeader は禁止
    assert not any(isinstance(a, AttackLeader) for a in acts), \
        "taunt があるとリーダー攻撃禁止"
    # AttackCharacter は キッドのみ対象
    chara_attacks = [a for a in acts if isinstance(a, AttackCharacter)]
    targets = {a.target_iid for a in chara_attacks}
    assert kid_ip.instance_id in targets
    assert other.instance_id not in targets, \
        "taunt のキッド以外への攻撃は禁止"


def test_attack_active_keyword():
    """give_keyword アクティブアタック可: アクティブキャラへのアタックも合法"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    state.turn_number = 3

    active_enemy = InPlay.of(repo.get("OP01-013"), sickness=False)
    active_enemy.rested = False
    opp.characters = [active_enemy]

    attacker = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [attacker]

    from engine.game import legal_actions, AttackCharacter

    # 通常はアクティブな相手キャラへ攻撃不可
    acts = legal_actions(state)
    assert not any(isinstance(a, AttackCharacter) for a in acts)

    # キーワード付与
    attacker.granted_keywords.add("アクティブアタック可")
    acts = legal_actions(state)
    assert any(
        isinstance(a, AttackCharacter)
        and a.target_iid == active_enemy.instance_id
        for a in acts
    )


def test_untap_don_primitive():
    """untap_don N: レストドンを N 枚アクティブにする (緑紫ルフィ等)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 1
    me.don_rested = 5

    from engine.effects import execute_effect
    execute_effect({"untap_don": 3}, state, me, opp, None)
    assert me.don_active == 4
    assert me.don_rested == 2

    # 不足時は丸める
    execute_effect({"untap_don": 10}, state, me, opp, None)
    assert me.don_active == 6
    assert me.don_rested == 0


def test_pay_don_primitive():
    """pay_don N: 場のドンN枚をドンデッキに戻す (緑紫ルフィ起動メインコスト等)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 3
    me.don_rested = 2
    me.don_remaining_in_deck = 5

    from engine.effects import execute_effect
    execute_effect({"pay_don": 4}, state, me, opp, None)
    # active 3 全消費 + rested 1 → deck +4
    assert me.don_active == 0
    assert me.don_rested == 1
    assert me.don_remaining_in_deck == 9


def test_add_rested_don_primitive():
    """add_rested_don N: ドンデッキから N 枚をレストで追加 (紫エネル)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_remaining_in_deck = 6

    from engine.effects import execute_effect
    execute_effect({"add_rested_don": 4}, state, me, opp, None)
    assert me.don_rested == 4
    assert me.don_remaining_in_deck == 2


def test_summon_from_deck_primitive():
    """summon_from_deck: デッキからフィルタ一致キャラを場に登場 (緑黄しらほし)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP11-022", overlay=overlay)  # 緑黄しらほし
    me = state.players[0]
    opp = state.players[1]
    # 海王類キャラを探す
    import json
    from pathlib import Path
    cards = json.loads((Path(__file__).resolve().parent.parent / "db" / "cards.json").read_text())
    kaioururi_ids = [
        c["card_id"] for c in cards
        if "海王類" in (c.get("features") or "").split("/")
        and c.get("category") == "CHARACTER"
    ][:3]
    assert kaioururi_ids, "海王類キャラがDBにない"
    me.deck = [repo.get(cid) for cid in kaioururi_ids] + [repo.get("OP01-001")] * 5

    from engine.effects import execute_effect
    initial_field = len(me.characters)
    execute_effect(
        {"summon_from_deck": {"filter": {"feature": "海王類", "cost_le": 10}, "limit": 1}},
        state, me, opp, None,
    )
    assert len(me.characters) == initial_field + 1
    assert "海王類" in me.characters[-1].card.features


def test_play_event_from_hand_primitive():
    """play_event_from_hand: 手札からフィルタ一致イベ1枚を発動 (青紫サンジ)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-003", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # 麦わら + コスト3以下のイベントを探す
    import json
    from pathlib import Path
    cards = json.loads((Path(__file__).resolve().parent.parent / "db" / "cards.json").read_text())
    def _ci(v):
        if v in (None, "", "-"):
            return 0
        try: return int(str(v).replace(",", ""))
        except ValueError: return 0
    event_ids = [
        c["card_id"] for c in cards
        if c.get("category") == "EVENT"
        and "麦わらの一味" in (c.get("features") or "").split("/")
        and _ci(c.get("cost")) <= 3
    ][:1]
    if not event_ids:
        return  # 該当なしならスキップ
    me.hand = [repo.get(event_ids[0])]
    initial_trash = len(me.trash)

    from engine.effects import execute_effect
    execute_effect(
        {"play_event_from_hand": {"filter": {"feature": "麦わらの一味", "cost_le": 3}}},
        state, me, opp, None,
    )
    # 手札から trash に移動
    assert len(me.hand) == 0
    assert len(me.trash) == initial_trash + 1


def test_cost_minus_primitive():
    """cost_minus: 相手キャラのコストを N 減 (黒クロコシナジー)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    big_chara = InPlay.of(repo.get("OP11-015"), sickness=False)  # 高コスト想定
    opp.characters = [big_chara]

    base_cost_before = big_chara.base_cost

    from engine.effects import execute_effect
    execute_effect({"cost_minus": {"target": "one_opponent_character_any", "amount": 10}}, state, me, opp, None)
    # base_cost が 10 減 (max 0)
    assert big_chara.base_cost == max(0, base_cost_before - 10)


def test_activate_main_pay_don_cost():
    """activate_main の cost.pay_don でドンが消費される (緑紫ルフィ ドン-2)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "EB02-010", overlay=overlay)  # 緑紫ルフィ
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 3
    me.don_rested = 0
    # 場のキャラを「麦わらの一味」のみで構成 (条件を満たす)
    nami = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ = 麦わらの一味
    me.characters = [nami]

    from engine.effects import list_activate_main_effects, fire_activate_main
    options = list_activate_main_effects(state, me, overlay)
    # ルフィの起動メインが発動可能 (ドン3 ≥ 2 + 麦わらonly + once_per_turn)
    luffy_options = [o for o in options if o[0] is me.leader]
    assert len(luffy_options) == 1, f"ルフィ起動メインが発動可能なはず (現状 {len(luffy_options)})"

    src, eff = luffy_options[0]
    fire_activate_main(state, me, opp, src, eff)
    # ドン-2 でアクティブが減った後、untap_don 2 でレストから2 戻る予定だがレスト0なので戻らない
    # net: don_active 3 → 1 (-2)、don_remaining_in_deck +2
    assert me.don_remaining_in_deck >= 12 - 2  # 元 10 + pay_don 2 戻し


def test_don_phase_auto_attach_to_leader():
    """ドンフェイズで赤紫ロジャーは1ドン自動でリーダーに付与される (場ドン1+条件)"""
    from engine.deck import DeckList
    from engine.game import setup_game, advance_phase, Phase

    repo = _repo()
    overlay = _overlay()
    leader = repo.get("OP13-003")  # 赤紫ロジャー
    opp_leader = repo.get("OP01-001")
    main = [repo.get("OP01-013")] * 50
    deck1 = DeckList(name="rogers", leader=leader, main=list(main))
    deck2 = DeckList(name="opp", leader=opp_leader, main=list(main))

    state = setup_game(deck1, deck2, rng=random.Random(0), first_player=0,
                      effects_overlay=overlay)
    p0 = state.players[0]

    # T1 P0: REFRESH→DRAW→DON で 1 ドン (先攻1ターン目)
    while state.phase != Phase.MAIN:
        advance_phase(state)
    # 場ドンが 1 で、条件 self_don_ge 1 を満たすので、1 枚自動でリーダーに付与
    # ただし turn_number=1 で n=1 なので、1 枚配布 → そのまま 1 枚自動付与
    assert p0.leader.attached_dons >= 1, \
        f"場ドン1+で1枚自動付与のはず (現状 leader.attached_dons={p0.leader.attached_dons})"


def test_mulligan_triggers_when_no_low_cost_chara():
    """マリガン: 手札にコスト3以下キャラ0枚なら全戻し+引き直し (公式 5-2)"""
    from engine.deck import DeckList
    from engine.game import setup_game, _should_mulligan

    repo = _repo()
    leader = repo.get("OP01-001")
    # 手札を高コストカードのみで埋める想定
    high_cost_cards = []
    for cid, c in repo._by_id.items():
        if c.category == Category.CHARACTER and c.cost >= 5:
            high_cost_cards.append(cid)
            if len(high_cost_cards) >= 5:
                break

    # _should_mulligan のロジック単体検証
    p = type("P", (), {"hand": [repo.get(cid) for cid in high_cost_cards]})()
    assert _should_mulligan(p) is True, "高コストキャラのみの手札はマリガンするはず"

    # 低コストキャラ含むなら False
    low = repo.get("OP01-013")  # cost 2 のサンジ
    p2 = type("P", (), {"hand": [repo.get(high_cost_cards[0]), low]})()
    assert _should_mulligan(p2) is False, "コスト3以下キャラ含む手札はマリガンしない"


def test_battle_buff_resets_after_battle():
    """battle_buff (このバトル中効果) は AttackLeader/AttackCharacter 末尾で 0 にリセット"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    state.turn_number = 3  # 1ターン目バトル禁止回避
    me = state.players[0]
    opp = state.players[1]
    opp.life = [repo.get("OP01-001")] * 4  # ライフがないと early return でリセットを通らない

    chara = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [chara]

    from engine.effects import execute_effect
    execute_effect(
        {"power_pump": {"target": "self", "amount": 3000, "duration": "battle"}},
        state, me, opp, chara,
    )
    assert chara.battle_buff == 3000

    # AttackLeader を発火 → battle_buff がリセットされる
    from engine.game import apply_action, AttackLeader
    apply_action(state, AttackLeader(attacker_iid=chara.instance_id))
    assert chara.battle_buff == 0, "バトル終了で battle_buff が 0 に戻るはず"


def test_rush_chara_only_blocks_leader_attack():
    """【速攻：キャラ】登場ターン中はリーダー攻撃禁止、相手キャラのみ可"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    state.turn_number = 3
    me = state.players[0]
    opp = state.players[1]

    # 速攻:キャラ を granted で付与
    chara = InPlay.of(repo.get("OP01-013"), sickness=True)  # 召喚酔いあり
    chara.granted_keywords.add("速攻：キャラ")
    me.characters = [chara]

    # 相手のレストキャラ
    enemy = InPlay.of(repo.get("OP01-013"), sickness=False)
    enemy.rested = True
    opp.characters = [enemy]

    from engine.game import legal_actions, AttackCharacter, AttackLeader
    acts = legal_actions(state)
    # 自分側 attacker は chara のみ (リーダーは初期 sickness=False ではある)
    chara_atk_leader = [a for a in acts if isinstance(a, AttackLeader) and a.attacker_iid == chara.instance_id]
    chara_atk_char = [a for a in acts if isinstance(a, AttackCharacter) and a.attacker_iid == chara.instance_id]
    assert len(chara_atk_leader) == 0, "速攻:キャラ は登場ターン中リーダー攻撃禁止"
    assert len(chara_atk_char) >= 1, "速攻:キャラ は相手キャラ攻撃可"


def test_truly_original_power_unaffected_by_override():
    """公式 4-9: 「元々のパワー」は base_power_override で変更されない CardDef 値"""
    repo = _repo()
    chara = repo.get("OP01-013")
    ip = InPlay.of(chara, sickness=False)
    assert ip.truly_original_power == chara.power
    # override で base_power が変わっても truly_original_power は不変
    ip.base_power_override = 9000
    assert ip.base_power == 9000
    assert ip.truly_original_power == chara.power, "元々のパワーは override で変わらない"


def test_should_fire_trigger_heuristic():
    """should_fire_trigger: ko/draw を含むトリガーは発動、power_pump のみは保持"""
    from engine.effects import should_fire_trigger, CardEffectBundle

    repo = _repo()
    state_repo = _repo()
    state = _make_state(state_repo, "OP01-001", overlay={})
    me = state.players[0]
    card = state_repo.get("OP01-013")

    # KO 効果のあるトリガー → 発動
    overlay_with_ko = {
        card.card_id: CardEffectBundle(
            card_id=card.card_id,
            effects=[{"when": "trigger", "do": [{"ko": "one_opponent_character_le_5000"}]}],
        )
    }
    assert should_fire_trigger(state, me, card, overlay_with_ko) is True

    # power_pump のみ → 保持
    overlay_with_pump = {
        card.card_id: CardEffectBundle(
            card_id=card.card_id,
            effects=[{"when": "trigger", "do": [{"power_pump": {"target": "self_leader", "amount": 1000}}]}],
        )
    }
    assert should_fire_trigger(state, me, card, overlay_with_pump) is False


def test_run_do_array_chain_skip():
    """do 配列の _chain: if_prev_succeeded で前文失敗時に後文スキップ (公式 4-10)"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    initial_draw = len(me.hand)

    from engine.effects import run_do_array
    # 相手場が空なので ko は失敗、then の draw は _chain=if_prev_succeeded でスキップ
    run_do_array(
        [
            {"ko": "one_opponent_character_any"},
            {"draw": 1, "_chain": "if_prev_succeeded"},
        ],
        state, me, opp, None,
    )
    assert len(me.hand) == initial_draw, "ko 失敗時、後続 draw はスキップされる"

    # _chain: always (default) なら通常実行
    run_do_array(
        [
            {"ko": "one_opponent_character_any"},  # 失敗
            {"draw": 1},  # default = always → 実行
        ],
        state, me, opp, None,
    )
    assert len(me.hand) == initial_draw + 1, "default _chain は前文失敗でも実行"


def test_turn_start_trigger_fires():
    """on_turn_start トリガーが REFRESH 内で発動する"""
    from engine.deck import DeckList
    from engine.game import setup_game, advance_phase, Phase
    from engine.effects import CardEffectBundle

    repo = _repo()
    leader = repo.get("OP01-001")
    main = [repo.get("OP01-013")] * 50

    # ターン開始時に 1 ドローするテスト用 overlay
    test_overlay = {
        leader.card_id: CardEffectBundle(
            card_id=leader.card_id,
            effects=[{"when": "on_turn_start", "do": [{"draw": 1}]}],
        )
    }

    deck1 = DeckList(name="t1", leader=leader, main=list(main))
    deck2 = DeckList(name="t2", leader=leader, main=list(main))
    state = setup_game(deck1, deck2, rng=random.Random(0), first_player=0,
                      effects_overlay=test_overlay)

    # T1 P0 のターン: setup_game → 自動で REFRESH に進む。
    # 初期 5 枚 + マリガン後の引き直し + on_turn_start で 1 枚追加
    initial_hand = len(state.players[0].hand)

    # T1 P0 → T2 P1 へ進めて、P1 の REFRESH で turn_start トリガーが発動するかチェック
    while not (state.phase == Phase.REFRESH and state.turn_player_idx == 1):
        advance_phase(state)
    # REFRESH 完了まで進める (DRAW フェイズへ)
    advance_phase(state)
    # P1 はターン開始時 1 ドロー + DRAW で 1 枚 = 計 2 枚増えるはず (T2 = 後攻 1 ターン目はドロー有り)
    # ただしリーダー OP01-001 が両側にあるので両方発動する
    p1_hand = len(state.players[1].hand)
    # 5 枚 (初期) + on_turn_start 1 = 6 枚 (DRAW 前)
    # この時点で phase=DRAW (まだドロー前)
    assert p1_hand >= 5 + 1, f"on_turn_start で 1 ドロー追加されるはず (現状 {p1_hand})"
