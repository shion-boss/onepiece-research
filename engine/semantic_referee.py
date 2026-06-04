# -*- coding: utf-8 -*-
"""SemanticReferee — 実対戦中に「効果がカードを複製/消失させていないか」 を監視する強化レフェリー。

RuleReferee (構造整合性: ドン総数 / フィールド超過 / instance 一意 / 合法手) に対し、
**メインデッキ札の保存則** を足す。 OPTCG にカードを場外へ消す領域は無く (deck/hand/trash/
life/characters/stages のいずれかに必ず居る)、 リーダーは常に 1、 ドンは別系統。 よって
各プレイヤーのメインデッキ札数は **ゲーム通して一定** (= 標準 50)。 これは数学的に常に真
なので **誤検出ゼロ**。 ズレ = カード複製/消失バグ (= シュガー複製 class) の確証。

設計方針 (= ohtsuki「バグはもう勘弁」):
- **健全な不変条件のみ** (= 保存則)。 効果ごとの期待値推定はしない → false positive を出さない。
- **read-only** (= state を一切変更しない) → 監視が対戦を壊すことが原理的に無い。
- **局所化**: 違反時に 直前 action を併記し、 どの手で壊れたかを示す。
- baseline は ゲーム開始直後 (= 最初の手の前、 既知正常状態) の実数を採用 (= 非標準デッキでも可)。

使い方: RuleReferee と同じ slot に差せる drop-in。
  ref = SemanticReferee(strict=False)
  # play_one_action(state, ai, ai, referee=ref) / HumanSession ループで after_action(state)
"""
from __future__ import annotations

from typing import Optional

from .core import GameState
from .game import Action
from .referee import RuleReferee


def main_card_count(p) -> int:
    """プレイヤー p のメインデッキ札数 (= 場外消失領域なし、 ゲーム通して一定)。
    リーダー (常に1) と ドン (別系統、 RuleReferee が検査) は除く。"""
    return (
        len(p.deck) + len(p.hand) + len(p.trash)
        + len(p.life) + len(p.characters) + len(p.stages)
    )


class SemanticReferee(RuleReferee):
    """RuleReferee + メインデッキ札 保存則。 read-only / 誤検出ゼロ。"""

    def __init__(self, strict: bool = True, log_fn=None):
        super().__init__(strict=strict, log_fn=log_fn)
        self._baseline: Optional[list[int]] = None
        self._last_action_label: str = "(初手前)"

    # baseline を 最初の before_action (= 既知正常な初期状態) で確定。
    def before_action(self, state: GameState, action: Action) -> None:
        if self._baseline is None:
            self._capture_baseline(state)
        self._last_action_label = type(action).__name__
        super().before_action(state, action)

    def after_action(self, state: GameState) -> None:
        super().after_action(state)
        self._check_card_conservation(state)

    def _capture_baseline(self, state: GameState) -> None:
        self._baseline = [main_card_count(p) for p in state.players]

    def _check_card_conservation(self, state: GameState) -> None:
        if self._baseline is None:
            # before_action を経ずに after_action された場合の保険。
            self._capture_baseline(state)
            return
        for i, p in enumerate(state.players):
            if i >= len(self._baseline):
                continue
            now = main_card_count(p)
            if now != self._baseline[i]:
                self._violate(
                    f"{p.name}: メインデッキ札 {now} != {self._baseline[i]} "
                    f"(= カード複製/消失。 直前action={self._last_action_label})"
                )
