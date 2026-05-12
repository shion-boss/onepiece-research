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
    blocker_iid: Optional[int] = None           # ブロッカー発動時のブロッカー iid (10-1-4)


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
    deck1_analysis: Optional[dict] = None,
    deck2_analysis: Optional[dict] = None,
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
    # 各プレイヤーに analysis を割り当て (= マリガン判定で使う)。
    # state.players の並び順は first_player に従って入れ替えてあるので、 それに合わせる。
    if first_player == 0:
        analyses = [deck1_analysis, deck2_analysis]
    else:
        analyses = [deck2_analysis, deck1_analysis]

    for p in state.players:
        p.draw(5)
    # マリガン (公式 5-2-1-2): 各プレイヤーは1度だけ手札全戻し+引き直し可能。
    # deck_analysis があれば mulligan_keep_card_ids を見てキープ判定、 無ければフォールバック。
    for p, a in zip(state.players, analyses):
        if _should_mulligan(p, a):
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


def _should_mulligan(
    p: Player,
    deck_analysis: Optional[dict] = None,
) -> bool:
    """AI ヒューリスティックでマリガン判断。

    deck_analysis があれば mulligan_keep_card_ids ベースで判定:
      - 手札に「キープしたい主力カード」が1枚以上 → キープ (mulligan しない)
      - 0枚 → マリガン
    無ければフォールバック (= 「コスト3以下のキャラ」が0枚ならマリガン)。
    """
    if deck_analysis:
        keep_ids = set(deck_analysis.get("mulligan_keep_card_ids") or [])
        if keep_ids:
            has_key = any(c.card_id in keep_ids for c in p.hand)
            return not has_key
    # フォールバック
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


def _battle_ko_immune_by_attribute(defender: InPlay, attacker: InPlay) -> bool:
    """defender が attacker の attribute によってバトル KO 不可かどうか判定。
    P-052 ミホーク 「属性(斬)を持つカードとのバトルで KO されない」 等。
    """
    atk_attr = attacker.card.attribute or ""
    if atk_attr and atk_attr in defender.ko_immune_battle_attributes_in:
        return True
    if defender.ko_immune_battle_attributes_not_in:
        # 「属性 X を持たないカードとのバトルで KO されない」 (P-025 スモーカー等)
        # = attacker が ko_immune_battle_attributes_not_in に含まれない attribute なら KO 不可
        if atk_attr not in defender.ko_immune_battle_attributes_not_in:
            return True
    return False


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
    me_turn = state.turn_player
    for player in state.players:
        for ip in [player.leader, *player.characters, *player.stages]:
            ip.turn_buff = 0
            ip.granted_keywords = set()
            ip.ko_immune_until_turn_end = False
            ip.cannot_attack_until_turn_end = False
            ip.cost_minus_until_turn_end = 0
            ip.attacker_prevents_blocker_until_turn_end = False
            ip.cannot_attack_target_cost_le_until_turn_end = -1
            ip.turn_base_power_override = None
        player.play_cost_reduction = 0
        player.block_chara_play_until_turn_end = False
        player.block_self_draw_until_turn_end = False
        player.prevent_self_life_to_hand_until_turn_end = False
    # 「次の相手ターン終了時まで」 disable_effect / アタック不可 は、 所有者のターン
    # 終了時にクリア (= 自分が相手ターン中に解除される動きを実現)。
    # ターン主のキャラ/リーダーのみクリア対象とする。
    for ip in [me_turn.leader, *me_turn.characters, *me_turn.stages]:
        ip.effect_disabled_through_opp_turn = False
        ip.cannot_attack_through_opp_turn = False
        ip.ko_immune_through_opp_turn = False

    # 次の(相手|自分)のターン終了時まで タイムドバフ系を applier-tracking でクリア。
    # 条件: applied_turn < state.turn_number (= 少なくとも 1 ターン経過)
    # かつ ended_idx の判定 (next_opp = !=applier、 next_self = ==applier)
    ended_idx = state.players.index(me_turn)
    for player in state.players:
        for ip in [player.leader, *player.characters, *player.stages]:
            # next_opp_turn_end_buff: applier の相手のターン終了で消える
            if ip.next_opp_turn_end_buff != 0 or ip.next_opp_turn_end_applier_idx >= 0:
                if (ip.next_opp_turn_end_applier_idx >= 0
                        and ip.next_opp_turn_end_applied_turn < state.turn_number
                        and ended_idx != ip.next_opp_turn_end_applier_idx):
                    ip.next_opp_turn_end_buff = 0
                    ip.next_opp_turn_end_applier_idx = -1
                    ip.next_opp_turn_end_applied_turn = 0
            # next_self_turn_end_buff: applier の自身のターン終了で消える
            if ip.next_self_turn_end_buff != 0 or ip.next_self_turn_end_applier_idx >= 0:
                if (ip.next_self_turn_end_applier_idx >= 0
                        and ip.next_self_turn_end_applied_turn < state.turn_number
                        and ended_idx == ip.next_self_turn_end_applier_idx):
                    ip.next_self_turn_end_buff = 0
                    ip.next_self_turn_end_applier_idx = -1
                    ip.next_self_turn_end_applied_turn = 0
            # cannot_be_rested_buff: applier の相手ターン終了で消える (= 防衛効果)
            if ip.cannot_be_rested_buff:
                if (ip.cannot_be_rested_applier_idx >= 0
                        and ip.cannot_be_rested_applied_turn < state.turn_number
                        and ended_idx != ip.cannot_be_rested_applier_idx):
                    ip.cannot_be_rested_buff = False
                    ip.cannot_be_rested_applier_idx = -1
                    ip.cannot_be_rested_applied_turn = 0
            # next_opp_turn_end_base_power_override:
            # applier の opp ターン (= 相手ターン) 終了で消える。
            # ST26-005 ルフィ 「自分のリーダーを 次の相手のエンドフェイズ終了時まで、 元々のパワー7000」 等。
            if ip.next_opp_turn_end_base_power_override is not None:
                if (ip.next_opp_turn_end_base_power_override_applier_idx >= 0
                        and ip.next_opp_turn_end_base_power_override_applied_turn < state.turn_number
                        and ended_idx != ip.next_opp_turn_end_base_power_override_applier_idx):
                    ip.next_opp_turn_end_base_power_override = None
                    ip.next_opp_turn_end_base_power_override_applier_idx = -1
                    ip.next_opp_turn_end_base_power_override_applied_turn = 0
            # granted_keywords_through_opp_turn: applier の opp ターン (= 相手ターン) 終了で消える。
            # OP09-084 カタリーナ・デボン 「次の相手のターン終了時まで、 【ダブルアタック】か【バニッシュ】か【ブロッカー】を得る」 等。
            if ip.attack_cost_discard_hand_n > 0:
                if (ip.attack_cost_discard_hand_applier_idx >= 0
                        and ip.attack_cost_discard_hand_applied_turn < state.turn_number
                        and ended_idx != ip.attack_cost_discard_hand_applier_idx):
                    ip.attack_cost_discard_hand_n = 0
                    ip.attack_cost_discard_hand_applier_idx = -1
                    ip.attack_cost_discard_hand_applied_turn = 0
            if ip.granted_keywords_through_opp_turn:
                if (ip.granted_keywords_through_opp_turn_applier_idx >= 0
                        and ip.granted_keywords_through_opp_turn_applied_turn < state.turn_number
                        and ended_idx != ip.granted_keywords_through_opp_turn_applier_idx):
                    ip.granted_keywords_through_opp_turn = set()
                    ip.granted_keywords_through_opp_turn_applier_idx = -1
                    ip.granted_keywords_through_opp_turn_applied_turn = 0


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
                # on_attack のターン1回フラグもクリア (任意 idx)
                for attr in list(c.__dict__.keys()):
                    if attr.startswith("_on_attack_used_"):
                        delattr(c, attr)
            # 「次のリフレッシュでアクティブにならない」 ドン数 (OP10-033 ナミ等) を差し引く
            kept_rested = me.next_refresh_kept_rested_don
            available_rested = me.don_rested - kept_rested
            if available_rested < 0:
                available_rested = 0
                kept_rested = me.don_rested
            me.don_active += available_rested + me.leader.attached_dons
            me.leader.attached_dons = 0
            me.don_rested = kept_rested
            me.next_refresh_kept_rested_don = 0
            # ステージのレスト解除 (3-8 + 6-2-4)
            for s in me.stages:
                s.rested = False
            for c in me.characters:
                c.summoning_sickness = False
            if hasattr(me.leader, "_act_used"):
                delattr(me.leader, "_act_used")
            for attr in list(me.leader.__dict__.keys()):
                if attr.startswith("_on_attack_used_"):
                    delattr(me.leader, attr)
            # next_turn_buff (= 「次の自分のターン開始時まで」 期限) を所有者側でクリア。
            # 自分のターン開始時 = ここで自分の InPlay の next_turn_buff を 0 に。
            me.leader.next_turn_buff = 0
            me.leader.next_turn_base_power_override = None
            for c in me.characters:
                c.next_turn_buff = 0
                c.next_turn_base_power_override = None
            for s in me.stages:
                s.next_turn_buff = 0
                s.next_turn_base_power_override = None
            # 【ターン1回】 効果の発動済みキー集合をクリア (= 次自ターンで再発動可)。
            # effect spec の top-level `once_per_turn` を _execute_event がガードに使う。
            me.once_per_turn_used.clear()
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
        # 「次の相手のメインフェイズ開始時」 効果 (PRB02-005 ルフィ等)
        # me = 現在 turn_player、 opp_player = me の相手 = 効果保有側 (= PRB02-005 持ち)。
        # effect の "me" 視点は opp_player (= 効果保有側)、 "opp" は me (= turn_player)。
        opp_player = state.players[1 - state.turn_player_idx]
        if opp_player.delayed_at_opp_main_phase_start and state.effects_overlay:
            from .effects import execute_effect
            for spec in opp_player.delayed_at_opp_main_phase_start:
                for prim in spec.get("do", []):
                    execute_effect(prim, state, opp_player, me, None)
            opp_player.delayed_at_opp_main_phase_start = []

    elif cur == Phase.MAIN:
        state.phase = Phase.END

    elif cur == Phase.END:
        # 公式 6-6-1-1: 【自分/相手のターン終了時】の自動効果発動
        if state.effects_overlay:
            from .effects import trigger_end_of_turn
            trigger_end_of_turn(state, state.effects_overlay)
        # 公式ルール上、手札上限はない (3-4)。ターン終了時の discard は不要。
        _reset_turn_buff(state)
        if state.extra_turn_pending:
            # 「ターン追加」 効果: ターンプレイヤーを変えず、 そのまま REFRESH へ。
            state.extra_turn_pending = False
            state.turn_number += 1
            state.push_log(f"=== extra turn: P{state.turn_player_idx} ===")
        else:
            state.turn_player_idx = 1 - state.turn_player_idx
            state.turn_number += 1
        state.phase = Phase.REFRESH

    # 各 trigger_* が enqueue しただけで終わっているケースに備え、
    # フェーズ境界でもキューを掃く。
    if state.effects_overlay and state.event_queue and not state.resolving:
        from .effects import resolve_triggers
        resolve_triggers(state)
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

    def _in_hand_cost_minus(card: CardDef) -> int:
        """手札時のカード固有コスト軽減 (overlay の when:"in_hand" + cost_minus)。
        条件 (if 句) を満たす effect の cost_minus を合計する。 公式: 「手札のこのカードは
        〜の場合、 コスト-N」 を表現。"""
        from .effects import eval_condition
        if not state.effects_overlay:
            return 0
        bundle = state.effects_overlay.get(card.card_id)
        if bundle is None:
            return 0
        total = 0
        for eff in bundle.effects:
            if eff.get("when") != "in_hand":
                continue
            if not eval_condition(eff.get("if", {}), state, me, None):
                continue
            for prim in eff.get("do", []):
                if not isinstance(prim, dict):
                    continue
                if "in_hand_cost_minus" in prim:
                    val = prim["in_hand_cost_minus"]
                    total += int(val) if isinstance(val, int) else int(val.get("amount", 0))
        return total

    def _eff_cost(card: CardDef) -> int:
        from .effects import _matches_filter as _matches
        filtered_reduction = sum(
            int(r.get("amount", 0))
            for r in me.play_cost_reductions_filtered
            if _matches(card, r.get("filter", {}))
        )
        base = card.cost - me.play_cost_reduction - _in_hand_cost_minus(card) - filtered_reduction
        return max(0, base)

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
            and not me.leader.cannot_attack_through_opp_turn
        ):
            attackers.append(me.leader)
        for ch in me.characters:
            if ch.rested:
                continue
            if (
                ch.cannot_attack_until_turn_end
                or ch.cannot_attack_static
                or ch.cannot_attack_through_opp_turn
            ):
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
    def _can_attack_target(attacker, target_cost: int) -> bool:
        cap = attacker.cannot_attack_target_cost_le_until_turn_end
        return cap < 0 or target_cost > cap

    for atk in attackers:
        # 「アクティブアタック可」キーワード付与時はアクティブも対象に (give_keyword で付与)
        attack_active_ok = "アクティブアタック可" in atk.granted_keywords
        if opp_taunts:
            for tgt in opp_taunts:
                if (tgt.rested or attack_active_ok) and _can_attack_target(atk, tgt.card.cost):
                    actions.append(
                        AttackCharacter(attacker_iid=atk.instance_id, target_iid=tgt.instance_id)
                    )
        else:
            actions.append(AttackLeader(attacker_iid=atk.instance_id))
            for tgt in opponent.characters:
                if (tgt.rested or attack_active_ok) and _can_attack_target(atk, tgt.card.cost):
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
        # トリガー解決 → 静的効果 (KO/登場で場が変動した可能性あり) の順で正規化。
        # _maybe_resolve は trigger_* 内で都度呼ばれるが、 ここでは「アクション境界」 で
        # キューが残っていれば最終ドレイン (例: enqueue だけして resolve せず終わるパス対策)。
        if state.effects_overlay and state.event_queue and not state.resolving:
            from .effects import resolve_triggers
            resolve_triggers(state)
        _recompute_static(state)


def _compute_filtered_cost_reduction(me: Player, card: CardDef) -> int:
    """場の静的効果 (play_cost_reductions_filtered) から、 card がマッチする
    軽減量を合計する。 OP05-097 「コスト2以上の天竜人キャラのコスト -1」 等。"""
    from .effects import _matches_filter
    total = 0
    for r in me.play_cost_reductions_filtered:
        if _matches_filter(card, r.get("filter", {})):
            total += int(r.get("amount", 0))
    return total


def _compute_in_hand_cost_minus(state: GameState, me: Player, card: CardDef) -> int:
    """手札時のカード固有コスト軽減 (overlay の when:"in_hand" + cost_minus)。
    apply_action でも legal_actions と同じ計算を共有するためのモジュールレベル helper。"""
    from .effects import eval_condition
    if not state.effects_overlay:
        return 0
    bundle = state.effects_overlay.get(card.card_id)
    if bundle is None:
        return 0
    total = 0
    for eff in bundle.effects:
        if eff.get("when") != "in_hand":
            continue
        if not eval_condition(eff.get("if", {}), state, me, None):
            continue
        for prim in eff.get("do", []):
            if not isinstance(prim, dict):
                continue
            if "in_hand_cost_minus" in prim:
                val = prim["in_hand_cost_minus"]
                total += int(val) if isinstance(val, int) else int(val.get("amount", 0))
    return total


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
        eff_cost = max(0, card.cost - me.play_cost_reduction - _compute_in_hand_cost_minus(state, me, card) - _compute_filtered_cost_reduction(me, card))
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
        eff_cost = max(0, card.cost - me.play_cost_reduction - _compute_in_hand_cost_minus(state, me, card) - _compute_filtered_cost_reduction(me, card))
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
        eff_cost = max(0, card.cost - me.play_cost_reduction - _compute_in_hand_cost_minus(state, me, card) - _compute_filtered_cost_reduction(me, card))
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
        # アタック時 手札捨てコスト (OP08-043 エドワード等)
        if attacker.attack_cost_discard_hand_n > 0:
            n_needed = attacker.attack_cost_discard_hand_n
            if len(me.hand) < n_needed:
                state.push_log(
                    f"  アタック不能: {attacker.card.name} は手札{n_needed}枚不足 ({len(me.hand)}枚)"
                )
                return
            # ランダムに N 枚を trash (= 「捨てなければアタックできない」)
            import random as _r
            rng = state.rng if hasattr(state, "rng") else _r.Random()
            for _ in range(n_needed):
                if not me.hand:
                    break
                idx = rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
            state.push_log(f"  アタック前コスト: 手札{n_needed}枚捨て ({attacker.card.name})")
        attacker.rested = True
        if state.effects_overlay:
            from .effects import trigger_on_attack, trigger_on_opp_attack, trigger_on_opp_attack_on_leader
            # 7-1-1-3: 【アタック時】と【相手のアタック時】が同時に発動可
            trigger_on_attack(state, me, opp, attacker, state.effects_overlay)
            trigger_on_opp_attack(state, opp, me, attacker, state.effects_overlay)
            # defender=リーダー 限定の opp_attack (OP03-001 エース等)
            trigger_on_opp_attack_on_leader(state, opp, me, attacker, state.effects_overlay)
        # アタック対象変更チェック (OP14-060 紫ドフラ等。redirect_attack プリミティブが set)
        if state.pending_attack_redirect is not None:
            redirect_iid = state.pending_attack_redirect
            state.pending_attack_redirect = None
            # opp の場 (リーダー or キャラ) で iid を解決
            if redirect_iid == opp.leader.instance_id:
                # リーダー → リーダー (= no-op)
                pass
            else:
                redirect_target = next(
                    (c for c in opp.characters if c.instance_id == redirect_iid),
                    None,
                )
                if redirect_target is None:
                    state.push_log(
                        f"  対象変更失敗: redirect iid={redirect_iid} は既に場にない"
                    )
                    _reset_battle_buffs(state)
                    return
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
                # === Pre-counter snapshot ===
                atk_power = attacker.power
                base_defender_power = redirect_target.power
                state.pending_event = {
                    "type": "attack",
                    "attacker_iid": attacker.instance_id,
                    "target_iid": redirect_target.instance_id,
                    "target_kind": "character",
                    "atk_power": atk_power,
                    "defender_power": base_defender_power,
                }
                state.push_log(
                    f"atk: {attacker.card.name}(P={atk_power}) -> "
                    f"{redirect_target.card.name}(P={base_defender_power})"
                )
                # === Counter フェイズ ===
                _fire_counter_events(state, opp, me, action.counter_event_idxs)
                counter_added = _spend_counters(opp, action.counter_card_idxs)
                defender_power = base_defender_power + counter_added
                if counter_added > 0:
                    state.pending_event = {
                        "type": "attack",
                        "attacker_iid": attacker.instance_id,
                        "target_iid": redirect_target.instance_id,
                        "target_kind": "character",
                        "atk_power": atk_power,
                        "defender_power": defender_power,
                    }
                    state.push_log(
                        f"  counter +{counter_added} → "
                        f"{redirect_target.card.name}(P={defender_power})"
                    )
                if atk_power >= defender_power:
                    if not redirect_target.ko_immune_until_turn_end:
                        opp.characters.remove(redirect_target)
                        opp.trash.append(redirect_target.card)
                        if redirect_target.attached_dons > 0:
                            opp.don_rested += redirect_target.attached_dons
                        state.push_log(f"  KO: {redirect_target.card.name}")
                        if state.effects_overlay:
                            from .effects import (
                                trigger_on_ko,
                                trigger_on_opp_chara_ko,
                                trigger_on_self_chara_ko,
                            )
                            trigger_on_ko(
                                state, opp, me, redirect_target.card,
                                state.effects_overlay,
                            )
                            trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                            trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
                else:
                    state.push_log("  survived")
                _reset_battle_buffs(state)
                return
        # === ブロックステップ (7-1-2): blocker_iid 指定時 ===
        # 公式 10-1-4: アクティブなブロッカー 1 枚をレストにすると、 アタック対象を
        # ブロッカーに変更する。 【ブロック時】効果が発動する (10-2-15-1)。
        actual_target: InPlay = opp.leader
        target_iid = opp.leader.instance_id
        target_kind = "leader"
        is_blocked = False
        if action.blocker_iid is not None and not attacker.has_no_block_now:
            blocker = next(
                (c for c in opp.characters if c.instance_id == action.blocker_iid),
                None,
            )
            if blocker is None:
                state.push_log(
                    f"  ブロッカー消失: iid={action.blocker_iid} は既に場にない (ブロッカー無効)"
                )
            elif (
                blocker.rested
                or not blocker.is_blocker_now
                or blocker.summoning_sickness
            ):
                state.push_log(
                    f"  ブロッカー無効: {blocker.card.name} (rested/sickness/blocker特性なし)"
                )
            else:
                blocker.rested = True
                actual_target = blocker
                target_iid = blocker.instance_id
                target_kind = "blocker"
                is_blocked = True
                state.push_log(f"  blocker: {blocker.card.name}")
                if state.effects_overlay:
                    from .effects import trigger_on_block, trigger_on_opp_blocker_use
                    trigger_on_block(state, opp, me, blocker, state.effects_overlay)
                    # アタッカー側 (me) の「相手が【ブロッカー】を発動した時」 効果 (OP09-118 等)
                    trigger_on_opp_blocker_use(state, me, opp, blocker, state.effects_overlay)
                # ブロック時効果で blocker が KO されている可能性 → 場から消えていれば fallback
                if blocker not in opp.characters:
                    state.push_log(
                        f"  ブロック中に消失: {blocker.card.name} → 攻撃不発"
                    )
                    _reset_battle_buffs(state)
                    return

        # === Pre-counter snapshot: アタッカー対防御側 (counter 反映前) ===
        atk_power = attacker.power
        base_defender_power = actual_target.power
        state.pending_event = {
            "type": "attack",
            "attacker_iid": attacker.instance_id,
            "target_iid": target_iid,
            "target_kind": target_kind,
            "atk_power": atk_power,
            "defender_power": base_defender_power,
        }
        state.push_log(
            f"atk: {attacker.card.name}(P={atk_power}) -> "
            f"{actual_target.card.name}(P={base_defender_power})"
        )
        # === Counter フェイズ ===
        # カウンターイベント発動 (7-1-3-1-2): 各イベント毎に push_log → snapshot
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        # カウンターカード消費 (キャラ counter 値、_spend_counters は log なし)
        counter_added = _spend_counters(opp, action.counter_card_idxs)
        defender_power = base_defender_power + counter_added
        # === Post-counter snapshot: counter 加算後の defender_power ===
        if counter_added > 0:
            state.pending_event = {
                "type": "attack",
                "attacker_iid": attacker.instance_id,
                "target_iid": target_iid,
                "target_kind": target_kind,
                "atk_power": atk_power,
                "defender_power": defender_power,
            }
            state.push_log(
                f"  counter +{counter_added} → "
                f"{actual_target.card.name}(P={defender_power})"
            )
        # ブロックされた場合: 勝てばブロッカーが KO、 負ければ生存 (リーダーへのダメージなし)
        if is_blocked:
            if atk_power >= defender_power:
                if (
                    not actual_target.ko_immune_until_turn_end
                    and not actual_target.static_ko_immune
                    and not _battle_ko_immune_by_attribute(actual_target, attacker)
                ):
                    opp.characters.remove(actual_target)
                    opp.trash.append(actual_target.card)
                    if actual_target.attached_dons > 0:
                        opp.don_rested += actual_target.attached_dons
                    state.push_log(f"  KO: {actual_target.card.name}")
                    if state.effects_overlay:
                        from .effects import (
                            trigger_on_ko,
                            trigger_on_opp_chara_ko,
                            trigger_on_self_chara_ko,
                        )
                        trigger_on_ko(
                            state, opp, me, actual_target.card,
                            state.effects_overlay,
                        )
                        trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                        trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
            else:
                state.push_log("  blocker survived")
            _reset_battle_buffs(state)
            return
        if atk_power >= defender_power:
            # 【ダブルアタック】: ダメージが 1 → 2 (10-1-2-1)
            damage = 2 if attacker.is_double_attack_now else 1
            is_banish = attacker.is_banish_now
            # 公式 9-2-1 + cardqa Q36: 敗北判定は「アタック開始時にライフ 0」のみ。
            # ダブルアタックでライフ 1 → 1 枚消費して 0 になっても、その時点では敗北しない
            # (= 2 発目はライフが無いため空打ち)。次のアタックで「アタック開始時 life=0」 → 敗北。
            if not opp.life:
                # ライフ 0 トリガー (OP05-098 紫エネル等): デッキ上 1 枚をライフに移して
                # 敗北回避するパターン。 効果でライフが回復していれば下記 winner 宣言を回避。
                if state.effects_overlay:
                    from .effects import trigger_on_life_zero
                    trigger_on_life_zero(state, opp, me, state.effects_overlay)
                if not opp.life:
                    state.declare_winner(state.turn_player_idx, f"{opp.name} life=0 hit")
                    return
            if damage == 2:
                state.push_log(f"  ダブルアタック: 2 ダメージ")
            for _ in range(damage):
                if not opp.life:
                    # 攻撃中にライフが尽きた → 残りダメージは空打ち (Q36)。敗北は宣言しない
                    state.push_log(f"  ライフ尽きた、残り {damage} 発目以降は空打ち")
                    break
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
                    went_to_hand = False
                else:
                    opp.hand.append(taken)
                    state.push_log(f"  hit: {opp.name} life->hand ({taken.name})")
                    went_to_hand = True
                # 公式 10-1-5 直後: 「相手のライフが離れた時」 / 「自分のライフが (手札に加わった | トラッシュに置かれた) 時」
                # OP08-105 ジュエリー・ボニー / OP05-107 スペーシー中尉 等
                if state.effects_overlay:
                    from .effects import trigger_on_opp_life_taken
                    trigger_on_opp_life_taken(
                        state, me, opp, went_to_hand, state.effects_overlay,
                    )
        else:
            state.push_log("  blocked")
        # 公式 7-1-5-1: バトル終了時に「このバトル中」効果をリセット
        _reset_battle_buffs(state)
        return

    if isinstance(action, AttackCharacter):
        attacker = _find_attacker(me, action.attacker_iid)
        if attacker.attack_cost_discard_hand_n > 0:
            n_needed = attacker.attack_cost_discard_hand_n
            if len(me.hand) < n_needed:
                state.push_log(
                    f"  アタック不能: {attacker.card.name} は手札{n_needed}枚不足 ({len(me.hand)}枚)"
                )
                return
            for _ in range(n_needed):
                if not me.hand:
                    break
                idx = state.rng.randrange(len(me.hand))
                me.trash.append(me.hand.pop(idx))
            state.push_log(f"  アタック前コスト: 手札{n_needed}枚捨て ({attacker.card.name})")
        attacker.rested = True
        if state.effects_overlay:
            from .effects import trigger_on_attack, trigger_on_opp_attack, trigger_on_opp_attack_on_chara
            trigger_on_attack(state, me, opp, attacker, state.effects_overlay)
            trigger_on_opp_attack(state, opp, me, attacker, state.effects_overlay)
            # defender=キャラ 限定の opp_attack
            trigger_on_opp_attack_on_chara(state, opp, me, attacker, state.effects_overlay)
        # 対象消失チェック: trigger_on_attack/opp_attack が target を KO してしまうケースに対応 (= 空打ち)
        target = next(
            (c for c in opp.characters if c.instance_id == action.target_iid),
            None,
        )
        if target is None:
            state.push_log(
                f"  対象消失: 攻撃時効果で iid={action.target_iid} は既に場にない (空打ち)"
            )
            _reset_battle_buffs(state)
            return

        actual_target: InPlay = target
        if action.blocker_iid is not None:
            blocker = next(
                (c for c in opp.characters if c.instance_id == action.blocker_iid),
                None,
            )
            if blocker is None:
                state.push_log(
                    f"  ブロッカー消失: iid={action.blocker_iid} は既に場にない (ブロッカー無効)"
                )
            elif (
                blocker.rested
                or not blocker.is_blocker_now
                or blocker.summoning_sickness
            ):
                # 不正ブロッカーは無視 (KO してきた可能性等)
                state.push_log(
                    f"  ブロッカー無効: {blocker.card.name} (rested/sickness/blocker特性なし)"
                )
                blocker = None
            if blocker is not None:
                blocker.rested = True
                actual_target = blocker
                state.push_log(f"  blocker: {blocker.card.name}")
                # 10-2-15-1: 【ブロック時】効果発動
                if state.effects_overlay:
                    from .effects import trigger_on_block
                    trigger_on_block(state, opp, me, blocker, state.effects_overlay)

        # === Pre-counter snapshot ===
        atk_power = attacker.power
        base_defender_power = actual_target.power
        target_kind = "blocker" if action.blocker_iid is not None else "character"
        state.pending_event = {
            "type": "attack",
            "attacker_iid": attacker.instance_id,
            "target_iid": actual_target.instance_id,
            "target_kind": target_kind,
            "atk_power": atk_power,
            "defender_power": base_defender_power,
        }
        state.push_log(
            f"atk: {attacker.card.name}(P={atk_power}) -> "
            f"{actual_target.card.name}(P={base_defender_power})"
        )
        # === Counter フェイズ ===
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        counter_added = _spend_counters(opp, action.counter_card_idxs)
        defender_power = base_defender_power + counter_added
        # === Post-counter snapshot ===
        if counter_added > 0:
            state.pending_event = {
                "type": "attack",
                "attacker_iid": attacker.instance_id,
                "target_iid": actual_target.instance_id,
                "target_kind": target_kind,
                "atk_power": atk_power,
                "defender_power": defender_power,
            }
            state.push_log(
                f"  counter +{counter_added} → "
                f"{actual_target.card.name}(P={defender_power})"
            )
        if atk_power >= defender_power:
            if actual_target.ko_immune_until_turn_end:
                state.push_log(f"  KO 耐性: {actual_target.card.name} は KO されない")
            elif _battle_ko_immune_by_attribute(actual_target, attacker):
                state.push_log(
                    f"  バトル KO 耐性 (属性): {actual_target.card.name} は"
                    f" 属性({attacker.card.attribute}) との バトルで KO されない"
                )
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
                        from .effects import (
                            trigger_on_ko,
                            trigger_on_opp_chara_ko,
                            trigger_on_self_chara_ko,
                        )
                        trigger_on_ko(state, opp, me, actual_target.card, state.effects_overlay)
                        trigger_on_opp_chara_ko(state, me, opp, state.effects_overlay)
                        trigger_on_self_chara_ko(state, opp, me, state.effects_overlay)
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
