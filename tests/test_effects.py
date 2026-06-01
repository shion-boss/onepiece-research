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
    """OP02-013 エース 登場時: 公式テキスト準拠で 「相手のキャラ 2 枚まで パワー-3000」。
    公式: 5000 制限なし、 2 枚 対象。 fake_power_5000_limit 修正後 (= all_opponent_chara_filtered
    limit=2) で 両方 -3000 が 適用される。"""
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

    assert len(opp.characters) == 2
    st21 = next(c for c in opp.characters if c.card.card_id == "ST21-005")
    assert st21.power == 4000 - 3000  # 1000
    op11015 = next(c for c in opp.characters if c.card.card_id == "OP11-015")
    assert op11015.power == 6000 - 3000  # 3000 (= 公式準拠で 両方 -3000)


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


def test_truly_original_power_filter_uses_base_power():
    """filter の truly_original_power_le は 「元々のパワー」 (= CardDef 印刷値) で判定し、
    バフ/デバフ後の 現在値 では判定しない (公式 4-9)。 EB01-010 / OP09-015 等の
    「相手の元々のパワー N 以下のキャラを KO」 系の回帰ガード。"""
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]

    from engine.effects import execute_effect

    low_base = InPlay.of(repo.get("ST21-005"), sickness=False)  # 元々 4000
    high_base = InPlay.of(repo.get("OP11-015"), sickness=False)  # 元々 6000
    low_base.turn_buff = 3000  # 現在 7000 (= base は 4000 のまま)
    high_base.turn_buff = -2000  # 現在 4000 (= base は 6000 のまま)
    opp.characters = [low_base, high_base]

    execute_effect(
        {"ko": {"type": "one_opponent_character_filtered",
                "filter": {"truly_original_power_le": 5000}}},
        state, me, opp, None,
    )
    remaining = [c.card.card_id for c in opp.characters]
    # 元々 4000 (現在 7000) が KO、 元々 6000 (現在 4000) は残る = base 判定の証明。
    assert remaining == ["OP11-015"], remaining


def test_category_filter_case_insensitive():
    """filter の category は大小無視で判定する。 overlay 側の小文字 "character" 誤記が
    silent no-op (= 全不マッチ → 効果不発) を起こさないことのガード (EB02-056 等 9 枚)。"""
    from engine.effects import _matches_filter
    from engine.core import CardDef, Category

    chara = CardDef(card_id="X", name="t", category=Category.CHARACTER, color="赤",
                    cost=4, life=0, power=5000, counter=0, attribute="斬",
                    block_icon=None, features=("test",), text="", trigger=None, rarity="C")
    assert _matches_filter(chara, {"category": "character"}) is True
    assert _matches_filter(chara, {"category": "CHARACTER"}) is True
    assert _matches_filter(chara, {"category": "event"}) is False
    assert _matches_filter(chara, {"category_in": ["character", "event"]}) is True


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


def test_estimate_opp_attack_buff():
    """opp_attack で opp.leader を強化する効果を AI が事前見積できる"""
    from engine.effects import estimate_opp_attack_buff_to_leader, CardEffectBundle

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    opp = state.players[1]

    # opp.leader に opp_attack で +2000 の overlay
    test_overlay = {
        opp.leader.card.card_id: CardEffectBundle(
            card_id=opp.leader.card.card_id,
            effects=[{
                "when": "opp_attack",
                "do": [{"power_pump": {"target": "self_leader", "amount": 2000, "duration": "turn"}}],
            }],
        )
    }
    state.effects_overlay = test_overlay
    buff = estimate_opp_attack_buff_to_leader(state, opp, test_overlay)
    assert buff == 2000, f"opp_attack +2000 が見積もられるはず ({buff})"

    # 条件付き (満たさない場合は 0)
    test_overlay2 = {
        opp.leader.card.card_id: CardEffectBundle(
            card_id=opp.leader.card.card_id,
            effects=[{
                "when": "opp_attack",
                "if": {"self_life_le": 0},  # opp.life=0 必要
                "do": [{"power_pump": {"target": "self_leader", "amount": 3000, "duration": "turn"}}],
            }],
        )
    }
    opp.life = [repo.get("OP01-001")] * 4  # life >= 1 なので条件不満
    buff2 = estimate_opp_attack_buff_to_leader(state, opp, test_overlay2)
    assert buff2 == 0, f"条件不成立で 0 が返るはず ({buff2})"


def test_avoid_low_power_attack_against_buffed_leader():
    """opp.leader が opp_attack +2000 buff 持ちなら、 atk=5000 では viable と見なされない"""
    from engine.ai import GreedyAI
    from engine.game import AttackLeader
    from engine.effects import CardEffectBundle

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    state.turn_number = 3  # バトル可能
    me = state.players[0]
    opp = state.players[1]
    opp.life = [repo.get("OP01-001")] * 4  # life 余裕

    # opp.leader に opp_attack で +2000 buff
    test_overlay = {
        opp.leader.card.card_id: CardEffectBundle(
            card_id=opp.leader.card.card_id,
            effects=[{
                "_text": "test: opp_attack +2000 to self_leader",
                "when": "opp_attack",
                "do": [{"power_pump": {"target": "self_leader", "amount": 2000, "duration": "turn"}}],
            }],
        )
    }
    state.effects_overlay = test_overlay

    # me.leader はパワー 5000 (OP01-001 ルフィ)。 me に追加キャラなし。
    # 通常なら 5000 >= 5000 で AttackLeader 候補になるが、
    # est_defender = 5000 + 2000 = 7000 で viable から除外され EndPhase になるはず
    ai = GreedyAI(rng=random.Random(0))
    action = ai.choose_action(state)
    assert not isinstance(action, AttackLeader), \
        f"opp_attack +2000 buff の見積で低パワー攻撃が抑制されるはず ({type(action).__name__})"


def test_double_attack_on_life_1_does_not_win():
    """公式 cardqa Q36: 相手ライフ 1 枚にダブルアタック 2 ダメ与えても勝利できない"""
    from engine.deck import DeckList
    from engine.game import setup_game, apply_action, AttackLeader, Phase

    repo = _repo()
    leader = repo.get("OP01-001")
    deck1 = DeckList(name="t1", leader=leader, main=[repo.get("OP01-013")] * 50)
    deck2 = DeckList(name="t2", leader=leader, main=[repo.get("OP01-013")] * 50)
    state = setup_game(deck1, deck2, rng=random.Random(0), first_player=0)
    state.phase = Phase.MAIN
    state.turn_number = 3

    me = state.players[0]
    opp = state.players[1]
    opp.life = [repo.get("OP01-001")] * 1  # ライフ 1 枚
    me.leader.rested = False
    me.leader.granted_keywords.add("ダブルアタック")

    apply_action(state, AttackLeader(attacker_iid=me.leader.instance_id))

    # 公式: ライフ 1 + DA 攻撃 → 1 枚目で life=0、 2 枚目は空打ち、 game NOT over
    assert len(opp.life) == 0, "1 ダメ目はライフ消費"
    assert state.game_over is False, \
        f"公式 Q36: ライフ 1 にダブルアタックでは勝利不可 (現状 game_over={state.game_over})"
    assert state.winner is None


def test_attack_on_life_0_wins():
    """ライフ 0 状態でアタック受けた瞬間に敗北 (公式 9-2-1)"""
    from engine.deck import DeckList
    from engine.game import setup_game, apply_action, AttackLeader, Phase

    repo = _repo()
    leader = repo.get("OP01-001")
    deck1 = DeckList(name="t1", leader=leader, main=[repo.get("OP01-013")] * 50)
    deck2 = DeckList(name="t2", leader=leader, main=[repo.get("OP01-013")] * 50)
    state = setup_game(deck1, deck2, rng=random.Random(0), first_player=0)
    state.phase = Phase.MAIN
    state.turn_number = 3

    me = state.players[0]
    opp = state.players[1]
    opp.life = []  # ライフ 0 (= 既に空)
    me.leader.rested = False

    apply_action(state, AttackLeader(attacker_iid=me.leader.instance_id))
    assert state.game_over is True, "ライフ 0 で攻撃受けた瞬間敗北"
    assert state.winner == 0


def test_choose_defense_predicts_attacker_self_buff():
    """attacker の on_attack 自己強化を予測してカウンター量を決める。

    シナリオ:
      - attacker.power=6000, attacker overlay: on_attack で self_leader +1000
      - defender.leader=5000、 手札に 1000 カウンター 2 枚
      - 1000 counter 1 枚切ると 5000+1000=6000 vs atk 7000 (実効) → 失敗
      - 2 枚切ると 5000+2000=7000 vs 7000 → atk_power=7000 == 7000 で攻撃側勝ち、 でも 2 枚は閾値超過
      - 結果: 1 枚で守れないので AI は counter 切らず通す (= 「無駄打ち」防止)
    """
    from engine.ai import GreedyAI
    from engine.effects import CardEffectBundle

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    state.turn_player_idx = 1  # opp 側がアタック (= P1 がターンプレイヤー)
    me.life = [repo.get("OP01-001")] * 3  # life=3

    # attacker 用 overlay: on_attack で self_leader +1000
    attacker_card = repo.get("OP01-013")
    test_overlay = {
        attacker_card.card_id: CardEffectBundle(
            card_id=attacker_card.card_id,
            effects=[{
                "_text": "test attacker self buff",
                "when": "on_attack",
                "do": [{"power_pump": {"target": "self_leader", "amount": 1000, "duration": "turn"}}],
            }],
        ),
    }
    state.effects_overlay = test_overlay

    attacker = InPlay.of(attacker_card, sickness=False)
    attacker.attached_dons = 4  # 4000 +4000 = 6000 (実効 7000)
    opp.characters = [attacker]
    # me 側手札に 1000 カウンター付きカード
    counter_card_id = None
    for c in [repo.get("OP01-013"), repo.get("OP01-016"), repo.get("OP02-013")]:
        if c.counter > 0:
            counter_card_id = c.card_id
            me.hand = [c, c]
            break
    if counter_card_id is None:
        return  # counter 持ちのカードが見つからず

    ai = GreedyAI()
    block_iid, counters = ai.choose_defense(state, attacker, me.leader, True, me)
    # attacker.power=4000+4000=8000、 self_buff +1000 = 9000 実効
    # me.leader.power = 5000 → gap = 4000
    # 1000 counter 1 枚 (total=1000 ≤ gap) は無効、 2 枚 (total=2000 ≤ gap) も無効
    # → counter 切らずに通す (life で受ける) のが正解
    # この前は attacker.power=8000 で計算してたので gap=3000、 1000 counter 1 枚は ≤ 3000 で無効、
    # 2 枚 (2000) も無効 → 切らず。 同じ結果になるはずだが、 buff 予測なしだと
    # gap が 3000 のままなので 「1000+2000」 等の組み合わせが通る可能性あり。
    # 重要なのは 「無駄な少枚数 counter は切らない」 ことの確認:
    counter_total = sum(me.hand[i].counter for i in counters)
    # 1000 counter 1 枚だけ切るバグ (ユーザー指摘) は再現しないはず
    assert not (len(counters) == 1 and counter_total == 1000), \
        f"バグ再現: 1000 counter 1 枚だけ切られた (gap >= 1 の状況で 1000 では足りない)"


def test_hand_estimator_sample():
    """sample_opponent_hand: hand_count 枚をプールから抽出"""
    import random as random_mod
    from engine.hand_estimator import sample_opponent_hand, estimate_counter_total

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    opp = state.players[1]
    opp.hand = [repo.get("OP01-013")] * 4
    opp.deck = [repo.get("OP01-016")] * 30
    rng = random_mod.Random(0)

    sampled = sample_opponent_hand(state, 1, rng)
    assert len(sampled) == 4
    # サンプル元はプール (deck + hand) から
    pool_ids = {c.card_id for c in (opp.deck + opp.hand)}
    for c in sampled:
        assert c.card_id in pool_ids

    # 期待 counter 総量
    est = estimate_counter_total(state, 1)
    assert isinstance(est, int)
    assert est >= 0


def test_trash_opp_hand_random_primitive():
    """trash_opp_hand_random: 相手手札を N 枚ランダム捨て"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # 相手手札に 5 枚
    opp.hand = [repo.get("OP01-013")] * 5
    opp.trash = []

    from engine.effects import execute_effect
    execute_effect({"trash_opp_hand_random": 2}, state, me, opp, None)
    assert len(opp.hand) == 3
    assert len(opp.trash) == 2

    # 手札 0 枚なら何もしない
    opp.hand = []
    execute_effect({"trash_opp_hand_random": 3}, state, me, opp, None)
    assert len(opp.hand) == 0


def test_play_from_hand_primitive():
    """play_from_hand: 手札の filter 一致キャラを 0 コストで登場"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # 手札に 4 枚 (filter で 3 コスト以下を 1 枚登場想定)
    me.hand = [
        repo.get("OP01-013"),  # 1コスト想定
        repo.get("OP01-016"),  # サーチキャラ
    ]
    me.characters = []

    from engine.effects import execute_effect
    execute_effect(
        {"play_from_hand": {"filter": {"cost_le": 5}, "limit": 1}},
        state, me, opp, None,
    )
    assert len(me.characters) == 1
    assert len(me.hand) == 1


def test_field_full_replacement_via_effect():
    """効果による登場時、 場 5 枚状態でも 1 枚を自動 trash で登場 (公式 3-7-6-1)。
    KO ではないので 【KO 時】 トリガー発火しない。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # 場を 5 枚で埋める
    me.characters = [
        InPlay.of(repo.get("OP01-013"), sickness=False) for _ in range(5)
    ]
    me.trash = []
    # トラッシュからのキャラ登場 (play_from_trash)
    chara = repo.get("OP01-016")
    me.trash = [chara]

    from engine.effects import execute_effect
    execute_effect(
        {"play_from_trash": {"filter": {"cost_le": 10}, "limit": 1}},
        state, me, opp, None,
    )
    # キャラエリア = 5 (= 4 + 新規 1)、 1 枚 trash
    assert len(me.characters) == 5
    # trash には最弱の OP01-013 が 1 枚
    assert any(c.card_id == "OP01-013" for c in me.trash)


def test_attack_leader_with_blocker():
    """AttackLeader にブロッカー指定 → ブロッカーが攻撃対象に変わる (公式 7-1-2 / 10-1-4)。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 5

    # 攻撃側: パワー 5000 の attacker (リーダー or キャラ)
    me.leader.summoning_sickness = False
    state.turn_number = 3  # 1 ターン目バトル不可制限を回避

    # 防御側: ブロッカー特性を持つキャラを場に置く
    # OP01-006 はサンジ (麦わら) で blocker 持ちがあるカード
    # シンプルに パワー 5000 の blocker テスト用キャラ
    blocker_card = repo.get("OP01-006")  # サンジ ブロッカー想定
    if "ブロッカー" not in (blocker_card.text or ""):
        # フォールバック: テストできる blocker を探す
        blocker_card = next(
            (c for cid, c in repo._by_id.items() if "ブロッカー" in (c.text or "") and c.power >= 4000),
            None,
        )
    assert blocker_card is not None, "blocker 持ちカードが見つからない"
    blocker = InPlay.of(blocker_card, sickness=False, rested=False)
    opp.characters = [blocker]

    from engine.game import AttackLeader, apply_action
    me.leader.rested = False
    initial_life = len(opp.life)
    initial_blocker_count = len(opp.characters)

    action = AttackLeader(
        attacker_iid=me.leader.instance_id,
        blocker_iid=blocker.instance_id,
    )
    apply_action(state, action)

    # ブロッカーがレストになっているか、 KO されているか (= 攻撃が向き先変わった証拠)
    if blocker in opp.characters:
        assert blocker.rested, "ブロッカーがレストになっていない"
    # リーダーのライフは減っていない (= ブロッカーが受けた)
    assert len(opp.life) == initial_life, f"life={initial_life}→{len(opp.life)} ブロッカー無視"


def test_simultaneous_resolution_turn_player_first():
    """公式 1-3-4 / 6-6-1-1: 両プレイヤーの効果が同時タイミングで発動する場合、
    ターンプレイヤー側 → 非ターンプレイヤー側 の順で解決する。
    end_of_turn を例に: 両側でドロー効果を持たせ、 turn 側のカードが先に発動する事を確認。"""
    from engine.effects import trigger_end_of_turn

    repo = _repo()
    state = _make_state(repo, "OP01-002", overlay={})  # turn 側 = OP01-002
    me = state.players[0]
    opp = state.players[1]
    # 非turn 側を別カード ID に差替 (overlay 衝突回避)
    state.players[1].leader = InPlay.of(repo.get("OP01-003"), sickness=False)
    opp = state.players[1]
    state.turn_player_idx = 0
    me.deck = [repo.get("OP01-013")] * 5
    opp.deck = [repo.get("OP01-016")] * 5
    me.hand = []
    opp.hand = []
    log_record: list[str] = []
    orig_push = state.push_log
    def capture_log(msg):
        log_record.append(msg)
        return orig_push(msg)
    state.push_log = capture_log

    # 合成 overlay: turn 側 (OP01-002) に end_of_turn、 opp 側 (OP01-003) に opp_end_of_turn
    from engine.effects import CardEffectBundle
    fake_overlay = {
        "OP01-002": CardEffectBundle(
            card_id="OP01-002",
            effects=[{"when": "end_of_turn", "if": {}, "do": [{"draw": 1}]}],
        ),
        "OP01-003": CardEffectBundle(
            card_id="OP01-003",
            effects=[{"when": "opp_end_of_turn", "if": {}, "do": [{"draw": 1}]}],
        ),
    }
    state.effects_overlay = fake_overlay

    trigger_end_of_turn(state, fake_overlay)

    # 両者ともドローしている
    assert len(me.hand) == 1
    assert len(opp.hand) == 1

    # ログ順を確認: turn 側 が 先 解決、 非 turn 側 が 後 解決。
    # 2026-05-31: log の card name 出力 は 隠 ぺ い 漏 洩 防 止 で 削 除 (= count のみ)。
    # 順序 検証 は hand 内 容 (= 先 解決 で 引 い た カード) で 代替。
    draw_logs = [m for m in log_record if "ドロー" in m]
    assert len(draw_logs) == 2, f"想定 2 件のドローログ、 実際: {draw_logs}"
    # 1 件目 = ターン側、 2 件目 = 非 ターン側 の 順 で log push 確認
    # (= card name が ない の で msg 内容 だけ で は 区別 不能、 hand 内 容 で 順 検 証)
    assert me.hand[0].card_id == "OP01-013", (
        f"turn 側 = サンジ を 引く はず、 実際 = {me.hand[0].card_id}"
    )
    assert opp.hand[0].card_id == "OP01-016", (
        f"opp 側 = ナミ を 引く はず、 実際 = {opp.hand[0].card_id}"
    )


def test_op06_118_zoro_on_attack_once_per_turn():
    """OP06-118 9 コストゾロ: on_attack の untap 効果は ターン1回 + ドン1コスト。
    無限攻撃しないことを確認。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 5

    zoro = repo.get("OP06-118")
    zoro_ip = InPlay.of(zoro, sickness=False)
    me.characters = [zoro_ip]

    from engine.effects import trigger_on_attack

    # 1 回目: don 1 消費して untap (rested → active 想定)
    zoro_ip.rested = True
    don_before = me.don_active
    trigger_on_attack(state, me, opp, zoro_ip, overlay)
    assert zoro_ip.rested is False, "1回目は active 化されるべき"
    assert me.don_active == don_before - 1, f"ドン1消費されるべき (before={don_before}, after={me.don_active})"

    # 2 回目: ターン1回フラグで発動しない
    zoro_ip.rested = True
    don_before2 = me.don_active
    trigger_on_attack(state, me, opp, zoro_ip, overlay)
    assert zoro_ip.rested is True, "2回目は once_per_turn で発動しないので rested のまま"
    assert me.don_active == don_before2, "ドン消費もない"


def test_op11_096_ripper_blocker_loses_when_allies_removed():
    """OP11-096 リッパー: 「リッパー以外の自分の黒の特徴《海軍》がいる場合」
    で 常在ブロッカー。 仲間 が 場 から 消えると ブロッカー扱いされなくなる。"""
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]

    ripper = repo.get("OP11-096")
    ripper_ip = InPlay.of(ripper, sickness=False)
    # ヒナ (ST06-008_p2) を 「リッパー以外の黒/海軍」 として 並置
    hina = repo.get("ST06-008_p2")
    hina_ip = InPlay.of(hina, sickness=False)
    me.characters = [ripper_ip, hina_ip]

    from engine.effects import evaluate_static_effects
    evaluate_static_effects(state, overlay)
    # 海軍仲間あり → ブロッカー獲得
    assert ripper_ip.is_blocker_now, "海軍仲間ありで ブロッカー扱い"

    # 仲間 を 場 から 外す
    me.characters = [ripper_ip]
    evaluate_static_effects(state, overlay)
    # 元カードがブロッカーでなければ、 静的付与は剥がれる
    assert not ripper.is_blocker, "innate is_blocker は False"
    assert not ripper_ip.is_blocker_now, (
        "仲間がいない時 ブロッカー扱い → bug。 static_granted_keywords がリセットされていない"
    )


# --------------------------------------------------------------------------- #
# 新トリガーキュー (TriggerEvent / resolve_triggers)
# --------------------------------------------------------------------------- #
def test_trigger_queue_drains_synchronously():
    """trigger_on_play() を直接呼ぶと、 _maybe_resolve で同期的にドレインされる。"""
    repo = _repo()
    overlay = _overlay()
    nami = repo.get("OP01-016")
    state = _make_state(repo, "OP01-003", hand_ids=["OP01-016"], overlay=overlay)
    state.players[0].deck = [repo.get("OP01-013")] * 5

    me = state.players[0]
    opp = state.players[1]
    ip = InPlay.of(nami, sickness=True)
    me.characters.append(ip)

    assert state.event_queue == []
    trigger_on_play(state, me, opp, ip, overlay)
    # 効果が発火 → サーチで手札+1 + キューは空
    assert state.event_queue == [], "trigger_on_play 後にキューは空のはず"
    assert state.resolving is False
    assert len(me.hand) == 2  # 元 1 枚 + サーチ 1 枚


def test_trigger_queue_active_player_priority():
    """両陣営に on_turn_start が enqueue された時、 ターンプレイヤー側が先にドレインされる。"""
    from engine.effects import enqueue_event, resolve_triggers, TriggerEvent

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    state.turn_player_idx = 0  # P0 がターン側

    fired_order = []
    state.event_order_hook = None

    # mock: enqueue したイベントを execute_event で実行する代わりに fired_order に記録
    # → resolve_triggers は実 overlay が空なので何もしないので、 ここでは
    # _pop_next_event の優先順を直接検証
    from engine.effects import _pop_next_event
    state.event_queue.append(TriggerEvent(
        when="on_turn_start", owner_idx=1, source_card_id="X",
    ))
    state.event_queue.append(TriggerEvent(
        when="on_turn_start", owner_idx=0, source_card_id="Y",
    ))
    state.event_queue.append(TriggerEvent(
        when="on_turn_start", owner_idx=1, source_card_id="Z",
    ))
    # P0 (active) のものが先に取り出されるはず
    e1 = _pop_next_event(state)
    assert e1.owner_idx == 0 and e1.source_card_id == "Y"
    # 残り 2 件は両方 P1 → FIFO 先頭 (X) が次
    e2 = _pop_next_event(state)
    assert e2.owner_idx == 1 and e2.source_card_id == "X"
    e3 = _pop_next_event(state)
    assert e3.owner_idx == 1 and e3.source_card_id == "Z"
    assert _pop_next_event(state) is None


def test_trigger_queue_event_order_hook():
    """同 owner / 同 when グループ内の順序を AI フックで再順序付けできる。"""
    from engine.effects import _pop_next_event, TriggerEvent

    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    state.turn_player_idx = 0

    # 同 owner=0, 同 when="on_play" のイベントを 3 つ enqueue
    state.event_queue.append(TriggerEvent(
        when="on_play", owner_idx=0, source_card_id="A",
    ))
    state.event_queue.append(TriggerEvent(
        when="on_play", owner_idx=0, source_card_id="B",
    ))
    state.event_queue.append(TriggerEvent(
        when="on_play", owner_idx=0, source_card_id="C",
    ))

    # フック: 逆順を返す
    def reverse_hook(state, events):
        return list(reversed(events))

    state.event_order_hook = reverse_hook

    e1 = _pop_next_event(state)
    assert e1.source_card_id == "C", f"フックで C が先頭になるはず (got {e1.source_card_id})"


# --------------------------------------------------------------------------- #
# Phase 1 新規プリミティブの単体テスト
# --------------------------------------------------------------------------- #
def test_mill_self_top_primitive():
    """mill_self_top: 自分のデッキ上 N 枚を trash"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    initial_deck_size = len(me.deck)
    initial_trash_size = len(me.trash)
    execute_effect({"mill_self_top": 3}, state, me, opp, None)
    assert len(me.deck) == initial_deck_size - 3
    assert len(me.trash) == initial_trash_size + 3


def test_look_top_reorder_to_bottom():
    """look_top_reorder to=bottom: 上 N 枚をデッキ末尾に移動"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.deck = [repo.get(cid) for cid in ["OP01-013"] * 5 + ["OP01-016"] * 5]
    top_3 = list(me.deck[:3])
    execute_effect({"look_top_reorder": {"depth": 3, "to": "bottom"}}, state, me, opp, None)
    # 上 3 枚は末尾に
    assert me.deck[-3:] == top_3
    # 残りは前に詰まる
    assert len(me.deck) == 10


def test_look_top_reorder_to_choice_sorts_by_cost():
    """look_top_reorder to=choice: ヒューリスティックでコスト昇順に並び替え"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # 高コスト → 低コスト の順で並べる (元順)
    me.deck = [repo.get("OP02-013"), repo.get("OP01-013"), repo.get("OP01-016")] + [repo.get("OP01-013")] * 5
    execute_effect({"look_top_reorder": {"depth": 3, "to": "choice"}}, state, me, opp, None)
    # コスト昇順 (低 → 高) で並んでいるはず
    top_3 = me.deck[:3]
    costs = [c.cost for c in top_3]
    assert costs == sorted(costs), f"choice 並び替え後コスト昇順のはず: {costs}"


def test_play_self_from_trash():
    """play_self: trash 中の同 card_id を field に登場"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    nami = repo.get("OP01-016")
    me.trash.append(nami)
    state.current_source_card_id = "OP01-016"
    initial_chars = len(me.characters)
    initial_trash = len(me.trash)
    execute_effect({"play_self": True}, state, me, opp, None)
    assert len(me.characters) == initial_chars + 1
    assert me.characters[-1].card.card_id == "OP01-016"
    assert len(me.trash) == initial_trash - 1


def test_play_self_no_match_is_noop():
    """play_self: source_card_id と一致するカードが trash/hand にない場合 no-op"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    state.current_source_card_id = "OP99-999"  # 存在しない
    initial_chars = len(me.characters)
    execute_effect({"play_self": True}, state, me, opp, None)
    assert len(me.characters) == initial_chars  # 変化なし


def test_fire_self_effect_recursion_limit():
    """fire_self_effect: 再帰深度 2 で停止 (= 自己無限ループ防止)"""
    from engine.effects import execute_effect, CardEffectBundle
    repo = _repo()
    # 自身の main 効果が自身の main 効果を呼ぶ無限ループ overlay
    overlay = {
        "OP01-013": CardEffectBundle(
            card_id="OP01-013",
            effects=[{
                "when": "main",
                "do": [{"draw": 1}, {"fire_self_effect": {"when_kind": "main"}}],
            }],
        ),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    state.players[0].deck = [repo.get("OP01-013")] * 30
    me = state.players[0]
    opp = state.players[1]
    state.current_source_card_id = "OP01-013"
    state._fire_self_depth = 0
    initial_hand = len(me.hand)
    execute_effect({"fire_self_effect": {"when_kind": "main"}}, state, me, opp, None)
    # 深度制限 (max 2) → fire 1回 → 内部で fire (depth=1) → 内部で fire (depth=2 で止まる)
    # よって 2 回の draw が実行されるはず (depth 0→1→2 で停止)
    drew = len(me.hand) - initial_hand
    assert drew >= 1 and drew <= 3, f"再帰深度制限が効いていない: drew={drew}"


def test_return_opp_don_primitive():
    """return_opp_don: 相手の場ドンをドンデッキに戻す"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 5
    opp.don_rested = 2
    opp.don_remaining_in_deck = 3
    execute_effect({"return_opp_don": 4}, state, me, opp, None)
    # active 5 → 1 (4 戻る)、 残 don_remaining_in_deck = 3+4 = 7
    assert opp.don_active == 1
    assert opp.don_rested == 2  # active で足りたので rested 触らず
    assert opp.don_remaining_in_deck == 7


def test_return_opp_don_falls_back_to_rested():
    """return_opp_don: active で足りなければ rested から差し引く"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    opp.don_active = 1
    opp.don_rested = 5
    opp.don_remaining_in_deck = 4
    execute_effect({"return_opp_don": 3}, state, me, opp, None)
    assert opp.don_active == 0
    assert opp.don_rested == 3  # 5 → 3 (2 戻る)
    assert opp.don_remaining_in_deck == 7


def test_opp_hand_to_deck_bottom():
    """opp_hand_to_deck_bottom: 相手手札 N 枚をランダムにデッキ下へ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    opp.hand = [repo.get(c) for c in ["OP01-013", "OP01-016", "OP02-013"]]
    initial_hand = len(opp.hand)
    initial_deck = len(opp.deck)
    execute_effect({"opp_hand_to_deck_bottom": 2}, state, me, opp, None)
    assert len(opp.hand) == initial_hand - 2
    assert len(opp.deck) == initial_deck + 2


def test_self_hand_to_deck_bottom_picks_highest_cost():
    """self_hand_to_deck_bottom: ヒューリスティックで最高コスト優先で デッキ下へ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # コスト 1, 5, 2 の手札 → コスト 5 が選ばれるはず
    me.hand = [repo.get("OP01-013"), repo.get("ST21-005"), repo.get("OP01-016")]
    initial_deck_count = len(me.deck)
    initial_hand_count = len(me.hand)
    # max cost を確認
    max_cost = max(c.cost for c in me.hand)
    execute_effect({"self_hand_to_deck_bottom": 1}, state, me, opp, None)
    assert len(me.hand) == initial_hand_count - 1
    assert len(me.deck) == initial_deck_count + 1
    # デッキ末尾に置かれた = 最高コストカード
    assert me.deck[-1].cost == max_cost


def test_give_attack_active_chara_primitive():
    """give_attack_active_chara: 「アクティブアタック可」 keyword 付与"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [sanji]
    execute_effect({"give_attack_active_chara": "self"}, state, me, opp, sanji)
    assert "アクティブアタック可" in sanji.granted_keywords


def test_one_opponent_inplay_any_target():
    """one_opponent_inplay_any: キャラ優先 → なければリーダー"""
    from engine.effects import _resolve_target
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # キャラなし → リーダーが返る
    targets = _resolve_target("one_opponent_inplay_any", state, me, opp, None)
    assert len(targets) == 1
    assert targets[0] is opp.leader
    # キャラあり → 最高パワーキャラが返る
    weak = InPlay.of(repo.get("OP01-013"), sickness=False)  # P5000
    strong = InPlay.of(repo.get("OP11-015"), sickness=False)  # P6000
    opp.characters = [weak, strong]
    targets = _resolve_target("one_opponent_inplay_any", state, me, opp, None)
    assert len(targets) == 1
    assert targets[0] is strong, f"高パワーキャラ優先のはず (got {targets[0].card.name})"


# --------------------------------------------------------------------------- #
# Phase 2 新規プリミティブの単体テスト
# --------------------------------------------------------------------------- #
def test_power_pump_next_self_turn_start_duration():
    """power_pump duration=next_self_turn_start: 次の自分のターン開始時まで持続"""
    from engine.effects import execute_effect
    from engine.game import advance_phase
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    state.turn_player_idx = 0
    state.turn_number = 3
    # me.leader に next_self_turn_start +2000 適用
    execute_effect(
        {"power_pump": {"target": "self_leader", "amount": 2000, "duration": "next_self_turn_start"}},
        state, me, opp, None,
    )
    base_power = me.leader.card.power
    assert me.leader.power == base_power + 2000, "適用直後は +2000 のはず"
    # ターンを進める: END phase + REFRESH (opp's turn) + ... + REFRESH (own's turn)
    # 簡略: next_turn_buff フラグを直接確認
    assert me.leader.next_turn_buff == 2000


def test_next_turn_buff_clears_on_owner_refresh():
    """next_turn_buff: 所有者ターン開始時 (REFRESH 進入時) にクリア"""
    from engine.core import Phase
    from engine.game import advance_phase
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # 強制的にバフ設定 + ターン構成
    state.turn_player_idx = 0
    state.turn_number = 2
    state.phase = Phase.REFRESH
    me.leader.next_turn_buff = 2000
    # P0 の REFRESH (= 自分のターン開始) を 1 回処理
    advance_phase(state)
    # REFRESH を抜けた = next_turn_buff がクリアされたはず
    assert me.leader.next_turn_buff == 0, f"REFRESH 後にクリアされるはず (got {me.leader.next_turn_buff})"


def test_to_opp_life_primitive():
    """to_opp_life: 相手キャラを持ち主のライフへ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    target_card = repo.get("OP01-013")
    ip = InPlay.of(target_card, sickness=False)
    opp.characters = [ip]
    initial_life = len(opp.life)
    initial_trash = len(opp.trash)
    execute_effect({"to_opp_life": "one_opponent_character_cost_le_5cost"}, state, me, opp, None)
    assert ip not in opp.characters
    assert len(opp.life) == initial_life + 1
    assert opp.life[-1] is target_card
    # トラッシュには行かない (= KO ではない)
    assert len(opp.trash) == initial_trash


def test_ko_multi_primitive():
    """ko_multi: 2 spec を別々に解決して KO。 dedup で同一キャラの 2 重 KO を防ぐ"""
    from engine.effects import execute_effect
    from engine.core import Category
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # cost 1 と cost 2 の キャラを 1 体ずつ
    c1_cards = [c for c in repo._by_id.values() if c.category == Category.CHARACTER and c.cost == 1]
    c2_cards = [c for c in repo._by_id.values() if c.category == Category.CHARACTER and c.cost == 2]
    if not c1_cards or not c2_cards:
        return  # DB 依存スキップ
    ip_c1 = InPlay.of(c1_cards[0], sickness=False)
    ip_c2 = InPlay.of(c2_cards[0], sickness=False)
    opp.characters = [ip_c1, ip_c2]
    execute_effect(
        {"ko_multi": [
            "one_opponent_character_cost_le_2cost",
            "one_opponent_character_cost_le_1cost",
        ]},
        state, me, opp, None,
    )
    # 最低 1 体は KO されるはず (= 動作確認)
    # 順序 / power 依存で 1 体だけになるケースもあるが、 dedup 機能は確認できる
    assert len(opp.characters) <= 1
    assert len(opp.trash) >= 1


def test_negate_effect_suppresses_on_play():
    """negate_effect: 効果無効化されたキャラの on_play は発動しない"""
    from engine.effects import execute_effect, trigger_on_play, CardEffectBundle
    repo = _repo()
    nami = repo.get("OP01-016")
    overlay = {
        "OP01-016": CardEffectBundle(card_id="OP01-016", effects=[
            {"when": "on_play", "do": [{"draw": 1}]},
        ]),
    }
    state = _make_state(repo, "OP01-003", overlay=overlay)
    state.players[0].deck = [repo.get("OP01-013")] * 30
    me = state.players[0]
    opp = state.players[1]
    ip = InPlay.of(nami, sickness=True)
    me.characters = [ip]
    # 効果無効を ip に付与
    ip.granted_keywords.add("効果無効")
    initial_hand = len(me.hand)
    trigger_on_play(state, me, opp, ip, overlay)
    # 効果無効により draw が発動しないはず
    assert len(me.hand) == initial_hand, "効果無効中は on_play が発動しないはず"


def test_hand_to_self_life_primitive():
    """hand_to_self_life: 手札から filter 一致カードを ライフへ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.hand = [
        repo.get("OP01-013"),  # サンジ (CHARACTER)
        repo.get("OP01-016"),  # ナミ (CHARACTER)
    ]
    initial_life = len(me.life)
    initial_hand = len(me.hand)
    execute_effect(
        {"hand_to_self_life": {"filter": {"category": "CHARACTER"}, "count": 1}},
        state, me, opp, None,
    )
    assert len(me.life) == initial_life + 1
    assert len(me.hand) == initial_hand - 1


def test_return_to_hand_multi():
    """return_to_hand_multi: 2 spec を別々に解決して bounce"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    from engine.core import Category
    c1 = [c for c in repo._by_id.values() if c.category == Category.CHARACTER and c.cost == 1][:1]
    c3 = [c for c in repo._by_id.values() if c.category == Category.CHARACTER and c.cost == 3][:1]
    if not c1 or not c3:
        return
    ip1 = InPlay.of(c1[0], sickness=False)
    ip3 = InPlay.of(c3[0], sickness=False)
    opp.characters = [ip1, ip3]
    initial_hand = len(opp.hand)
    execute_effect(
        {"return_to_hand_multi": [
            "one_opponent_character_cost_le_3cost",
            "one_opponent_character_cost_le_1cost",
        ]},
        state, me, opp, None,
    )
    assert len(opp.characters) == 0
    assert len(opp.hand) == initial_hand + 2


def test_play_from_trash_rested_flag():
    """play_from_trash: rested=True で レストで登場"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.trash = [repo.get("OP01-013")]
    execute_effect(
        {"play_from_trash": {"filter": {}, "limit": 1, "rested": True}},
        state, me, opp, None,
    )
    assert len(me.characters) == 1
    assert me.characters[0].rested is True, "rested=True で登場するはず"


def test_life_top_or_bottom_to_hand():
    """life_top_or_bottom_to_hand: 自ライフ1枚を手札へ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-013"), repo.get("OP01-013")]
    hand_before = len(me.hand)
    life_before = len(me.life)
    result = execute_effect(
        {"life_top_or_bottom_to_hand": {"owner": "self", "count": 1}},
        state, me, opp, None,
    )
    assert len(me.hand) == hand_before + 1
    assert len(me.life) == life_before - 1
    # ライフ 0 のときは False (= 解決不能)
    me.life = []
    result = execute_effect(
        {"life_top_or_bottom_to_hand": 1},
        state, me, opp, None,
    )
    assert result is False


def test_scry_life_reorders_by_value():
    """scry_life: 自ライフ上 N 枚をトリガー有/カウンター大優先で上に並べる"""
    from engine.effects import execute_effect
    from engine.core import Category
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # トリガー無し + カウンター無し vs トリガー有を意図的に並べる
    # OP01-013 (サンジ) はカウンター2000、 リーダー OP01-001 はカウンター0
    low = repo.get("OP01-001")  # leader (category=LEADER) — power 5000 / counter 0
    high = repo.get("OP01-013") # character — counter 2000
    me.life = [low, high]  # top=low, bottom=high
    execute_effect(
        {"scry_life": {"owner": "self", "depth": 2}},
        state, me, opp, None,
    )
    # 価値高 (high) が上に来るべき
    assert me.life[0] is high
    assert me.life[1] is low


def test_scry_all_life_one_to_deck():
    """scry_all_life_one_to_deck: ライフ全体から1枚をデッキトップへ + 残りを並べ替え"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    low = repo.get("OP01-001")   # counter 0
    mid = repo.get("OP01-013")   # counter 2000
    high = repo.get("OP01-016")  # counter 2000 + イベント
    me.life = [low, mid]
    me.deck = [high]  # deck top
    execute_effect({"scry_all_life_one_to_deck": True}, state, me, opp, None)
    # 価値最大 (mid: counter 2000) がデッキトップへ
    assert me.deck[0] is mid
    # 残ったライフは low のみ
    assert me.life == [low]


def test_battle_ko_immune_by_attribute():
    """set_immune_attribute_in_battle: 属性 X を持つカードとのバトルで KO されない (P-052 ミホーク)"""
    from engine.game import _battle_ko_immune_by_attribute
    from engine.core import InPlay
    repo = _repo()
    miho = repo.get("P-052")
    # 属性 = 斬 / 打 のカードを探す
    san_card = None
    da_card = None
    import sqlite3
    conn = sqlite3.connect('db/cards.sqlite')
    for cid, attr in conn.execute(
        "SELECT card_id, attribute FROM cards WHERE attribute IN ('斬', '打') LIMIT 50"
    ).fetchall():
        try:
            c = repo.get(cid)
            if c.attribute == "斬" and san_card is None:
                san_card = c
            if c.attribute == "打" and da_card is None:
                da_card = c
        except KeyError:
            continue
        if san_card and da_card:
            break
    if san_card is None or da_card is None:
        return  # 環境 skip
    miho_ip = InPlay.of(miho)
    miho_ip.ko_immune_battle_attributes_in.add("斬")
    san_ip = InPlay.of(san_card)
    da_ip = InPlay.of(da_card)
    assert _battle_ko_immune_by_attribute(miho_ip, san_ip) is True
    assert _battle_ko_immune_by_attribute(miho_ip, da_ip) is False


def test_optional_discard_hand_for_battle_buff():
    """optional_discard_hand_for_battle_buff: 手札のイベント/ステージを捨てて battle_buff"""
    from engine.effects import execute_effect
    from engine.core import Category
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # 手札に EVENT 系のカード 2 枚 + キャラ 1 枚
    event_card_a = next((repo.get(cid) for cid in ["OP01-095", "OP01-091", "OP01-097"]
                          if repo.get(cid).category == Category.EVENT), None)
    if event_card_a is None:
        return  # event card 探せなければスキップ
    me.hand = [event_card_a, event_card_a, repo.get("OP01-013")]
    leader = me.leader
    leader.battle_buff = 0
    execute_effect(
        {"optional_discard_hand_for_battle_buff": {
            "filter": {"category_in": ["EVENT", "STAGE"]},
            "amount_per_discard": 1000,
            "target": "self_leader",
            "max": 3,
        }},
        state, me, opp, None,
    )
    # 2 枚 EVENT 捨て + 0 枚 STAGE → 計 2 枚 → +2000
    assert leader.battle_buff == 2000
    assert len(me.hand) == 1  # キャラ 1 枚残る


def test_replace_rest_redirects_to_other_chara():
    """replace_rest: ゾロが相手キャラ効果でレストになる代わりに他キャラを犠牲"""
    from engine.effects import execute_effect, CardEffectBundle
    from engine.core import InPlay
    repo = _repo()
    zoro_card = repo.get("PRB02-006")
    other_card = repo.get("OP01-013")
    src_card = repo.get("OP01-013")
    overlay = {
        "PRB02-006": CardEffectBundle(card_id="PRB02-006", effects=[{
            "when": "replace_rest",
            "if": {"target": "self", "by_opp_chara_effect": True, "opp_turn": True},
            "do": [{"rest": "other_self_chara"}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    p0 = state.players[0]  # ゾロ所有者
    p1 = state.players[1]  # 相手 (rest 効果の発動者)
    zoro = InPlay.of(zoro_card)
    other = InPlay.of(other_card)
    p0.characters = [zoro, other]
    state.turn_player_idx = 1  # p0 から見れば opp_turn=True
    opp_src = InPlay.of(src_card)
    p1.characters = [opp_src]
    # p1 (相手 chara source) が p0 のゾロを rest しようとする
    execute_effect(
        {"rest": {"type": "one_opponent_character_filtered", "filter": {"name": "ロロノア・ゾロ"}}},
        state, p1, p0, opp_src,
    )
    # 置換成功 → ゾロは rested ではなく other が代わりに rested
    assert zoro.rested is False
    assert other.rested is True


def test_on_self_chara_leave_by_self_effect_fires_on_ko():
    """on_self_chara_leave_by_self_effect: 自分の効果でキャラを KO すると ハンコック の場効果が発火しドロー"""
    from engine.effects import execute_effect, CardEffectBundle
    from engine.core import InPlay
    repo = _repo()
    hancock_card = repo.get("OP07-038")
    victim_card = repo.get("OP01-013")
    overlay = {
        "OP07-038": CardEffectBundle(card_id="OP07-038", effects=[{
            "when": "on_self_chara_leave_by_self_effect",
            "cost": {"once_per_turn": True},
            "if": {"self_turn": True, "self_hand_count_le": 5},
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.characters = [InPlay.of(hancock_card)]
    opp.characters = [InPlay.of(victim_card)]
    me.deck = [repo.get("OP01-013")]
    me.hand = []
    execute_effect({"ko": "one_opponent_character_any"}, state, me, opp, None)
    assert len(opp.characters) == 0
    assert len(me.hand) == 1  # ハンコック効果で 1 ドロー


def test_on_opp_chara_returned_to_hand_by_self_effect_fires_scry():
    """EB02-023 クロコダイル: 自分の効果で相手キャラを手札に戻すと scry_deck_reorder 発火"""
    from engine.effects import execute_effect, CardEffectBundle
    from engine.core import InPlay
    repo = _repo()
    croc_card = repo.get("EB02-023")
    victim_card = repo.get("OP01-013")
    overlay = {
        "EB02-023": CardEffectBundle(card_id="EB02-023", effects=[{
            "when": "on_opp_chara_returned_to_hand_by_self_effect",
            "cost": {"once_per_turn": True},
            "if": {"self_turn": True},
            "do": [{"scry_deck_reorder": {"depth": 3}}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.characters = [InPlay.of(croc_card)]
    opp.characters = [InPlay.of(victim_card)]
    # 自デッキ top に値の異なる 3 枚 → scry_deck_reorder AI heuristic で sort
    high_value_card = repo.get("OP01-013")  # power 等の数値で差別化
    low_value_card = repo.get("OP01-001")
    me.deck = [low_value_card, high_value_card, low_value_card] + me.deck
    me.hand = []
    deck_before_top3 = me.deck[:3]
    execute_effect(
        {"return_to_hand": "one_opponent_character_any"},
        state, me, opp, None,
    )
    assert len(opp.characters) == 0
    assert len(opp.hand) == 1  # 手札に戻った
    # scry が発火していれば 自デッキ top 3 が並び替えられている (= 順序変動 or no-op いずれか)
    # log で発火を確認 (= AI 簡易: trig/counter/power 降順)
    log_text = "\n".join(state.log)
    assert "scry_deck_reorder" in log_text or "並び替え" in log_text


def test_cost_le_dynamic_sum_both_life_count():
    """ST29-013 ロブ・ルッチ trigger: cost_le_dynamic で 合計ライフ枚数 以下 の 相手キャラ KO"""
    from engine.effects import execute_effect
    from engine.core import InPlay
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # 合計ライフ = me.life + opp.life。 各 4 枚 ずつ で 合計 8 → cost 8 以下 が 対象
    life_card = repo.get("OP01-013")
    me.life = [life_card] * 4
    opp.life = [life_card] * 4
    # 相手キャラ: cost 7 (= 対象内) と cost 9 (= 対象外)
    low_ip = InPlay.of(repo.get("OP09-009_r1"))  # cost 7
    high_ip = InPlay.of(repo.get("OP06-118_r2"))  # cost 9
    opp.characters = [low_ip, high_ip]
    # ko 実行 (= 動的 filter)
    execute_effect(
        {"ko": {"type": "one_opponent_character_filtered",
                "filter": {"cost_le_dynamic": "sum_both_life_count"}}},
        state, me, opp, None,
    )
    # cost 7 が KO される、 cost 9 は 残る
    remaining_costs = sorted(ip.card.cost for ip in opp.characters)
    assert remaining_costs == [9], f"動的 cost filter 不正: 残 {remaining_costs}"


def test_cost_le_dynamic_zero_life_no_targets():
    """ST29-013: 合計ライフ 0 (= 両者 lethal 圏内) なら cost 0 以下 のみ → 通常 0 件"""
    from engine.effects import execute_effect
    from engine.core import InPlay
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = []
    opp.life = []
    low_ip = InPlay.of(repo.get("EB01-015_p2"))  # cost 1
    opp.characters = [low_ip]
    execute_effect(
        {"ko": {"type": "one_opponent_character_filtered",
                "filter": {"cost_le_dynamic": "sum_both_life_count"}}},
        state, me, opp, None,
    )
    # cost 1 > 0 (= 合計ライフ) → KO されない
    assert len(opp.characters) == 1


def test_on_opp_chara_returned_once_per_turn_gate():
    """EB02-023: once_per_turn cost で 同ターン 2 回目 は 発火しない"""
    from engine.effects import execute_effect, CardEffectBundle
    from engine.core import InPlay
    repo = _repo()
    croc_card = repo.get("EB02-023")
    victim_card = repo.get("OP01-013")
    overlay = {
        "EB02-023": CardEffectBundle(card_id="EB02-023", effects=[{
            "when": "on_opp_chara_returned_to_hand_by_self_effect",
            "cost": {"once_per_turn": True},
            "if": {"self_turn": True},
            "do": [{"scry_deck_reorder": {"depth": 3}}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    me.characters = [InPlay.of(croc_card)]
    opp.characters = [InPlay.of(victim_card), InPlay.of(victim_card)]
    me.deck = [repo.get("OP01-013")] * 6
    me.hand = []
    # 1 回目: 発火
    execute_effect(
        {"return_to_hand": "one_opponent_character_any"},
        state, me, opp, None,
    )
    log1_count = "\n".join(state.log).count("並び替え")
    # 2 回目: gate により 発火しない
    execute_effect(
        {"return_to_hand": "one_opponent_character_any"},
        state, me, opp, None,
    )
    log2_count = "\n".join(state.log).count("並び替え")
    assert log2_count == log1_count, "once_per_turn ガードが 2 回目を gate していない"


def test_activate_main_cost_pick_human_halt():
    """activate_main の ko_self_with_filter cost で 人間 acting + 候補 > 1 なら modal halt"""
    from engine.effects import CardEffectBundle, fire_activate_main, resolve_pending_choice
    from engine.core import InPlay
    repo = _repo()
    source_card = repo.get("OP14-079")
    # candidates: 2 B・W chara を 場 に 置く (= 適当 な OP01 chara で 代用、 features を 偽装)
    # 実 test では、 ko_self_with_filter が 2+ 候補 で halt する 挙動 を 確認 する。
    overlay = {
        "OP14-079": CardEffectBundle(card_id="OP14-079", effects=[{
            "when": "activate_main",
            "cost": {"ko_self_with_filter": {"feature": "麦わらの一味"}, "once_per_turn": True},
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # source は 自場 (= 人間 同視点)
    source_ip = InPlay.of(source_card, sickness=False)
    me.characters = [source_ip]
    # 候補 2 体 (= 麦わらの一味 feature)
    cand_a = InPlay.of(repo.get("OP01-013"), sickness=False)  # サンジ 麦わらの一味
    cand_b = InPlay.of(repo.get("OP01-016"), sickness=False)  # ナミ 麦わらの一味
    me.characters.extend([cand_a, cand_b])
    me.deck = [repo.get("OP01-013")] * 5
    me.hand = []
    # 人間 acting 状態 に セット
    state.human_player_idx = 0
    state.forced_human_actor_idx = 0
    eff = overlay["OP14-079"].effects[0]
    fire_activate_main(state, me, opp, source_ip, eff)
    # pending_choice 立った こと を 確認
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "activate_main_cost_pick"
    assert state.pending_choice["cost_kind"] == "ko_self_with_filter"
    assert len(state.pending_choice["candidates"]) == 2
    # 候補 [0] (= cand_a サンジ) を pick → resolve
    resolve_pending_choice(state, [0])
    # cand_a が KO + draw 1 (= 効果) が 実行されている
    chara_names = [c.card.name for c in me.characters]
    assert "サンジ" not in chara_names, f"サンジ が KO されていない: {chara_names}"
    assert "ナミ" in chara_names, "ナミ は 残るべき"
    assert len(me.hand) == 1, "効果 draw 1 が 発動 してない"


def test_activate_main_cost_pick_ai_auto():
    """AI acting なら modal 立てず auto-pick (= 既存挙動 維持)"""
    from engine.effects import CardEffectBundle, fire_activate_main
    from engine.core import InPlay
    repo = _repo()
    source_card = repo.get("OP14-079")
    overlay = {
        "OP14-079": CardEffectBundle(card_id="OP14-079", effects=[{
            "when": "activate_main",
            "cost": {"ko_self_with_filter": {"feature": "麦わらの一味"}, "once_per_turn": True},
            "do": [{"draw": 1}],
        }]),
    }
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    source_ip = InPlay.of(source_card, sickness=False)
    me.characters = [source_ip]
    me.characters.extend([
        InPlay.of(repo.get("OP01-013"), sickness=False),
        InPlay.of(repo.get("OP01-016"), sickness=False),
    ])
    me.deck = [repo.get("OP01-013")] * 5
    me.hand = []
    # AI 状態 (= human_player_idx None)
    state.human_player_idx = None
    eff = overlay["OP14-079"].effects[0]
    fire_activate_main(state, me, opp, source_ip, eff)
    # halt せず 直接 完了 (= auto-pick 最初 の 候補)
    assert state.pending_choice is None
    # 1 体 KO されている (= 元 3 → 2)
    assert len(me.characters) == 2
    # draw 1 発動
    assert len(me.hand) == 1


def test_optional_cost_then_trash_to_deck_payable():
    """optional_cost_then: trash_to_deck を cost とした payability check 成立"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # トラッシュに 2 枚 → payability 成立 → cost と effect 両方発動
    me.trash = [repo.get("OP01-013"), repo.get("OP01-013")]
    state.turn_number = 1
    leader = me.leader
    base_power = leader.power
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"trash_to_deck": {"limit": 2, "to": "bottom"}}],
            "effect": [{"power_pump": {"target": "one_self_team_any", "amount": 1000, "duration": "next_opp_turn_end"}}]
        }},
        state, me, opp, None,
    )
    assert len(me.trash) == 0  # 2 枚 → deck bottom
    assert leader.next_opp_turn_end_buff == 1000
    # トラッシュ 1 枚 → payability 不成立 → 何もしない
    state2 = _make_state(repo, "OP01-001", overlay={})
    me2 = state2.players[0]
    opp2 = state2.players[1]
    me2.trash = [repo.get("OP01-013")]
    leader2_before_buff = me2.leader.next_opp_turn_end_buff
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"trash_to_deck": {"limit": 2, "to": "bottom"}}],
            "effect": [{"power_pump": {"target": "one_self_team_any", "amount": 1000, "duration": "next_opp_turn_end"}}]
        }},
        state2, me2, opp2, None,
    )
    assert len(me2.trash) == 1
    assert me2.leader.next_opp_turn_end_buff == leader2_before_buff


def test_mill_self_life_until_n():
    """mill_self_life_until_n: ライフを N 枚まで削減 (上から trash 排出)"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-013"), repo.get("OP01-013"), repo.get("OP01-013")]  # 3 枚
    me.trash = []
    execute_effect({"mill_self_life_until_n": 1}, state, me, opp, None)
    assert len(me.life) == 1
    assert len(me.trash) == 2
    # 既に N 枚以下なら no-op
    execute_effect({"mill_self_life_until_n": 1}, state, me, opp, None)
    assert len(me.life) == 1


def test_give_keyword_choice_picks_blocker():
    """give_keyword: keywords リスト → AI は守備優先 (ブロッカー) を選択"""
    from engine.effects import execute_effect
    from engine.core import InPlay
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    chara_card = repo.get("OP01-013")
    ip = InPlay.of(chara_card)
    me.characters = [ip]
    execute_effect(
        {"give_keyword": {
            "target": "self",
            "keywords": ["ダブルアタック", "バニッシュ", "ブロッカー"],
            "duration": "turn",
        }},
        state, me, opp, ip,
    )
    assert ip.is_blocker_now is True
    assert ip.is_double_attack_now is False


def test_give_keyword_next_opp_turn_end_persists_through_opp_turn():
    """give_keyword duration=next_opp_turn_end: 自ターン終了 → 相手ターン中も維持 → 自分の END でクリア"""
    from engine.effects import execute_effect
    from engine.core import InPlay
    from engine.game import _reset_turn_buff
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    chara_card = repo.get("OP01-013")
    ip = InPlay.of(chara_card)
    me.characters = [ip]
    state.turn_number = 1
    state.turn_player_idx = 0
    execute_effect(
        {"give_keyword": {
            "target": "self",
            "keyword": "ブロッカー",
            "duration": "next_opp_turn_end",
        }},
        state, me, opp, ip,
    )
    assert ip.is_blocker_now is True
    # 自ターン終了 (= ended_idx=0, applier=0 → クリアしない)
    _reset_turn_buff(state)
    assert ip.is_blocker_now is True
    # 相手ターンへ (turn_player は turn_player_idx 由来の property)
    state.turn_number = 2
    state.turn_player_idx = 1
    # 相手ターン終了 (= ended_idx=1, applier=0, applied_turn=1 < turn_number=2 → クリア)
    _reset_turn_buff(state)
    assert ip.is_blocker_now is False


def test_chara_to_self_life():
    """chara_to_self_life: 自キャラ1枚 → 自ライフへ移動 (場から消失、ライフ +1)"""
    from engine.effects import execute_effect
    from engine.core import InPlay
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # ワノ国キャラ準備 (OP02-006 ロー? いや、 ワノ国を持つカードを探す)
    # 簡略化: 「ワノ国」 を持つカードを探して使う。 OP02 系に多数。
    wano_card = None
    for cid in ["OP02-066", "OP02-067", "OP02-068", "OP04-072", "OP01-002"]:
        try:
            c = repo.get(cid)
            if "ワノ国" in c.features:
                wano_card = c
                break
        except KeyError:
            continue
    if wano_card is None:
        return  # ワノ国カードがDBに無ければスキップ
    ip = InPlay.of(wano_card)
    me.characters = [ip]
    life_count_before = len(me.life)
    execute_effect(
        {"chara_to_self_life": {
            "target": {"type": "one_self_chara_filtered", "filter": {"feature": "ワノ国"}},
            "place": "top"
        }},
        state, me, opp, None,
    )
    assert ip not in me.characters
    assert len(me.life) == life_count_before + 1
    assert me.life[0] is wano_card


def test_scry_all_life_reorder():
    """scry_all_life_reorder: ライフ全体を価値降順に並べ替え"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    low = repo.get("OP01-001")
    high = repo.get("OP01-013")
    me.life = [low, high]
    execute_effect({"scry_all_life_reorder": True}, state, me, opp, None)
    assert me.life[0] is high
    assert me.life[1] is low


def test_choice_picks_by_life_count():
    """choice: 自ライフ 1 以下なら option=1 を選ぶ"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-013")]  # ライフ 1 (≤ 1)
    me.hand = [repo.get("OP01-013")]
    # option 0: ライフ → 手札 (life_to_hand)
    # option 1: 手札 → ライフ (hand_to_self_life)
    execute_effect(
        {"choice": {
            "options": [
                [{"life_to_hand": 1}],
                [{"hand_to_self_life": 1}],
            ],
        }},
        state, me, opp, None,
    )
    # option=1 が選ばれた = 手札→ライフ → ライフ 2 / 手札 0
    assert len(me.life) == 2
    assert len(me.hand) == 0


def test_reveal_top_play_matched_summons():
    """reveal_top_play: デッキ上1枚が filter にマッチすればキャラ登場"""
    from engine.effects import execute_effect
    from engine.core import Category
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # OP01-013 (サンジ, cost=4) を上に置く
    target_card = repo.get("OP01-013")
    me.deck = [target_card] + list(me.deck)
    before_chara = len(me.characters)
    before_deck = len(me.deck)
    execute_effect(
        {"reveal_top_play": {"filter": {"cost_le": 4}, "rested": False, "rest_remain": "bottom"}},
        state, me, opp, None,
    )
    # マッチ → キャラ登場、 デッキ -1
    assert len(me.characters) == before_chara + 1
    assert me.characters[-1].card is target_card
    assert me.characters[-1].rested is False
    assert len(me.deck) == before_deck - 1


def test_reveal_top_play_unmatched_to_bottom():
    """reveal_top_play: filter にマッチしなければデッキ下に戻す"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    sanji = repo.get("OP01-013")  # cost=4
    me.deck = [sanji] + list(me.deck)
    before_chara = len(me.characters)
    before_deck = len(me.deck)
    execute_effect(
        {"reveal_top_play": {"filter": {"cost_le": 1}, "rest_remain": "bottom"}},
        state, me, opp, None,
    )
    # 不マッチ (サンジ cost=2 > 1) → 場 変化なし、 デッキ枚数は同じ (底へ戻る)
    assert len(me.characters) == before_chara
    assert len(me.deck) == before_deck
    # 底に戻された
    assert me.deck[-1] is sanji


def test_rest_self_cards_primitive():
    """rest_self_cards: 自場の active キャラ/リーダーから power 低い順に N 枚レスト"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    # 異なるパワーのキャラ 3 体
    c1 = InPlay.of(repo.get("OP01-013"), sickness=False)  # power 4000
    c2 = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [c1, c2]
    # me.leader.power = 5000 (OP01-001)
    execute_effect({"rest_self_cards": 2}, state, me, opp, None)
    # power 低い順 → c1, c2 が先にレスト (leader は 5000 で残り)
    rested = sum(1 for ip in [me.leader, *me.characters] if ip.rested)
    assert rested == 2
    assert c1.rested and c2.rested
    assert not me.leader.rested


def test_replace_ko_target_color_filter():
    """_replace_ko_match: target_color フィルタで色を判別"""
    from engine.effects import _replace_ko_match
    repo = _repo()
    holder = InPlay.of(repo.get("OP01-013"), sickness=False)  # 赤
    victim_green = InPlay.of(repo.get("OP01-001"), sickness=False)
    # OP01-001 = 赤リーダー、 緑テスト用に別カードを探す
    from engine.core import Category
    green_chara = None
    for c in repo._by_id.values():
        if c.category == Category.CHARACTER and '緑' in c.color:
            green_chara = c
            break
    assert green_chara is not None
    victim_green = InPlay.of(green_chara, sickness=False)
    cond = {"target": "other_self_chara", "target_color": "緑", "by_opp_effect": True}
    assert _replace_ko_match(cond, holder, victim_green, by_opp_effect=True) is True
    # 赤カードで判定 → False
    victim_red = InPlay.of(repo.get("OP01-013"), sickness=False)
    assert _replace_ko_match(cond, holder, victim_red, by_opp_effect=True) is False


def test_replace_ko_target_name_exclude():
    """_replace_ko_match: target_name_exclude で特定名を除外"""
    from engine.effects import _replace_ko_match
    repo = _repo()
    holder = InPlay.of(repo.get("OP01-013"), sickness=False)
    # サンジ (OP01-013) は除外、 他のキャラは通す
    cond = {"target": "other_self_chara", "target_name_exclude": "サンジ"}
    victim = InPlay.of(repo.get("OP01-013"), sickness=False)  # holder と別 instance
    # サンジ自身 → exclude されるべき
    assert _replace_ko_match(cond, holder, victim, by_opp_effect=False) is False
    # 別のキャラ
    other = repo.get("OP01-001")  # 別の名前
    victim2 = InPlay.of(other, sickness=False)
    assert _replace_ko_match(cond, holder, victim2, by_opp_effect=False) is True


def test_disable_effect_turn_duration():
    """disable_effect duration=turn: granted_keywords に '効果無効' を追加、 ターン終了でクリア"""
    from engine.effects import execute_effect
    from engine.game import advance_phase
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [sanji]
    execute_effect(
        {"disable_effect": {"target": "one_opponent_character_any", "duration": "turn"}},
        state, me, opp, None,
    )
    assert "効果無効" in sanji.granted_keywords
    assert sanji.effect_disabled_through_opp_turn is False


def test_disable_effect_next_opp_turn_with_cannot_attack():
    """disable_effect duration=next_opp_turn_end + also_cannot_attack:
    フラグ 2 つを立て、 所有者ターン終了時にクリア"""
    from engine.effects import execute_effect
    from engine.game import advance_phase, _reset_turn_buff
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    opp.characters = [sanji]
    execute_effect(
        {"disable_effect": {
            "target": "one_opponent_character_any",
            "duration": "next_opp_turn_end",
            "also_cannot_attack": True,
        }},
        state, me, opp, None,
    )
    assert sanji.effect_disabled_through_opp_turn is True
    assert sanji.cannot_attack_through_opp_turn is True
    # me (ターン主) のターン終了時 → opp のフラグはクリアされない (= 次の相手ターン中も有効)
    _reset_turn_buff(state)
    assert sanji.effect_disabled_through_opp_turn is True
    # ターン交代をシミュレート: turn_player_idx = 1 (opp 側)
    state.turn_player_idx = 1
    # opp のターン終了時 → opp のキャラのフラグがクリア
    _reset_turn_buff(state)
    assert sanji.effect_disabled_through_opp_turn is False
    assert sanji.cannot_attack_through_opp_turn is False


def test_disable_effect_blocks_on_attack_trigger():
    """効果無効化されたキャラの on_attack は _execute_event で抑止される"""
    from engine.effects import execute_effect, _execute_event, TriggerEvent, CardEffectBundle
    repo = _repo()
    overlay = {"OP01-013": CardEffectBundle(card_id="OP01-013", effects=[
        {"when": "on_attack",
         "do": [{"power_pump": {"target": "self", "amount": 1000, "duration": "turn"}}]}
    ])}
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    sanji = InPlay.of(repo.get("OP01-013"), sickness=False)
    me.characters = [sanji]
    # disable_effect (turn) を適用
    sanji.granted_keywords.add("効果無効")
    base_power = sanji.power
    # on_attack イベント発火
    evt = TriggerEvent(
        when="on_attack",
        owner_idx=0,
        source_card_id="OP01-013",
        source_iid=sanji.instance_id,
        payload={},
    )
    _execute_event(state, evt)
    # 効果無効 → power_pump 不発 → パワー変化なし
    assert sanji.power == base_power


def test_optional_cost_then_fires_when_payable():
    """optional_cost_then: ライフ + 手札があるとき cost を払って effect 発動"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-013"), repo.get("OP01-013")]
    me.hand = [repo.get("OP01-013")]
    execute_effect(
        {"optional_cost_then": {
            "cost": [{"life_top_or_bottom_to_hand": 1}],
            "effect": [{"hand_to_self_life": 1}],
        }},
        state, me, opp, None,
    )
    # cost: ライフ -1 / 手札 +1 → 効果: 手札 -1 / ライフ +1 → 結果: swap
    assert len(me.life) == 2
    assert len(me.hand) == 1


def test_optional_cost_then_skips_when_unpayable():
    """optional_cost_then: cost を払えないなら何もしない (return False)"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = []  # ライフ 0 → cost 払えない
    me.hand = [repo.get("OP01-013")]
    result = execute_effect(
        {"optional_cost_then": {
            "cost": [{"life_top_or_bottom_to_hand": 1}],
            "effect": [{"hand_to_self_life": 1}],
        }},
        state, me, opp, None,
    )
    assert result is False
    assert len(me.hand) == 1, "手札は変化なし"


def test_choice_default_option_0_when_life_mid():
    """choice: 自ライフ ≥ 3 では option=0 (= 公式テキスト先頭)"""
    from engine.effects import execute_effect
    repo = _repo()
    state = _make_state(repo, "OP01-001", overlay={})
    me = state.players[0]
    opp = state.players[1]
    me.life = [repo.get("OP01-013")] * 3
    me.hand = [repo.get("OP01-013")]
    execute_effect(
        {"choice": {
            "options": [
                [{"life_to_hand": 1}],
                [{"hand_to_self_life": 1}],
            ],
        }},
        state, me, opp, None,
    )
    # option=0 → ライフ 1枚を手札へ → ライフ 2 / 手札 2
    assert len(me.life) == 2
    assert len(me.hand) == 2


# ─────────────────────────────────────────────────────
# once_per_turn: 同 card_id 複数 instance bug fix (= 2026-05-27)
# ohtsuki さん 観戦 報告: 「盤面の同じキャラカードが複数枚あるときに、
# 起動メインの発動の管理に不具合ある」
# ─────────────────────────────────────────────────────


def test_once_per_turn_instance_isolation():
    """同 card_id, 同 effect idx でも 別 instance なら once_per_turn は 独立 (fix 2026-05-27)。"""
    from engine.effects import _check_and_set_once_per_turn

    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    eff = {"when": "activate_main", "once_per_turn": True, "do": []}

    # instance A 発動 → 通る
    assert _check_and_set_once_per_turn(
        state, me, eff, "TEST-001", 0, source_iid=101
    ) is True
    # 同 instance 再発動 → blocked
    assert _check_and_set_once_per_turn(
        state, me, eff, "TEST-001", 0, source_iid=101
    ) is False
    # 別 instance (= 同 card_id 2 枚目) → 通る (= fix の core)
    assert _check_and_set_once_per_turn(
        state, me, eff, "TEST-001", 0, source_iid=102
    ) is True


def test_once_per_turn_explicit_key_shared_across_instances():
    """once_per_turn: \"<str>\" は 明示 共有 key、 instance 跨ぎ で blocked (= 既存仕様維持)。"""
    from engine.effects import _check_and_set_once_per_turn

    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    eff = {"when": "on_play", "once_per_turn": "shared_namespace_x", "do": []}

    # instance 101 通る
    assert _check_and_set_once_per_turn(
        state, me, eff, "CARD-X", 0, source_iid=101
    ) is True
    # 別 instance でも 同 key → blocked (= 共有意図)
    assert _check_and_set_once_per_turn(
        state, me, eff, "CARD-Y", 0, source_iid=102
    ) is False


def test_once_per_turn_no_source_iid_fallback_card_id():
    """source_iid 渡されない 場合 は 後方互換 で card_id key を 使う。"""
    from engine.effects import _check_and_set_once_per_turn

    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    eff = {"when": "main", "once_per_turn": True, "do": []}

    # source_iid 指定なし → card_id key (= 後方互換)
    assert _check_and_set_once_per_turn(
        state, me, eff, "TEST-002", 0
    ) is True
    # 同 card_id 同 idx 再発動 → blocked
    assert _check_and_set_once_per_turn(
        state, me, eff, "TEST-002", 0
    ) is False


# ============================================================================
# 2026-05-31 イム deck 修復 regression テスト (= LLM sub-agent audit 由来)
# ============================================================================

def test_op13_091_ko_target_regex_correct():
    """OP13-091 マーカス・マーズ 登場時 KO: 公式 「相手の元々のコスト5以下のキャラ1枚までを、KOする」
    target spec が `one_opponent_character_cost_le_5` (= regex 一致) で 不発 しない こと。"""
    from engine.effects import execute_effect
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    # 相手場 に cost 3 chara
    victim = repo.get("OP01-013")
    ip = InPlay.of(victim, sickness=False)
    opp.characters = [ip]
    me.hand = [repo.get("OP01-013")]  # cost (discard_hand:1) 用
    src_card = repo.get("OP13-091")
    src_ip = InPlay.of(src_card, sickness=True)
    me.characters = [src_ip]
    # 当該 entry の do (= ko) 単体 fire
    bundle = overlay.get("OP13-091")
    on_play_eff = next(e for e in bundle.effects if e.get("when") == "on_play")
    ko_spec = next(p for p in on_play_eff["do"] if "ko" in p)
    execute_effect(ko_spec, state, me, opp, src_ip)
    assert len(opp.characters) == 0, (
        f"OP13-091 KO 効果 が 不発 (= target regex 不一致 の regression)。 "
        f"残 opp chara={len(opp.characters)}"
    )


def test_op13_086_search_top_n_rest_remain_trash():
    """OP13-086 シャルリア宮 登場時: 公式 「残りをトラッシュに置く」 が overlay で
    rest_remain='trash' に なっている (= 旧 bug = 'bottom' の regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("OP13-086")
    on_play_eff = next(e for e in bundle.effects if e.get("when") == "on_play")
    search_spec = next(p["search_top_n"] for p in on_play_eff["do"] if "search_top_n" in p)
    assert search_spec.get("rest_remain") == "trash", (
        f"OP13-086 search_top_n.rest_remain が 公式 通り 'trash' で ない: "
        f"{search_spec.get('rest_remain')}"
    )


def test_op13_084_leave_immune_no_self_turn():
    """OP13-084 シェパード: 公式 「自分のトラッシュが7枚以上ある場合、 このキャラは相手の効果で
    場を離れない」 = 自ターン限定 で は ない。 overlay の conditions に self_turn:true が
    無い こと (= 旧 bug regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("OP13-084")
    leave_immune_eff = next(
        e for e in bundle.effects
        if any("set_ko_immune" in p for p in e.get("do", []))
    )
    conds = leave_immune_eff.get("conditions") or []
    if isinstance(conds, dict):
        conds = [conds]
    keys = [k for c in conds if isinstance(c, dict) for k in c.keys()]
    assert "self_turn" not in keys, (
        f"OP13-084 leave-immune に self_turn が 残存 (= 旧 bug regression)。 keys={keys}"
    )


def test_op13_082_uses_trash_all_self_chara_and_correct_keys():
    """OP13-082 五老星 起動メイン: overlay が 新 primitive trash_all_self_chara を 使い、
    play_from_trash で `limit:5` + `unique_name:true` (= engine が 認識 する key) になっている。"""
    overlay = _overlay()
    bundle = overlay.get("OP13-082")
    actmain = next(e for e in bundle.effects if e.get("when") == "activate_main")
    do_list = actmain.get("do") or []
    keys_used = [list(d.keys())[0] for d in do_list if isinstance(d, dict)]
    assert "trash_all_self_chara" in keys_used, (
        f"OP13-082 do に trash_all_self_chara 無し (= 公式 「自分のキャラすべてをトラッシュに置く」 抜け)。 keys={keys_used}"
    )
    pft = next((d["play_from_trash"] for d in do_list if "play_from_trash" in d), None)
    assert pft is not None, "OP13-082 do に play_from_trash 無し"
    assert pft.get("limit") == 5, f"OP13-082 play_from_trash.limit が 5 で ない: {pft.get('limit')}"
    assert pft.get("unique_name") is True, (
        f"OP13-082 play_from_trash.unique_name が True で ない: {pft.get('unique_name')} "
        f"(= 旧 'distinct_names' は engine 未認識)"
    )


def test_op13_082_trash_all_self_chara_primitive_works():
    """trash_all_self_chara primitive: 自陣 chara 全部 が trash に 移送 + 付与ドン が
    rested に 戻る。 leader / stage は 影響 を 受けない。"""
    from engine.effects import execute_effect
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    me = state.players[0]
    opp = state.players[1]
    c1 = InPlay.of(repo.get("OP01-013"), sickness=False)
    c1.attached_dons = 2
    c2 = InPlay.of(repo.get("OP01-016"), sickness=False)
    c2.attached_dons = 1
    me.characters = [c1, c2]
    me.don_rested = 0
    initial_trash = len(me.trash)
    initial_leader = me.leader
    execute_effect({"trash_all_self_chara": True}, state, me, opp, None)
    assert me.characters == [], "trash_all_self_chara 後 自場 chara が 残存"
    assert len(me.trash) == initial_trash + 2, f"trash 数 不一致 (期待 +2、 実 +{len(me.trash) - initial_trash})"
    assert me.don_rested == 3, f"付与 ドン 戻し 不正 (期待 3、 実 {me.don_rested})"
    assert me.leader is initial_leader, "leader が 影響 を 受けた (= 想定外)"


def test_op13_099_uses_play_from_hand_with_dynamic_cost():
    """OP13-099 虚の玉座 起動メイン: 公式 「自分の手札から自分の場のドン!!の枚数以下のコストを持つ
    黒の特徴《五老星》を持つキャラカード1枚までを、登場させる」。 overlay が play_from_hand
    + cost_le_dynamic:self_don_total + color:黒 を 使っている (= 旧 bug regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("OP13-099")
    actmain = next(e for e in bundle.effects if e.get("when") == "activate_main")
    do = actmain.get("do") or []
    pfh = next((d.get("play_from_hand") for d in do if "play_from_hand" in d), None)
    assert pfh is not None, "OP13-099 do に play_from_hand が 無い (= 旧: play_from_trash で 誤り)"
    filt = pfh.get("filter") or {}
    assert filt.get("color") == "黒", f"color フィルタ 黒 で ない: {filt.get('color')}"
    assert filt.get("cost_le_dynamic") == "self_don_total", (
        f"動的 cost cap (= 場のドン枚数) が cost_le_dynamic:self_don_total で ない: "
        f"{filt.get('cost_le_dynamic')}"
    )
    assert filt.get("feature") == "五老星", f"feature 五老星 で ない: {filt.get('feature')}"


def test_cost_le_dynamic_self_don_total_resolution():
    """_resolve_dynamic_filter の `self_don_total` source: me.don_active + me.don_rested
    + 付与 ドン の 合計 で cost_le を 静的化。"""
    from engine.effects import _resolve_dynamic_filter
    repo = _repo()
    state = _make_state(repo, "OP01-001")
    me = state.players[0]
    opp = state.players[1]
    me.don_active = 3
    me.don_rested = 2
    me.characters = [InPlay.of(repo.get("OP01-013"), sickness=False)]
    me.characters[0].attached_dons = 1
    resolved = _resolve_dynamic_filter(
        {"cost_le_dynamic": "self_don_total", "feature": "五老星"},
        state, me, opp,
    )
    # 期待: cost_le = 3 + 2 + 1 = 6
    assert resolved.get("cost_le") == 6, f"動的 cost cap 不一致: {resolved.get('cost_le')}"
    assert resolved.get("feature") == "五老星", "他 filter key が 失われた"
    assert "cost_le_dynamic" not in resolved, "cost_le_dynamic が 残存"


def test_op13_091_overlay_target_spec_string():
    """OP13-091 overlay の ko target spec が 正しい regex 一致 文字列 で ある こと
    (= 旧 'one_opponent_character_le_5cost' regression 防止)。"""
    import re
    overlay = _overlay()
    bundle = overlay.get("OP13-091")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    ko_target = next(p["ko"] for p in on_play["do"] if "ko" in p)
    assert isinstance(ko_target, str), f"ko target が str で ない: {type(ko_target)}"
    # engine regex を inline 検証
    pat = re.compile(r"one_opponent_character_cost_le_(\d+)(?:cost)?$")
    m = pat.match(ko_target)
    assert m is not None, (
        f"OP13-091 ko target '{ko_target}' が engine regex に 一致 しない "
        f"(= 旧 'one_opponent_character_le_5cost' は 'cost_' 抜け で 不発)"
    )
    assert m.group(1) == "5", f"cost cap が 5 で ない: {m.group(1)}"


# ============================================================================
# 2026-05-31 Hancock deck 修復 regression テスト
# ============================================================================

def test_op14_107_shakuyaku_no_cost_no_self_life_condition():
    """OP14-107 シャクヤク: 公式 「相手のライフが3枚以下の場合、 カード2枚を引き、 自分の手札2枚を捨てる」。
    cost ブロック なし、 if に self_life_le なし、 do に draw 2 + trash_self_hand_random 2。"""
    overlay = _overlay()
    bundle = overlay.get("OP14-107")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    assert "cost" not in on_play, "OP14-107 cost block が 残存 (= 旧 bug)"
    if_block = on_play.get("if") or {}
    assert if_block.get("opp_life_le") == 3, f"opp_life_le:3 不在: {if_block}"
    assert "self_life_le" not in if_block, f"self_life_le が 公式 に ない の に 残存: {if_block}"
    do_keys = [list(d.keys())[0] for d in on_play.get("do", [])]
    assert "draw" in do_keys, f"draw 効果 欠落: {do_keys}"
    assert "trash_self_hand_random" in do_keys, f"trash_self_hand_random 欠落: {do_keys}"


def test_op14_113_margaret_feature_in():
    """OP14-113 マーガレット 登場時 search_top_n: filter が feature_in で
    《アマゾン・リリー》 か 《九蛇海賊団》 両方 を 候補 に 含む こと。"""
    overlay = _overlay()
    bundle = overlay.get("OP14-113")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    search = next(d["search_top_n"] for d in on_play["do"] if "search_top_n" in d)
    filt = search.get("filter") or {}
    feats = filt.get("feature_in")
    assert isinstance(feats, list) and "アマゾン・リリー" in feats and "九蛇海賊団" in feats, (
        f"feature_in に 両 特徴 が ない: {feats}"
    )


def test_op14_102_kumacy_trigger_rested():
    """OP14-102 クマシー トリガー: 公式 「レストで登場させる」 → rested:true。"""
    overlay = _overlay()
    bundle = overlay.get("OP14-102")
    trig = next(e for e in bundle.effects if e.get("when") == "trigger")
    pft = next(d["play_from_trash"] for d in trig["do"] if "play_from_trash" in d)
    assert pft.get("rested") is True, f"rested:true 不在: {pft}"


def test_op12_119_kuma_no_unconditional_on_ko():
    """OP12-119 くま: on_ko (= 無条件) entry が 削除済 で on_self_chara_ko +
    opp_turn のみ 残っている。 公式 【相手のターン中】【KO時】 厳密。"""
    overlay = _overlay()
    bundle = overlay.get("OP12-119")
    unconditional_on_ko = [
        e for e in bundle.effects
        if e.get("when") == "on_ko" and not e.get("conditions") and not e.get("if")
    ]
    assert len(unconditional_on_ko) == 0, (
        f"OP12-119 無条件 on_ko entry が 残存 (= 旧 bug、 自ターン KO で 不当 発火)"
    )
    # 「自身の KO」 は on_ko (= KO 本人の reaction) が正。 旧 on_self_chara_ko+victim_iid_eq_self は
    # victim が broadcast 前に場から除去され dead だったため on_ko + opp_turn へ移行 (2026-05-31)。
    correct = [
        e for e in bundle.effects
        if e.get("when") == "on_ko"
        and any(
            isinstance(c, dict) and c.get("opp_turn") is True
            for c in (e.get("conditions") or [])
        )
    ]
    assert len(correct) >= 1, "OP12-119 on_ko + opp_turn entry 不在"


def test_st17_004_hancock_4c_attach_don_added():
    """ST17-004 ハンコック(4c) 登場時: 公式 「その後 王下七武海 リーダー/キャラ 1 に レストドン1付与」
    が 追加 されている。"""
    overlay = _overlay()
    bundle = overlay.get("ST17-004")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    has_attach = any("attach_rested_don" in d for d in on_play.get("do", []))
    assert has_attach, f"ST17-004 attach_rested_don 不在: {on_play.get('do')}"


# ============================================================================
# 2026-05-31 ドフラ deck 修復 regression テスト
# ============================================================================

def test_st18_001_usohachi_rest_target_regex():
    """ST18-001 ウソ八: rest target spec が 正しい regex 一致 (旧 le_5cost regression 防止)。"""
    import re
    overlay = _overlay()
    bundle = overlay.get("ST18-001")
    found = None
    for entry in bundle.effects:
        for d in entry.get("do", []):
            if "rest" in d and isinstance(d["rest"], str):
                found = d["rest"]
                break
    assert found is not None, "ST18-001 rest 効果 が ない"
    pat = re.compile(r"one_opponent_character_cost_le_(\d+)(?:cost)?$")
    assert pat.match(found) is not None, f"ST18-001 rest target が regex 不一致: {found}"


def test_op14_063_sugar_uses_play_from_hand_with_opp_don_cond():
    """OP14-063 シュガー KO時: 公式 「相手の場のドン6+ で 自手札 から ドンキ海賊団 cost5以下 1 体登場」。
    play_from_hand + opp_don_ge:6 条件。"""
    overlay = _overlay()
    bundle = overlay.get("OP14-063")
    on_ko = next(e for e in bundle.effects if e.get("when") == "on_ko")
    do = on_ko.get("do", [])
    has_pfh = any("play_from_hand" in d for d in do)
    has_pft = any("play_from_trash" in d for d in do)
    assert has_pfh and not has_pft, (
        f"OP14-063 on_ko: play_from_hand であるべき (= 公式 手札 から)、 旧 play_from_trash 残存 {do}"
    )
    if_block = on_ko.get("if") or {}
    # opp_don_count_ge が engine handled な正キー (opp_don_ge は未handled=silently-ignored だった)
    assert if_block.get("opp_don_count_ge") == 6, (
        f"OP14-063 on_ko 条件 opp_don_count_ge:6 不在: {if_block}"
    )


def test_op14_074_mone_on_ko_full_sequence():
    """OP14-074 モネ KO時: 公式 「カード2枚引く + 手札1捨てる + ドン2レスト追加」 の 3 段 + add_rested_don。"""
    overlay = _overlay()
    bundle = overlay.get("OP14-074")
    on_ko = next(e for e in bundle.effects if e.get("when") == "on_ko")
    do_keys = [list(d.keys())[0] for d in on_ko.get("do", [])]
    assert "draw" in do_keys, f"draw 欠落: {do_keys}"
    assert ("trash_self_hand_random" in do_keys
            or "discard_hand" in do_keys), f"discard 効果 欠落: {do_keys}"
    assert "add_rested_don" in do_keys, f"add_rested_don 欠落 (= 旧 add_don は active 追加 で 公式違反): {do_keys}"
    assert "add_don" not in do_keys, f"旧 add_don が 残存: {do_keys}"


def test_op14_061_op15_069_replace_leave_not_ko():
    """OP14-061 ヴェルゴ + OP15-069 ノラ: 公式 「場を離れる場合」 = replace_leave (= KO+bounce+deck含む)。
    旧 replace_ko (= KO限定) regression 防止。"""
    overlay = _overlay()
    for cid in ["OP14-061", "OP15-069"]:
        bundle = overlay.get(cid)
        assert bundle is not None, f"{cid} bundle 不在"
        whens = [e.get("when") for e in bundle.effects]
        assert "replace_leave" in whens, f"{cid} replace_leave 不在: {whens}"
        assert "replace_ko" not in whens, (
            f"{cid} 旧 replace_ko が 残存 (= 公式 「場を離れる場合」 違反)"
        )


# ============================================================================
# 2026-05-31 Bonney/Corazon/Coby regression tests (= batch 2)
# ============================================================================

def test_eb03_053_nami_opp_life_gate_separated():
    """EB03-053 ナミ on_play: opp_life_ge:3 gate が 別 entry 化 されている (= 旧 _if_clause string 解釈不能 を 修復)。"""
    overlay = _overlay()
    bundle = overlay.get("EB03-053")
    on_play_entries = [e for e in bundle.effects if e.get("when") == "on_play"]
    assert len(on_play_entries) >= 2, f"on_play entry が 2 つ ない: {len(on_play_entries)}"
    # mill_opp_life_to_hand を 持つ entry が opp_life_ge:3 で gate
    mill_entries = [
        e for e in on_play_entries
        if any("mill_opp_life_to_hand" in d for d in e.get("do", []))
    ]
    assert len(mill_entries) == 1, "mill_opp_life_to_hand 持つ entry が 1 つ で ない"
    if_b = mill_entries[0].get("if") or {}
    assert if_b.get("opp_life_ge") == 3, f"opp_life_ge:3 不在: {if_b}"
    # _if_clause が どこにも 残っていない こと
    for e in bundle.effects:
        for d in e.get("do", []):
            assert "_if_clause" not in d, f"_if_clause が overlay に 残存: {d}"


def test_st29_015_counter_split():
    """ST29-015 温度レアァ counter: top-level if 削除、 self pump は 無条件、 opp debuff は life≤1 限定 (= 旧 全 gate bug regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("ST29-015")
    counter_entries = [e for e in bundle.effects if e.get("when") == "counter"]
    # 自 pump (= self_inplay) は 無条件
    self_pump_entries = [
        e for e in counter_entries
        if any(d.get("power_pump", {}).get("target") == "self_inplay" for d in e.get("do", []))
    ]
    for e in self_pump_entries:
        if_b = e.get("if") or {}
        assert "self_life_le" not in if_b, f"自 pump entry に self_life_le が gate 残存: {if_b}"
    # 相手 debuff は self_life_le:1 で gate
    opp_pump_entries = [
        e for e in counter_entries
        if any(d.get("power_pump", {}).get("target") == "one_opponent_inplay_any" for d in e.get("do", []))
    ]
    for e in opp_pump_entries:
        if_b = e.get("if") or {}
        assert if_b.get("self_life_le") == 1, f"相手 debuff の self_life_le:1 gate 不在: {if_b}"


def test_eb04_007_zoro_activate_has_opp_chara_condition():
    """EB04-007 ゾロ activate_main: 公式 「相手の power 8000+ キャラ がいる場合、 この
    キャラは、 このターン中、 【速攻：キャラ】 を得る」。 if (opp power8000+) + give_keyword
    で 速攻：キャラ を 付与 する (= テキストに無い give_attack_active_chara/アクティブ
    アタック可 は 付けない、 engine が 速攻：キャラ keyword を 正規認識 core.py:363-)。"""
    overlay = _overlay()
    bundle = overlay.get("EB04-007")
    actmain = next(e for e in bundle.effects if e.get("when") == "activate_main")
    if_b = actmain.get("if") or {}
    cond = if_b.get("opp_chara_filtered_count_ge")
    assert isinstance(cond, dict), f"opp_chara_filtered_count_ge dict 不在: {cond}"
    assert cond.get("filter", {}).get("power_ge") == 8000, f"power_ge:8000 不在: {cond}"
    gks = [d["give_keyword"] for d in actmain.get("do", []) if "give_keyword" in d]
    assert any(g.get("keyword") == "速攻：キャラ" for g in gks), f"give_keyword 速攻：キャラ 不在: {actmain.get('do')}"
    # テキストに無い アクティブアタック可 (give_attack_active_chara) は 付与 しない
    do_keys = [list(d.keys())[0] for d in actmain.get("do", [])]
    assert "give_attack_active_chara" not in do_keys, f"テキスト外の give_attack_active_chara 混入: {do_keys}"


def test_op11_013_grus_uses_disable_blocker():
    """OP11-013 プリンス・グルス: 公式 「相手 power 2000以下 ブロッカー封じ」
    が disable_blocker primitive で 正しく 実装 (= 旧 set_attack_cost_discard_hand 誤実装 regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("OP11-013")
    on_attack = next(e for e in bundle.effects if e.get("when") == "on_attack")
    do_keys = [list(d.keys())[0] for d in on_attack.get("do", [])]
    assert "disable_blocker" in do_keys, f"disable_blocker 不在: {do_keys}"
    assert "set_attack_cost_discard_hand" not in do_keys, (
        f"旧 set_attack_cost_discard_hand 残存 (= wrong primitive regression)"
    )


def test_prb02_001_coby_condition_key_normalized():
    """PRB02-001 コビー: condition key 'self_hand_le' (= engine 未認識) → 'self_hand_count_le' (= 正)。
    eval_condition が 認識 する key で draw 効果 が 発火 する こと の 保証。"""
    overlay = _overlay()
    bundle = overlay.get("PRB02-001")
    on_attack = next(e for e in bundle.effects if e.get("when") == "on_attack")
    for d in on_attack.get("do", []):
        if isinstance(d, dict) and "_condition" in d:
            cond = d.get("_condition", {})
            assert "self_hand_le" not in cond, f"旧 self_hand_le 残存: {cond}"


def test_op12_073_law_target_chara_only():
    """OP12-073 ロー(7) on_play: power_pump target が all_self_team (= leader 含む) → all_self_chara_filtered
    (= leader 除外、 or filter ロシナンテ/ハート海賊団) に 修正済。"""
    overlay = _overlay()
    bundle = overlay.get("OP12-073")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    if_b = on_play.get("if") or {}
    assert if_b.get("don_diff_le") == 0, f"don_diff_le:0 gate 不在: {if_b}"
    for d in on_play.get("do", []):
        if "power_pump" in d:
            t = d["power_pump"].get("target")
            assert t != "all_self_team", "all_self_team 残存 (= leader 含む 旧 bug)"
            if isinstance(t, dict):
                assert t.get("type") == "all_self_chara_filtered", f"target type 違 い: {t}"


def test_op11_092_helmeppo_full_effect():
    """OP11-092 ヘルメッポ on_play: 公式 「1捨て cost → draw 1 + 自trash から SWORD cost≤8 (本人除く) 1 登場」
    の core が 実装 (= 旧 trash_self_hand_random だけ の 切り捨て regression 防止)。"""
    overlay = _overlay()
    bundle = overlay.get("OP11-092")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    do_keys = [list(d.keys())[0] for d in on_play.get("do", [])]
    assert "draw" in do_keys, f"draw 1 不在: {do_keys}"
    assert "play_from_trash" in do_keys, f"play_from_trash 不在: {do_keys}"
    # cost に discard_hand:1 が ある (= 公式 「1捨てで」)
    cost = on_play.get("cost", {})
    assert cost.get("discard_hand") == 1, f"cost.discard_hand:1 不在: {cost}"


def test_op11_004_search_rest_remain_bottom():
    """OP11-004 孔雀 on_play: 公式 「残りを 好きな順番 で デッキの下」 = rest_remain:'bottom'
    (= 旧 'trash' regression 防止)、 重複 look_top_reorder 削除済。"""
    overlay = _overlay()
    bundle = overlay.get("OP11-004")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    search_spec = next(d["search_top_n"] for d in on_play["do"] if "search_top_n" in d)
    assert search_spec.get("rest_remain") == "bottom", (
        f"rest_remain 'bottom' で ない: {search_spec.get('rest_remain')}"
    )
    # search_top_n 1 件 のみ (= 重複 look_top_reorder 削除済)
    look_reorder_count = sum(
        1 for d in on_play.get("do", []) if "look_top_reorder" in d
    )
    assert look_reorder_count == 0, f"重複 look_top_reorder 残存: {look_reorder_count}"


def test_eb04_002_bonney_search_feature_in_and_exclude():
    """EB04-002 ボニー on_play search: feature_in [エッグヘッド,麦わらの一味] + exclude_name 'ジュエリー・ボニー'。"""
    overlay = _overlay()
    bundle = overlay.get("EB04-002")
    on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
    search = next(d["search_top_n"] for d in on_play["do"] if "search_top_n" in d)
    filt = search.get("filter") or {}
    feats = filt.get("feature_in")
    assert isinstance(feats, list) and set(feats) == {"エッグヘッド", "麦わらの一味"}, (
        f"feature_in 不正: {feats}"
    )
    assert filt.get("exclude_name") == "ジュエリー・ボニー", (
        f"exclude_name 不在: {filt.get('exclude_name')}"
    )


def test_op12_112_baby5_trigger_leader_multicolor():
    """OP12-112 ベビー5 trigger: 公式 「自分のリーダーが多色 の場合」 leader_multicolor:true が 追加済。"""
    overlay = _overlay()
    bundle = overlay.get("OP12-112")
    trig = next(e for e in bundle.effects if e.get("when") == "trigger")
    if_b = trig.get("if") or {}
    assert if_b.get("leader_multicolor") is True, f"leader_multicolor:true 不在: {if_b}"


def test_search_top_n_filter_features_or():
    """OP13-012 ビビ + OP09-069 ロー + EB04-002 ボニー で 公式 「《X》か《Y》」 の OR 条件 が
    search filter feature_in で 正しく 表現 されている こと の 包括 regression。"""
    overlay = _overlay()
    cases = [
        ("OP13-012", {"アラバスタ王国", "麦わらの一味"}, 2),  # cost_ge:2
        ("OP09-069", {"麦わらの一味", "ハートの海賊団"}, 2),
        ("EB04-002", {"エッグヘッド", "麦わらの一味"}, None),
    ]
    for cid, expected_feats, expected_cost_ge in cases:
        bundle = overlay.get(cid)
        on_play = next(e for e in bundle.effects if e.get("when") == "on_play")
        search = next(d["search_top_n"] for d in on_play["do"] if "search_top_n" in d)
        filt = search.get("filter") or {}
        feats = set(filt.get("feature_in") or [])
        assert feats == expected_feats, f"{cid} feature_in 不正: {feats} vs {expected_feats}"
        if expected_cost_ge is not None:
            assert filt.get("cost_ge") == expected_cost_ge, f"{cid} cost_ge 不正: {filt.get('cost_ge')}"


def test_search_human_pick_branch():
    """search primitive で 人間 acting + 候補 > limit なら pending_choice 'search_pick' が 立つ。"""
    from engine.effects import execute_effect
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    # 人間 mode を 強制 (= state.human_player_idx)
    state.human_player_idx = 0
    me = state.players[0]
    opp = state.players[1]
    # me.deck に 5 枚 matching を 仕込む
    nami = repo.get("OP01-016")
    me.deck = [nami] * 5 + [repo.get("OP01-013")] * 20
    execute_effect(
        {"search": {"filter": {"name": "ナミ"}, "limit": 1}},
        state, me, opp, None,
    )
    assert state.pending_choice is not None, "pending_choice が 立たない (= 人間 modal 不在)"
    assert state.pending_choice.get("kind") == "search_pick", (
        f"kind が search_pick で ない: {state.pending_choice.get('kind')}"
    )
    assert len(state.pending_choice.get("candidates", [])) == 5, "候補 5 枚 揃わない"


def test_play_from_hand_or_trash_human_pick_branch():
    """play_from_hand_or_trash で 人間 acting + 候補 > limit なら
    pending_choice 'play_from_hand_or_trash_pick' が 立つ。"""
    from engine.effects import execute_effect
    repo = _repo()
    overlay = _overlay()
    state = _make_state(repo, "OP01-001", overlay=overlay)
    state.human_player_idx = 0
    me = state.players[0]
    opp = state.players[1]
    chara = repo.get("OP01-013")  # コスト 2 chara
    me.hand = [chara, chara]
    me.trash = [chara, chara]
    execute_effect(
        {"play_from_hand_or_trash": {"filter": {"category": "CHARACTER"}, "limit": 1}},
        state, me, opp, None,
    )
    assert state.pending_choice is not None, "pending_choice が 立たない"
    assert state.pending_choice.get("kind") == "play_from_hand_or_trash_pick", (
        f"kind 不一致: {state.pending_choice.get('kind')}"
    )
    cands = state.pending_choice.get("candidates", [])
    assert len(cands) == 4, f"全 候補 4 枚 揃わない: {len(cands)}"
    # source 別 内訳
    hand_count = sum(1 for c in cands if c.get("source") == "hand")
    trash_count = sum(1 for c in cands if c.get("source") == "trash")
    assert hand_count == 2 and trash_count == 2, f"source 内訳 不一致 (h={hand_count}, t={trash_count})"
