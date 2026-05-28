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
    do_mulligan_and_finalize: bool = True,
) -> GameState:
    """試合 初期化。

    do_mulligan_and_finalize=False で 「5 枚 draw 段階」 で 一旦 停止、 マリガン適用 +
    ライフ配布 + game_start 効果 は 行わない。 呼び出し側 が finalize_setup_after_mulligan
    で 後段 を 実行 する 用 (= human session で user マリガン 選択 modal を 挿入)。
    """
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

    # deck slug + archetype を state に記録 (= eval.py が archetype 別重みを load 用)。
    # first_player に従って 並び順を合わせる。
    if first_player == 0:
        decks_in_order = [deck1, deck2]
        analyses_in_order = [deck1_analysis, deck2_analysis]
    else:
        decks_in_order = [deck2, deck1]
        analyses_in_order = [deck2_analysis, deck1_analysis]
    for idx, (dk, ana) in enumerate(zip(decks_in_order, analyses_in_order)):
        state.deck_slugs[idx] = getattr(dk, "slug", "") or ""
        if ana and isinstance(ana, dict):
            state.archetypes[idx] = ana.get("archetype", "") or ""
            # Plan Step 1: ai_hint_signals から leader 固有効果 flag を抽出して state に登録。
            # eval.py の interaction features が参照する。
            flags: dict = {}
            for sig in ana.get("ai_hint_signals", []) or []:
                t = sig.get("type", "")
                if t.startswith("have_"):
                    flags[t] = bool(sig.get("value", False))
            state.deck_flags[idx] = flags
    # 各プレイヤーに analysis を割り当て (= マリガン判定で使う)。
    # state.players の並び順は first_player に従って入れ替えてあるので、 それに合わせる。
    if first_player == 0:
        analyses = [deck1_analysis, deck2_analysis]
    else:
        analyses = [deck2_analysis, deck1_analysis]

    # 公式 5-2 セットアップ 順序: ライフ配置 → 手札 5 枚 → マリガン。
    # 旧 implementation は 「手札 → マリガン → ライフ」 で 逆順 だった。
    for p in state.players:
        for _ in range(p.leader.card.life):
            if p.deck:
                p.life.append(p.deck.pop(0))
    for p in state.players:
        p.draw(5)
    state._mulligan_analyses = analyses  # type: ignore[attr-defined]
    if do_mulligan_and_finalize:
        # AI vs AI 試合 用 (= 全 player AI 自動判定)、 結果 を log に 明示
        for p, a in zip(state.players, analyses):
            if _should_mulligan(p, a):
                p.deck.extend(p.hand)
                p.hand = []
                p.shuffle_deck(rng)
                p.draw(5)
                state.push_log(f"  マリガン: {p.name} (AI) 手札 引き直し")
            else:
                state.push_log(f"  マリガン: {p.name} (AI) 引き直さない (keep)")
    else:
        # マリガン skip path: state を 「pre-mulligan」 で 返す。
        # 呼び出し側 が finalize_setup_after_mulligan を 呼んで 完了 する 想定。
        state._pre_mulligan_pending = True  # type: ignore[attr-defined]
        return state

    state.push_log(
        f"start: P0={p1.leader.card.name}({p1.leader.card.life}L) "
        f"vs P1={p2.leader.card.name}({p2.leader.card.life}L)"
    )

    # リーダーの「ゲーム開始時」 効果を発火 (= OP13-079 黒イム の デッキから
    # 聖地マリージョア ステージ登場 等)。 公式: setup の最後 = ライフ配布後 ~ 1 ターン目
    # 開始前の隙間で 1 度のみ。 対応 primitive:
    # - summon_stage_from_deck_with_feature: 自デッキから 特徴 X を持つ STAGE 1 枚を
    #   登場、 デッキから除去 + 残りデッキ シャッフル。
    if effects_overlay:
        for p in state.players:
            bundle = effects_overlay.get(p.leader.card.card_id)
            if bundle is None:
                continue
            for eff in bundle.effects:
                if eff.get("when") != "game_start":
                    continue
                for prim in eff.get("do", []):
                    if not isinstance(prim, dict):
                        continue
                    feat = prim.get("summon_stage_from_deck_with_feature")
                    if not feat:
                        continue
                    # 自デッキから feat を含む特徴を持つ STAGE 1 枚を探す
                    target_idx = None
                    for i, c in enumerate(p.deck):
                        if c.category != Category.STAGE:
                            continue
                        if feat in (c.features or ""):
                            target_idx = i
                            break
                    if target_idx is not None:
                        card = p.deck.pop(target_idx)
                        ip = InPlay.of(card, rested=False, sickness=False)
                        p.stages.append(ip)
                        # search 後はデッキシャッフル (公式)
                        p.shuffle_deck(rng)
                        state.push_log(
                            f"  game_start: {p.name} ({p.leader.card.name}) "
                            f"→ ステージ登場: {card.name}"
                        )

    _recompute_static(state)
    return state


def finalize_setup_after_mulligan(
    state: GameState,
    rng: random.Random,
    effects_overlay: Optional[dict] = None,
    human_mulligan: Optional[bool] = None,
    human_player_idx: Optional[int] = None,
    human_already_processed: bool = False,
) -> None:
    """setup_game(do_mulligan_and_finalize=False) で 留めた state に マリガン適用 +
    ライフ配布 + game_start 効果 を 後段適用 して 試合 を 開始可能 状態 にする。

    human_mulligan: 人間 player の マリガン 選択 (= True 引き直し / False keep / None なら
       _should_mulligan で auto)。 None なら AI 側 と 同じ logic。
    human_player_idx: 人間 player の index (= state.players 内)。
    human_already_processed: True なら 人間 側 の マリガン は 既 適用 + log 済 と 判断 し
       finalize 内 では skip (= MulliganRedrawnModal 後 の OK で finalize 呼ぶ ケース)。
       これ が ない と 「引き直し」 後 に 続けて 「引き直さない (keep)」 が log されて 矛盾。
    """
    analyses = getattr(state, "_mulligan_analyses", [None, None])
    # マリガン適用 (= ライフ は setup_game で 既配布、 keep)
    # マリガン した か どうか を 各 player 別 で log に 明示 (= ユーザ要望)
    for idx, (p, a) in enumerate(zip(state.players, analyses)):
        actor = "人間" if idx == human_player_idx else "AI"
        # 人間 側 が 外部 (= human_session) で 既 マリガン 処理 + log 済 なら skip
        if idx == human_player_idx and human_already_processed:
            continue
        if idx == human_player_idx and human_mulligan is not None:
            do_mull = human_mulligan
        else:
            do_mull = _should_mulligan(p, a)
        if do_mull:
            p.deck.extend(p.hand)
            p.hand = []
            p.shuffle_deck(rng)
            p.draw(5)
            state.push_log(f"  マリガン: {p.name} ({actor}) 手札 引き直し")
        else:
            state.push_log(f"  マリガン: {p.name} ({actor}) 引き直さない (keep)")
    p0, p1 = state.players[0], state.players[1]
    state.push_log(
        f"start: P0={p0.leader.card.name}({p0.leader.card.life}L) "
        f"vs P1={p1.leader.card.name}({p1.leader.card.life}L)"
    )
    # リーダー game_start 効果
    if effects_overlay:
        for p in state.players:
            bundle = effects_overlay.get(p.leader.card.card_id)
            if bundle is None:
                continue
            for eff in bundle.effects:
                if eff.get("when") != "game_start":
                    continue
                for prim in eff.get("do", []):
                    if not isinstance(prim, dict):
                        continue
                    feat = prim.get("summon_stage_from_deck_with_feature")
                    if not feat:
                        continue
                    target_idx = None
                    for i, c in enumerate(p.deck):
                        if c.category != Category.STAGE:
                            continue
                        if feat in (c.features or ""):
                            target_idx = i
                            break
                    if target_idx is not None:
                        card = p.deck.pop(target_idx)
                        ip = InPlay.of(card, rested=False, sickness=False)
                        p.stages.append(ip)
                        p.shuffle_deck(rng)
                        state.push_log(
                            f"  game_start: {p.name} ({p.leader.card.name}) "
                            f"→ ステージ登場: {card.name}"
                        )
    _recompute_static(state)
    state._pre_mulligan_pending = False  # type: ignore[attr-defined]


def _should_mulligan(
    p: Player,
    deck_analysis: Optional[dict] = None,
) -> bool:
    """AI ヒューリスティックでマリガン判断。

    優先順位:
      1. deck_analysis.mulligan_keep_card_ids (= 手書き、 deck/<slug>.analysis.json)
      2. imitation prior (= db/imitation_patterns.json 大会優勝レシピ採用率、 2026-05-18 追加)
      3. fallback (= 「コスト3以下のキャラ」 が0枚ならマリガン)
    """
    if deck_analysis:
        keep_ids = set(deck_analysis.get("mulligan_keep_card_ids") or [])
        if keep_ids:
            has_key = any(c.card_id in keep_ids for c in p.hand)
            return not has_key

    # 2. imitation prior (= 大会優勝レシピ採用率) を活用
    try:
        from .imitation_prior import get_mulligan_priority
        leader_id = getattr(p.leader.card, "card_id", None)
        if leader_id:
            # 手札の mulligan keep score 合計 (= 高優先候補がいくつあるか)
            scores = [get_mulligan_priority(leader_id, c.card_id) for c in p.hand]
            # 高 score (= 0.5+ = 採用率 50%+ の mulligan candidate) が 1 枚以上で keep
            has_high_priority = any(s >= 0.5 for s in scores)
            if has_high_priority:
                return False  # keep (= 大会優勝 mulligan keep 候補がある)
    except Exception:
        pass  # imitation 失敗時は fallback へ

    # 3. fallback
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
    if defender.battle_ko_immune_static:
        return True
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
        ip.cost_minus_through_opp_turn = 0

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
            if ip.next_opp_turn_end_base_cost_override is not None:
                if (ip.next_opp_turn_end_base_cost_override_applier_idx >= 0
                        and ip.next_opp_turn_end_base_cost_override_applied_turn < state.turn_number
                        and ended_idx != ip.next_opp_turn_end_base_cost_override_applier_idx):
                    ip.next_opp_turn_end_base_cost_override = None
                    ip.next_opp_turn_end_base_cost_override_applier_idx = -1
                    ip.next_opp_turn_end_base_cost_override_applied_turn = 0
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
            # ko_per_turn_immune 補充 (= OP10-118 等、 自ターン 開始 時 1 reset)
            if me.leader.ko_per_turn_immune_max > 0:
                me.leader.ko_per_turn_immune_remaining = me.leader.ko_per_turn_immune_max
            for c in me.characters:
                if c.stay_rested_next_refresh:
                    c.stay_rested_next_refresh = False
                else:
                    c.rested = False
                me.don_active += c.attached_dons
                c.attached_dons = 0
                if c.ko_per_turn_immune_max > 0:
                    c.ko_per_turn_immune_remaining = c.ko_per_turn_immune_max
                if hasattr(c, "_act_used"):
                    delattr(c, "_act_used")
                # on_attack / opp_attack のターン1回フラグもクリア (任意 idx)
                for attr in list(c.__dict__.keys()):
                    if attr.startswith("_on_attack_used_") or attr.startswith("_opp_attack_used_"):
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
                if attr.startswith("_on_attack_used_") or attr.startswith("_opp_attack_used_"):
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
            # snapshot/animation 用に「REFRESH 完了」 を 1 log = 1 snapshot として明示。
            # 以前は無 log のまま次フェーズへ進み、 戻り DON + 未使用 DON 起き上げ +
            # 後続フェーズ (DRAW / DON deck→cost) が 全部 1 snapshot 内で同時に流れ、
            # spectate UI でアニメが重なって「何が起きたか追えない」 状態だった。
            state.push_log(
                f"refresh: untap + DON return (active={me.don_active}, rested={me.don_rested})"
            )
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
            # 1 snapshot = 1 行動 の原則: deck → hand を明示 (アニメ分離用)。
            state.push_log(f"draw: +1 → hand ({len(me.hand)})")
        state.phase = Phase.DON

    elif cur == Phase.DON:
        if state.turn_number == 1 and state.turn_player_idx == 0:
            n = 1
        else:
            n = 2
        n = min(n, me.don_remaining_in_deck)
        me.don_active += n
        me.don_remaining_in_deck -= n
        if n > 0:
            # 1 snapshot = 1 行動 の原則: DON deck → cost を attach より先に確定 snapshot。
            # これがないと、 次の MAIN 第 1 アクション (= attach 等) の snapshot 内で
            # 「DON deck → cost」 と「cost → chara attach」 が同時アニメになる。
            state.push_log(
                f"don phase: +{n} → cost (active={me.don_active})"
            )
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
        # 公式 6-6-1-1: 【自分/相手のターン終了時】の自動効果発動。
        # cost 付き optional 効果 は human owner の 場合 pending_choice を 立てて 待機。
        # 同 ターン 内 で 既に trigger 済 (= choice 解決 後 の 再 entry) なら skip。
        if state.effects_overlay and getattr(state, "_end_of_turn_done_for_turn", -1) != state.turn_number:
            from .effects import trigger_end_of_turn
            trigger_end_of_turn(state, state.effects_overlay)
            state._end_of_turn_done_for_turn = state.turn_number
        # pending_choice が 立った 場合 は phase を END で 据え置き、 user 入力 待ち。
        # resolve_pending_choice → human_session.advance_until_pause が この 関数 を 再 呼出。
        if state.pending_choice is not None:
            return
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
        # human pending_choice (= ターン終了時 任意効果 等) で 止まっている なら 抜ける
        if state.pending_choice is not None:
            return
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
                elif "in_hand_cost_plus" in prim:
                    # 公式 「手札のこのカードは ... の場合、 コスト+N」 (= EB03-042 革命軍 等)。
                    # play_cost に 加算 する 方向。 minus と 符号 逆 で 合算。
                    val = prim["in_hand_cost_plus"]
                    total -= int(val) if isinstance(val, int) else int(val.get("amount", 0))
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
            # 「レストにできない」 効果中はアタック禁止 (= 攻撃で rest 化する為、 cannot_be_rested と矛盾)
            # 公式 set_cannot_rest (OP14-033 / OP14-069 ドフラ option 2 等)
            and not me.leader.cannot_be_rested_buff
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
            # 「レストにできない」 効果中はアタック禁止 (= 攻撃で rest 化する為)
            if ch.cannot_be_rested_buff:
                continue
            if ch.summoning_sickness and not ch.is_rush_now:
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

    # Phase 2 audit hook (= env ONEPIECE_AUDIT_INVARIANTS=1 で 有効化、 default off)。
    # legal_actions の 出力 が 公式 ルール 由来 の invariant に 違反 していないか 機械的 監査。
    # 例: cannot_be_rested_buff の chara が attacker に 含まれる (= Bug 1) を catch。
    from .audit_invariants import is_audit_enabled
    if is_audit_enabled():
        from .audit_invariants import check_legal_actions_invariants, check_state_invariants
        for v in check_state_invariants(state):
            state.audit_violations.append(v.to_dict())
            state.push_log(f"  [AUDIT] {v.rule_id} sev{v.severity}: {v.message}")
        for v in check_legal_actions_invariants(state, actions):
            state.audit_violations.append(v.to_dict())
            state.push_log(f"  [AUDIT] {v.rule_id} sev{v.severity}: {v.message}")

    return actions


# --------------------------------------------------------------------------- #
# アクション適用
# --------------------------------------------------------------------------- #
def _build_action_context(state: GameState, action: Action) -> dict:
    """action 適用直前の文脈を最小情報で記録 (= 悪手/無駄行動 検出用)。

    eval delta だけでは捕まらない構造的悪手 (例: rested キャラへの attach_don)
    を post-hoc 分析できるよう、 対象 iid / target_rested / cost / 残ドン 等を残す。
    例外時は空 dict を返す (action_evals の記録自体は止めない)。
    """
    me = state.turn_player
    ctx: dict = {"don_active_before": me.don_active}

    if isinstance(action, AttachDonToCharacter):
        ch = next((c for c in me.characters if c.instance_id == action.target_iid), None)
        if ch is None:
            ctx["target_iid"] = action.target_iid
            ctx["target_missing"] = True
            return ctx
        ctx["target_iid"] = action.target_iid
        ctx["target_card_id"] = ch.card.card_id
        ctx["target_card_name"] = ch.card.name
        ctx["target_rested"] = ch.rested
        ctx["target_summoning_sickness"] = ch.summoning_sickness
        ctx["target_can_attack_now"] = (not ch.rested) and (
            (not ch.summoning_sickness) or ch.is_rush_now
        )
        ctx["target_attached_don_before"] = ch.attached_dons
        ctx["n"] = action.n
        return ctx

    if isinstance(action, AttachDonToLeader):
        ctx["target_kind"] = "leader"
        ctx["leader_rested"] = me.leader.rested
        ctx["leader_can_attack_now"] = not me.leader.rested
        ctx["leader_attached_don_before"] = me.leader.attached_dons
        ctx["n"] = action.n
        return ctx

    if isinstance(action, (AttackLeader, AttackCharacter)):
        atk = next(
            (c for c in [me.leader] + list(me.characters) if c.instance_id == action.attacker_iid),
            None,
        )
        if atk is not None:
            ctx["attacker_iid"] = action.attacker_iid
            ctx["attacker_card_id"] = atk.card.card_id
            ctx["attacker_card_name"] = atk.card.name
            ctx["attacker_power"] = atk.power
            ctx["attacker_attached_don"] = atk.attached_dons
        if isinstance(action, AttackLeader):
            ctx["target_kind"] = "leader"
        else:
            ctx["target_kind"] = "chara"
            ctx["target_iid"] = action.target_iid
        ctx["counter_card_n"] = len(action.counter_card_idxs)
        ctx["counter_event_n"] = len(action.counter_event_idxs)
        return ctx

    if isinstance(action, (PlayCharacter, PlayEvent, PlayStage)):
        if 0 <= action.hand_idx < len(me.hand):
            c = me.hand[action.hand_idx]
            ctx["card_id"] = c.card_id
            ctx["card_name"] = c.name
            ctx["cost"] = c.cost
            ctx["category"] = c.category.name if hasattr(c.category, "name") else str(c.category)
        return ctx

    if isinstance(action, ActivateMain):
        src = next(
            (c for c in [me.leader] + list(me.characters) + list(me.stages)
             if c.instance_id == action.source_iid),
            None,
        )
        if src is not None:
            ctx["source_iid"] = action.source_iid
            ctx["source_card_id"] = src.card.card_id
            ctx["source_card_name"] = src.card.name
        ctx["effect_index"] = action.effect_index
        return ctx

    if isinstance(action, EndPhase):
        # MAIN フェイズ終了時点の「未使用ドン」 = 機会損失候補
        ctx["don_remaining"] = me.don_active
        ctx["hand_size"] = len(me.hand)
        ctx["active_chara_remaining"] = sum(
            1 for c in me.characters
            if not c.rested and (not c.summoning_sickness or c.is_rush_now)
        )
        ctx["leader_unrested"] = not me.leader.rested
        return ctx

    return ctx


def apply_action(state: GameState, action: Action, ai=None) -> None:
    """action を state に適用。

    Args:
        state: GameState (= 副作用で更新される)
        action: 適用する Action
        ai: Optional[BaseAI]、 関数 15 (= 2026-05-16) hook。
            None なら後方互換挙動 (= belief 更新なし)。
            指定時、 action 後に opp action 観測 hook (= update_belief_from_action) を実行。
            plan_search.fast_clone 内では ai=None で hook skip 推奨 (= sim 中は belief 不更新)。
    """
    if state.game_over:
        return
    if state.phase != Phase.MAIN:
        raise ValueError("apply_action MAIN only")
    # AI 行動品質評価 (R62+): action 開始時の eval を記録。
    # plan_search の cloned state では record_action_evals=False で skip (= R70 高速化)。
    actor_idx = state.turn_player_idx
    eval_before = None
    action_context: Optional[dict] = None
    if getattr(state, "record_action_evals", True):
        try:
            from .eval import compute_score
            eval_before = compute_score(state, actor_idx)
        except Exception:
            pass
        try:
            action_context = _build_action_context(state, action)
        except Exception:
            action_context = None
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
        # Phase 7I: known_hand_card_ids を hand と整合性で正規化 (= 手札退場分を削除)
        for p in state.players:
            p.normalize_known_hand()
        # action 完了後の eval (actor 視点) — delta を記録
        if eval_before is not None:
            try:
                from .eval import compute_score
                eval_after = compute_score(state, actor_idx)
                entry = {
                    "turn": state.turn_number,
                    "player_idx": actor_idx,
                    "action": type(action).__name__,
                    "eval_before": eval_before,
                    "eval_after": eval_after,
                    "delta": eval_after - eval_before,
                }
                if action_context:
                    entry["context"] = action_context
                state.action_evals.append(entry)
            except Exception:
                pass

        # 関数 15 (= 2026-05-16): opp action 観測 hook
        # ai が指定 + actor が opp (= ai 視点で相手) なら inverse reasoning belief 更新
        if ai is not None:
            ai_me = getattr(ai, "me_idx", None)
            if ai_me is not None and actor_idx != ai_me:
                try:
                    # belief 4 field を持つ AI (= GreedyAI 派生) でのみ動作
                    if hasattr(ai, "opp_action_history"):
                        ai.opp_action_history.append(action)
                    if hasattr(ai, "opp_belief_pmf"):
                        from .hand_estimator import update_belief_from_action, counter_total_pmf
                        prior = ai.opp_belief_pmf or counter_total_pmf(state, actor_idx)
                        ai.opp_belief_pmf = update_belief_from_action(
                            state, opp_idx=actor_idx, opp_action=action, prior_pmf=prior,
                        )
                except Exception:
                    # hook 失敗で apply_action 全体を壊さない
                    pass


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
            elif "in_hand_cost_plus" in prim:
                val = prim["in_hand_cost_plus"]
                total -= int(val) if isinstance(val, int) else int(val.get("amount", 0))
    return total


def _apply_action_impl(state: GameState, action: Action) -> None:
    me = state.turn_player
    opp = state.opponent

    if isinstance(action, EndPhase):
        # Step 2-pre: ターン終了時の don_active 残数 = 機会損失累積
        me.dons_unused_at_end_count += me.don_active
        advance_phase(state)  # MAIN → END
        if state.pending_choice is not None or state.game_over:
            return
        advance_phase(state)  # END → REFRESH (= trigger_end_of_turn)
        if state.pending_choice is not None or state.game_over:
            return
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
        me.cards_played_count += 1
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
        me.cards_played_count += 1
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
        me.cards_played_count += 1
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
        me.dons_used_count += n
        state.push_log(f"attach don to leader x{n} (P={me.leader.power})")
        return

    if isinstance(action, AttachDonToCharacter):
        ch = _find_character(me, action.target_iid)
        n = min(action.n, me.don_active)
        me.don_active -= n
        ch.attached_dons += n
        me.dons_used_count += n
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
            # play_one_action で 既 pre-fire 済 なら skip (= 二重発火 防止)。
            # play_one_action 経由 でない 呼出 (= 直接 apply_action) では 通常通り 発火。
            opp_pre_fired = getattr(state, "_opp_attack_pre_fired_id", None) == id(attacker)
            if not opp_pre_fired:
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
                # 発火 後 は battle_buff (= 神避 等) が redirect_target に 載るので 再読。
                _fire_counter_events(state, opp, me, action.counter_event_idxs)
                counter_added = _spend_counters(opp, action.counter_card_idxs)
                defender_power = redirect_target.power + counter_added
                if defender_power != base_defender_power:
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
                            # battle KO → by_opp_effect=False (= バトル由来)
                            trigger_on_ko(
                                state, opp, me, redirect_target.card,
                                state.effects_overlay, by_opp_effect=False,
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
        # counter event (= 神避 等) は play_one_action で 事前 発火 済 の 場合 idxs 空。
        # 直接 apply_action 経由 (= テスト等) の 未発火 case も 残す。
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        # カウンターカード消費 (キャラ counter 値、_spend_counters は log なし)
        counter_added = _spend_counters(opp, action.counter_card_idxs)
        # 発火 後 は battle_buff が actual_target に 載るので 再読 (= 神避 +3000 等)。
        defender_power = actual_target.power + counter_added
        # === Post-counter snapshot: counter 加算後の defender_power ===
        if defender_power != base_defender_power:
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
                        # battle KO (blocker) → by_opp_effect=False
                        trigger_on_ko(
                            state, opp, me, actual_target.card,
                            state.effects_overlay, by_opp_effect=False,
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
                    state.push_log(f"  ライフ尽きた、残り {damage} 発目以降は空打ち")
                    break
                taken = opp.life.pop(0)
                if is_banish:
                    opp.trash.append(taken)
                    state.push_log(
                        f"  hit: {opp.name} BANISH life->trash ({taken.name})"
                    )
                    continue
                # 防御側 が 人間 + trigger 有無 を 確認 する 場合 は user 選択 待ち で 中断
                opp_idx = state.players.index(opp)
                is_human_defender = (
                    state.human_player_idx is not None
                    and opp_idx == state.human_player_idx
                )
                has_trigger = bool(
                    state.effects_overlay
                    and state.effects_overlay.get(taken.card_id)
                    and any(
                        e.get("when") == "trigger"
                        for e in state.effects_overlay[taken.card_id].effects
                    )
                )
                if is_human_defender:
                    # 残 damage 計算 (= 既 消化 + 残)
                    consumed = (damage - len(opp.life) + (
                        0 if opp.life else 0
                    ))
                    state.pending_attack_hits = {
                        "attacker_iid": attacker.instance_id,
                        "target_kind": "leader",
                        "defender_idx": opp_idx,
                        "remaining_damage": 0,  # 後段 残 hit は loop で 処理
                        "is_banish": is_banish,
                        "taken_card_id": taken.card_id,
                    }
                    # taken を 一旦 life の 0 番目 に 戻す (= resolve で 再 pop)
                    opp.life.insert(0, taken)
                    state.pending_choice = {
                        "kind": "life_taken_choice",
                        "card_id": taken.card_id,
                        "name": taken.name,
                        "has_trigger": has_trigger,
                    }
                    state.push_log(
                        f"  hit: {opp.name} ライフ受け取り 確認 待ち ({taken.name})"
                    )
                    # consumed 未使用 (= 構造 簡略)
                    _ = consumed
                    return
                # AI defender: 旧挙動
                _resolve_life_taken(state, me, opp, taken)
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
            opp_pre_fired = getattr(state, "_opp_attack_pre_fired_id", None) == id(attacker)
            if not opp_pre_fired:
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
        # counter event (= 神避 等) は play_one_action で 事前 発火 済 だが、 AI sim や
        # 直接 apply_action 経由 で 未発火 の case も 残す。 発火 後 は battle_buff が
        # actual_target に 載るので、 defender_power は actual_target.power を 再読 する。
        _fire_counter_events(state, opp, me, action.counter_event_idxs)
        counter_added = _spend_counters(opp, action.counter_card_idxs)
        defender_power = actual_target.power + counter_added
        # === Post-counter snapshot ===
        if defender_power != base_defender_power:
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
                        # battle KO → by_opp_effect=False
                        trigger_on_ko(state, opp, me, actual_target.card, state.effects_overlay, by_opp_effect=False)
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


def _resolve_life_taken(
    state: GameState,
    me: "Player",
    opp: "Player",
    taken: "CardDef",
    use_trigger: Optional[bool] = None,
) -> None:
    """1 hit 分 の life→hand / trigger 処理。

    use_trigger:
        None: 旧挙動 (= should_fire_trigger で AI 判定)
        True: user 「使う」 → fire
        False: user 「使わない」 → 手札 add のみ
    """
    fired = False
    kept_in_hand = False
    if state.effects_overlay:
        from .effects import trigger_lifecard_trigger, should_fire_trigger
        if use_trigger is None:
            auto_fire = should_fire_trigger(state, opp, taken, state.effects_overlay)
        else:
            auto_fire = use_trigger
        state.last_trigger_kept_in_hand = False
        fired = trigger_lifecard_trigger(
            state, opp, me, taken, state.effects_overlay,
            auto_fire=auto_fire,
        )
        kept_in_hand = state.last_trigger_kept_in_hand
        state.last_trigger_kept_in_hand = False
    went_to_hand: bool
    if fired and not kept_in_hand:
        opp.trash.append(taken)
        state.push_log(f"  hit: {opp.name} trigger->trash ({taken.name})")
        went_to_hand = False
    elif fired and kept_in_hand:
        opp.hand.append(taken)
        state.push_log(f"  hit: {opp.name} trigger->hand ({taken.name})")
        went_to_hand = True
    else:
        opp.hand.append(taken)
        state.push_log(f"  hit: {opp.name} life->hand ({taken.name})")
        went_to_hand = True
    if state.effects_overlay:
        from .effects import trigger_on_opp_life_taken
        trigger_on_opp_life_taken(
            state, me, opp, went_to_hand, state.effects_overlay,
        )


def resume_pending_attack_hit(state: GameState, use_trigger: bool) -> None:
    """pending_attack_hits 状態 から user 選択 を 反映 して 1 hit 解決。

    use_trigger: True = trigger 使う、 False = 使わない (= 手札 add のみ)。
    """
    pa = state.pending_attack_hits
    if pa is None:
        return
    defender_idx = pa["defender_idx"]
    opp = state.players[defender_idx]
    me = state.players[1 - defender_idx]
    if not opp.life:
        state.pending_attack_hits = None
        return
    taken = opp.life.pop(0)
    state.pending_attack_hits = None
    _resolve_life_taken(state, me, opp, taken, use_trigger=use_trigger)


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
