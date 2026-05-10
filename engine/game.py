# -*- coding: utf-8 -*-
"""
ONE PIECE Card Game ルールエンジン - ゲーム進行
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Union

from .core import CardDef, Category, GameState, InPlay, Phase, Player
from .deck import DeckList


# --------------------------------------------------------------------------- #
# アクション
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlayCharacter:
    hand_idx: int
    # 場 5 枚埋まっている時の差替対象 InPlay (公式 3-7-6-1)。None なら通常登場。
    sacrifice_iid: Optional[int] = None


@dataclass(frozen=True)
class PlayEvent:
    """【メイン】イベントカードの発動。手札から公開→コスト支払→トラッシュへ→効果発動 (8-4-2)"""
    hand_idx: int


@dataclass(frozen=True)
class PlayStage:
    """ステージカードの登場 (3-8-3)。既存ステージがあれば持ち主のトラッシュへ。"""
    hand_idx: int


@dataclass(frozen=True)
class AttachDonToLeader:
    n: int = 1


@dataclass(frozen=True)
class AttachDonToCharacter:
    target_iid: int
    n: int = 1


@dataclass(frozen=True)
class AttackLeader:
    attacker_iid: int
    counter_card_idxs: tuple[int, ...] = ()
    counter_event_idxs: tuple[int, ...] = ()    # 【カウンター】イベントの手札 idx


@dataclass(frozen=True)
class AttackCharacter:
    attacker_iid: int
    target_iid: int
    counter_card_idxs: tuple[int, ...] = ()
    counter_event_idxs: tuple[int, ...] = ()
    blocker_iid: Optional[int] = None


@dataclass(frozen=True)
class ActivateMain:
    source_iid: int
    effect_index: int


@dataclass(frozen=True)
class EndPhase:
    pass


Action = Union[
    PlayCharacter,
    PlayEvent,
    PlayStage,
    AttachDonToLeader,
    AttachDonToCharacter,
    AttackLeader,
    AttackCharacter,
    ActivateMain,
    EndPhase,
]


# --------------------------------------------------------------------------- #
# セットアップ
# --------------------------------------------------------------------------- #
def setup_game(
    deck1: DeckList,
    deck2: DeckList,
    rng: Optional[random.Random] = None,
    first_player: Optional[int] = None,
    effects_overlay: Optional[dict] = None,
) -> GameState:
    if rng is None:
        rng = random.Random()
    if first_player is None:
        first_player = rng.randrange(2)

    p1 = _make_player(deck1, "P0", rng, effects_overlay)
    p2 = _make_player(deck2, "P1", rng, effects_overlay)
    state = GameState(
        players=[p1, p2] if first_player == 0 else [p2, p1],
        turn_player_idx=0,
        turn_number=1,
        phase=Phase.REFRESH,
        rng=rng,
        effects_overlay=effects_overlay or {},
    )
    state.players[0].name = "P0"
    state.players[1].name = "P1"

    for p in state.players:
        p.draw(5)
    # マリガン (公式 5-2-1-2): 各プレイヤーは1度だけ手札全戻し+引き直し可能。
    # 先攻側から順に判定。AI ヒューリスティック: 手札に「3コスト以下のキャラ」が0枚ならマリガン。
    # (序盤に登場できるキャラがいないなら引き直すべき)
    for p in state.players:
        if _should_mulligan(p):
            # 手札を全部デッキに戻して シャッフル → 5 枚引き直し
            p.deck.extend(p.hand)
            p.hand = []
            p.shuffle_deck(rng)
            p.draw(5)
            state.push_log(f"  マリガン: {p.name} 手札を引き直し")
    for p in state.players:
        for _ in range(p.leader.card.life):
            if p.deck:
                p.life.append(p.deck.pop(0))

    state.push_log(
        f"start: P0={p1.leader.card.name}({p1.leader.card.life}L) "
        f"vs P1={p2.leader.card.name}({p2.leader.card.life}L)"
    )
    _recompute_static(state)
    return state


def _should_mulligan(p: Player) -> bool:
    """AI ヒューリスティックでマリガン判断。

    序盤展開のため「コスト3以下のキャラ」が手札に1枚以上欲しい。
    0枚ならマリガンする。コスト3以下のキャラが1+枚あれば現状の手札を保持。
    """
    low_cost_chars = [
        c for c in p.hand
        if c.category == Category.CHARACTER and c.cost <= 3
    ]
    return len(low_cost_chars) == 0


def _make_player(
    deck: DeckList,
    name: str,
    rng: random.Random,
    effects_overlay: Optional[dict] = None,
) -> Player:
    leader_inplay = InPlay.of(deck.leader, rested=False, sickness=False)
    # 公式ルール上、ドン!!デッキは 10 枚 (5-1-2-3) だが、
    # OP15-058 紫エネル等の「ルール上、自分のドン!!デッキは N 枚になる」効果に対応するため
    # leader の overlay の when:"setup_modifier" + set_don_deck_size を反映する。
    don_deck_size = 10
    if effects_overlay is not None:
        bundle = effects_overlay.get(deck.leader.card_id)
        if bundle is not None:
            for eff in bundle.effects:
                if eff.get("when") != "setup_modifier":
                    continue
                for prim in eff.get("do", []):
                    if "set_don_deck_size" in prim:
                        don_deck_size = int(prim["set_don_deck_size"])
    p = Player(
        name=name,
        leader=leader_inplay,
        deck=list(deck.main),
        don_active=0,
        don_rested=0,
        don_remaining_in_deck=don_deck_size,
    )
    p.shuffle_deck(rng)
    return p


# --------------------------------------------------------------------------- #
# フェーズ進行
# --------------------------------------------------------------------------- #
def _update_ownership_flags(state: GameState) -> None:
    """各 InPlay の owner_idx と is_owners_turn を state から再計算。

    DON+1000 は「所有者のターン中のみ」有効 (公式 6-5-5) なので、
    InPlay.power はこのフラグを参照する。アクション適用後・ターン推移後に呼ぶ。
    """
    for me_idx in (0, 1):
        p = state.players[me_idx]
        is_my_turn = (me_idx == state.turn_player_idx)
        for ip in [p.leader, *p.characters, *p.stages]:
            ip.owner_idx = me_idx
            ip.is_owners_turn = is_my_turn


def _recompute_static(state: GameState) -> None:
    """state.effects_overlay があれば常在効果 (on_attached_don 等) を再評価。

    overlay の有無に関わらず、所有者ターンフラグ (DON+1000 ゲート用) は更新する。
    """
    _update_ownership_flags(state)
    if state.effects_overlay:
        from .effects import evaluate_static_effects
        evaluate_static_effects(state, state.effects_overlay)


def _reset_battle_buffs(state: GameState) -> None:
    """バトル終了時 (公式 7-1-5-1) に全 InPlay の battle_buff (このバトル中効果) をクリア。

    AttackLeader / AttackCharacter の処理末尾で呼ぶ。"""
    for player in state.players:
        for ip in [player.leader, *player.characters, *player.stages]:
            ip.battle_buff = 0


def _reset_turn_buff(state: GameState) -> None:
    """ターン終了時に全 InPlay の turn_buff / 動的キーワード / KO 耐性 /
    アタック不可フラグをクリア。Player.play_cost_reduction も 0 に。
    cannot_attack_static は静的効果由来なのでここではクリアしない。"""
    for player in state.players:
        for ip in [player.leader, *player.characters, *player.stages]:
            ip.turn_buff = 0
            ip.granted_keywords = set()
            ip.ko_immune_until_turn_end = False
            ip.cannot_attack_until_turn_end = False
            ip.cost_minus_until_turn_end = 0
        player.play_cost_reduction = 0
        player.block_chara_play_until_turn_end = False


def advance_phase(state: GameState) -> None:
    if state.game_over:
        return

    cur = state.phase
    me = state.turn_player

    if cur == Phase.REFRESH:
        if state.turn_number > 1:
            # 公式 6-2-3: 付与ドン!!カードをレストでコストエリアに戻す
            # 公式 6-2-4: その後、レストのカード全部をアクティブに
            # → net effect: 付与ドンは active で復帰する。中間状態を観測する
            #   効果は現存しないので 1 ステップで実施。
            # ただし stay_rested_next_refresh が True のキャラは rested 維持し
            # フラグをクリア (1 回限りのターン跨ぎ効果、OP04-031 等)
            if me.leader.stay_rested_next_refresh:
                me.leader.stay_rested_next_refresh = False
            else:
                me.leader.rested = False
            for c in me.characters:
                if c.stay_rested_next_refresh:
                    c.stay_rested_next_refresh = False
                else:
                    c.rested = False
                me.don_active += c.attached_dons
                c.attached_dons = 0
                if hasattr(c, "_act_used"):
                    delattr(c, "_act_used")
            me.don_active += me.don_rested + me.leader.attached_dons
            me.leader.attached_dons = 0
            me.don_rested = 0
            # ステージのレスト解除 (3-8 + 6-2-4)
            for s in me.stages:
                s.rested = False
            for c in me.characters:
                c.summoning_sickness = False
            if hasattr(me.leader, "_act_used"):
                delattr(me.leader, "_act_used")
        # 公式 6-2-1-1-2: ターン開始時の自動効果を発動 (turn_number==1 含む全ターン)
        if state.effects_overlay:
            from .effects import trigger_turn_start
            trigger_turn_start(state, state.effects_overlay)
        state.phase = Phase.DRAW

    elif cur == Phase.DRAW:
        if not (state.turn_number == 1 and state.turn_player_idx == 0):
            drawn = me.draw(1)
            if not drawn:
                state.declare_winner(1 - state.turn_player_idx, f"{me.name} deckout")
                return
        state.phase = Phase.DON

    elif cur == Phase.DON:
        if state.turn_number == 1 and state.turn_player_idx == 0:
            n = 1
        else:
            n = 2
        n = min(n, me.don_remaining_in_deck)
        me.don_active += n
        me.don_remaining_in_deck -= n
        # ドンフェイズ修飾: リーダー overlay の when:"don_phase_modifier"
        # auto_attach_to_leader: 配られた N 枚のうち M 枚を自リーダーに自動付与
        # (OP13-003 赤紫ロジャー: 場ドンある場合 1 枚自動付与)
        if state.effects_overlay and n > 0:
            leader_id = me.leader.card.card_id
            bundle = state.effects_overlay.get(leader_id)
            if bundle is not None:
                from .effects import eval_condition
                for eff in bundle.effects:
                    if eff.get("when") != "don_phase_modifier":
                        continue
                    if not eval_condition(eff.get("if", {}), state, me, me.leader):
                        continue
                    for prim in eff.get("do", []):
                        attach_n = int(prim.get("auto_attach_to_leader", 0))
                        if attach_n > 0:
                            attach_n = min(attach_n, me.don_active)
                            me.don_active -= attach_n
                            me.leader.attached_dons += attach_n
                            state.push_log(
                                f"  自動付与: {me.name} リーダーにドン {attach_n} 枚"
                            )
        state.phase = Phase.MAIN

    elif cur == Phase.MAIN:
        state.phase = Phase.END

    elif cur == Phase.END:
        # 公式 6-6-1-1: 【自分/相手のターン終了時】の自動効果発動
        if state.effects_overlay:
            from .effects import trigger_end_of_turn
            trigger_end_of_turn(state, state.effects_overlay)
        # 公式ルール上、手札上限はない (3-4)。ターン終了時の discard は不要。
        _reset_turn_buff(state)
        state.turn_player_idx = 1 - state.turn_player_idx
        state.turn_number += 1
        state.phase = Phase.REFRESH

    _recompute_static(state)


def play_until_main(state: GameState) -> None:
    while state.phase != Phase.MAIN and not state.game_over:
        advance_phase(state)


# --------------------------------------------------------------------------- #
# 合法手生成
# --------------------------------------------------------------------------- #
def legal_actions(state: GameState) -> list[Action]:
    if state.game_over or state.phase != Phase.MAIN:
        return []

    me = state.turn_player
    actions: list[Action] = [EndPhase()]

    def _eff_cost(card: CardDef) -> int:
        return max(0, card.cost - me.play_cost_reduction)

    # キャラ登場禁止 (OP14-020 ミホーク等のペナルティでこのターン中ブロック)
    chara_play_blocked = me.block_chara_play_until_turn_end

    # 場 5 枚未満: 通常登場
    if me.can_play_character() and not chara_play_blocked:
        for i, c in enumerate(me.hand):
            if c.category != Category.CHARACTER:
                continue
            if _eff_cost(c) <= me.don_active:
                actions.append(PlayCharacter(hand_idx=i))
    elif not chara_play_blocked:
        # 場 5 枚埋まり: 既存 1 枚を sacrifice して登場 (3-7-6-1)
        # 手札の playable × 既存最弱を 1 候補のみ生成 (爆発を抑える)
        for i, c in enumerate(me.hand):
            if c.category != Category.CHARACTER:
                continue
            if _eff_cost(c) > me.don_active:
                continue
            # 最弱 (パワー低 → コスト低) を犠牲にする
            if not me.characters:
                continue
            sacrifice = min(
                me.characters,
                key=lambda ip: (ip.power, ip.card.cost),
            )
            actions.append(
                PlayCharacter(hand_idx=i, sacrifice_iid=sacrifice.instance_id)
            )

    # 【メイン】イベントカード: コスト払えるなら発動可能
    for i, c in enumerate(me.hand):
        if c.category != Category.EVENT:
            continue
        if _eff_cost(c) > me.don_active:
            continue
        # overlay に main 効果がある場合のみ発動候補に (空効果の event でもプレイ可)
        actions.append(PlayEvent(hand_idx=i))

    # ステージカード: コスト払えるなら登場可能 (既存ステージは差替)
    for i, c in enumerate(me.hand):
        if c.category != Category.STAGE:
            continue
        if _eff_cost(c) > me.don_active:
            continue
        actions.append(PlayStage(hand_idx=i))

    if me.don_active >= 1:
        actions.append(AttachDonToLeader(n=1))

    if me.don_active >= 1:
        for ch in me.characters:
            actions.append(AttachDonToCharacter(target_iid=ch.instance_id, n=1))

    # 公式 6-5-6-1: 両プレイヤーの 1 ターン目はバトル不可。
    # turn 1 = P0 の 1 ターン目, turn 2 = P1 の 1 ターン目, turn 3 以降が通常進行。
    can_battle = state.turn_number > 2

    attackers: list[InPlay] = []
    # 「速攻:キャラ」のみ持つキャラを別カテゴリで attacker に追加 (リーダー攻撃不可)
    chara_only_attackers: list[InPlay] = []
    if can_battle:
        if (
            not me.leader.rested
            and not me.leader.cannot_attack_until_turn_end
            and not me.leader.cannot_attack_static
        ):
            attackers.append(me.leader)
        for ch in me.characters:
            if ch.rested:
                continue
            if ch.cannot_attack_until_turn_end or ch.cannot_attack_static:
                continue
            if ch.summoning_sickness:
                # 召喚酔いでも 速攻:キャラ なら例外的に「キャラ攻撃のみ」可能
                if ch.is_rush_chara_only_now:
                    chara_only_attackers.append(ch)
                continue
            attackers.append(ch)

    opponent = state.opponent
    # 相手場に attack_taunt 持ちキャラがいる場合 (OP01-051 キッド等):
    # AttackLeader 禁止 + AttackCharacter は taunt キャラのみ対象
    opp_taunts = [c for c in opponent.characters if c.attack_taunt]
    for atk in attackers:
        # 「アクティブアタック可」キーワード付与時はアクティブも対象に (give_keyword で付与)
        attack_active_ok = "アクティブアタック可" in atk.granted_keywords
        if opp_taunts:
            for tgt in opp_taunts:
                if tgt.rested or attack_active_ok:
                    actions.append(
                        AttackCharacter(attacker_iid=atk.instance_id, target_iid=tgt.instance_id)
                    )
        else:
            actions.append(AttackLeader(attacker_iid=atk.instance_id))
            for tgt in opponent.characters:
                if tgt.rested or attack_active_ok:
                    actions.append(
                        AttackCharacter(attacker_iid=atk.instance_id, target_iid=tgt.instance_id)
                    )

    # 速攻:キャラ 専用 attacker: リーダー攻撃禁止、相手キャラのみ
    for atk in chara_only_attackers:
        attack_active_ok = "アクティブアタック可" in atk.granted_keywords
        # taunt があるなら taunt のみ
        if opp_taunts:
            for tgt in opp_taunts:
                if tgt.rested or attack_active_ok:
                    actions.append(
                        AttackCharacter(attacker_iid=atk.instance_id, target_iid=tgt.instance_id)
                    )
        else:
            for tgt in opponent.characters:
                if tgt.rested or attack_active_ok:
                    actions.append(
                        AttackCharacter(attacker_iid=atk.instance_id, target_iid=tgt.instance_id)
                    )

    if state.effects_overlay:
        from .effects import list_activate_main_effects
        for source, eff in list_activate_main_effects(state, me, state.effects_overlay):
            bundle = state.effects_overlay.get(source.card.card_id)
            if bundle is None:
                continue
            for idx, e in enumerate(bundle.effects):
                if e is eff:
                    actions.append(ActivateMain(source_iid=source.instance_id, effect_index=idx))
                    break

    return actions


# --------------------------------------------------------------------------- #
# アクション適用
# --------------------------------------------------------------------------- #
def apply_action(state: GameState, action: Action) -> None:
    if state.game_over:
        return
    if state.phase != Phase.MAIN:
        raise ValueError("apply_action MAIN only")
    try:
        _apply_action_impl(state, action)
    finally:
        _recompute_static(state)


def _apply_action_impl(state: GameState, action: Action) -> None:
    me = state.turn_player
    opp = state.opponent

    if isinstance(action, EndPhase):
        advance_phase(state)
        advance_phase(state)
        play_until_main(state)
        return

    if isinstance(action, PlayCharacter):
        card = me.hand[action.hand_idx]
        if card.category != Category.CHARACTER:
            raise ValueError(f"PlayCharacter category={card.category}")
        eff_cost = max(0, card.cost - me.play_cost_reduction)
        if me.don_active < eff_cost:
            raise ValueError("not enough don")
        if action.sacrifice_iid is not None:
            # 場 5 枚埋まり: 既存キャラを犠牲にして登場 (3-7-6-1)
            sacrifice = next(
                (ip for ip in me.characters if ip.instance_id == action.sacrifice_iid),
                None,
            )
            if sacrifice is None:
                raise ValueError("sacrifice target not found")
            me.characters.remove(sacrifice)
            me.trash.append(sacrifice.card)
            # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
            if sacrifice.attached_dons > 0:
                me.don_rested += sacrifice.attached_dons
            state.push_log(f"  差替: {sacrifice.card.name} をトラッシュへ")
            # 3-7-6-1-1: ルール処理であり【KO時】は発動しない
        elif not me.can_play_character():
            raise ValueError("field full (sacrifice required)")
        me.hand.pop(action.hand_idx)
        me.don_rested += eff_cost
        me.don_active -= eff_cost
        # 軽減の使用分を消費 (累積値が複数キャラ登場でも次の登場には残る簡略化)
        consumed = card.cost - eff_cost
        me.play_cost_reduction = max(0, me.play_cost_reduction - consumed)
        ip = InPlay.of(card, rested=False, sickness=not card.is_rush)
        me.characters.append(ip)
        state.push_log(f"play: {card.name} (cost {card.cost} pay {eff_cost})")
        if state.effects_overlay:
            from .effects import trigger_on_play
            trigger_on_play(state, me, opp, ip, state.effects_overlay)
        return

    if isinstance(action, PlayEvent):
        card = me.hand[action.hand_idx]
        if card.category != Category.EVENT:
            raise ValueError(f"PlayEvent category={card.category}")
        eff_cost = max(0, card.cost - me.play_cost_reduction)
        if me.don_active < eff_cost:
            raise ValueError("not enough don")
        # 8-4-2: イベントを公開→コスト→トラッシュ→効果発動 の順
        me.hand.pop(action.hand_idx)
        me.don_rested += eff_cost
        me.don_active -= eff_cost
        consumed = card.cost - eff_cost
        me.play_cost_reduction = max(0, me.play_cost_reduction - consumed)
        me.trash.append(card)
        state.push_log(f"event: {card.name} (cost {card.cost} pay {eff_cost})")
        if state.effects_overlay:
            from .effects import trigger_main_event
            trigger_main_event(state, me, opp, card, state.effects_overlay)
        return

    if isinstance(action, PlayStage):
        card = me.hand[action.hand_idx]
        if card.category != Category.STAGE:
            raise ValueError(f"PlayStage category={card.category}")
        eff_cost = max(0, card.cost - me.play_cost_reduction)
        if me.don_active < eff_cost:
            raise ValueError("not enough don")
        # 3-8-5-1: 既存ステージがあれば持ち主のトラッシュへ
        if len(me.stages) >= Player.MAX_STAGES:
            old = me.stages.pop()
            me.trash.append(old.card)
            # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
            if old.attached_dons > 0:
                me.don_rested += old.attached_dons
            state.push_log(f"  既存ステージ {old.card.name} をトラッシュへ")
        me.hand.pop(action.hand_idx)
        me.don_rested += eff_cost
        me.don_active -= eff_cost
        consumed = card.cost - eff_cost
        me.play_cost_reduction = max(0, me.play_cost_reduction - consumed)
        ip = InPlay.of(card, rested=False, sickness=False)
        me.stages.append(ip)
        state.push_log(f"stage: {card.name} (cost {card.cost} pay {eff_cost})")
        if state.effects_overlay:
            from .effects import trigger_on_play
            # 3-8-3: ステージエリアに置くことも「登場」 → 【登場時】を発動可
            trigger_on_play(state, me, opp, ip, state.effects_overlay)
        return

    if isinstance(action, AttachDonToLeader):
        n = min(action.n, me.don_active)
        me.don_active -= n
        me.leader.attached_dons += n
        state.push_log(f"attach don to leader x{n} (P={me.leader.power})")
        return

    if isinstance(action, AttachDonToCharacter):
        ch = _find_character(me, action.target_iid)
        n = min(action.n, me.don_active)
        me.don_active -= n
        ch.attached_dons += n
        state.push_log(f"attach don to {ch.card.name} x{n} (P={ch.power})")
        return

    if isinstance(action, AttackLeader):
        attacker = _find_attacker(me, action.attacker_iid)
        attacker.rested = True
        if state.effects_overlay:
            from .effects import trigger_on_attack, trigger_on_opp_attack
            # 7-1-1-3: 【アタック時】と【相手のアタック時】が同時に発動可
            trigger_on_attack(state, me, opp, attacker, state.effects_overlay)
            trigger_on_opp_attack(state, opp, me, attacker, state.effects_overlay)
        # アタック対象変更チェック (OP14-060 紫ドフラ等。redirect_attack プリミティブが set)
        if state.pending_attack_redirect is not None:
            redirect_iid = state.pending_attack_redirect
            state.pending_attack_redirect = None
            # opp の場 (リーダー or キャラ) で iid を解決
            if redirect_iid == opp.leader.instance_id:
                # リーダー → リーダー (= no-op)
                pass
            else:
                redirect_target = _find_character(opp, redirect_iid)
                # AttackLeader → AttackCharacter にコンバート
                redirected = AttackCharacter(
                    attacker_iid=action.attacker_iid,
                    target_iid=redirect_iid,
                    counter_card_idxs=action.counter_card_idxs,
                    counter_event_idxs=action.counter_event_idxs,
                    blocker_iid=None,
                )
                state.push_log(
                    f"  対象変更: leader → {redirect_target.card.name}"
                )
                # AttackCharacter ロジックを再帰呼出 (attack_rested は維持)
                # ただし trigger_on_attack は既に発火済なのでスキップしたい
                # 簡略実装: 再帰せず直接 KO 判定を行う
                counter_added = _spend_counters(opp, action.counter_card_idxs)
                _fire_counter_events(state, opp, me, action.counter_event_idxs)
                defender_power = redirect_target.power + counter_added
                atk_power = attacker.power
                state.push_log(
                    f"atk: {attacker.card.name}(P={atk_power}) -> "
                    f"{redirect_target.card.name}(P={defender_power}) [c={counter_added}]"
                )
                if atk_power >= defender_power:
                    if not redirect_target.ko_immune_until_turn_end:
                        opp.characters.remove(redirect_target)
                        opp.trash.append(redirect_target.card)
                        if redirect_target.attached_dons > 0:
                            opp.don_rested += redirect_target.attached_dons
                        state.push_log(f"  KO: {redirect_target.card.name}")
                        if state.effects_overlay:
                            from .effects import trigger_on_ko
                            trigger_on_ko(
                                state, opp, me, redirect_target.card,
                                state.effects_overlay,
                            )
                else:
                    state.push_log("  survived")
                _reset_battle_buffs(state)
                return
        # カウンターイベント発動 (7-1-3-1-2): 防御側 = opp が手札からイベントをトラッシュ
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        counter_added = _spend_counters(opp, action.counter_card_idxs)
        defender_power = opp.leader.power + counter_added
        atk_power = attacker.power
        state.pending_event = {
            "type": "attack",
            "attacker_iid": attacker.instance_id,
            "target_iid": opp.leader.instance_id,
            "target_kind": "leader",
            "atk_power": atk_power,
            "defender_power": defender_power,
        }
        state.push_log(
            f"atk: {attacker.card.name}(P={atk_power}) -> "
            f"{opp.leader.card.name}(P={defender_power}) [c={counter_added}]"
        )
        if atk_power >= defender_power:
            # 【ダブルアタック】: ダメージが 1 → 2 (10-1-2-1)
            damage = 2 if attacker.is_double_attack_now else 1
            is_banish = attacker.is_banish_now
            if damage == 2:
                state.push_log(f"  ダブルアタック: 2 ダメージ")
            for _ in range(damage):
                if not opp.life:
                    state.declare_winner(state.turn_player_idx, f"{opp.name} life=0 hit")
                    return
                taken = opp.life.pop(0)
                if is_banish:
                    # 【バニッシュ】: トリガー発動せずトラッシュへ (10-1-3-1)
                    opp.trash.append(taken)
                    state.push_log(
                        f"  hit: {opp.name} BANISH life->trash ({taken.name})"
                    )
                    continue
                fired = False
                if state.effects_overlay:
                    from .effects import trigger_lifecard_trigger, should_fire_trigger
                    # 公式 10-1-5: 防御側プレイヤーが発動するか選択
                    auto_fire = should_fire_trigger(state, opp, taken, state.effects_overlay)
                    fired = trigger_lifecard_trigger(
                        state, opp, me, taken, state.effects_overlay,
                        auto_fire=auto_fire,
                    )
                if fired:
                    opp.trash.append(taken)
                    state.push_log(f"  hit: {opp.name} trigger->trash ({taken.name})")
                else:
                    opp.hand.append(taken)
                    state.push_log(f"  hit: {opp.name} life->hand ({taken.name})")
        else:
            state.push_log("  blocked")
        # 公式 7-1-5-1: バトル終了時に「このバトル中」効果をリセット
        _reset_battle_buffs(state)
        return

    if isinstance(action, AttackCharacter):
        attacker = _find_attacker(me, action.attacker_iid)
        attacker.rested = True
        if state.effects_overlay:
            from .effects import trigger_on_attack, trigger_on_opp_attack
            trigger_on_attack(state, me, opp, attacker, state.effects_overlay)
            trigger_on_opp_attack(state, opp, me, attacker, state.effects_overlay)
        # カウンターイベント発動 (7-1-3-1-2)
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        target = _find_character(opp, action.target_iid)

        actual_target: InPlay = target
        if action.blocker_iid is not None:
            blocker = _find_character(opp, action.blocker_iid)
            if blocker.rested or not blocker.is_blocker_now or blocker.summoning_sickness:
                raise ValueError("invalid blocker")
            blocker.rested = True
            actual_target = blocker
            state.push_log(f"  blocker: {blocker.card.name}")
            # 10-2-15-1: 【ブロック時】効果発動
            if state.effects_overlay:
                from .effects import trigger_on_block
                trigger_on_block(state, opp, me, blocker, state.effects_overlay)

        counter_added = _spend_counters(opp, action.counter_card_idxs)
        defender_power = actual_target.power + counter_added
        atk_power = attacker.power
        state.pending_event = {
            "type": "attack",
            "attacker_iid": attacker.instance_id,
            "target_iid": actual_target.instance_id,
            "target_kind": "blocker" if action.blocker_iid is not None else "character",
            "atk_power": atk_power,
            "defender_power": defender_power,
        }
        state.push_log(
            f"atk: {attacker.card.name}(P={atk_power}) -> "
            f"{actual_target.card.name}(P={defender_power}) [c={counter_added}]"
        )
        if atk_power >= defender_power:
            if actual_target.ko_immune_until_turn_end:
                state.push_log(f"  KO 耐性: {actual_target.card.name} は KO されない")
            else:
                # 置換効果 (KOされる場合、代わりに〜)。バトルKO は by_opp_effect=False
                replaced = False
                if state.effects_overlay:
                    from .effects import try_replace_ko
                    replaced = try_replace_ko(
                        state, opp, me, actual_target, state.effects_overlay,
                        by_opp_effect=False,
                    )
                if replaced:
                    state.push_log(f"  KO 置換適用: {actual_target.card.name}")
                else:
                    opp.characters.remove(actual_target)
                    opp.trash.append(actual_target.card)
                    # 6-5-5-4: 付与ドンはレストでコストエリアに戻る
                    if actual_target.attached_dons > 0:
                        opp.don_rested += actual_target.attached_dons
                        state.push_log(
                            f"  KO: {actual_target.card.name} (don x{actual_target.attached_dons} returned)"
                        )
                    else:
                        state.push_log(f"  KO: {actual_target.card.name}")
                    if state.effects_overlay:
                        from .effects import trigger_on_ko
                        trigger_on_ko(state, opp, me, actual_target.card, state.effects_overlay)
        else:
            state.push_log("  survived")
        # 公式 7-1-5-1: バトル終了時に「このバトル中」効果をリセット
        _reset_battle_buffs(state)
        return

    if isinstance(action, ActivateMain):
        from .effects import fire_activate_main
        source = _find_attacker(me, action.source_iid)
        bundle = state.effects_overlay.get(source.card.card_id)
        if bundle is None:
            raise ValueError("ActivateMain no effect bundle")
        eff = bundle.effects[action.effect_index]
        fire_activate_main(state, me, opp, source, eff)
        return

    raise ValueError(f"unknown action: {action}")


def _find_character(p: Player, iid: int) -> InPlay:
    for ch in p.characters:
        if ch.instance_id == iid:
            return ch
    raise ValueError(f"P={p.name} no char iid={iid}")


def _find_attacker(p: Player, iid: int) -> InPlay:
    if p.leader.instance_id == iid:
        return p.leader
    return _find_character(p, iid)


def _spend_counters(p: Player, idxs: tuple[int, ...]) -> int:
    if not idxs:
        return 0
    total = 0
    for i in sorted(set(idxs), reverse=True):
        if 0 <= i < len(p.hand):
            card = p.hand.pop(i)
            p.trash.append(card)
            total += card.counter
    return total


def _fire_counter_events(
    state: GameState,
    defender: Player,
    attacker_player: Player,
    idxs: tuple[int, ...],
) -> None:
    """【カウンター】イベントカードの発動 (7-1-3-1-2)。

    defender = アタックを受けている側 (= イベントの "自分")。
    各 idx は defender.hand 中のイベントカード位置。
    コスト支払い → トラッシュ → when:"counter" 効果発動 の順。
    """
    if not idxs or not state.effects_overlay:
        return
    from .effects import trigger_counter_event

    # 後方から処理して idx を不変に保つ
    for i in sorted(set(idxs), reverse=True):
        if not (0 <= i < len(defender.hand)):
            continue
        card = defender.hand[i]
        if card.category != Category.EVENT:
            continue
        if defender.don_active < card.cost:
            # コスト不足: 発動できない (トラッシュもしない)
            continue
        defender.hand.pop(i)
        defender.don_rested += card.cost
        defender.don_active -= card.cost
        defender.trash.append(card)
        state.push_log(f"  counter event: {card.name} (cost {card.cost})")
        trigger_counter_event(state, defender, attacker_player, card, state.effects_overlay)
