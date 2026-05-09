# -*- coding: utf-8 -*-
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


class Phase(Enum):
    REFRESH = auto()
    DRAW = auto()
    DON = auto()
    MAIN = auto()
    END = auto()


class Category(Enum):
    LEADER = "LEADER"
    CHARACTER = "CHARACTER"
    EVENT = "EVENT"
    STAGE = "STAGE"


@dataclass(frozen=True)
class CardDef:
    card_id: str
    name: str
    category: Category
    color: tuple = ()
    cost: int = 0
    life: int = 0
    power: int = 0
    counter: int = 0
    attribute: str = ""
    block_icon: int = 0
    features: tuple = ()
    text: str = ""
    trigger: str = ""
    rarity: str = ""

    @classmethod
    def from_db_row(cls, row):
        def _to_int(v):
            if v is None or v == "" or v == "-":
                return 0
            try:
                return int(str(v).replace(",", ""))
            except ValueError:
                return 0

        color_raw = row.get("color") or ""
        colors = tuple(c.strip() for c in color_raw.split("/") if c.strip())
        features_raw = row.get("features") or ""
        features = tuple(f.strip() for f in features_raw.split("/") if f.strip())

        category_str = (row.get("category") or "CHARACTER").upper()
        try:
            category = Category(category_str)
        except ValueError:
            category = Category.CHARACTER

        return cls(
            card_id=row["card_id"],
            name=row.get("name", ""),
            category=category,
            color=colors,
            cost=_to_int(row.get("cost")),
            life=_to_int(row.get("life")),
            power=_to_int(row.get("power")),
            counter=_to_int(row.get("counter")),
            attribute=row.get("attribute") or "",
            block_icon=_to_int(row.get("block_icon")),
            features=features,
            text=row.get("text") or "",
            trigger=row.get("trigger") or "",
            rarity=row.get("rarity") or "",
        )

    def has_keyword(self, keyword):
        return f"[{keyword}]" in self.text or "【" + keyword + "】" in self.text

    @property
    def is_blocker(self):
        return self.has_keyword("ブロッカー")

    @property
    def is_rush(self):
        return self.has_keyword("スピード") or self.has_keyword("速攻")

    @property
    def is_double_attack(self):
        """【ダブルアタック】: アタックでリーダーライフに与えるダメージが 1→2"""
        return self.has_keyword("ダブルアタック")

    @property
    def is_banish(self):
        """【バニッシュ】: リーダーライフにダメージを与えた場合、ライフはトラッシュへ (トリガー発動せず)"""
        return self.has_keyword("バニッシュ")

    @property
    def has_no_block(self):
        """【ブロック不可】: このカードのアタック中、相手は【ブロッカー】を発動できない"""
        return self.has_keyword("ブロック不可")


_iid = itertools.count(1)


def _new_iid():
    return next(_iid)


@dataclass
class InPlay:
    instance_id: int
    card: CardDef
    rested: bool = False
    attached_dons: int = 0
    summoning_sickness: bool = True
    counters_used_this_battle: int = 0
    # 常在効果 (on_attached_don 等) による加算。evaluate_static_effects で毎回再計算
    static_buff: int = 0
    # ターン中限定 (activate_main の power_pump duration:turn)。Phase.END でリセット
    turn_buff: int = 0
    # 動的に付与されるキーワード (effect 由来)。Phase.END でクリア
    granted_keywords: set = field(default_factory=set)
    # ターン中 KO 耐性 (prevent_ko で True)。Phase.END でクリア
    ko_immune_until_turn_end: bool = False
    # ターン中アタック不可 (set_cannot_attack で True)。Phase.END でクリア
    cannot_attack_until_turn_end: bool = False
    # 次のリフレッシュフェイズでアクティブにならない (stay_rested_next_refresh)
    # 該当プレイヤーのリフレッシュ時に消費 (rested 維持してフラグクリア)
    stay_rested_next_refresh: bool = False
    # 静的 KO 耐性 (on_attached_don 等の常在条件で True)。
    # evaluate_static_effects で毎回 False に戻されてから再計算される
    static_ko_immune: bool = False
    # 「元々のパワー」を上書き (None なら CardDef.power を使う)。
    # 静的効果でセット (on_attached_don)、evaluate_static_effects でリセット
    base_power_override: Optional[int] = None
    # 「元々のコスト」を上書き (None なら CardDef.cost を使う)
    base_cost_override: Optional[int] = None
    # 「相手はこのキャラ以外にアタックできない」常在 (taunt)。
    # 静的効果でセット、evaluate_static_effects でリセット
    attack_taunt: bool = False

    def has_keyword_active(self, keyword: str) -> bool:
        """カードの基本キーワード or 動的に付与されたキーワードを保有するか。"""
        return self.card.has_keyword(keyword) or keyword in self.granted_keywords

    @property
    def is_blocker_now(self):
        return self.card.is_blocker or "ブロッカー" in self.granted_keywords

    @property
    def is_rush_now(self):
        return self.card.is_rush or "速攻" in self.granted_keywords

    @property
    def is_double_attack_now(self):
        return self.card.is_double_attack or "ダブルアタック" in self.granted_keywords

    @property
    def is_banish_now(self):
        return self.card.is_banish or "バニッシュ" in self.granted_keywords

    @property
    def has_no_block_now(self):
        return self.card.has_no_block or "ブロック不可" in self.granted_keywords

    @property
    def base_power(self) -> int:
        """元々のパワー (override があればそちら)。「元々のパワー X 以下」判定に使う。"""
        return self.base_power_override if self.base_power_override is not None else self.card.power

    @property
    def base_cost(self) -> int:
        """元々のコスト (override があればそちら)。"""
        return self.base_cost_override if self.base_cost_override is not None else self.card.cost

    @property
    def power(self):
        base = self.base_power
        return base + 1000 * self.attached_dons + self.static_buff + self.turn_buff

    @classmethod
    def of(cls, card, rested=False, sickness=False):
        return cls(
            instance_id=_new_iid(),
            card=card,
            rested=rested,
            summoning_sickness=sickness,
        )


@dataclass
class Player:
    name: str
    leader: InPlay
    deck: list = field(default_factory=list)
    hand: list = field(default_factory=list)
    characters: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    trash: list = field(default_factory=list)
    life: list = field(default_factory=list)
    don_active: int = 0
    don_rested: int = 0
    don_remaining_in_deck: int = 10
    # ターン中、次にプレイするキャラ/イベントのコスト軽減 (累積)。Phase.END でリセット
    play_cost_reduction: int = 0

    MAX_CHARACTERS = 5
    MAX_STAGES = 1     # 公式 3-8-5
    # One Piece TCG には手札上限なし (公式ルール 3-4 参照)。MTG ルールが混入していたバグ。

    @property
    def total_don(self):
        return self.don_active + self.don_rested

    def shuffle_deck(self, rng):
        rng.shuffle(self.deck)

    def draw(self, n=1):
        drawn = []
        for _ in range(n):
            if not self.deck:
                break
            drawn.append(self.deck.pop(0))
        self.hand.extend(drawn)
        return drawn

    def field_count(self):
        return len(self.characters)

    def can_play_character(self):
        return self.field_count() < self.MAX_CHARACTERS


@dataclass
class GameState:
    players: list
    turn_player_idx: int = 0
    turn_number: int = 1
    phase: Phase = Phase.REFRESH
    rng: random.Random = field(default_factory=random.Random)
    log: list = field(default_factory=list)
    winner: Optional[int] = None
    game_over: bool = False
    effects_overlay: dict = field(default_factory=dict)

    @property
    def turn_player(self):
        return self.players[self.turn_player_idx]

    @property
    def opponent(self):
        return self.players[1 - self.turn_player_idx]

    def opponent_of(self, player):
        return self.players[1 - self.players.index(player)]

    def player_idx(self, player):
        return self.players.index(player)

    def push_log(self, msg):
        self.log.append(f"T{self.turn_number} P{self.turn_player_idx}: {msg}")

    def declare_winner(self, winner_idx, reason):
        if self.game_over:
            return
        self.winner = winner_idx
        self.game_over = True
        self.push_log(f"GAME OVER (winner={winner_idx}): {reason}")
