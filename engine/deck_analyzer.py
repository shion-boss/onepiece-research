# -*- coding: utf-8 -*-
"""
デッキ静的分析 (Deck Static Analyzer)
=====================================

デッキ構成 (リーダー + 50 枚 + overlay 効果) から、 動的対戦なしで戦略プロファイル・
マリガン基準・理想ムーブ・弱点・キーカードを推論する。

AI がデッキを使いこなすための「設計書」を自動生成。

入力: DeckList (engine.deck.DeckList) + effects_overlay (任意、 効果分類のため)。
出力: DeckAnalysis dataclass。

使い方:
    from engine.deck import CardRepository, DeckList
    from engine.deck_analyzer import analyze_deck
    from engine.effects import load_effect_overlay

    repo = CardRepository.from_json("db/cards.json")
    overlay = load_effect_overlay("db/card_effects.json")
    deck = DeckList.from_json("decks/cardrush_1429.json", repo)
    analysis = analyze_deck(deck, overlay)
    print(analysis.strategy)   # "コントロール (中盤型)"
    print(analysis.mulligan_keep_card_ids)   # ["EB02-052", ...]
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import card_role
from .core import CardDef, Category
from .deck import DeckList


@dataclass
class CostCurveBucket:
    cost: int
    count: int


@dataclass
class KeyCard:
    card_id: str
    name: str
    count: int
    cost: int
    role: str  # "search" | "draw" | "removal" | "blocker" | "finisher" | "synergy" | "counter" | "ramp"
    reason: str


@dataclass
class IdealMove:
    turn: int
    description: str
    candidate_cards: list[str] = field(default_factory=list)


@dataclass
class DeckAnalysis:
    deck_name: str
    leader_id: str
    leader_name: str
    leader_color: list[str]
    leader_features: list[str]
    leader_text: str

    # 構成統計
    total_cards: int
    n_character: int
    n_event: int
    n_stage: int
    avg_cost: float
    cost_curve: list[CostCurveBucket]
    counter_total: int
    counter_2k_count: int
    counter_1k_count: int
    blocker_count: int
    color_distribution: dict[str, int]
    top_features: list[tuple[str, int]]  # 上位 5 特徴とその枚数

    # 戦略プロファイル
    archetype: str  # "アグロ" | "ミッドレンジ" | "コントロール" | "ランプ" | "ハイブリッド"
    speed: str  # "高速" | "中速" | "低速"
    defense: str  # "硬い" | "標準" | "脆い"
    consistency: str  # "高い" | "標準" | "不安定"
    strategy_summary: str  # 1-2 文の作戦概要

    # マリガン
    mulligan_keep_card_ids: list[str]  # キープしたい 4 枚積み主力
    mulligan_keep_criteria: list[str]
    mulligan_throw_criteria: list[str]

    # 理想ムーブ (T1〜T6)
    ideal_moves: list[IdealMove]

    # 弱点
    weaknesses: list[str]

    # 強み
    strengths: list[str]

    # キーカード (役割別)
    key_cards: list[KeyCard]

    # AI 戦略ヒント (このデッキ専用、 人間用 = 表示)
    ai_hints: list[str]
    # AI が読んで動作にマップする構造化ヒント (= 自動消費)
    # 各シグナル: { "type": str, "value": int|str|bool|list }
    ai_hint_signals: list[dict]


# ----------------------------------------------------------------------------- #
# ユーティリティ (engine.card_role 経由で単一情報源化、 R65)
# ----------------------------------------------------------------------------- #
def _is_search_card(card: CardDef, overlay: Optional[dict]) -> bool:
    return card_role.has_role_or_tag(card, overlay, "search")


def _is_draw_card(card: CardDef, overlay: Optional[dict]) -> bool:
    return card_role.has_role_or_tag(card, overlay, "draw")


def _is_removal_card(card: CardDef, overlay: Optional[dict]) -> bool:
    return card_role.has_role_or_tag(card, overlay, "removal")


def _is_ramp_card(card: CardDef, overlay: Optional[dict]) -> bool:
    return card_role.has_role_or_tag(card, overlay, "ramp")


def _has_blocker(card: CardDef) -> bool:
    return card_role.has_role_or_tag(card, None, "blocker")


# ----------------------------------------------------------------------------- #
# メイン分析
# ----------------------------------------------------------------------------- #
def analyze_deck(
    deck: DeckList,
    overlay: Optional[dict] = None,
) -> DeckAnalysis:
    """デッキ + overlay から DeckAnalysis を生成。"""
    leader = deck.leader
    main = deck.main

    # 構成統計
    total_cards = len(main)
    n_character = sum(1 for c in main if c.category == Category.CHARACTER)
    n_event = sum(1 for c in main if c.category == Category.EVENT)
    n_stage = sum(1 for c in main if c.category == Category.STAGE)

    costs = [c.cost for c in main if c.category != Category.STAGE]
    avg_cost = sum(costs) / len(costs) if costs else 0.0

    cost_counter: Counter = Counter()
    for c in main:
        cost_counter[c.cost] += 1
    cost_curve = [
        CostCurveBucket(cost=k, count=v)
        for k, v in sorted(cost_counter.items())
    ]

    counter_total = sum(c.counter for c in main)
    counter_2k_count = sum(1 for c in main if c.counter == 2000)
    counter_1k_count = sum(1 for c in main if c.counter == 1000)
    blocker_count = sum(1 for c in main if _has_blocker(c))

    # 色分布
    color_counter: Counter = Counter()
    for c in main:
        for color in c.color:
            color_counter[color] += 1
    color_distribution = dict(color_counter)

    # 上位特徴 (リーダー特徴と一致するカードが多いほど該当特徴の専用デッキ)
    feature_counter: Counter = Counter()
    for c in main:
        for f in c.features:
            feature_counter[f] += 1
    top_features = feature_counter.most_common(5)

    # === アーキタイプ判定 ===
    archetype, speed = _classify_archetype(avg_cost, blocker_count, n_event, main, overlay)

    # === 防御度 ===
    if counter_total >= 32000:
        defense = "硬い"
    elif counter_total >= 24000:
        defense = "標準"
    else:
        defense = "脆い"

    # === 安定性 (search/draw 系の枚数で評価) ===
    consistency_count = sum(
        1 for c in main if _is_search_card(c, overlay) or _is_draw_card(c, overlay)
    )
    if consistency_count >= 8:
        consistency = "高い"
    elif consistency_count >= 4:
        consistency = "標準"
    else:
        consistency = "不安定"

    # === 戦略要約 ===
    feat_phrase = ""
    if top_features and top_features[0][1] >= 15:
        feat_phrase = f"特徴《{top_features[0][0]}》軸の"
    strategy_summary = (
        f"{feat_phrase}{archetype}デッキ ({speed})。"
        f"防御 {defense}・安定性 {consistency}。"
    )

    # === マリガン ===
    mulligan_keep_ids, keep_criteria, throw_criteria = _compute_mulligan(
        main, leader, overlay
    )

    # === 理想ムーブ ===
    ideal_moves = _compute_ideal_moves(main, leader, overlay, archetype)

    # === 弱点 ===
    weaknesses = _compute_weaknesses(
        main, defense, consistency, blocker_count, avg_cost, archetype
    )

    # === 強み ===
    strengths = _compute_strengths(
        main, defense, consistency, blocker_count, top_features, archetype
    )

    # === キーカード ===
    key_cards = _compute_key_cards(main, leader, overlay)

    # === AI ヒント (人間表示 + 構造化) ===
    ai_hints = _compute_ai_hints(archetype, defense, blocker_count, top_features, leader)
    ai_hint_signals = _compute_ai_hint_signals(
        archetype, defense, blocker_count, top_features, key_cards, leader
    )

    return DeckAnalysis(
        deck_name=deck.name,
        leader_id=leader.card_id,
        leader_name=leader.name,
        leader_color=list(leader.color),
        leader_features=list(leader.features),
        leader_text=leader.text or "",
        total_cards=total_cards,
        n_character=n_character,
        n_event=n_event,
        n_stage=n_stage,
        avg_cost=avg_cost,
        cost_curve=cost_curve,
        counter_total=counter_total,
        counter_2k_count=counter_2k_count,
        counter_1k_count=counter_1k_count,
        blocker_count=blocker_count,
        color_distribution=color_distribution,
        top_features=top_features,
        archetype=archetype,
        speed=speed,
        defense=defense,
        consistency=consistency,
        strategy_summary=strategy_summary,
        mulligan_keep_card_ids=mulligan_keep_ids,
        mulligan_keep_criteria=keep_criteria,
        mulligan_throw_criteria=throw_criteria,
        ideal_moves=ideal_moves,
        weaknesses=weaknesses,
        strengths=strengths,
        key_cards=key_cards,
        ai_hints=ai_hints,
        ai_hint_signals=ai_hint_signals,
    )


# ----------------------------------------------------------------------------- #
# サブ判定
# ----------------------------------------------------------------------------- #
def _classify_archetype(
    avg_cost: float,
    blocker_count: int,
    n_event: int,
    main: list[CardDef],
    overlay: Optional[dict],
) -> tuple[str, str]:
    """アーキタイプ + 速度を multi-signal scoring で判定。

    各アーキ (アグロ/コントロール/ランプ/ミッドレンジ) に複数のシグナルから 0-100 のスコアを付与、
    最大スコアのアーキを採用。 タイ時はミッドレンジ優先 (バランス型扱い)。

    シグナル:
      アグロ    : 低コストキャラ密度、 速攻持ち、 リーダー on_attack 強化、 平均コスト低、 リーダー攻撃の打点伸ばし傾向
      コントロール: ブロッカー数、 除去カード数、 counter 総量、 平均コスト高、 起動メイン制御系リーダー
      ランプ    : ramp 系カード数 (untap_don/add_don/add_rested_don)、 高コストキャラ数、 リーダーの DON 関連効果
      ミッドレンジ: 平均コスト 2.7〜3.5、 上記いずれにも特化していない (デフォ)
    """
    # 集計用カウント
    n_low_cost_chara = sum(
        1 for c in main if c.category == Category.CHARACTER and c.cost <= 3
    )
    n_rush = sum(1 for c in main if "速攻" in (c.text or "") or "スピード" in (c.text or ""))
    n_high_cost_chara = sum(
        1 for c in main if c.category == Category.CHARACTER and c.cost >= 6
    )
    ramp_count = sum(1 for c in main if _is_ramp_card(c, overlay))
    removal_count = sum(1 for c in main if _is_removal_card(c, overlay))
    counter_2k = sum(1 for c in main if c.counter == 2000)
    counter_total = sum(c.counter for c in main)

    # 速攻 / on_attack +N power 効果数 (アグロ判定)
    on_attack_buff_count = 0
    if overlay:
        for c in main:
            bundle = overlay.get(c.card_id)
            if bundle is None:
                continue
            for eff in bundle.effects:
                if eff.get("when") != "on_attack":
                    continue
                for prim in eff.get("do", []):
                    pp = prim.get("power_pump")
                    if pp and pp.get("amount", 0) > 0:
                        on_attack_buff_count += 1
                        break
                else:
                    continue
                break

    # === アグロスコア ===
    # 「ライフ詰め型」 を捉える。 平均コスト・低コスト密度・速攻持ち・on_attack 強化 が主シグナル
    aggro = 0
    if avg_cost <= 2.7:
        aggro += 30
    elif avg_cost <= 3.0:
        aggro += 22
    elif avg_cost <= 3.3:
        aggro += 12
    elif avg_cost <= 3.6:
        aggro += 5
    if n_low_cost_chara >= 25:
        aggro += 25
    elif n_low_cost_chara >= 18:
        aggro += 15
    elif n_low_cost_chara >= 14:
        aggro += 8
    if n_rush >= 6:
        aggro += 22
    elif n_rush >= 3:
        aggro += 12
    elif n_rush >= 1:
        aggro += 5
    if on_attack_buff_count >= 8:
        aggro += 18
    elif on_attack_buff_count >= 4:
        aggro += 10
    elif on_attack_buff_count >= 2:
        aggro += 4
    # 高コスト キャラ少ないほどアグロ寄り
    if n_high_cost_chara <= 3:
        aggro += 10
    # 除去・ramp 軸でない = アグロ寄り (= 純粋な打点デッキ)
    if removal_count <= 2 and ramp_count <= 2:
        aggro += 8

    # === コントロールスコア ===
    # 「除去 + ブロッカー多用」 を主軸とした「除去重型」 のみ純コントロール扱い
    control = 0
    if avg_cost >= 4.0:
        control += 22
    elif avg_cost >= 3.6:
        control += 12
    elif avg_cost >= 3.3:
        control += 5
    if blocker_count >= 12:
        control += 25
    elif blocker_count >= 9:
        control += 15
    elif blocker_count >= 6:
        control += 7
    if removal_count >= 6:
        control += 25
    elif removal_count >= 4:
        control += 15
    elif removal_count >= 2:
        control += 5
    if counter_total >= 36000:
        control += 12
    elif counter_total >= 32000:
        control += 7
    if counter_2k >= 14:
        control += 8
    if n_high_cost_chara >= 8:
        control += 10
    elif n_high_cost_chara >= 6:
        control += 5

    # === ランプスコア ===
    ramp = 0
    if ramp_count >= 6:
        ramp += 35
    elif ramp_count >= 3:
        ramp += 15
    if n_high_cost_chara >= 6:
        ramp += 20
    elif n_high_cost_chara >= 4:
        ramp += 10
    if avg_cost >= 3.7:
        ramp += 10

    # === ミッドレンジスコア ===
    # base を上げて、 「中型キャラ + 適度な除去/ブロッカー」 の中庸デッキを拾う
    midrange = 35
    if 2.8 <= avg_cost <= 3.7:
        midrange += 18
    elif 2.5 <= avg_cost <= 4.0:
        midrange += 8
    if 5 <= blocker_count <= 9:
        midrange += 10
    if 2 <= removal_count <= 5:
        midrange += 12
    # 中型キャラ (cost 4-5) が主体 → midrange
    n_mid_cost = sum(
        1 for c in main if c.category == Category.CHARACTER and 4 <= c.cost <= 5
    )
    if n_mid_cost >= 16:
        midrange += 10
    elif n_mid_cost >= 12:
        midrange += 5

    scores = {
        "アグロ": aggro,
        "コントロール": control,
        "ランプ": ramp,
        "ミッドレンジ": midrange,
    }
    best_arch = max(scores, key=lambda k: scores[k])

    # 速度判定 (アーキ独立、 avg_cost ベース)
    if avg_cost <= 2.7:
        speed = "高速"
    elif avg_cost <= 3.5:
        speed = "中速"
    else:
        speed = "低速"
    # ランプ専用調整 (低速気味でも中速扱い)
    if best_arch == "ランプ" and speed == "低速":
        speed = "中速"

    return best_arch, speed


def _compute_mulligan(
    main: list[CardDef],
    leader: CardDef,
    overlay: Optional[dict],
) -> tuple[list[str], list[str], list[str]]:
    """マリガン基準を生成。"""
    # キープしたい 4 枚積みのカード (= 序盤に欲しい安価キー)
    counter = Counter(c.card_id for c in main)
    leader_features = set(leader.features)

    keep_ids: list[str] = []
    seen: set[str] = set()
    for c in main:
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        n = counter[c.card_id]
        if n < 4:
            continue
        if c.cost > 4:
            continue
        # サーチ・ドロー・登場時除去 = 序盤キー
        if _is_search_card(c, overlay) or _is_draw_card(c, overlay) or _is_removal_card(c, overlay):
            keep_ids.append(c.card_id)
            continue
        # リーダー特徴一致のコスト1〜3 キャラもキー
        if c.cost <= 3 and c.category == Category.CHARACTER and (
            set(c.features) & leader_features
        ):
            keep_ids.append(c.card_id)

    keep_criteria = [
        "コスト 3 以下のキャラ ≥ 1 枚",
        "サーチ / ドローカード ≥ 1 枚",
    ]
    if leader_features:
        keep_criteria.append(
            f"リーダー特徴《{'/'.join(list(leader_features)[:2])}》を持つキャラ ≥ 1 枚"
        )

    throw_criteria = [
        "5 コスト以上のカードしかない",
        "リーダー特徴と無関係なカードばかり",
        "1 ターン目に展開できる手数なし",
    ]
    return keep_ids[:6], keep_criteria, throw_criteria


def _compute_ideal_moves(
    main: list[CardDef],
    leader: CardDef,
    overlay: Optional[dict],
    archetype: str,
) -> list[IdealMove]:
    """T1〜T6 の理想ムーブ。"""
    cost_to_chars: dict[int, list[CardDef]] = {}
    for c in main:
        if c.category != Category.CHARACTER:
            continue
        cost_to_chars.setdefault(c.cost, []).append(c)

    moves: list[IdealMove] = []

    # T1: 1 ドン → 1 コストキャラ展開
    cost1 = cost_to_chars.get(1, [])
    if cost1:
        moves.append(IdealMove(
            turn=1,
            description="1 コストキャラを展開、 序盤テンポ確保",
            candidate_cards=[c.card_id for c in sorted(cost1, key=lambda x: -x.power)[:3]],
        ))
    else:
        moves.append(IdealMove(turn=1, description="1 コストキャラ無し → DON 付与でリーダー攻撃の準備"))

    # T2: 2 ドン → 2 コストキャラ + DON 付与
    cost2 = cost_to_chars.get(2, [])
    if cost2:
        moves.append(IdealMove(
            turn=2,
            description="2 コストキャラ展開 (登場時効果優先)",
            candidate_cards=[c.card_id for c in sorted(cost2, key=lambda x: -x.power)[:3]],
        ))

    # T3: 3 ドン → 3 コストキャラ
    cost3 = cost_to_chars.get(3, [])
    if cost3:
        moves.append(IdealMove(
            turn=3,
            description="3 コスト主力キャラ展開、 リーダー攻撃で圧",
            candidate_cards=[c.card_id for c in sorted(cost3, key=lambda x: -x.power)[:3]],
        ))

    # T4-5: 4-5 コスト
    cost4_5 = cost_to_chars.get(4, []) + cost_to_chars.get(5, [])
    if cost4_5:
        moves.append(IdealMove(
            turn=4,
            description="4-5 コスト中堅展開、 盤面強化",
            candidate_cards=[c.card_id for c in sorted(cost4_5, key=lambda x: -x.power)[:3]],
        ))

    # T6+: 6+ コスト = フィニッシャー
    cost6plus = []
    for cost, chars in cost_to_chars.items():
        if cost >= 6:
            cost6plus.extend(chars)
    if cost6plus:
        moves.append(IdealMove(
            turn=6,
            description="フィニッシャー展開、 リーサル準備",
            candidate_cards=[c.card_id for c in sorted(cost6plus, key=lambda x: -x.power)[:3]],
        ))

    return moves


def _compute_weaknesses(
    main: list[CardDef],
    defense: str,
    consistency: str,
    blocker_count: int,
    avg_cost: float,
    archetype: str,
) -> list[str]:
    out: list[str] = []
    if defense == "脆い":
        out.append(f"カウンター総量 < 24,000: 防御薄、 連続攻撃に弱い")
    if blocker_count <= 4:
        out.append(f"ブロッカー {blocker_count} 枚のみ: 直接攻撃を止めにくい")
    if consistency == "不安定":
        out.append("サーチ / ドローカード少ない: ハンド事故の影響大")
    if avg_cost >= 4.0:
        out.append("平均コスト高い: 序盤の展開遅く、 アグロに押し切られる懸念")
    if archetype == "アグロ":
        out.append("コントロールに対しガス欠リスク: 後半の手札・打点が枯れる")
    elif archetype == "コントロール":
        out.append("アグロデッキの早期 ライフ削りに脆弱、 序盤の捌きが重要")

    # KO 効果が少ない
    high_cost_chars = [c for c in main if c.category.value == "CHARACTER" and c.cost >= 5]
    if len(high_cost_chars) <= 4:
        out.append("コスト 5+ キャラ少ない: 大型相手の処理手段が限定的")
    return out


def _compute_strengths(
    main: list[CardDef],
    defense: str,
    consistency: str,
    blocker_count: int,
    top_features: list,
    archetype: str,
) -> list[str]:
    out: list[str] = []
    if defense == "硬い":
        out.append("カウンター総量 ≥ 32,000: 防御層が厚く、 ライフ詰めに強い")
    if consistency == "高い":
        out.append("サーチ / ドロー多数: ハンド事故しにくい、 動きの再現性高い")
    if blocker_count >= 8:
        out.append(f"ブロッカー {blocker_count} 枚: 直接攻撃を抑止できる")
    if top_features and top_features[0][1] >= 20:
        out.append(
            f"特徴《{top_features[0][0]}》専属 ({top_features[0][1]} 枚): "
            f"シナジーカードで爆発力"
        )
    if archetype == "アグロ":
        out.append("低コスト多数: 序盤からライフ詰めの圧、 先攻有利")
    elif archetype == "コントロール":
        out.append("除去・防御で序盤捌き、 後半フィニッシャーで決める")
    return out


def _compute_key_cards(
    main: list[CardDef],
    leader: CardDef,
    overlay: Optional[dict],
) -> list[KeyCard]:
    counter = Counter(c.card_id for c in main)
    seen: set[str] = set()
    out: list[KeyCard] = []
    leader_features = set(leader.features)

    # 4 枚積みカード = キーカード候補
    for c in main:
        if c.card_id in seen:
            continue
        seen.add(c.card_id)
        n = counter[c.card_id]
        if n < 3:
            continue  # 3-4 枚積みのみ

        role = None
        reason = ""
        if _is_search_card(c, overlay):
            role = "search"
            reason = "デッキからサーチ → 安定性向上の柱"
        elif _is_draw_card(c, overlay):
            role = "draw"
            reason = "ドロー加速 → 手札枚数とカウンター総量を維持"
        elif _is_removal_card(c, overlay):
            role = "removal"
            reason = "相手キャラ除去 → 盤面コントロールの要"
        elif _is_ramp_card(c, overlay):
            role = "ramp"
            reason = "DON 加速 → 大型早出しの起点"
        elif _has_blocker(c):
            role = "blocker"
            reason = "ブロッカー → 直接攻撃を止める防御の柱"
        elif c.cost >= 6:
            role = "finisher"
            reason = f"高コスト ({c.cost})・高パワー ({c.power}) フィニッシャー"
        elif set(c.features) & leader_features and c.cost <= 4:
            role = "synergy"
            reason = f"リーダー特徴一致 + 安価 → 序盤のシナジー要員"
        elif c.counter >= 2000:
            role = "counter"
            reason = f"2k カウンター → 防御リソース"

        if role:
            out.append(KeyCard(
                card_id=c.card_id,
                name=c.name,
                count=n,
                cost=c.cost,
                role=role,
                reason=reason,
            ))

    # 役割の優先度でソート
    role_priority = {
        "finisher": 0, "removal": 1, "search": 2, "draw": 3, "ramp": 4,
        "synergy": 5, "blocker": 6, "counter": 7,
    }
    out.sort(key=lambda k: (role_priority.get(k.role, 99), -k.cost))
    return out[:10]


def _compute_ai_hints(
    archetype: str,
    defense: str,
    blocker_count: int,
    top_features: list,
    leader: CardDef,
) -> list[str]:
    """AI がこのデッキを使う時の戦術ヒント (= 将来 AI が読む)。"""
    hints: list[str] = []
    if archetype == "アグロ":
        hints.append("序盤からリーダー攻撃を最優先、 カウンターは温存しすぎない")
        hints.append("ライフ受けで手札増やすより、 1 ターンでも早く詰めに行く")
    elif archetype == "コントロール":
        hints.append("序盤は耐える、 相手のキャラ展開を都度処理")
        hints.append("カウンター温存、 ライフは積極的に受けて手札を増やす")
        hints.append("中盤以降にフィニッシャーで一気に決める")
    elif archetype == "ランプ":
        hints.append("DON 加速を最優先、 小型ブロッカーで凌いで大型展開へ")
    else:  # ミッドレンジ
        hints.append("コスト効率を最大化、 毎ターン展開と除去のバランスを取る")

    if defense == "脆い":
        hints.append("ブロッカーは慎重に切る (= 1 体の生存価値が高い)")
    if blocker_count <= 4:
        hints.append("ブロッカー少ないので、 リーダー攻撃を許容してライフで受ける選択も")

    if top_features and top_features[0][1] >= 18:
        feat = top_features[0][0]
        hints.append(f"特徴《{feat}》専属: シナジーカードを優先プレイ")

    if leader.text and "ドン" in leader.text and "アクティブ" in leader.text:
        hints.append("リーダー効果で DON アクティブ化 = 起動メイン使用後の追加展開を計算")

    return hints


def _compute_ai_hint_signals(
    archetype: str,
    defense: str,
    blocker_count: int,
    top_features: list,
    key_cards: list,
    leader: CardDef,
) -> list[dict]:
    """構造化ヒント: AI が直接読んで挙動にマップするシグナル。

    各シグナル例:
      {"type": "prefer_low_cost_attacks", "value": True}
      {"type": "preserve_counter_for_lethal", "value": True}
      {"type": "prioritize_ramp_first", "value": True}
      {"type": "synergy_feature_priority", "value": "麦わらの一味"}
      {"type": "early_finisher_hold", "value": ["OP15-002", ...]}
      {"type": "counter_aggression", "value": "low"|"mid"|"high"}
    """
    out: list[dict] = []

    # 1) アーキタイプ別の主要シグナル
    if archetype == "アグロ":
        out.append({"type": "prefer_low_cost_attacks", "value": True})
        out.append({"type": "counter_aggression", "value": "low"})
    elif archetype == "コントロール":
        out.append({"type": "preserve_counter_for_lethal", "value": True})
        out.append({"type": "counter_aggression", "value": "high"})
    elif archetype == "ランプ":
        out.append({"type": "prioritize_ramp_first", "value": True})
        out.append({"type": "counter_aggression", "value": "mid"})
    else:  # ミッドレンジ
        out.append({"type": "counter_aggression", "value": "mid"})

    # 2) 特徴シナジー (リーダーと top_features 一致)
    if top_features:
        feat, count = top_features[0]
        if count >= 18 and feat in leader.features:
            out.append({
                "type": "synergy_feature_priority",
                "value": feat,
            })

    # 3) フィニッシャー温存 (key_cards 中の finisher を ライフ ≥ 3 では温存)
    finisher_ids = [k.card_id for k in key_cards if k.role == "finisher"]
    if finisher_ids:
        out.append({
            "type": "early_finisher_hold",
            "value": finisher_ids,
        })

    # 4) 防御力に応じた攻撃積極性
    if defense == "硬い":
        out.append({"type": "tank_lifeup_ok", "value": True})
    elif defense == "脆い":
        out.append({"type": "avoid_life_loss", "value": True})

    # 5) ブロッカー希少 → 慎重に切る
    if blocker_count <= 4:
        out.append({"type": "blocker_scarce", "value": True})

    # 6) リーダー固有効果 flag (= Plan Step 1: AI が「このデッキの戦術」 を判断するための効果系シグナル)
    # 既存 KeyCard.role から自動判定 (= 拡張 effect は card_role.py 3 軸 tag で別途対応)
    key_card_roles = {k.role for k in key_cards}
    if "ramp" in key_card_roles:
        out.append({"type": "have_ramp", "value": True})
    if "search" in key_card_roles:
        out.append({"type": "have_search_loop", "value": True})
    if "removal" in key_card_roles:
        out.append({"type": "have_removal_arsenal", "value": True})
    if "draw" in key_card_roles:
        out.append({"type": "have_draw_engine", "value": True})
    # 重 finisher (= cost >= 7 の finisher が key_cards に居る) の有無
    heavy_finishers = [
        k for k in key_cards if k.role == "finisher" and k.cost >= 7
    ]
    if heavy_finishers:
        out.append({"type": "have_burst_finisher", "value": True})

    return out
