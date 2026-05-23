# -*- coding: utf-8 -*-
"""人間 vs AI 対戦 セッション。

人間 が action を 1 つ ずつ 選び、 AI が 自動 で 相手 ターン を 進める loop。
攻撃時 の 防御 (= ブロッカー / カウンター) も 人間 が 操作 する。

実装:
- HumanAI: choose_action / choose_defense が PauseSignal を 投げる擬似 AI。
  session が pending state を 持ち、 web 経由 で 人間 input が来たら resume。
- HumanSession: GameState + AI (= opp) + HumanAI (= self) を 保持。
  advance_until_pause() で AI 自動進行、 PauseSignal で 停止。
  apply_human_action() で 人間 input を 受けて 進行 再開。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .core import GameState, Phase
from .deck import DeckList
from .game import (
    apply_action,
    legal_actions,
    setup_game,
    finalize_setup_after_mulligan,
    play_until_main,
    AttackLeader,
    AttackCharacter,
)


class PauseSignal(Exception):
    """HumanAI が action を 求められた 時に raise。
    session.run loop が catch して 「人間 input 待ち」 状態 に 入る。
    """

    def __init__(self, kind: str, payload: dict):
        self.kind = kind  # "action" | "defense"
        self.payload = payload


@dataclass
class PendingDefense:
    """attack の defense 選択 を 人間 から 受け付ける ための pending state。"""
    attacker_iid: int
    target_iid: Optional[int]  # None = leader
    is_leader_attack: bool
    legal_blocker_iids: list[int]  # 候補
    legal_counter_card_idxs: list[int]  # hand index の counter 候補


class HumanAI:
    """人間 を 代理 する 「擬似 AI」。 choose_* で PauseSignal を 投げる。

    session.resume_with_action / resume_with_defense で human input を 注入。
    """

    def __init__(self, session: "HumanSession"):
        self.session = session

    def set_ai_opp(self, _ai_opp):
        """harness 互換 stub (= PlanningAI が plan_search 用に 相手 AI 注入する hook)"""
        pass

    def choose_action(self, state: GameState):
        # session に resume_action が 設定 されていれば それ を 返す
        if self.session._pending_action is not None:
            action = self.session._pending_action
            self.session._pending_action = None
            return action
        # 未設定 → pause
        raise PauseSignal("action", {})

    def choose_defense(self, state, attacker, target, is_leader_attack, defender):
        if self.session._pending_defense is not None:
            block_iid, counters = self.session._pending_defense
            self.session._pending_defense = None
            return block_iid, counters
        # pending_attack_redirect (= OP14-060 紫ドフラ 等 で 効果適用 済) が セット
        # されていれば 攻撃対象 を その iid に 上書き (= UI が 正しい target に 矢印 を 向ける ため)。
        redirected_iid = getattr(state, "pending_attack_redirect", None)
        if redirected_iid is not None:
            # 該当 InPlay を defender 側 から 探索 (= リーダー or キャラ)
            new_target = None
            new_is_leader = False
            if redirected_iid == defender.leader.instance_id:
                new_target = defender.leader
                new_is_leader = True
            else:
                for c in defender.characters:
                    if c.instance_id == redirected_iid:
                        new_target = c
                        new_is_leader = False
                        break
            if new_target is not None:
                target = new_target
                is_leader_attack = new_is_leader
        # 未設定 → pause
        # blocker 候補 = defender.characters の中 で is_blocker_now かつ active な もの
        # (= 公式: ブロッカー キーワード 持ち + アクティブ + 召喚酔いなし)
        # is_leader_attack が False (= キャラ 攻撃) なら blocker は 通常 不可 だが redirect 後 は
        # blocker step 不要 (= 既に target 確定)。 簡略 で blocker 候補 を 出さない。
        if is_leader_attack:
            blocker_iids = [
                b.instance_id for b in defender.characters
                if b.is_blocker_now and not b.rested and not b.summoning_sickness
                and b.instance_id != getattr(target, "instance_id", None)
            ]
        else:
            blocker_iids = [
                b.instance_id for b in defender.characters
                if b.is_blocker_now and not b.rested and not b.summoning_sickness
                and b.instance_id != getattr(target, "instance_id", None)
            ]
        # counter 候補: hand の counter 持ち + 各 idx の counter 値
        # + 【カウンター】 EVENT カード (= when:"counter" 効果あり、 DON cost 支払い可能)。
        # 公式 7-1-3-1-2: defender は アタック宣言時 に counter event を 発動 可能。
        counter_idxs = []
        counter_values: dict[int, int] = {}
        counter_event_idxs: list[int] = []
        overlay = self.session.state.effects_overlay or {}
        don_avail = defender.don_active
        for i, c in enumerate(defender.hand):
            counter_val = int(c.counter) if (c.counter and c.counter > 0) else 0
            is_counter_event = False
            # EVENT カード で when:"counter" 効果 + DON cost 払える なら counter event 候補。
            # overlay.get() は CardEffectBundle オブジェクト を 返す (= 旧 isinstance list で
            # 常 False の bug、 2026-05-23 修正)。 .effects 属性 を 走査。
            if str(getattr(c, "category", "")).endswith("EVENT"):
                eff_bundle = overlay.get(c.card_id)
                effects_list = []
                if eff_bundle is not None:
                    if hasattr(eff_bundle, "effects"):
                        effects_list = eff_bundle.effects
                    elif isinstance(eff_bundle, list):
                        effects_list = eff_bundle
                for e in effects_list:
                    if isinstance(e, dict) and e.get("when") == "counter":
                        if c.cost <= don_avail:
                            is_counter_event = True
                        break
            if counter_val > 0 or is_counter_event:
                counter_idxs.append(i)
                # counter event のみ (= 数値なし) は表示用に 0 で記録
                counter_values[i] = counter_val
                if is_counter_event:
                    counter_event_idxs.append(i)
        # 人間 defender 用 「相手のアタック時」 効果 リスト (= clickable で 発動)
        available_effects = getattr(state, "_available_opp_attack_effects", []) or []
        raise PauseSignal(
            "defense",
            {
                "attacker_iid": attacker.instance_id,
                "attacker_power": int(getattr(attacker, "power", 0) or 0),
                "target_iid": None if is_leader_attack else target.instance_id,
                "is_leader_attack": is_leader_attack,
                "legal_blocker_iids": blocker_iids,
                "legal_counter_card_idxs": counter_idxs,
                "counter_values": counter_values,
                "counter_event_idxs": counter_event_idxs,
                "available_opp_attack_effects": list(available_effects),
            },
        )


class HumanSession:
    """1 試合 の 人間 vs AI セッション。

    Args:
        deck_a: 人間 が 使う デッキ
        deck_b: AI が 使う デッキ
        ai_factory: AI constructor (= harness.run_matchup の ai_factory 互換)
        seed: 乱数 seed
        effects_overlay: 効果 overlay (= load_effect_overlay 結果)
        deck_a_analysis / deck_b_analysis: 任意の deck 分析 (= GoalDirectedAI 等で 使う)
        human_first: True なら 人間 が 先攻、 False なら AI 先攻、 None なら random
    """

    def __init__(
        self,
        deck_a: DeckList,
        deck_b: DeckList,
        ai_factory,
        seed: int = 42,
        effects_overlay: Optional[dict] = None,
        deck_a_analysis: Optional[dict] = None,
        deck_b_analysis: Optional[dict] = None,
        human_first: Optional[bool] = None,
    ):
        self.rng = random.Random(seed)
        if human_first is None:
            human_first = self.rng.random() < 0.5
        first_player = 0 if human_first else 1
        # マリガン skip path で 5 枚 draw 段階 で 一旦 停止 (= user に keep/引き直し 委ね)
        self.state = setup_game(
            deck_a if human_first else deck_b,
            deck_b if human_first else deck_a,
            rng=self.rng,
            first_player=0,  # 強制 0 で 並び 固定 (= human_first 判定 は 上で 済)
            effects_overlay=effects_overlay,
            deck1_analysis=deck_a_analysis if human_first else deck_b_analysis,
            deck2_analysis=deck_b_analysis if human_first else deck_a_analysis,
            do_mulligan_and_finalize=False,
        )
        self.state.record_snapshots = True
        # human_idx は human_first から 直接 算出 (= setup_game で first_player=0 強制)
        self.human_idx = 0 if human_first else 1
        self.ai_idx = 1 - self.human_idx
        # マリガン pending を 設定 (= user 確認 を 待つ)
        self.state.human_player_idx = self.human_idx
        me_hand = self.state.players[self.human_idx].hand
        self.state.pending_choice = {
            "kind": "mulligan_confirm",
            "cards": [
                {"card_id": c.card_id, "name": c.name} for c in me_hand
            ],
        }
        self.state.push_log(
            f"マリガン: {self.state.players[self.human_idx].name} 手札確認 (keep/引き直し)"
        )
        # frame 再生 用: 前回 payload を 返した 時点 の snapshot 数。
        # snapshot_payload で 新規 frames を 返却 → ベースライン 更新。
        self._last_seen_snapshot_count = 0
        # human_idx / ai_idx / human_player_idx は 上 で 設定済
        self.effects_overlay = effects_overlay
        # マリガン pending を 設定済 → pending_kind 設定
        self.pending_kind: Optional[str] = "choice"
        self.pending_payload: Optional[dict] = dict(self.state.pending_choice or {})
        # AI を 構築 (= ai_idx 側)。 ai_factory は (rng, deck_analysis) を 受ける
        deck_for_ai_analysis = (
            deck_b_analysis if human_first else deck_a_analysis
        )
        if callable(ai_factory):
            try:
                self.ai = ai_factory(self.rng, deck_for_ai_analysis)
            except TypeError:
                self.ai = ai_factory(self.rng)
        else:
            self.ai = ai_factory
        self.human_ai = HumanAI(self)
        # plan_search 等 が ai_opp として 相手 AI を 要する 場合 注入
        if hasattr(self.ai, "set_ai_opp"):
            self.ai.set_ai_opp(self.human_ai)
        # pending input 受け取り 用 buffer
        self._pending_action = None
        self._pending_defense: Optional[tuple] = None
        self.deck_a_slug = getattr(deck_a, "slug", None) or deck_a.name
        self.deck_b_slug = getattr(deck_b, "slug", None) or deck_b.name

    def advance_until_pause(self, max_actions: int = 200) -> None:
        """ゲーム 終了 か 人間 input 必要 まで AI を 進める。"""
        from .ai import play_one_action
        from .game import Phase, advance_phase, play_until_main
        from .effects import _maybe_prompt_end_of_turn_optional, resolve_triggers

        for _ in range(max_actions):
            if self.state.game_over:
                self.pending_kind = None
                self.pending_payload = None
                return
            # 余 イベント が キュー に 残って いる なら drain (= 任意効果 解決後 の cleanup)
            if (
                self.state.event_queue
                and not self.state.resolving
                and self.state.pending_choice is None
            ):
                resolve_triggers(self.state)
            # END phase で deferred な ターン終了任意効果 が 残って いれば modal を 立てる
            if self.state.pending_choice is None:
                _maybe_prompt_end_of_turn_optional(self.state)
            # 人間 選択 待ち (= search_top_n / end_of_turn_optional 等) は pause 条件
            if self.state.pending_choice is not None:
                self.pending_kind = "choice"
                self.pending_payload = dict(self.state.pending_choice)
                return
            # Phase.END で 止まって いる (= 任意効果 解決後 など、 phase 進行 が 必要) なら
            # advance_phase + play_until_main で 次 ターン の MAIN まで 進める。
            if self.state.phase == Phase.END:
                advance_phase(self.state)
                if self.state.pending_choice is not None or self.state.game_over:
                    continue
                play_until_main(self.state)
                continue
            tp = self.state.turn_player_idx
            try:
                if tp == self.ai_idx:
                    # AI ターン: 通常 進行 (= AI が action 選び 適用)
                    play_one_action(self.state, self.ai, self.human_ai)
                else:
                    # 人間 ターン: HumanAI が PauseSignal を 投げる
                    play_one_action(self.state, self.human_ai, self.ai)
            except PauseSignal as p:
                self.pending_kind = p.kind
                self.pending_payload = p.payload
                return
            except Exception as e:
                # engine error → ゲーム 強制 終了 (= 相手 勝利 扱い)
                self.state.declare_winner(1 - tp, f"engine error: {e}")
                self.pending_kind = None
                self.pending_payload = None
                return
        # max_actions に 到達
        self.state.declare_winner(-1, "max_actions reached")
        self.pending_kind = None
        self.pending_payload = None

    def apply_human_choice(self, picks: list[int]) -> None:
        """人間 の interactive 選択 (= search_top_n 等) を 適用 → 進行 再開。"""
        if self.pending_kind != "choice":
            raise ValueError("not waiting for human choice")
        # マリガン pending 系 は 特別処理
        choice = self.state.pending_choice or {}
        if choice.get("kind") == "mulligan_confirm":
            do_mulligan = bool(picks and picks[0] == 1)
            self.state.pending_choice = None
            if do_mulligan:
                # 「引き直し」 → 手札 戻し + 新 5 枚 ドロー のみ。 user に 新手札 確認 modal
                # を 立てる (= finalize は OK 後)。
                me = self.state.players[self.human_idx]
                me.deck.extend(me.hand)
                me.hand = []
                me.shuffle_deck(self.rng)
                me.draw(5)
                self.state.push_log(
                    f"  マリガン: {me.name} (人間) 手札 引き直し"
                )
                self.state.pending_choice = {
                    "kind": "mulligan_redrawn",
                    "cards": [
                        {"card_id": c.card_id, "name": c.name} for c in me.hand
                    ],
                }
                self.pending_kind = "choice"
                self.pending_payload = dict(self.state.pending_choice)
                return
            # keep: finalize 直接
            finalize_setup_after_mulligan(
                self.state,
                rng=self.rng,
                effects_overlay=self.effects_overlay,
                human_mulligan=False,
                human_player_idx=self.human_idx,
            )
            play_until_main(self.state)
            self.pending_kind = None
            self.pending_payload = None
            self.advance_until_pause()
            return
        if choice.get("kind") == "mulligan_redrawn":
            # 新手札 OK → finalize (= ライフ配布 既済 + AI 側 mulligan + game_start)
            self.state.pending_choice = None
            # 既 マリガン適用 済 なので human_mulligan=False で finalize 呼び (= もう 2 回目
            # 引き直し しない、 AI 側 のみ _should_mulligan で 判定)
            finalize_setup_after_mulligan(
                self.state,
                rng=self.rng,
                effects_overlay=self.effects_overlay,
                human_mulligan=False,
                human_player_idx=self.human_idx,
            )
            play_until_main(self.state)
            self.pending_kind = None
            self.pending_payload = None
            self.advance_until_pause()
            return
        from .effects import resolve_pending_choice
        resolve_pending_choice(self.state, picks)
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

    def legal_actions_for_human(self) -> list[dict]:
        """人間 ターン中 の legal actions を JSON-able dict 群 で 返す。"""
        if self.pending_kind != "action":
            return []
        actions = legal_actions(self.state)
        return [_action_to_dict(a, i) for i, a in enumerate(actions)]

    def apply_human_action(self, action_idx: int) -> None:
        """legal_actions の index を 指定 して 人間 action を 適用。 進行 を 再開。"""
        if self.pending_kind != "action":
            raise ValueError("not waiting for human action")
        actions = legal_actions(self.state)
        if not (0 <= action_idx < len(actions)):
            raise ValueError(f"action_idx {action_idx} out of range (0..{len(actions)-1})")
        self._pending_action = actions[action_idx]
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

    def apply_human_defense(
        self,
        blocker_iid: Optional[int],
        counter_card_idxs: list[int],
    ) -> None:
        """人間 防御 (= ブロッカー + カウンター 選択) を 適用。"""
        if self.pending_kind != "defense":
            raise ValueError("not waiting for human defense")
        # available_opp_attack_effects は defense 確定 で クリア (= 次 attack 用)
        if hasattr(self.state, "_available_opp_attack_effects"):
            self.state._available_opp_attack_effects = []
        self._pending_defense = (blocker_iid, tuple(counter_card_idxs))
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

    def apply_human_use_opp_attack_effect(
        self, source_iid: int, effect_idx: int
    ) -> None:
        """防御 pending 中、 場 の カード を クリック して 【相手のアタック時】 効果 を 発動。
        cost (DON / 手札) を 支払い + 効果 fire → 更新 された defense payload で 再 pause。
        """
        if self.pending_kind != "defense":
            raise ValueError("not waiting for human defense")
        # available list から 該当 effect を 取得
        avail = getattr(self.state, "_available_opp_attack_effects", []) or []
        match = None
        for e in avail:
            if e.get("source_iid") == source_iid and e.get("effect_idx") == effect_idx:
                match = e
                break
        if match is None:
            raise ValueError(f"effect not in available list: source={source_iid} idx={effect_idx}")
        # cost 支払い + enqueue
        defender_idx = self.human_idx
        defender = self.state.players[defender_idx]
        source = None
        for ip in [defender.leader, *defender.characters, *defender.stages]:
            if ip.instance_id == source_iid:
                source = ip
                break
        if source is None:
            raise ValueError(f"source iid not found: {source_iid}")
        pay_don = int(match.get("pay_don", 0))
        rest_don = int(match.get("rest_self_don", 0))
        discard_n = int(match.get("discard_hand", 0))
        if pay_don > 0:
            # ドン!!-N: don_active から N 枚 を don_remaining_in_deck に 戻す
            taken = min(pay_don, defender.don_active)
            defender.don_active -= taken
            defender.don_remaining_in_deck += taken
            rest_more = min(pay_don - taken, defender.don_rested)
            defender.don_rested -= rest_more
            defender.don_remaining_in_deck += rest_more
        if rest_don > 0:
            defender.don_active -= rest_don
            defender.don_rested += rest_don
        if discard_n > 0:
            for _ in range(min(discard_n, len(defender.hand))):
                i = self.rng.randrange(len(defender.hand))
                defender.trash.append(defender.hand.pop(i))
        bundle = self.state.effects_overlay.get(source.card.card_id) if self.state.effects_overlay else None
        if bundle is None:
            return
        eff = bundle.effects[effect_idx] if 0 <= effect_idx < len(bundle.effects) else None
        if eff is None:
            return
        cost = eff.get("cost") or {}
        if cost.get("once_per_turn"):
            setattr(source, f"_opp_attack_used_{effect_idx}", True)
        when_key = str(match.get("when_key") or "opp_attack")
        from .effects import enqueue_event, resolve_triggers
        enqueue_event(
            self.state,
            when=when_key,
            owner_idx=defender_idx,
            source_card_id=source.card.card_id,
            source_iid=source.instance_id,
            payload={"effect_indexes": [effect_idx]},
        )
        prev_forced = getattr(self.state, "forced_human_actor_idx", None)
        self.state.forced_human_actor_idx = defender_idx
        try:
            resolve_triggers(self.state)
        finally:
            self.state.forced_human_actor_idx = prev_forced
        # available list から 消費 済 を 除外
        self.state._available_opp_attack_effects = [
            e for e in avail
            if not (e.get("source_iid") == source_iid and e.get("effect_idx") == effect_idx)
        ]
        # 効果 解決中 に target_pick 等 の pending_choice が 立った場合 (= OP14-060
        # ドフラ の 「リーダー or ドンキホーテ海賊団 キャラ」 選択 等) は そちら を
        # 優先 表示。 user 解決 後 advance_until_pause で defense に 戻る。
        if self.state.pending_choice is not None:
            self.pending_kind = "choice"
            self.pending_payload = dict(self.state.pending_choice)
            return
        # defense payload を 更新: attacker_power が 変動 した 可能性 があるので 再構築
        if self.pending_payload is not None:
            attacker_iid = self.pending_payload.get("attacker_iid")
            # 最新 power を 反映
            for ip in [*self.state.players[1 - defender_idx].characters, self.state.players[1 - defender_idx].leader]:
                if ip.instance_id == attacker_iid:
                    self.pending_payload["attacker_power"] = int(getattr(ip, "power", 0) or 0)
                    break
            self.pending_payload["available_opp_attack_effects"] = list(self.state._available_opp_attack_effects)

    def serialize_for_log(self) -> dict:
        """試合終了後 の full データ を 1 dict に まとめる (= Blob upload 用)。

        含むもの:
        - metadata: timestamp / deck slugs / seed / human_first / winner / turns
        - log: 全 push_log
        - snapshots: 全 snapshot (= 中間 state、 frontend 再生 と同じ)
        - action_evals: 全 action の eval_before/after/delta (= 人間 + AI 両方、
          player_idx で 分離可能。 「AI 悪手」 + 「人間 良手」 両方の 解析素材)
        - winner_for_human: 1=人間勝利、 0=AI勝利、 -1=引き分け/時間切れ

        Raises:
            ValueError: game_over=False の場合
        """
        if not self.state.game_over:
            raise ValueError("serialize_for_log は 試合終了後のみ呼び出せます")

        from datetime import datetime, timezone

        winner_for_human = -1
        if self.state.winner == self.human_idx:
            winner_for_human = 1
        elif self.state.winner == self.ai_idx:
            winner_for_human = 0

        ai_class_name = type(self.ai).__name__
        ai_spec_version = getattr(self.ai, "spec_version", None)

        return {
            "schema_version": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "deck_human_slug": self.deck_a_slug,
                "deck_ai_slug": self.deck_b_slug,
                "human_idx": self.human_idx,
                "ai_idx": self.ai_idx,
                "human_first": (self.human_idx == 0),
                "seed": getattr(self.rng, "_seed_for_log", None),
                "ai_class": ai_class_name,
                "ai_spec_version": ai_spec_version,
            },
            "result": {
                "winner_idx": self.state.winner,
                "winner_for_human": winner_for_human,
                "turns": self.state.turn_number,
                "p_human_life_left": len(self.state.players[self.human_idx].life),
                "p_ai_life_left": len(self.state.players[self.ai_idx].life),
            },
            "log": list(self.state.log),
            "snapshots": [dict(s) for s in self.state.snapshots],
            "action_evals": list(self.state.action_evals),
        }

    def save_replay(self, max_per_pair: int = 500) -> Optional[int]:
        """試合終了後 に 棋譜 を db/match_replays.sqlite に 保存。

        Returns: replay row id (= 成功時)、 失敗 / 未完 なら None。
        """
        if not self.state.game_over:
            return None
        from .replay_recorder import save_replay

        winner_for_deck_a = -1
        if self.state.winner == self.human_idx:
            winner_for_deck_a = 0  # 人間 (deck_a) 勝利
        elif self.state.winner == self.ai_idx:
            winner_for_deck_a = 1  # AI (deck_b) 勝利

        try:
            return save_replay(
                deck_a=self.deck_a_slug,
                deck_b=self.deck_b_slug,
                game_idx=0,
                winner_for_deck_a=winner_for_deck_a,
                first_player=0 if self.human_idx == 0 else 1,
                turns=self.state.turn_number,
                log=list(self.state.log),
                snapshots=list(self.state.snapshots),
                seed=0,
                extra_meta={
                    "source": "human_vs_ai",
                    "human_idx": self.human_idx,
                    "ai_idx": self.ai_idx,
                },
                max_per_pair=max_per_pair,
            )
        except Exception:
            return None

    def _consume_new_frames(self) -> list[dict]:
        """前回 payload 返却 以降 に 追加 された snapshot を 返す + baseline 更新。

        AI ターン中 の 中間 state を frontend 側 で 順次 アニメ 再生 する 用途。
        """
        all_snaps = self.state.snapshots
        new_frames = all_snaps[self._last_seen_snapshot_count:]
        self._last_seen_snapshot_count = len(all_snaps)
        return [dict(s) for s in new_frames]

    def snapshot_payload(self) -> dict:
        """API レスポンス 用 の 全 state snapshot。"""
        # 最終 snapshot は state.snapshots 末尾 を 取る (= 既存 仕組み と整合)
        last_snap = self.state.snapshots[-1] if self.state.snapshots else None
        frames = self._consume_new_frames()
        return {
            "game_over": self.state.game_over,
            "winner": self.state.winner,
            "turn": self.state.turn_number,
            "turn_player_idx": self.state.turn_player_idx,
            "phase": (
                self.state.phase.name
                if hasattr(self.state.phase, "name")
                else str(self.state.phase)
            ),
            "human_idx": self.human_idx,
            "ai_idx": self.ai_idx,
            "pending_kind": self.pending_kind,
            "pending_payload": self.pending_payload,
            "log": list(self.state.log[-30:]),  # 直近 30 行
            "snapshot": last_snap,
            "frames": frames,
            "legal_actions": self.legal_actions_for_human(),
            "snapshots_count": len(self.state.snapshots),
            "deck_a_slug": self.deck_a_slug,
            "deck_b_slug": self.deck_b_slug,
        }


def _action_to_dict(action, idx: int) -> dict:
    """Action を JSON-able dict に。 instance_id / hand_idx 等 を 表示する形に。"""
    cls = type(action).__name__
    out = {"idx": idx, "kind": cls}
    for f in (
        "hand_idx",
        "iid",
        "instance_id",
        "attacker_iid",
        "target_iid",
        "source_iid",
        "effect_index",
        "from_idx",
        "to_iid",
        "n",
        "card_id",
    ):
        if hasattr(action, f):
            v = getattr(action, f)
            if v is not None:
                out[f] = v
    # human 用 短文 description (= UI ボタン 文言)
    out["label"] = _action_label(action)
    return out


def _action_label(action) -> str:
    cls = type(action).__name__
    if cls == "PlayCharacter":
        return f"キャラ登場: hand[{action.hand_idx}]"
    if cls == "PlayEvent":
        return f"イベント発動: hand[{action.hand_idx}]"
    if cls == "PlayStage":
        return f"ステージ設置: hand[{action.hand_idx}]"
    if cls == "AttachDonToLeader":
        return f"DON → リーダー x{getattr(action, 'n', 1)}"
    if cls == "AttachDonToCharacter":
        return f"DON → キャラ iid={action.target_iid} x{getattr(action, 'n', 1)}"
    if cls == "AttackLeader":
        return f"リーダー攻撃: attacker={action.attacker_iid}"
    if cls == "AttackCharacter":
        return f"キャラ攻撃: attacker={action.attacker_iid} → target={action.target_iid}"
    if cls == "ActivateMain":
        return f"起動メイン: iid={action.source_iid} effect[{action.effect_index}]"
    if cls == "EndPhase":
        return "ターン終了"
    if cls == "EventPlay":
        return f"イベント: hand[{getattr(action, 'hand_idx', '?')}]"
    return cls
