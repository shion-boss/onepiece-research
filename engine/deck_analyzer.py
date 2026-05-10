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

    # AI 戦略ヒント (このデッキ専用)
    ai_hints: list[str]


# ----------------------------------------------------------------------------- #
# ユーティリティ
# ----------------------------------------------------------------------------- #
def _is_search_card(card: CardDef, overlay: Optional[dict]) -> bool:
    """search 系効果を持つか (overlay の `search` プリミティブ or text 一致)。"""
    if overlay and card.card_id in overlay:
        bundle = overlay[card.card_id]
        for eff in bundle.effects:
            for prim in eff.get("do", []):
                if "search" in prim or "summon_from_deck" in prim:
                    return True
    text = card.text or ""
    return ("デッキ" in text and "見て" in text) or ("デッキから" in text and "公開" in text)


def _is_draw_card(card: CardDef, overlay: Optional[dict]) -> bool:
    if overlay and card.card_id in overlay:
        bundle = overlay[card.card_id]
        for eff in bundle.effects:
            for prim in eff.get("do", []):
                if "draw" in prim:
                    return True
    return "カード1枚を引く" in (card.text or "") or "カード2枚を引く" in (card.text or "")


def _is_removal_card(card: CardDef, overlay: Optional[dict]) -> bool:
    if overlay and card.card_id in overlay:
        bundle = overlay[card.card_id]
        for eff in bundle.effects:
            for prim in eff.get("do", []):
                if "ko" in prim or "return_to_hand" in prim:
                    return True
    return "KOする" in (card.text or "") or "手札に戻す" in (card.text or "")


def _is_ramp_card(card: CardDef, overlay: Optional[dict]) -> bool:
    """DON 加速系。"""
    if overlay and card.card_id in overlay:
        bundle = overlay[card.card_id]
        for eff in bundle.effects:
            for prim in eff.get("do", []):
                if any(k in prim for k in ("add_don", "add_rested_don", "untap_don")):
                    return True
    return False


def _has_blocker(card: CardDef) -> bool:
    return "ブロッカー" in (card.text or "")


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

    # === AI ヒント ===
    ai_hints = _compute_ai_hints(archetype, defense, blocker_count, top_features, leader)

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
    """アーキタイプ + 速度を返す。"""
    # ramp 系カードが多ければ ramp
    ramp_count = sum(1 for c in main if _is_ramp_card(c, overlay))
    if ramp_count >= 6:
        return "ランプ", "中速"

    if avg_cost <= 2.7:
        speed = "高速"
        archetype = "アグロ"
    elif avg_cost <= 3.5:
        speed = "中速"
        archetype = "ミッドレンジ"
    else:
        speed = "低速"
        archetype = "コントロール"

    # ブロッカー多 + イベ多 = コントロール寄り上書き
    if blocker_count >= 8 and n_event >= 8 and archetype != "アグロ":
        archetype = "コントロール"

    return archetype, speed


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
