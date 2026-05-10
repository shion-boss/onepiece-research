# -*- coding: utf-8 -*-
"""
ルール違反監視 AI (RuleReferee)
================================

AI vs AI 対戦中、各アクションの前後でルール準拠を監視する。
違反検出時:
  - strict=True (既定): RuleViolation 例外を raise してゲーム停止
  - strict=False:        違反を self.violations に記録、ログ出力のみ

監視内容:
  PRE-ACTION (アクション選択直後、適用前):
    - 選んだアクションが legal_actions に含まれているか (基底形での比較)

  POST-ACTION (アクション適用後):
    - フィールド最大 5 (3-7-6)
    - ステージ最大 1 (3-8-5)
    - DON 総数 = 期待値 (active+rested+attached+deck = 10、紫エネルは 6)
    - 数値が負ではない (DON, hand, life, deck, trash, characters, stages)
    - instance_id 重複なし
    - リーダーカードが LEADER カテゴリ
    - キャラエリアにいるカードが CHARACTER カテゴリ
    - 場のカードに紐づく付与ドンが負ではない
    - turn_player_idx が 0 / 1
    - phase が有効な enum 値
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .core import Category, GameState, Phase
from .game import (
    Action,
    AttackCharacter,
    AttackLeader,
    legal_actions,
)


class RuleViolation(Exception):
    """ルール違反検出時に raise される。strict モードで停止。"""

    pass


@dataclass
class RefereeReport:
    """RuleReferee の結果サマリ。"""

    violations: list[str] = field(default_factory=list)
    actions_checked: int = 0


class RuleReferee:
    """ルール違反監視 AI。

    使い方:
        ref = RuleReferee(strict=True)
        # play_one_action 内で ref.before_action(state, action) と
        # ref.after_action(state) を呼ぶ
    """

    def __init__(self, strict: bool = True, log_fn=None):
        self.strict = strict
        self.violations: list[str] = []
        self.actions_checked: int = 0
        # ログ関数 (None なら print 抑制)
        self._log_fn = log_fn

    def report(self) -> RefereeReport:
        return RefereeReport(
            violations=list(self.violations),
            actions_checked=self.actions_checked,
        )

    def _violate(self, msg: str) -> None:
        """違反を記録。strict なら例外を投げる。"""
        self.violations.append(msg)
        if self._log_fn:
            self._log_fn(f"[RULE VIOLATION] {msg}")
        if self.strict:
            raise RuleViolation(msg)

    # ----------------------------------------------------------------- #
    # PRE-ACTION: AI が選んだ action が合法か
    # ----------------------------------------------------------------- #
    def before_action(self, state: GameState, action: Action) -> None:
        """AI が choose_action で選んだ action を、apply_action 前に検証。

        action は AttackLeader / AttackCharacter の場合 counter_card_idxs や
        blocker_iid が上乗せされた版で渡る。基底形 (counter / blocker を空) に
        正規化してから legal_actions と比較する。
        """
        self.actions_checked += 1
        legal = legal_actions(state)
        # 基底形に正規化
        base = self._normalize(action)
        legal_bases = [self._normalize(a) for a in legal]
        if base not in legal_bases:
            self._violate(
                f"非合法アクション: {type(action).__name__} {base} "
                f"(合法手 {len(legal)} 件中に存在しない、phase={state.phase.name})"
            )

    @staticmethod
    def _normalize(action: Action) -> Action:
        """AttackLeader / AttackCharacter の counter / blocker を剥ぎ落とした基底形。"""
        if isinstance(action, AttackLeader):
            return AttackLeader(
                attacker_iid=action.attacker_iid,
                counter_card_idxs=(),
                counter_event_idxs=(),
            )
        if isinstance(action, AttackCharacter):
            return AttackCharacter(
                attacker_iid=action.attacker_iid,
                target_iid=action.target_iid,
                counter_card_idxs=(),
                counter_event_idxs=(),
                blocker_iid=None,
            )
        return action

    # ----------------------------------------------------------------- #
    # POST-ACTION: 状態の不変条件チェック
    # ----------------------------------------------------------------- #
    def after_action(self, state: GameState) -> None:
        """アクション適用後 (and フェイズ進行後) の不変条件をチェック。"""
        # turn_player_idx 範囲
        if state.turn_player_idx not in (0, 1):
            self._violate(f"turn_player_idx={state.turn_player_idx} (不正)")
            return

        # phase が enum
        if not isinstance(state.phase, Phase):
            self._violate(f"phase={state.phase} (Phase enum でない)")

        # 重複 instance_id を全プレイヤー横断で検出
        seen_iids: set[int] = set()

        for p in state.players:
            # フィールド最大 5
            if len(p.characters) > 5:
                self._violate(
                    f"{p.name}: キャラエリア超過 ({len(p.characters)} > 5)"
                )

            # ステージ最大 1
            if len(p.stages) > 1:
                self._violate(f"{p.name}: ステージ超過 ({len(p.stages)} > 1)")

            # 数値負値
            if p.don_active < 0:
                self._violate(f"{p.name}: don_active = {p.don_active} (負)")
            if p.don_rested < 0:
                self._violate(f"{p.name}: don_rested = {p.don_rested} (負)")
            if p.don_remaining_in_deck < 0:
                self._violate(
                    f"{p.name}: don_remaining_in_deck = {p.don_remaining_in_deck} (負)"
                )
            if len(p.life) < 0 or len(p.deck) < 0 or len(p.hand) < 0:
                self._violate(f"{p.name}: 領域に負数 (life/deck/hand)")
            if p.leader.attached_dons < 0:
                self._violate(f"{p.name}: leader 付与ドン負")
            for c in p.characters:
                if c.attached_dons < 0:
                    self._violate(f"{p.name}: char {c.card.name} 付与ドン負")

            # DON 総数 (active + rested + attached + deck) が初期値と一致
            attached = (
                p.leader.attached_dons
                + sum(c.attached_dons for c in p.characters)
                + sum(s.attached_dons for s in p.stages)
            )
            total_don = (
                p.don_active + p.don_rested + attached + p.don_remaining_in_deck
            )
            # 紫エネル ルール: ドンデッキ 6 枚 (overlay setup_modifier で初期化)
            expected = 6 if p.leader.card.card_id == "OP15-058" else 10
            if total_don != expected:
                self._violate(
                    f"{p.name}: DON 総数 {total_don} != {expected} "
                    f"(active={p.don_active}/rested={p.don_rested}/"
                    f"attached={attached}/deck={p.don_remaining_in_deck})"
                )

            # カテゴリ整合
            if p.leader.card.category != Category.LEADER:
                self._violate(
                    f"{p.name}: leader が LEADER でない ({p.leader.card.category})"
                )
            for c in p.characters:
                if c.card.category != Category.CHARACTER:
                    self._violate(
                        f"{p.name}: characters に非 CHARACTER ({c.card.category})"
                    )
            for s in p.stages:
                if s.card.category != Category.STAGE:
                    self._violate(
                        f"{p.name}: stages に非 STAGE ({s.card.category})"
                    )

            # instance_id 重複 (両プレイヤー横断)
            for ip in [p.leader, *p.characters, *p.stages]:
                if ip.instance_id in seen_iids:
                    self._violate(
                        f"{p.name}: 重複 instance_id={ip.instance_id} "
                        f"({ip.card.name})"
                    )
                seen_iids.add(ip.instance_id)
