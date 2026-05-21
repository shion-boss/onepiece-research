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
        # 未設定 → pause
        # blocker 候補 = defender.characters の中 で is_blocker_now かつ active な もの
        # (= 公式: ブロッカー キーワード 持ち + アクティブ + 召喚酔いなし)
        blocker_iids = [
            b.instance_id for b in defender.characters
            if b.is_blocker_now and not b.rested and not b.summoning_sickness
        ]
        # counter 候補: hand の counter 持ち + 各 idx の counter 値
        counter_idxs = []
        counter_values: dict[int, int] = {}
        for i, c in enumerate(defender.hand):
            if c.counter and c.counter > 0:
                counter_idxs.append(i)
                counter_values[i] = int(c.counter)
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
        if self.state.log:
            self.state.snapshots.append(self.state._build_snapshot(self.state.log[-1]))
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

        for _ in range(max_actions):
            if self.state.game_over:
                self.pending_kind = None
                self.pending_payload = None
                return
            # 人間 選択 待ち (= search_top_n 等) も pause 条件
            if self.state.pending_choice is not None:
                self.pending_kind = "choice"
                self.pending_payload = dict(self.state.pending_choice)
                return
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
        # マリガン pending の 場合 は 特別処理 (= setup 後段 完了 + play_until_main)
        choice = self.state.pending_choice or {}
        if choice.get("kind") == "mulligan_confirm":
            do_mulligan = bool(picks and picks[0] == 1)
            self.state.pending_choice = None
            finalize_setup_after_mulligan(
                self.state,
                rng=self.rng,
                effects_overlay=self.effects_overlay,
                human_mulligan=do_mulligan,
                human_player_idx=self.human_idx,
            )
            # snapshot 更新
            if self.state.log:
                self.state.snapshots.append(
                    self.state._build_snapshot(self.state.log[-1])
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
        self._pending_defense = (blocker_iid, tuple(counter_card_idxs))
        self.pending_kind = None
        self.pending_payload = None
        self.advance_until_pause()

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
