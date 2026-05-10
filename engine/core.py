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
    def is_rush_chara_only(self):
        """【速攻：キャラ】(公式 10-1-1 派生): 登場ターン中も相手キャラへのみアタック可能。
        is_rush とは独立。is_rush=False かつ summoning_sickness=True でも、
        この属性で「相手キャラ攻撃のみ」例外的に許可する。"""
        return self.has_keyword("速攻：キャラ") or self.has_keyword("速攻:キャラ")

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
    # 「このバトル中」期限 (公式 7-1-5-1)。AttackLeader/AttackCharacter の最後でリセット。
    # power_pump の duration:"battle" で加算される。
    battle_buff: int = 0
    # 動的に付与されるキーワード (effect 由来)。Phase.END でクリア
    granted_keywords: set = field(default_factory=set)
    # ターン中 KO 耐性 (prevent_ko で True)。Phase.END でクリア
    ko_immune_until_turn_end: bool = False
    # ターン中アタック不可 (set_cannot_attack で True)。Phase.END でクリア
    cannot_attack_until_turn_end: bool = False
    # ターン中の元々のコスト軽減 (cost_minus 効果)。Phase.END でクリア。
    # 「元々のコスト N 以下」判定にこの修正値を反映する (= cost - cost_minus_until_turn_end)
    cost_minus_until_turn_end: int = 0
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
    # 永続的な「アタックできない」フラグ (OP11-022 緑黄しらほし等のリーダー)。
    # 静的効果でセット、evaluate_static_effects でリセット。turn_end でクリアされない。
    cannot_attack_static: bool = False
    # 「自分の効果で離れない」常在 (OP14-079 黒クロコのリーダー効果で相手キャラ全員にセット)。
    # 静的効果でセット、evaluate_static_effects でリセット。
    # 相手の効果 (ko / return_to_hand) からこのキャラを除外する保護。
    protect_from_opp_effect: bool = False
    # 所有者プレイヤー idx (0 or 1)。-1 は未設定 (テスト用直接生成のデフォルト)。
    # _recompute_static / evaluate_static_effects で state.players から逆引き設定
    owner_idx: int = -1
    # 所有者のターン中か (公式 6-5-5: ドン+1000 は自分のターン中のみ有効)。
    # _recompute_static で state.turn_player_idx と owner_idx を比較して更新。
    # 直接生成された InPlay (テスト) はデフォルト True で従来通り動く。
    is_owners_turn: bool = True

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
    def is_rush_chara_only_now(self):
        """【速攻：キャラ】キャラのみアタック可能 (リーダー攻撃禁止)。
        is_rush_now とは独立 (登場ターン中の特例)。"""
        return (
            self.card.is_rush_chara_only
            or "速攻：キャラ" in self.granted_keywords
            or "速攻:キャラ" in self.granted_keywords
        )

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
        """現在の base power 値 (= override が無ければ card.power、あればその値)。
        power プロパティの計算根。「元々のパワー」判定には truly_original_power を使う。"""
        return self.base_power_override if self.base_power_override is not None else self.card.power

    @property
    def truly_original_power(self) -> int:
        """公式 4-9: 「元々のパワー」は永続効果で変更されても変わらない、CardDef オリジナル値。
        「元々のパワー X 以下」(target_power_le) 等のフィルタ判定に使う。"""
        return self.card.power

    @property
    def base_cost(self) -> int:
        """元々のコスト (override があればそちら、ターン中の cost_minus を反映)。
        「元々のコスト X 以下」判定 (KO 効果など) はこの値を使う。"""
        raw = (
            self.base_cost_override
            if self.base_cost_override is not None
            else self.card.cost
        )
        return max(0, raw - self.cost_minus_until_turn_end)

    @property
    def power(self):
        base = self.base_power
        # 公式 6-5-5: ドン+1000 は所有者のターン中のみ有効。
        # 相手ターン中は物理的に付いていてもパワーには寄与しない。
        don_buff = 1000 * self.attached_dons if self.is_owners_turn else 0
        return base + don_buff + self.static_buff + self.turn_buff + self.battle_buff

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
    # ターン中、キャラ登場を禁止するフラグ (OP14-020 緑ミホーク等のペナルティ)。Phase.END でリセット
    block_chara_play_until_turn_end: bool = False

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

    def trash_weakest_chara_for_field_full(self, state=None):
        """場 5 枚状態で新規登場時、 最弱キャラを 1 枚トラッシュへ送る (公式 3-7-6-1)。

        これは ルール処理 であり KO ではないので 【KO 時】 トリガーは発火しない (3-7-6-1-1)。
        付与ドンはレストでコストエリアに戻る (6-5-5-4 と同様)。
        選択基準: パワー低 → コスト低 (= 最弱) を自動選択 (将来 AI 判断置換可)。
        戻り値: trash したキャラ (いなければ None)。
        """
        if self.field_count() < self.MAX_CHARACTERS:
            return None
        sacrifice = min(self.characters, key=lambda ip: (ip.power, ip.card.cost))
        self.characters.remove(sacrifice)
        self.trash.append(sacrifice.card)
        if sacrifice.attached_dons > 0:
            self.don_rested += sacrifice.attached_dons
        if state is not None:
            state.push_log(
                f"  差替 (3-7-6-1): {sacrifice.card.name} をトラッシュへ "
                f"(KO ではないため【KO時】不発動)"
            )
        return sacrifice


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
    # 盤面スナップショット (UI リプレイ用)。True の時のみ push_log() 毎に記録
    record_snapshots: bool = False
    snapshots: list = field(default_factory=list)
    # 次の push_log で記録される snapshot に含めるイベント情報 (例: attack の attacker/target iid)。
    # スナップショット時に消費される (= 1 回限り)。
    pending_event: Optional[dict] = None
    # アタック対象変更フラグ (OP14-060 紫ドフラミンゴ等)。
    # opp_attack トリガー内で redirect_attack プリミティブが set。
    # AttackLeader/AttackCharacter 処理がこれを検知して対象を切替後 None にリセット。
    pending_attack_redirect: Optional[int] = None

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
        line = f"T{self.turn_number} P{self.turn_player_idx}: {msg}"
        self.log.append(line)
        if self.record_snapshots:
            self.snapshots.append(self._build_snapshot(line))

    def declare_winner(self, winner_idx, reason):
        if self.game_over:
            return
        self.winner = winner_idx
        self.game_over = True
        self.push_log(f"GAME OVER (winner={winner_idx}): {reason}")

    def _build_snapshot(self, log_line: str) -> dict:
        """現在の state をリプレイ可能な dict に直列化。push_log で都度呼ばれる。"""
        event = self.pending_event
        self.pending_event = None  # 1 回限り
        return {
            "turn": self.turn_number,
            "turn_player_idx": self.turn_player_idx,
            "phase": self.phase.name if hasattr(self.phase, "name") else str(self.phase),
            "log": log_line,
            "game_over": self.game_over,
            "winner": self.winner,
            "event": event,
            "players": [_player_snapshot(p) for p in self.players],
        }


def _inplay_snapshot(ip) -> dict:
    return {
        "instance_id": ip.instance_id,
        "card_id": ip.card.card_id,
        "name": ip.card.name,
        "rested": ip.rested,
        "attached_dons": ip.attached_dons,
        "summoning_sickness": ip.summoning_sickness,
        "power": ip.power,
        "base_power": ip.base_power,
        "keywords": sorted({
            *(["速攻"] if ip.is_rush_now else []),
            *(["ブロッカー"] if ip.is_blocker_now else []),
            *(["ダブルアタック"] if ip.is_double_attack_now else []),
            *(["バニッシュ"] if ip.is_banish_now else []),
            *(["ブロック不可"] if ip.has_no_block_now else []),
        }),
    }


def _player_snapshot(p) -> dict:
    return {
        "name": p.name,
        "leader": _inplay_snapshot(p.leader),
        "characters": [_inplay_snapshot(c) for c in p.characters],
        "stages": [_inplay_snapshot(s) for s in p.stages],
        "hand": [c.card_id for c in p.hand],
        "hand_count": len(p.hand),
        "life_count": len(p.life),
        "trash": [c.card_id for c in p.trash],
        "trash_count": len(p.trash),
        "deck_count": len(p.deck),
        "don_active": p.don_active,
        "don_rested": p.don_rested,
        "don_total": p.total_don,
        "don_remaining_in_deck": p.don_remaining_in_deck,
    }
