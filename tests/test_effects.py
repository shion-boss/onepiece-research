# -*- coding: utf-8 -*-
"""効果DSL のユニットテスト: 個別効果が実際に発動することを確認する。"""

from __future__ import annotations

import random
from pathlib import Path

from engine.core import GameState, InPlay, Phase, Player
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
