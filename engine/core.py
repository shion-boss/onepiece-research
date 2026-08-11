# -*- coding: utf-8 -*-
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


def normalize_card_name(s: str) -> str:
    """カード名の表記ゆれを正規化する。

    公式データには 「モンキー・Ｄ・ルフィ」 (全角Ｄ) と 「モンキー・D・ルフィ」 (半角D) が
    混在し、 効果テキスト/overlay も両形を使う。 名前一致 (= 「『X』 がいる場合」 や
    named target) は文字列完全一致なので、 全角Ｄ↔半角D を揃えないと silent no-op になる。
    エンジン内では半角D を正準形とする (= CardDef.name と overlay name 参照の双方で適用)。
    """
    if not isinstance(s, str):
        return s
    return s.replace("Ｄ", "D")


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
            name=normalize_card_name(row.get("name", "")),
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

    def has_innate_keyword(self, keyword):
        """テキストに 【keyword】 が innate (常時所持) として 登場するか 判定。

        以下は 条件付き / 動的付与なので innate ではない:
        - 「場合、〜【keyword】を得る」 (= 状態 条件)
        - 「：〜【keyword】を得る」 (= 活性化/起動)
        - 直後が 「を得」「を発動」「になる」 (= 動的 grant)
        - 直後が 「を発動できない」 (= 相手キーワード disable)
        - 「【ドン‼×N】このキャラは【keyword】」 (= 静的 don 条件)

        innate と 判定する 例:
        - 「【ブロッカー】(相手のアタックの後...)」 (= 効果定義 で 説明)
        - 「【速攻】このカードは登場したターンに...」 (= 説明)
        - 文末 単独 出現
        """
        text = self.text
        if not text:
            return False
        brackets = [f"【{keyword}】", f"[{keyword}]"]
        if not any(b in text for b in brackets):
            return False
        sentences = text.replace("\n", "。").split("。")
        for s in sentences:
            for bracket in brackets:
                idx = s.find(bracket)
                if idx == -1:
                    continue
                after = s[idx + len(bracket) : idx + len(bracket) + 20]
                before = s[:idx]
                # 動的 grant / disable
                if after.startswith(("を得", "を発動", "になる", "を持つ", "を持た")):
                    continue
                # 「【ブロッカー】を発動できない」 系
                if "発動できない" in after[:10]:
                    continue
                # 条件節 内
                if "場合" in before:
                    continue
                if "：" in before or ":" in before:
                    continue
                # 【ドン‼×N】 等 の 直前 マーカー (= 静的 don 条件)
                # before の 末尾 が 】 で 終わる かつ ドン or × を 含む
                if before.endswith("】"):
                    last_bracket = before.rfind("【")
                    if last_bracket >= 0:
                        marker = before[last_bracket:]
                        if "ドン" in marker or "×" in marker or "ターン1回" in marker:
                            continue
                return True
        return False

    @property
    def is_blocker(self):
        return self.has_innate_keyword("ブロッカー")

    @property
    def is_rush(self):
        return self.has_innate_keyword("スピード") or self.has_innate_keyword("速攻")

    @property
    def is_rush_chara_only(self):
        """【速攻：キャラ】(公式 10-1-1 派生): 登場ターン中も相手キャラへのみアタック可能。
        is_rush とは独立。is_rush=False かつ summoning_sickness=True でも、
        この属性で「相手キャラ攻撃のみ」例外的に許可する。"""
        return self.has_innate_keyword("速攻：キャラ") or self.has_innate_keyword(
            "速攻:キャラ"
        )

    @property
    def is_double_attack(self):
        """【ダブルアタック】: アタックでリーダーライフに与えるダメージが 1→2"""
        return self.has_innate_keyword("ダブルアタック")

    @property
    def is_banish(self):
        """【バニッシュ】: リーダーライフにダメージを与えた場合、ライフはトラッシュへ (トリガー発動せず)"""
        return self.has_innate_keyword("バニッシュ")

    @property
    def has_no_block(self):
        """【ブロック不可】: このカードのアタック中、相手は【ブロッカー】を発動できない"""
        return self.has_innate_keyword("ブロック不可")

    def __deepcopy__(self, memo):
        # frozen=True で immutable。 sim 中 1 ゲームに 60+ 枚の card 参照が
        # fast_clone のたびに deepcopy されるとコストが膨大 (= profile で _reduce_ex__
        # 1.8M 回 / __slotnames 867k 回)。 self を返して共有参照化。
        return self


_iid = itertools.count(1)


def _new_iid():
    return next(_iid)


def reset_iid(start: int = 1) -> None:
    """instance_id カウンタを再初期化 (2026-07-29、 差分同期の決定論用)。

    ⚠ グローバルカウンタは game 間で継続採番するため、 同一 seed でも 2 回目のゲームは iid が
    offset される。 setup_game 冒頭で reset することで「同一 seed → 同一 iid 列」= 決定論を担保し、
    Python engine を Rust engine の ground truth にできる。 プロセス毎グローバルなので mp.Pool
    (worker 別プロセス) では干渉しない。 game 内では従来通り一意にインクリメント。
    """
    global _iid
    _iid = itertools.count(start)
    # 同時に plan_search._CLONE_RNG_COUNTER (fast_clone の clone RNG seed 用グローバル、 探索内 random 効果の
    # resolution を左右し AI 決定に伝播しうる) も 0 に戻す。 これも game 間で継続する offset で、 reset しないと
    # 「同一 seed でも 2 回目のゲームで clone seed がズレ→AI 決定が非決定論」 になる (= full-suite で他テストが
    # clone を回した後に determinism guard が偽陽性で落ちていた原因)。 reset_iid は差分ハーネス専用で deployed の
    # game.py/harness/api は呼ばない = 配備影響なし。 循環 import 回避のため遅延 import。
    try:
        from . import plan_search
        plan_search._CLONE_RNG_COUNTER = 0
    except Exception:
        pass


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
    # 「次の自分のターン開始時まで」 期限。 所有者の次の REFRESH 開始時 (advance_phase で
    # turn_player_idx == owner_idx 時) にリセットされる。 = ターンを 1 つ跨いで持続。
    # power_pump の duration:"next_self_turn_start" で加算される。
    next_turn_buff: int = 0
    # 動的に付与されるキーワード (event 由来 = give_keyword/give_rush 等の単発効果)。Phase.END でクリア
    granted_keywords: set = field(default_factory=set)
    # 動的付与された属性 (give_attribute、 OP15-093)。 Phase.END/refresh でクリア。
    granted_attributes: set = field(default_factory=set)
    # 静的に付与されるキーワード (on_attached_don 等の常在条件由来)。
    # evaluate_static_effects で毎回 False から再計算される。 ドンが外れれば消える。
    static_granted_keywords: set = field(default_factory=set)
    # 「次の相手ターン終了時まで」 付与されたキーワード (OP09-084 カタリーナ等)。
    # applier-tracking。 _reset_turn_buff で applier の opp ターン終了時にクリア。
    granted_keywords_through_opp_turn: set = field(default_factory=set)
    granted_keywords_through_opp_turn_applier_idx: int = -1
    granted_keywords_through_opp_turn_applied_turn: int = 0
    # 「アタックする際、 自身の手札 N 枚を捨てなければアタックできない」 (OP08-043 等)。
    # 次の相手ターン終了時までの applier-tracking 制約。 N=0 で無効。
    attack_cost_discard_hand_n: int = 0
    attack_cost_discard_hand_applier_idx: int = -1
    attack_cost_discard_hand_applied_turn: int = 0
    # 「このキャラはバトルで KO されない」 (= 効果による KO は通る)。 OP10-104 / OP10-035 等。
    # 静的効果でセット、 evaluate_static_effects でリセット。
    battle_ko_immune_static: bool = False
    # 「このターン中、バトルでKO されない」 (= turn 限定、 turn end で reset)
    battle_ko_immune_until_turn_end: bool = False
    # 「次の自分のターン開始時まで、バトルでKO されない」 (= 相手ターンを跨ぐ battle 耐性、
    # OP06-030 ドスン等)。 所有者の次の refresh (= 自ターン開始) でクリア。
    battle_ko_immune_through_opp_turn: bool = False
    # 「このキャラはリーダーとのバトルでKOされない」 (= 相手リーダーのアタックをブロックしても
    # KO されない、 OP09-025/ST08-002)。 静的効果でセット、 evaluate_static_effects でリセット。
    battle_ko_immune_vs_leader: bool = False
    # 「属性Xを持つキャラとバトルする時 パワー+N」 (ST05-010)。 {attr: amount}。 静的eval でリセット。
    battle_pump_vs_attribute: dict = field(default_factory=dict)
    # ブロッカー 効果 を 無効化 (turn 中、 OP12-051 等)。 _reset_turn_buff で False。
    blocker_disabled_until_turn_end: bool = False
    # ターン中 KO 耐性 (prevent_ko で True)。Phase.END でクリア
    ko_immune_until_turn_end: bool = False
    # 「バトルでKOされる場合、 代わりに手札1枚を捨てる」 の救済対象フラグ (EB02-030)。
    # ⚠ 効果発動時に **場にいたキャラだけ** に付与する (= その後登場したキャラは対象外)。
    #   公式 cardqa_eb_02: 「【カウンター】効果を発動した後に登場した自分のキャラは、
    #   バトルでKOされる場合に代わりに手札1枚を捨てることはできますか？」→ 「いいえ」。
    #   以前は player 単位の turn フラグで、 発動後に登場したキャラも救済していた (= 違反)。
    battle_ko_save_discard_until_turn_end: bool = False
    # ターン中アタック不可 (set_cannot_attack で True)。Phase.END でクリア
    cannot_attack_until_turn_end: bool = False
    # 「このターン終了時、 このキャラを持ち主のデッキの下に置く」 (= OP11-092 ヘルメッポ の
    # 一時登場)。 play_from_trash の return_to_deck_bottom_at_turn_end で True、
    # trigger_end_of_turn で デッキ底へ戻して消費。
    return_to_deck_bottom_at_turn_end: bool = False
    # play_from_trash で登場した時 True (= トラッシュ起源マーカー)。 trigger_on_play が
    # state.last_self_chara_played_from_trash へ反映 (= OP16-079 ヤマト「トラッシュから《ワノ国》
    # が登場した時」 の gate)。
    played_from_trash: bool = False
    # 「このターン終了時、このキャラをトラッシュに置く」 (= 自己犠牲 drawback、 OP03-005 サッチ)。
    # ターン終了 flush で me.characters → me.trash。
    trash_at_self_turn_end: bool = False
    # 「このバトル終了時、このキャラを持ち主のデッキの下に置く」 (OP02-064 等)。
    # バトル終了 flush で me.characters → me.deck (下)。
    return_to_deck_bottom_at_battle_end: bool = False
    # ターン中の元々のコスト軽減 (cost_minus 効果)。Phase.END でクリア。
    # 「元々のコスト N 以下」判定にこの修正値を反映する (= cost - cost_minus_until_turn_end)
    cost_minus_until_turn_end: int = 0
    # 次相手 end まで cost minus (= ST14-008 / ST14-016 系)
    cost_minus_through_opp_turn: int = 0
    # 次のリフレッシュフェイズでアクティブにならない (stay_rested_next_refresh)
    # 該当プレイヤーのリフレッシュ時に消費 (rested 維持してフラグクリア)
    stay_rested_next_refresh: bool = False
    # 静的 KO 耐性 (on_attached_don 等の常在条件で True)。
    # evaluate_static_effects で毎回 False に戻されてから再計算される
    static_ko_immune: bool = False
    # source-power-scoped KO 耐性 (= OP14-003 カポネ・ベッジ
    # 「相手の元々のパワー N 以下のキャラの効果でKOされない」)。
    # 値: 上限 N (= -1 で無効、 N で source.truly_original_power <= N なら KO 不発)。
    # 静的 evaluate で毎回 -1 に戻す。
    static_ko_immune_from_source_power_le: int = -1
    # 「属性Xを持たないキャラの効果でKOされない」 (OP11-005)。 "" = 無効。 source の attribute に
    # この属性が含まれない場合 効果KO を 無効化。
    static_ko_immune_from_non_attribute: str = ""
    # 「元々のパワー」を上書き (None なら CardDef.power を使う)。
    # 静的効果でセット (on_attached_don)、evaluate_static_effects でリセット
    base_power_override: Optional[int] = None
    # ⭐ 上書きが 「**元々の** パワーを◯◯にする」 効果由来か (公式 4-9-2-1 が
    #   「元々のパワーをある数値にする効果」 を明記 = 元々のパワーは効果で **書き換わる**)。
    #   素の 「パワーが◯◯になる」 (OP06-009 シュライヤ 等) は現在パワーだけを変え、
    #   「元々のパワーN以下」 のフィルタ判定には影響しない → False のまま。
    base_power_override_is_original: bool = False
    # ターン中限定の「元々のパワー」上書き (= 「このターン中、 元々のパワーが X になる」)。
    # EB01-061 Mr.2 等の power-copy 効果用。 _reset_turn_buff でクリア。
    # 静的 base_power_override より優先される (= 効果が有効な間は静的を覆い隠す)。
    turn_base_power_override: Optional[int] = None
    turn_base_power_override_is_original: bool = False
    # 「次の自分のターン開始時まで」 期限の base_power 上書き (= OP06-009 シュライヤ
    # 「このキャラは、 次の自分のターン開始時まで、 相手のリーダーと同じパワーになる」)。
    # 所有者の REFRESH 開始時 (= 次の自ターン開始時) にクリア。
    # turn_base_power_override より弱い優先 (= 「このターン中」 が同時に有効なら そちら勝ち)。
    next_turn_base_power_override: Optional[int] = None
    next_turn_base_power_override_is_original: bool = False
    # 「次の相手のターン (= エンドフェイズ) 終了時まで」 の base_power 上書き
    # (= ST26-005 モンキー・Ｄ・ルフィ 「自分のリーダーを 次の相手のエンドフェイズ終了時まで、 元々のパワー 7000 にする」)。
    # applier-tracking (= applier_idx の opp ターンが終了したら _reset_turn_buff でクリア、
    # ただし applied_turn より少なくとも 1 ターン以上経過必須)。 EB02-041 系のドン+2 と同じ仕組み。
    next_opp_turn_end_base_power_override: Optional[int] = None
    next_opp_turn_end_base_power_override_is_original: bool = False
    next_opp_turn_end_base_power_override_applier_idx: int = -1
    next_opp_turn_end_base_power_override_applied_turn: int = 0
    # 「元々のコスト」を上書き (None なら CardDef.cost を使う)
    base_cost_override: Optional[int] = None
    # 「次の相手のターン終了時まで、 コスト +N」 (EB02-041 メリー号等)。
    # applier-tracking。 _reset_turn_buff でクリア。
    next_opp_turn_end_base_cost_override: Optional[int] = None
    next_opp_turn_end_base_cost_override_applier_idx: int = -1
    next_opp_turn_end_base_cost_override_applied_turn: int = 0
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
    # 「属性 X を持つ (リーダー or キャラ) とのバトルで KO されない」 (P-052 ミホーク等)。
    # 静的効果でセット、 evaluate_static_effects でリセット。 set として複数 attribute をサポート。
    ko_immune_battle_attributes_in: set = field(default_factory=set)
    # 「属性 X を持たないキャラとのバトルで KO されない」 (P-025 スモーカー等)。
    # 同上、 negate 版。
    ko_immune_battle_attributes_not_in: set = field(default_factory=set)
    # 「次の相手のターン終了時まで」効果無効 (OP09-093 黒ひげ等)。
    # 所有者ターンの END で _reset_turn_buff がクリア (= ちょうど「次の相手ターン終了時」と一致)
    effect_disabled_through_opp_turn: bool = False
    # 「次の相手のターン終了時まで」アタック不可。同上でクリア。
    cannot_attack_through_opp_turn: bool = False
    # 「このキャラがアタックする場合、相手は【ブロッカー】を発動できない」 (ST21-003 等)。
    # Phase.END でクリア (turn-bound)。
    attacker_prevents_blocker_until_turn_end: bool = False
    # 「このキャラのアタック中、 相手はパワーN以下のキャラの【ブロッカー】を発動できない」
    # (OP01-120/OP03-002 等)。 -1 = 制約なし。 ブロッカー選択時に power<=N を除外。
    attacker_prevents_blocker_power_le: int = -1
    # 「相手の元々のコスト N 以下のキャラへアタックできない」 (OP12-020 リーダー等)。
    # -1 は無効、 0+ は cost 上限。 Phase.END でクリア。
    cannot_attack_target_cost_le_until_turn_end: int = -1
    # 「次の相手のターン終了時まで、効果で KO されない」 (OP09-033 等)。
    # 所有者ターン終了時 (= 公式「次の相手ターン終了時」と一致) にクリア。
    ko_immune_through_opp_turn: bool = False
    # 「このキャラはターンに 1 回、 相手の効果で KO されない」 (OP10-118 等)。
    # ターン毎 に 1 回 だけ 相手効果 KO を 無効化。 自ターン 開始 時 (REFRESH) に reset。
    # ko_per_turn_immune_remaining > 0 なら 相手効果 KO 試行 を 1 つ 無効化 + remaining -= 1。
    ko_per_turn_immune_remaining: int = 0
    ko_per_turn_immune_max: int = 0   # 補充 量 (= 通常 1)
    # 「次の相手のターン終了時まで、 パワー+N」 (= 自キャラ等を対象、 applier-tracking 必須)。
    # applier_idx と applied_turn を記録し、 _reset_timed_buffs で
    # 「applier 以外のターン終了 (= 1 回以上 turn_number 進行後)」 にクリア。
    # EB02-041 (麦わらの一味コスト+2) 等の自陣形式に対応。
    next_opp_turn_end_buff: int = 0
    next_opp_turn_end_applier_idx: int = -1
    next_opp_turn_end_applied_turn: int = 0
    # 「次の自分のターン終了時まで、 パワー+N」 (= ST10-016 トリガー等)。
    # applier の次の自身ターン終了時にクリア (applied_turn より後の applier 端のターン終了)。
    next_self_turn_end_buff: int = 0
    next_self_turn_end_applier_idx: int = -1
    next_self_turn_end_applied_turn: int = 0
    # 「次の相手のターン終了時まで、 レストにできない」 (= OP14-033 等の自陣防衛効果)。
    # rest primitive で flagged キャラをスキップする。
    # クリア: applier の次の相手ターン終了時 = ended_idx != applier_idx かつ
    # applied_turn < state.turn_number (= 既に 1 ターン以上経過)。
    cannot_be_rested_buff: bool = False
    cannot_be_rested_applier_idx: int = -1
    cannot_be_rested_applied_turn: int = 0
    # 常在「相手の効果でレストにされない」 (= set_cannot_be_rested_static、 OP12-021 いっぽんマツ)。
    # rest 限定の免疫 (protect_from_opp_effect と違い KO/離脱は防がない)。 recompute_static で再計算。
    static_cannot_be_rested: bool = False
    # 所有者プレイヤー idx (0 or 1)。-1 は未設定 (テスト用直接生成のデフォルト)。
    # _recompute_static / evaluate_static_effects で state.players から逆引き設定
    owner_idx: int = -1
    # 所有者のターン中か (公式 6-5-5: ドン+1000 は自分のターン中のみ有効)。
    # _recompute_static で state.turn_player_idx と owner_idx を比較して更新。
    # 直接生成された InPlay (テスト) はデフォルト True で従来通り動く。
    is_owners_turn: bool = True
    # 起動メイン (activate_main) を このターン 発動済か (once_per_turn ゲート、 公式 7-5-3)。
    # 旧来は dynamic attr (setattr/delattr) だったが、 canonical state (= Rust engine の差分同期)
    # に含めるため field 化 (2026-07-30)。 ターン開始 refresh で False に戻す。 挙動は従来と同一。
    _act_used: bool = False
    # 【アタック時】/【相手のアタック時】の once_per_turn 効果を このターン 消費した effect idx 群。
    # 旧来は dynamic attr (_on_attack_used_{idx} / _opp_attack_used_{idx}、 setattr/delattr) だったが、
    # canonical state (= Rust engine 差分同期) に含めるため単一 field 化 (2026-07-30)。 effect idx は
    # bundle 内で一意 (on_attack と opp_attack で衝突しない) ため 1 リストで両方を表現。 ソート保持で
    # digest 決定的。 ターン開始 refresh で clear。 挙動は従来と同一。
    attack_once_used: list = field(default_factory=list)

    def mark_attack_once_used(self, idx: int) -> None:
        """【アタック時】/【相手のアタック時】once_per_turn 効果 idx を消費済にする (ソート保持)。"""
        if idx not in self.attack_once_used:
            self.attack_once_used.append(idx)
            self.attack_once_used.sort()

    # field-when (on_self_life_to_hand 等) once_per_turn の canonical mirror。 _check_and_set_once_per_turn の
    # once_per_turn_used (iid-keyed=canonical 除外) を Rust が bit-match できるよう、 InPlay ごとに "{when}:{idx}"
    # で並行記録 (additive、 Python の判定は once_per_turn_used のまま)。 refresh で clear。 (2026-07-30)
    event_once_used: list = field(default_factory=list)

    def mark_event_once(self, when: str, idx: int) -> None:
        mk = f"{when}:{idx}"
        if mk not in self.event_once_used:
            self.event_once_used.append(mk)
            self.event_once_used.sort()

    def has_keyword_active(self, keyword: str) -> bool:
        """カードの基本キーワード or 動的に付与されたキーワードを保有するか。"""
        return (
            self.card.has_keyword(keyword)
            or keyword in self.granted_keywords
            or keyword in self.static_granted_keywords
            or keyword in self.granted_keywords_through_opp_turn
        )

    @property
    def is_blocker_now(self):
        return (
            self.card.is_blocker
            or "ブロッカー" in self.granted_keywords
            or "ブロッカー" in self.static_granted_keywords
            or "ブロッカー" in self.granted_keywords_through_opp_turn
        )

    @property
    def is_rush_now(self):
        return (
            self.card.is_rush
            or "速攻" in self.granted_keywords
            or "速攻" in self.static_granted_keywords
            or "速攻" in self.granted_keywords_through_opp_turn
        )

    @property
    def is_rush_chara_only_now(self):
        """【速攻：キャラ】キャラのみアタック可能 (リーダー攻撃禁止)。
        is_rush_now とは独立 (登場ターン中の特例)。"""
        return (
            self.card.is_rush_chara_only
            or "速攻：キャラ" in self.granted_keywords
            or "速攻:キャラ" in self.granted_keywords
            or "速攻：キャラ" in self.static_granted_keywords
            or "速攻:キャラ" in self.static_granted_keywords
            or "速攻：キャラ" in self.granted_keywords_through_opp_turn
            or "速攻:キャラ" in self.granted_keywords_through_opp_turn
        )

    @property
    def is_double_attack_now(self):
        return (
            self.card.is_double_attack
            or "ダブルアタック" in self.granted_keywords
            or "ダブルアタック" in self.static_granted_keywords
            or "ダブルアタック" in self.granted_keywords_through_opp_turn
        )

    @property
    def is_banish_now(self):
        return (
            self.card.is_banish
            or "バニッシュ" in self.granted_keywords
            or "バニッシュ" in self.static_granted_keywords
            or "バニッシュ" in self.granted_keywords_through_opp_turn
        )

    @property
    def has_no_block_now(self):
        return (
            self.card.has_no_block
            or "ブロック不可" in self.granted_keywords
            or "ブロック不可" in self.static_granted_keywords
            or "ブロック不可" in self.granted_keywords_through_opp_turn
        )

    @property
    def base_power(self) -> int:
        """現在の base power 値 (= override が無ければ card.power、あればその値)。
        power プロパティの計算根。「元々のパワー」判定には truly_original_power を使う。
        優先順位: turn_base_power_override (このターン中) > next_turn_base_power_override
        (次の自ターン開始時まで) > next_opp_turn_end_base_power_override (次の相手ターン
        終了時まで) > base_power_override (静的) > card.power。"""
        if self.turn_base_power_override is not None:
            return self.turn_base_power_override
        if self.next_turn_base_power_override is not None:
            return self.next_turn_base_power_override
        if self.next_opp_turn_end_base_power_override is not None:
            return self.next_opp_turn_end_base_power_override
        return self.base_power_override if self.base_power_override is not None else self.card.power

    @property
    def truly_original_power(self) -> int:
        """「元々のパワー」。 原則 CardDef の印刷値だが、 **「元々のパワーを◯◯にする」 効果**
        で書き換えられている場合はその値。

        公式 4-9-2-1: 「**元々のパワーをある数値にする効果**が複数あり、 その効果の対象と
        なるカードが同一であり、 数値が異なる場合、 数値の高い効果を適用します」
        = 元々のパワーは効果で書き換わりうる (4-9 は 「印刷値のまま不変」 とは言っていない)。
        一次情報 (cardqa_op_10 / EB01-061 Mr.2・ボン・クレー): 【アタック時】で元々のパワーが
        2000以上になった場合、 「元々のパワー2000以下をKO」 の対象に **ならない** (公式=KOされない)。

        ⚠ 素の 「パワーが◯◯になる」 (= 「元々の」 が無い、 OP06-009 シュライヤ) は現在パワー
          だけを変える。 overlay の `original` フラグで書き分ける (True の時だけここに効く)。
        ⚠ **複数の 「元々のパワーを◯◯にする」 が同じキャラに適用されている場合は 最も高い値**
          (公式 4-9-2-1 の逐語、 cardqa_st_34 / ST34-004 リンリン 「元々のパワー0にする」 ×
          他効果の 「元々のパワー6000にする」 → **6000** が適用される)。
          duration slot ごとに 1 枚しか持たないモデルなので、 **全 slot の最大値** を採る
          (優先順位で 1 つ選ぶと 後から掛けた低い値が高い値を潰す = 2026-08-11 に実測で発覚)。
        """
        vals = [
            v for v, is_orig in (
                (self.turn_base_power_override, self.turn_base_power_override_is_original),
                (self.next_turn_base_power_override,
                 self.next_turn_base_power_override_is_original),
                (self.next_opp_turn_end_base_power_override,
                 self.next_opp_turn_end_base_power_override_is_original),
                (self.base_power_override, self.base_power_override_is_original),
            )
            if v is not None and is_orig
        ]
        if vals:
            return max(vals)
        return self.card.power

    @property
    def base_cost(self) -> int:
        """元々のコスト (override があればそちら、ターン中の cost_minus を反映)。
        「元々のコスト X 以下」判定 (KO 効果など) はこの値を使う。"""
        raw = (
            self.next_opp_turn_end_base_cost_override
            if self.next_opp_turn_end_base_cost_override is not None
            else self.base_cost_override
            if self.base_cost_override is not None
            else self.card.cost
        )
        return max(0, raw - self.cost_minus_until_turn_end - self.cost_minus_through_opp_turn)

    @property
    def power(self):
        base = self.base_power
        # 公式 6-5-5: ドン+1000 は所有者のターン中のみ有効。
        # 相手ターン中は物理的に付いていてもパワーには寄与しない。
        don_buff = 1000 * self.attached_dons if self.is_owners_turn else 0
        return (
            base + don_buff + self.static_buff + self.turn_buff + self.battle_buff
            + self.next_turn_buff + self.next_opp_turn_end_buff + self.next_self_turn_end_buff
        )

    @classmethod
    def of(cls, card, rested=False, sickness=False):
        return cls(
            instance_id=_new_iid(),
            card=card,
            rested=rested,
            summoning_sickness=sickness,
        )

    def __deepcopy__(self, memo):
        # 40+ field のうち mutable は set 5 個だけ、 他は primitive (int/bool/None)。
        # 標準 deepcopy が __reduce_ex__ → _reconstruct を経由するコストを回避し、
        # __dict__ shallow copy + set.copy() で済ませる (= profile で sim 全体の
        # ~70% を占める deepcopy のうち InPlay 回路を桁レベルで削減)。
        # card (CardDef) は CardDef.__deepcopy__ で self を返すため共有 OK。
        new = InPlay.__new__(InPlay)
        new.__dict__.update(self.__dict__)
        new.granted_keywords = self.granted_keywords.copy()
        new.static_granted_keywords = self.static_granted_keywords.copy()
        new.granted_keywords_through_opp_turn = self.granted_keywords_through_opp_turn.copy()
        new.ko_immune_battle_attributes_in = self.ko_immune_battle_attributes_in.copy()
        new.ko_immune_battle_attributes_not_in = self.ko_immune_battle_attributes_not_in.copy()
        # attack_once_used は mutable list → shallow update だと参照共有で fast_clone がクロス汚染する。
        new.attack_once_used = self.attack_once_used.copy()
        new.event_once_used = self.event_once_used.copy()
        memo[id(self)] = new
        return new


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
    # ⭐ ライフ **1 枚ごと** の表向き/裏向き (= life と同じ長さ・同じ並び)。
    #   公式 (cardqa_st_13 / ST13-003 ルフィ 「ルール上、 自分の表向きのライフは手札に加わる
    #   代わりにデッキの下に置かれる」) を再現するには 「どの札が表向きか」 が要る。
    #   ⚠ 「表向きは上から N 枚」 の近似は **使えない**: ST13-012 マキノ 「自分のライフすべてを見て、
    #     好きな順番で置く」 が全体を並べ替えるため、 位置ベースのモデルが壊れる (2026-08-11)。
    life_face_up: list = field(default_factory=list)
    # ⭐ 「ルール上、 自分の表向きのライフは手札に加わる代わりにデッキの下に置かれる」
    #   (ST13-003 モンキー・D・ルフィ(L))。 静的効果なので evaluate_static_effects で毎回再計算する。
    face_up_life_to_deck_bottom: bool = False
    # Phase 7I (2026-05-14): opp に公開済の手札カード ID リスト。
    # return_to_hand / search 等で「公開してから手札に加える」 経路を経たカードが追加される。
    # 手札からの退場 (= play / counter / discard) で先頭マッチ分が削除される。
    # hand_estimator が「確定 (known) + 未知」 分離で pmf を計算する際に参照。
    known_hand_card_ids: list[str] = field(default_factory=list)
    # ⭐ 自分がデッキの底に送ったと **見て知っている** カード (2026-07-24、 ohtsuki 指摘)。
    # サーチ「上から N 枚を見て 1 枚を手札、 残りをデッキの下」 は、 選ばなかった札の
    # 内容も位置も本人には判る。 = 「当分引かない札」 が確定するので、 次に引く母集団が変わる。
    # 人間も追える情報だが数え落とす → AI は正確に追える (= 人間より正確に、 の範囲内)。
    # ⚠ デッキシャッフルで無効化される (位置が壊れるため clear する)。
    known_bottom_card_ids: list[str] = field(default_factory=list)
    # 自分がデッキの上に置いた (= 次に引くと確定している) カード。 top_or_bottom の「上」を
    # 選んだ時に入る。 引いたら pop する。 ⚠ シャッフルで無効化。
    known_top_card_ids: list[str] = field(default_factory=list)

    def add_to_hand_publicly(self, card) -> None:
        """カードを手札に公開で追加 (Phase 7I)。

        return_to_hand / search / 公開ライフ→手札 等の経路で使う。
        known_hand_card_ids に card_id を append、 hand にも追加。
        opp の hand_estimator がこのカードを「確定情報」 として扱える。
        """
        self.hand.append(card)
        self.known_hand_card_ids.append(card.card_id)

    def normalize_known_bottom(self) -> list:
        """known_bottom_card_ids を実際のデッキ内容と突き合わせて正規化し、 その list を返す。

        底に送った札はやがて引かれる (= もうデッキに無い)。 記録しっぱなしだとデッキ枚数を
        超えて膨らむ。 **現在デッキに在る分だけ**に絞る (= 引いた札は本人が知っているので
        除外できる = 公平)。 引く母集団の分母を出すのに使う。"""
        from collections import Counter
        in_deck = Counter(c.card_id for c in self.deck)
        out: list = []
        used: Counter = Counter()
        for cid in self.known_bottom_card_ids:
            if used[cid] < in_deck.get(cid, 0):
                used[cid] += 1
                out.append(cid)
        self.known_bottom_card_ids = out
        return out

    def normalize_known_top(self) -> list:
        """known_top_card_ids を実際のデッキ内容と突き合わせて正規化 (= 引いた分を除く)。"""
        from collections import Counter
        in_deck = Counter(c.card_id for c in self.deck)
        out: list = []
        used: Counter = Counter()
        for cid in self.known_top_card_ids:
            if used[cid] < in_deck.get(cid, 0):
                used[cid] += 1
                out.append(cid)
        self.known_top_card_ids = out
        return out

    def __setattr__(self, name, value):
        """`life` を **まるごと差し替え** たら表向きフラグを裏向きで張り直す。

        ⭐ 2026-08-11 の per-card 化で、 ライフは `life` と `life_face_up` の 2 本立てになった。
        構築 (setup / テスト / clone) は `p.life = [...]` と書くのが自然なので、 その場合は
        **全部裏向き** で長さを合わせる (= 公式どおり、 ライフは裏向きで置かれるのが既定)。

        ⚠ **表向きを保ったまま並べ替える** 経路 (ST13-012 マキノ 「自分のライフすべてを見て、
          好きな順番で置く」 等) は、 `life` を代入した **後に** `life_face_up` を明示代入すること。
          代入順を逆にすると ここで潰れる。
        """
        object.__setattr__(self, name, value)
        if name == "life":
            object.__setattr__(self, "life_face_up", [False] * len(value))

    @property
    def face_up_life_count(self) -> int:
        """表向きのライフ枚数 (= `life_face_up` の True の数)。

        ⚠ 2026-08-11 に **枚数だけ持つモデルから per-card フラグへ移行** した。 読み取り側
        (「表向きのライフがある場合」 条件 / 「ライフ上1枚を裏向きにできる」 cost 等) を
        無改修にするため property として残している。 **書き込みは `life_face_up` を直接操作する**。
        """
        return sum(1 for x in self.life_face_up if x)

    def life_sync_flags(self) -> None:
        """`life_face_up` の長さを `life` に揃える (不足は裏向きで埋め、 余りは切る)。

        ⚠ **通常運用で呼ぶ関数ではない**。 ライフを触る各所は `life` と `life_face_up` を
        **同じ行で対にして** 操作すること (= 片方だけ動かすと表向きが 1 枚ずれる)。
        これは `ONEPIECE_LIFE_FLAG_LAX=1` の緊急退避 (外部ツールが古い形の state を
        流し込んだ時) 専用の埋め合わせで、 既定では代わりに AssertionError を投げる。
        """
        n = len(self.life)
        if len(self.life_face_up) < n:
            self.life_face_up.extend([False] * (n - len(self.life_face_up)))
        elif len(self.life_face_up) > n:
            del self.life_face_up[n:]

    def normalize_known_hand(self) -> None:
        """known_hand_card_ids を hand との整合性で正規化 (Phase 7I)。

        hand から退場したカード分の entry を削除 (= 最初マッチ 1 件削除)。
        play / counter / discard 後に apply_action 末尾で呼び出される。
        """
        hand_counts: dict[str, int] = {}
        for c in self.hand:
            hand_counts[c.card_id] = hand_counts.get(c.card_id, 0) + 1
        new_known: list[str] = []
        used: dict[str, int] = {}
        for cid in self.known_hand_card_ids:
            if used.get(cid, 0) < hand_counts.get(cid, 0):
                new_known.append(cid)
                used[cid] = used.get(cid, 0) + 1
        self.known_hand_card_ids = new_known
    don_active: int = 0
    don_rested: int = 0
    don_remaining_in_deck: int = 10
    # ターン中、次にプレイするキャラ/イベントのコスト軽減 (累積)。Phase.END でリセット
    play_cost_reduction: int = 0
    # 静的 filter 付きコスト軽減 (= 場のキャラの常在効果)。
    # 各要素: {"filter": {...}, "amount": int}。 evaluate_static_effects で再構築。
    # OP05-097 「コスト2以上の天竜人キャラの支払うコストは1少なくなる」 等
    play_cost_reductions_filtered: list = field(default_factory=list)
    # ターン限定の filter 付き登場コスト軽減 (OP02-025 等)。 静的eval でクリアされず
    # ターン refresh でクリア。 _eff_cost に加算。
    play_cost_reductions_filtered_turn: list = field(default_factory=list)
    # ターン中、キャラ登場を禁止するフラグ (OP14-020 緑ミホーク等のペナルティ)。Phase.END でリセット
    block_chara_play_until_turn_end: bool = False
    # 「自分は、 このターン中、 リーダーにアタックできない」 (OP06-026 等)。
    # action 生成で AttackLeader を除外。 ターン開始 refresh でクリア。
    cannot_attack_leader_until_turn_end: bool = False
    # 「このターン中、 元々のコストN以上のキャラを登場できない」 (OP13-023 等)。
    # -1 = 制限なし。 PlayCharacter action 生成で card.cost >= 閾値 を除外。
    block_chara_play_cost_ge_threshold: int = -1
    # 次の相手のターン終了時 まで、 自分が play する キャラ の on_play 効果 を 無効化
    # (OP09-081 ティーチ等)。 trigger_on_play で 該当 player の フラグ 確認 → 効果 skip。
    # disable_opp_on_play_through_opp_turn = True で 設定、 設定 player の 次 ターン 開始 時 reset。
    opp_on_play_disabled_through_opp_turn: bool = False
    # ターン中、 自分の効果でカードを引くことができない (OP12-099 カルガラ等)。 Phase.END でリセット
    block_self_draw_until_turn_end: bool = False
    # 「自分は、 このターン中、 キャラの効果でドン‼をアクティブにできない」 (EB04-016 トリ /
    # OP10-030 スモーカー)。 公式はこの自己ロックで 起動メインの無限ループを防いでいる。
    block_chara_effect_untap_don_until_turn_end: bool = False
    # このターン中にライフを失ったか (P-120 「相手のライフが離れているターン中」)。 refreshでクリア。
    life_lost_this_turn: bool = False
    # 公式 (cardqa_op_12 / OP12-020 ゾロ): 「このターン中、 このリーダーが **相手のキャラと**
    # バトルしている場合」 の判定用。 リーダーがアタックし、 **実際にバトルした相手** が
    # キャラだった時のみ True (ブロッカーやアタック対象変更でリーダーとバトルしたなら False)。
    # ターン開始時 (_reset_turn_buff) に False へ戻す。
    leader_battled_opp_chara_this_turn: bool = False
    # このターン中に この player のキャラが KO された 回数 (OP16-100 氷諸斬り
    # 「このターン中、 相手のキャラがKOされている場合」 用)。 _reset_turn_buff でクリア。
    chara_ko_taken_this_turn: int = 0
    # 「デッキが0で敗北の代わりに勝利」 (OP03-040)。 leader静的でセット、 非reset。
    deck_out_wins: bool = False
    # 公式 「ルール上、 自分はデッキが0枚でも敗北せず、 デッキが0枚になったターン終了時に
    # 敗北する」 (OP15-022 ブルック リーダー)。 デッキ切れ敗北を **そのターンの終了時** へ遅延。
    deck_out_defer: bool = False
    # 「自分は、 このターン中、 自分の効果でライフを手札に加えられない」 (OP02-023 等)。
    # _reset_turn_buff で False に。 life_to_hand / life_top_or_bottom_to_hand (owner=self) が抑制される。
    prevent_self_life_to_hand_until_turn_end: bool = False
    # このターン中に 効果で 自分の手札が捨てられたか (ST33-004 ボルサリーノ
    # 「効果で自分の手札が捨てられているターン中、 コスト-3」)。 trigger_on_self_hand_discarded で
    # True、 _reset_turn_buff でクリア。 eval_condition:self_hand_discarded_by_effect_this_turn が参照。
    hand_discarded_by_effect_this_turn: bool = False
    # 「次の相手のメインフェイズ開始時に発動」 する遅延効果リスト (PRB02-005 ルフィ等)。
    # 自陣 player に登録 → 「相手の MAIN 開始時 (= 自分の opp 視点)」 に flush。
    delayed_at_opp_main_phase_start: list = field(default_factory=list)
    # 「このターン終了時に発動」 する予約効果リスト (OP15-025 クロ等)。 END phase (trigger_end_of_turn) で flush。
    # 旧来 dynamic attr だったが canonical state (= Rust engine 差分同期) に含めるため field 化 (2026-07-30)。
    scheduled_at_self_turn_end: list = field(default_factory=list)
    # 「次のリフレッシュフェイズでアクティブにならないドン数」 (OP10-033 ナミ等)。
    # REFRESH 時に この数だけ don_rested から差し引かれず残る。 適用後 0 にリセット。
    next_refresh_kept_rested_don: int = 0
    # 【ターン1回】効果の発動済みキー集合。
    # キー形式: f"{card_id}:{when}:{idx}" もしくは effect spec で指定された明示キー文字列。
    # 自分の REFRESH で全クリア (= 次の自ターンで再発動可)。
    # _execute_event が effect spec の once_per_turn を見て set / check する。
    once_per_turn_used: set = field(default_factory=set)
    # replace_ko/replace_leave の once_per_turn (card-id-keyed) を Rust が bit-match できるよう並行記録
    # (canonical、 判定は once_per_turn_used のまま = additive、 refresh で clear)。 (2026-07-30)
    replace_opt_used_cards: list = field(default_factory=list)
    # 明示キー (文字列) once_per_turn の canonical mirror。 `key:<opt>` は instance_id 非依存なので
    # そのまま digest 可 = Rust が bit-match できる。 OP13-002 の様に複数 when (KO / ライフ受け) が
    # 1 つのキーを共有する効果はこれが無いと Rust 側で追跡不能 → 全 bail していた。
    # 判定は once_per_turn_used のまま (additive)、 refresh で clear。 (2026-07-31)
    once_shared_used: list = field(default_factory=list)
    # 累積カウンタ (Phase 2 / Step 2-pre)。 outcome regression の特徴量に使う。
    # 試合開始時 0、 game.py の各 action 分岐で increment。 game_over まで保持。
    cards_drawn_count: int = 0      # Player.draw() で加算 = 累積ドロー数
    cards_played_count: int = 0     # PlayCharacter / PlayEvent / PlayStage 各分岐で +1
    # このターン中に自分が使用したイベントの最大コスト (= OP15-002 ルーシー 「コスト3以上の
    # イベントを使用していた場合」 等の per-turn 条件用)。 ターン境界 _reset_turn_buff で 0 戻し。
    max_event_cost_this_turn: int = 0
    dons_used_count: int = 0        # AttachDon 分岐で attach 数分加算 = 累積 DON 使用
    dons_unused_at_end_count: int = 0  # EndPhase 分岐で don_active 残数加算 = 累積機会損失
    # マリガン 履歴 (= 2026-05-29、 corpus 軸 用)。 setup_game で True / False が set される。
    # AI belief 推定 で 「opp が マリガン した = 初手 5 が 悪かった = 現 手札 は 二択 後」 軸 用。
    did_mulligan: bool = False
    # 手札のカウンター値を静的に上げる効果 (OP16-118 ポートガス: パワー8000キャラは counter+2000)。
    # evaluate_static_effects が場の該当カード有無で {"amount","power_eq","category"} を set/None。
    hand_counter_boost: Optional[dict] = None

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
        self.cards_drawn_count += len(drawn)
        # デッキ上に置いたと知っている札を引いたら、 その知識は消費される (= もう手札に在る)。
        # 引いた札は本人が見ているので known_hand へ移す必要はない (自分の手札は全部見える)。
        for c in drawn:
            try:
                if self.known_top_card_ids and self.known_top_card_ids[0] == c.card_id:
                    self.known_top_card_ids.pop(0)
                elif c.card_id in self.known_top_card_ids:
                    self.known_top_card_ids.remove(c.card_id)
            except Exception:
                pass
        return drawn

    def field_count(self):
        return len(self.characters)

    def can_play_character(self):
        return self.field_count() < self.MAX_CHARACTERS

    def trash_weakest_chara_for_field_full(self, state=None, owner_idx=None):
        """場 5 枚状態で新規登場時、 最弱キャラを 1 枚トラッシュへ送る (公式 3-7-6-1)。

        これは ルール処理 であり KO ではないので 【KO 時】 トリガーは発火しない (3-7-6-1-1)。
        付与ドンはレストでコストエリアに戻る (6-5-5-4 と同様)。

        ⚠ owner_idx は API 互換の ため 残すが **人間でも自動 trash する** (= 旧 2026-05-30 の
        「人間は field_full_select_trash modal で選ばせる」 defer は撤去)。 理由: この helper は
        効果召喚 (reveal_top_play / summon_from_deck / play_from_trash 等、 effects.py 19 箇所)
        専用で、 caller は trash 後に **新 chara を append + trigger_on_play を同期発火** する。
        defer すると pending_choice=field_full_select_trash を立てた直後に on_play が自身の modal
        (例: ウソ八 の rest 選択) で **それを clobber** し → trash が永久に失われ **場 6 体** に
        なる (= 2026-06-05 RuleReferee×人間 field-flood hunt が「キャラエリア超過 6>5」 で検出)。
        メイン PlayCharacter は action に sacrifice_iid を載せ trash→append→on_play 順で正しく
        人間に選ばせる (game.py) ので 人間の差替選択は そちらで保持される。

        戻り値: trash したキャラ (いなければ None)。
        """
        if self.field_count() < self.MAX_CHARACTERS:
            return None
        # 効果召喚の field-full は 自動 最 弱 trash (= 人間でも同期 trash で ≤5 を保証、 clobber 回避)
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
    # トリガー解決キュー (FIFO + ターンプレイヤー優先)。enqueue_event で push、
    # resolve_triggers でドレイン。各 trigger_* は同期で「fire するか」判断のみ行い、
    # 実際の効果実行はキューに積んで resolve_triggers が一箇所で実行する。
    event_queue: list = field(default_factory=list)
    # resolve_triggers の再入を防ぐフラグ (= ネストした enqueue 中に再ドレインしない)
    resolving: bool = False
    # 同時発火 (同 owner / 同 when グループ) の順序を AI に決めさせるフック。
    # シグネチャ: (state, events: list[TriggerEvent]) -> list[TriggerEvent]
    # None ならデフォルトで FIFO 順 (enqueue 順) を維持。
    event_order_hook: Optional[Callable] = None
    # 「このターンの後に自分のターンを追加で得る」 フラグ。 END phase で消費され、
    # turn_player_idx を切り替えずに REFRESH に戻ることで「もう 1 回ターン」 を実現。
    extra_turn_pending: bool = False
    # 人間プレイヤー対戦時、 human の player_idx を set (= HumanSession が セット)。
    # search_top_n 等の 効果 が interactive 選択 を 求める 時 に 参照。
    # None なら 全 自動 (= AI 同士、 旧挙動)。
    human_player_idx: Optional[int] = None
    # 人間プレイヤー の 選択 待ち。 search_top_n 等 で 設定 され、
    # frontend が /choice endpoint で 解消 する まで 進行 を 止める。
    # dict 形式: {"kind": "search_top_n", "cards": [...], "limit": N, ...}
    pending_choice: Optional[dict] = None
    # 「自ターン外 で actor が human の effect 発動中」 override。
    # 例: counter event を 防御中 (= AI ターン中) に 発動 する 際、 turn_player_idx は
    # AI だが、 effect の actor は defender=human。 この時 human pick を 有効化 する。
    # int = human_idx で set、 None = 通常。
    forced_human_actor_idx: Optional[int] = None
    # ライフ受け取り 確認 中断 状態 (= attack hit 中 で user 確認 待ち)。
    # {"attacker_iid", "target_kind", "target_iid", "remaining_damage",
    #  "is_banish", "defender_idx", "taken_card": CardDef, "post_hit_triggers": bool}
    pending_attack_hits: Optional[dict] = None
    # 直近の「自分の手札からカードが捨てられた」 イベントの context (OP12-040 クザン等)。
    # trigger_on_self_hand_discarded で一時的に保存され、 eval_condition で参照される。
    # actor_source_feature_contains 条件と draw_per_self_hand_discarded primitive で使用。
    last_discard_source_inplay: Optional[object] = None
    last_discard_count: int = 0
    # 直近に「自分の場のドンがドンデッキに戻された」 枚数 (= returned_don_count_ge 条件、 EB02-035/P-077)。
    last_returned_don_count: int = 0
    # 直近の「相手のデッキ上を見た」 私的情報 (= peek_opp_deck_top primitive、 OP11-070 等)。
    # {"viewer_idx": int, "card_ids": [str]}。 public log には出さず ここに記録 (= AI/UI が利用可)。
    last_peeked_opp_deck_top: Optional[dict] = None
    # 直近の「自分のキャラが KO された」 イベントの victim カード (= payload-aware 条件用)。
    # OP14-041 ハンコック 「元々のパワー5000以上 + 特徴《アマゾン・リリー》《九蛇海賊団》」 等。
    last_chara_ko_victim_card: Optional[object] = None
    # 直近の「相手のキャラが登場した」 イベントの played カード (= OP12-081 コアラ用)。
    last_opp_chara_played_card: Optional[object] = None
    # 直近の「自分のキャラが登場した」 イベントの played カード (= OP02-026 サンジ用)。
    last_self_chara_played_card: Optional[object] = None
    # 同イベントの played InPlay の instance_id と、 トラッシュ起源か (= OP16-079 ヤマト用)。
    # last_self_played_chara target / played_from_trash 条件が参照する。
    last_self_chara_played_iid: Optional[int] = None
    last_self_chara_played_from_trash: bool = False
    # 公式 (cardqa_op_12、 OP12-081 コアラ): 「**キャラの効果で**キャラを登場させた時」 =
    # **場にあるキャラ** の効果でなければならない。 【トリガー】/イベント/リーダー効果 に
    # よる登場は該当しない (「『場にあるキャラの効果』以外の効果によって…登場したときには
    # …発動できません。 そのため、【トリガー】効果による…登場では発動できません」)。
    last_chara_played_by_field_chara: bool = False
    # 直近のトリガー処理で「このカードを手札に加える」 効果が発動したか (ST09-002 雨月天ぷら等)。
    # trigger_lifecard_trigger 後に game.py が読んで trash 移動 → 手札 へ振替。
    last_trigger_kept_in_hand: bool = False
    # action 単位の board_eval 履歴 (R64+ AI 行動品質評価用)。
    # apply_action 開始時 / 終了時に push される dict: {turn, player_idx, action, eval_before, eval_after, delta}
    action_evals: list = field(default_factory=list)
    # Phase 2 audit (= engine/audit_invariants.py) で 検出 した 違反 list。
    # env ONEPIECE_AUDIT_INVARIANTS=1 で 有効化、 default off で zero overhead。
    # 各 element は AuditViolation.to_dict() 形式。
    audit_violations: list = field(default_factory=list)
    # plan_search の cloned state では compute_score (eval_before/after) 記録を抑止して
    # 不要な eval 計算を削減する (= R70 高速化)。 default True で本番試合は従来通り記録。
    record_action_evals: bool = True
    # 各プレイヤーの deck slug (= setup_game で記録)。
    # archetype 別重み load 用。 [p0_slug, p1_slug] (= "" は不明)。
    deck_slugs: list[str] = field(default_factory=lambda: ["", ""])
    # 各プレイヤーの archetype (= analysis から推定、 setup_game で記録)。
    # ["コントロール", "ミッドレンジ"] 等。 "" は不明 → base 重みフォールバック。
    archetypes: list[str] = field(default_factory=lambda: ["", ""])
    # 各プレイヤーの leader 固有効果 flag (= ai_hint_signals 由来、 Plan Step 1)。
    # 各 flag = bool。 例: {"have_ramp": True, "have_burst_finisher": False, ...}。
    # eval.py の interaction features が state.deck_flags[me_idx] を参照する。
    deck_flags: list[dict] = field(default_factory=lambda: [{}, {}])

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
        snap = {
            "turn": self.turn_number,
            "turn_player_idx": self.turn_player_idx,
            "phase": self.phase.name if hasattr(self.phase, "name") else str(self.phase),
            "log": log_line,
            "game_over": self.game_over,
            "winner": self.winner,
            "event": event,
            "players": [_player_snapshot(p) for p in self.players],
        }
        # AI 行動品質評価用: ターンプレイヤー視点の盤面評価値 (= self - opp)。
        # action ごとの delta_eval を後段で計算可能にする (R62-R63)。
        try:
            from .eval import compute_score
            snap["board_eval"] = compute_score(self, self.turn_player_idx)
        except Exception:
            # eval 計算失敗時は snapshot 自体は壊さない (= optional フィールド)
            pass
        # 観戦 UI 用: AI が手を判断する盤面データの内訳 (= 全指標 self/opp/diff/contribution)。
        # 視点は常に P0 (= 手前のデッキ) 固定。 record_snapshots=True (= replay/sample) 時のみ
        # snapshot() が呼ばれるため、 matrix 一括計算には影響しない。
        try:
            from .eval import compute_breakdown
            snap["board_eval_detail"] = compute_breakdown(self, 0)
        except Exception:
            pass
        return snap


def _inplay_status(ip) -> list:
    """効果で今このカードに付与されている「普通でない」状態/制限だけを短文で列挙 (= UI hover 用)。
    アクティブ/レスト等の当たり前の状態は含めない (= 盤面を見れば分かる為)。"""
    out: list = []
    if (
        getattr(ip, "cannot_attack_until_turn_end", False)
        or getattr(ip, "cannot_attack_static", False)
        or getattr(ip, "cannot_attack_through_opp_turn", False)
    ):
        out.append("攻撃できない")
    if getattr(ip, "stay_rested_next_refresh", False):
        out.append("次のリフレッシュで回復しない")
    if getattr(ip, "effect_disabled_through_opp_turn", False):
        out.append("効果が無効")
    if getattr(ip, "ko_immune_until_turn_end", False) or getattr(ip, "static_ko_immune", False):
        out.append("KO されない")
    if getattr(ip, "attack_taunt", False):
        out.append("相手はこのキャラを狙う（挑発）")
    return out


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
        # 効果で付与された「普通でない」状態/制限 (= UI hover で明示)。
        "status": _inplay_status(ip),
    }


def _player_snapshot(p) -> dict:
    return {
        "name": p.name,
        "leader": _inplay_snapshot(p.leader),
        "characters": [_inplay_snapshot(c) for c in p.characters],
        "stages": [_inplay_snapshot(s) for s in p.stages],
        "hand": [c.card_id for c in p.hand],
        "hand_count": len(p.hand),
        # 公開済 (= サーチ「公開して手札に加える」/ reveal 効果) の手札 card_id。 相手視点でも
        # 見てよい情報 = UI で「相手がサーチで公開したカード」を確認画面に出す用 (ohtsuki 提案)。
        "known_hand_card_ids": list(p.known_hand_card_ids),
        "life_count": len(p.life),
        "trash": [c.card_id for c in p.trash],
        "trash_count": len(p.trash),
        "deck_count": len(p.deck),
        "don_active": p.don_active,
        "don_rested": p.don_rested,
        "don_total": p.total_don,
        "don_remaining_in_deck": p.don_remaining_in_deck,
    }
