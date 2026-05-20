# -*- coding: utf-8 -*-
"""
ハンド推定 (隠匿情報モデル)
=============================

公式ルール上、 相手の手札は非公開 (= 自プレイヤーには見えない)。
現実装の AI は state.opponent.hand を直接読めるため「ズル」している。

このモジュールは、 相手手札を確率分布として扱う API を提供。

公開 API:
- `EstimatedHand`: 期待カウンター/ブロッカー残存確率 + 分布を集約
- `expected_counter_per_card(state, opp_idx)`: 1 枚あたり期待カウンター値
- `expected_counter_total(state, opp_idx)`: 期待カウンター総量
- `counter_total_pmf(state, opp_idx)`: 手札 counter 合計の確率分布 (Phase 7B 追加)
- `probability_counter_total_at_least(state, opp_idx, threshold)`: 合計 ≥ threshold の確率 (Phase 7B 追加)
- `counter_total_quantile(state, opp_idx, q)`: 合計の q-分位点 (Phase 7B 追加)
- `probability_of_blocker_in_hand(state, opp_idx)`: 手札に 1 枚以上ブロッカーが
  ある確率 (ハイパージオメトリック)
- `estimate_hand(state, opp_idx) -> EstimatedHand`: 上記をまとめて取得
- `sample_opponent_hand(state, opp_idx, rng)`: hand_count 枚を deck+hand プールから
  無作為サンプル (MCTS 決定論化用)
- `determinize_state(state, opp_idx, rng)`: state を完全情報化 (MCTS rollout 用)

「プール」の定義: opp.deck + opp.hand (= trash/play 以外の残カード全部)。
公開情報 (trash / play 済カード) は自動的に除外される。
"""

from __future__ import annotations

import random
from collections import Counter as _Counter
from dataclasses import dataclass, field
from math import comb
from typing import Optional

from .core import CardDef, GameState


@dataclass
class EstimatedHand:
    """相手手札の確率的推定値。

    - hand_count: 公開情報 (= 相手手札枚数、公式ルール上常に確認可能)
    - counter_per_card: deck+hand プール上の 1 枚あたり期待カウンター
    - counter_total: counter_per_card × hand_count (= 期待値)
    - counter_pmf: 手札 counter 合計の確率分布 {total: prob} (Phase 7B 追加)
    - counter_q50: counter 合計の中央値 (= P(<=q50) >= 0.5)
    - counter_q90: counter 合計の 90% 分位点 (= 「ほぼ確実にこれ以下」)
    - blocker_prob: 手札に 1 枚以上ブロッカーがある確率 (0.0〜1.0)
    """

    hand_count: int
    counter_per_card: float
    counter_total: int
    blocker_prob: float
    counter_pmf: dict[int, float] = field(default_factory=dict)
    counter_q50: int = 0
    counter_q90: int = 0


_USE_CLASSIFIER_FOR_POOL: bool = True
_CLASSIFIER_POOL_MIN_CONFIDENCE: float = 0.5
_VARIANT_POOL_MIN_CONFIDENCE: float = 0.6  # variant 識別はより高い信頼度が必要
_VARIANT_MIN_OBSERVATIONS: int = 2  # variant 採用には最低 2 枚の観測カード
_ARCHETYPE_RECIPE_CACHE: Optional[dict[str, list[CardDef]]] = None
_VARIANT_RECIPE_CACHE: Optional[dict[tuple[str, int], list[CardDef]]] = None


def set_pool_mode(use_classifier: bool, min_confidence: float = 0.5) -> None:
    """pool 構築モードを切替 (Phase 7E)。

    True (default): classifier で archetype を推定 → archetype の代表 recipe から
                    観測済を引いた残りを pool に使う (= 隠匿モデル準拠)
    False: 旧挙動 (= opp.deck + opp.hand を直読、 「ズル」 モード)
    """
    global _USE_CLASSIFIER_FOR_POOL, _CLASSIFIER_POOL_MIN_CONFIDENCE
    _USE_CLASSIFIER_FOR_POOL = bool(use_classifier)
    _CLASSIFIER_POOL_MIN_CONFIDENCE = float(min_confidence)


def _load_archetype_recipes() -> dict[str, list[CardDef]]:
    """全 archetype の代表 recipe を CardDef リストとしてロード (cache 付き、 Phase 7E)。

    Returns: `{archetype_name: [CardDef, ...]}` (= main の 50 枚分を flat list で)。
    archetype 名は deck JSON の "name" フィールド (= 「紫エネル」 等)。
    """
    global _ARCHETYPE_RECIPE_CACHE
    if _ARCHETYPE_RECIPE_CACHE is not None:
        return _ARCHETYPE_RECIPE_CACHE
    from pathlib import Path
    import json
    from .deck import CardRepository

    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    decks_dir = _PROJECT_ROOT / "decks"
    cards_path = _PROJECT_ROOT / "db" / "cards.json"
    try:
        repo = CardRepository.from_json(cards_path)
    except Exception:
        _ARCHETYPE_RECIPE_CACHE = {}
        return _ARCHETYPE_RECIPE_CACHE

    out: dict[str, list[CardDef]] = {}
    for p in sorted(decks_dir.glob("*.json")):
        if ".analysis" in p.name:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = d.get("name")
        if not name:
            continue
        cards: list[CardDef] = []
        for entry in d.get("main", []):
            cid = entry.get("card_id")
            count = entry.get("count", 0)
            if not cid or count <= 0:
                continue
            try:
                card = repo.get(cid)
            except KeyError:
                continue
            cards.extend([card] * count)
        if cards:
            out[name] = cards
    _ARCHETYPE_RECIPE_CACHE = out
    return out


def reset_pool_cache_for_testing() -> None:
    """pool cache を強制リセット (= test / refresh 用)。"""
    global _ARCHETYPE_RECIPE_CACHE, _VARIANT_RECIPE_CACHE
    _ARCHETYPE_RECIPE_CACHE = None
    _VARIANT_RECIPE_CACHE = None
    _ARCHETYPE_POOL_CACHE.clear()


def _load_variant_recipes() -> dict[tuple[str, int], list[CardDef]]:
    """全 leader × variant の代表 recipe を CardDef リストとしてロード (Phase 8、 2026-05-16)。

    入力: db/data_layer_64_status.json + decks/<slug>/variant_<id>.json
    Returns: `{(leader_id, variant_id): [CardDef × count]}`
    """
    global _VARIANT_RECIPE_CACHE
    if _VARIANT_RECIPE_CACHE is not None:
        return _VARIANT_RECIPE_CACHE

    from pathlib import Path
    import json as _json
    from .deck import CardRepository

    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    status_path = _PROJECT_ROOT / "db" / "data_layer_64_status.json"
    decks_root = _PROJECT_ROOT / "decks"
    cards_path = _PROJECT_ROOT / "db" / "cards.json"

    out: dict[tuple[str, int], list[CardDef]] = {}
    if not status_path.exists():
        _VARIANT_RECIPE_CACHE = out
        return out

    try:
        repo = CardRepository.from_json(cards_path)
    except Exception:
        _VARIANT_RECIPE_CACHE = out
        return out

    try:
        status = _json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        _VARIANT_RECIPE_CACHE = out
        return out

    for leader_id, info in status.get("leaders", {}).items():
        slug = info.get("slug")
        n_variants = info.get("n_variants", 0)
        if not slug or n_variants <= 0:
            continue
        for vid in range(n_variants):
            vpath = decks_root / slug / f"variant_{vid}.json"
            if not vpath.exists():
                continue
            try:
                vrec = _json.loads(vpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            cards: list[CardDef] = []
            for entry in vrec.get("main", []):
                cid = entry.get("card_id")
                count = entry.get("count", 0)
                if not cid or count <= 0:
                    continue
                try:
                    card = repo.get(cid)
                except KeyError:
                    continue
                cards.extend([card] * count)
            if cards:
                out[(leader_id, vid)] = cards

    _VARIANT_RECIPE_CACHE = out
    return out


# === memo cache (= 2026-05-19、 30g 累積問題 緩和、 read-only 共有なので 安全) ===
_ARCHETYPE_POOL_CACHE: dict = {}
_POOL_CACHE_MAX = 10000


def _archetype_pool(state: GameState, opp_idx: int) -> Optional[list[CardDef]]:
    """classifier で archetype + variant を推定 → recipe - 観測済 を pool に。

    Phase 8 (= 2026-05-16): variant 信頼度が `_VARIANT_POOL_MIN_CONFIDENCE` 以上なら
    variant 別 recipe を使い、 未満なら archetype 全体 recipe にフォールバック。

    高信頼度 (≥ `_CLASSIFIER_POOL_MIN_CONFIDENCE`) でのみ pool を返す。
    低信頼度 / classifier 不在なら None を返し、 呼出側で fallback。
    """
    # memo cache 確認 (= 2026-05-19、 4.9M call の 99%+ が cache hit 期待)
    opp = state.players[opp_idx]
    opp_leader_id = opp.leader.card.card_id if opp.leader else None
    chara_ids = tuple(sorted(ip.card.card_id for ip in opp.characters))
    stage_ids = tuple(sorted(ip.card.card_id for ip in opp.stages))
    trash_ids = tuple(sorted(c.card_id for c in opp.trash))
    cache_key = (opp_leader_id, chara_ids, stage_ids, trash_ids)
    cached = _ARCHETYPE_POOL_CACHE.get(cache_key)
    if cached is not None:
        # sentinel None → cache miss、 cached_NONE → 真に None だった (= 低信頼度)
        return None if cached == "NONE_SENTINEL" else cached

    try:
        from . import deck_classifier
        clf = deck_classifier.get_default_classifier()
        probs = clf.classify_from_state(state, opp_idx)
    except Exception:
        if len(_ARCHETYPE_POOL_CACHE) < _POOL_CACHE_MAX:
            _ARCHETYPE_POOL_CACHE[cache_key] = "NONE_SENTINEL"
        return None

    base_cards: Optional[list[CardDef]] = None
    pool_source = "fallback"

    # Phase 8: variant 推定を最優先で試す (= 同 leader 内 variant 信頼度高なら最精度)
    # ただし観測カード数 < _VARIANT_MIN_OBSERVATIONS なら採用しない (= 初期 turn の誤判定回避)
    if opp_leader_id:
        observed_ids = _collect_observed(state, opp_idx)
        if len(observed_ids) >= _VARIANT_MIN_OBSERVATIONS:
            try:
                v_probs = clf.classify_with_variant(
                    observed_card_ids=observed_ids,
                    opp_leader_id=opp_leader_id,
                )
            except Exception:
                v_probs = {}

            if v_probs:
                top_vid, top_v_prob = max(v_probs.items(), key=lambda x: x[1])
                if top_v_prob >= _VARIANT_POOL_MIN_CONFIDENCE:
                    v_recipes = _load_variant_recipes()
                    cards = v_recipes.get((opp_leader_id, top_vid))
                    if cards:
                        base_cards = cards
                        pool_source = f"variant:{opp_leader_id}:{top_vid}"

    # variant 不採用 → archetype level fallback (= 既存挙動)
    if base_cards is None:
        if not probs:
            if len(_ARCHETYPE_POOL_CACHE) < _POOL_CACHE_MAX:
                _ARCHETYPE_POOL_CACHE[cache_key] = "NONE_SENTINEL"
            return None
        top_arch, top_prob = max(probs.items(), key=lambda x: x[1])
        if top_prob < _CLASSIFIER_POOL_MIN_CONFIDENCE:
            if len(_ARCHETYPE_POOL_CACHE) < _POOL_CACHE_MAX:
                _ARCHETYPE_POOL_CACHE[cache_key] = "NONE_SENTINEL"
            return None

        recipes = _load_archetype_recipes()
        base_cards = recipes.get(top_arch)
        if not base_cards:
            # alias で再試行 (= 「空島ルフィ → 黄ルフィ（OP15）」 等)
            try:
                from .deck_classifier import ARCHETYPE_ALIASES
                for raw_name, canonical in ARCHETYPE_ALIASES.items():
                    if canonical == top_arch and raw_name in recipes:
                        base_cards = recipes[raw_name]
                        break
            except Exception:
                pass
        if not base_cards:
            if len(_ARCHETYPE_POOL_CACHE) < _POOL_CACHE_MAX:
                _ARCHETYPE_POOL_CACHE[cache_key] = "NONE_SENTINEL"
            return None
        pool_source = f"archetype:{top_arch}"

    # 観測済 (= 場 / トラッシュ / ステージ) を recipe から引く
    observed_counts: dict[str, int] = {}
    for ip in opp.characters:
        observed_counts[ip.card.card_id] = observed_counts.get(ip.card.card_id, 0) + 1
    for ip in opp.stages:
        observed_counts[ip.card.card_id] = observed_counts.get(ip.card.card_id, 0) + 1
    for c in opp.trash:
        observed_counts[c.card_id] = observed_counts.get(c.card_id, 0) + 1

    remaining: list[CardDef] = []
    for card in base_cards:
        cid = card.card_id
        if observed_counts.get(cid, 0) > 0:
            observed_counts[cid] -= 1
            continue
        remaining.append(card)
    # cache 保存 (= read-only 共有、 4.9M call の 99%+ が cache hit 期待)
    if len(_ARCHETYPE_POOL_CACHE) < _POOL_CACHE_MAX:
        _ARCHETYPE_POOL_CACHE[cache_key] = remaining
    return remaining


def _collect_observed(state: GameState, opp_idx: int) -> list[str]:
    """state から opp の可視カード id をリストで返す (= classify_with_variant 用)。"""
    opp = state.players[opp_idx]
    observed: list[str] = []
    for ip in opp.characters:
        observed.append(ip.card.card_id)
    for ip in opp.stages:
        observed.append(ip.card.card_id)
    for c in opp.trash:
        observed.append(c.card_id)
    return observed


def _opponent_pool(state: GameState, opp_idx: int) -> list[CardDef]:
    """opp の手札候補プール (Phase 7E 改修)。

    `_USE_CLASSIFIER_FOR_POOL = True` (default) で:
    - 高信頼度 (`_CLASSIFIER_POOL_MIN_CONFIDENCE` 以上) なら classifier-based pool
    - 低信頼度なら旧挙動 (opp.deck + opp.hand) に fallback

    `_USE_CLASSIFIER_FOR_POOL = False` で:
    - 常に旧挙動 (opp.deck + opp.hand 直読、 「ズル」 モード)
    """
    if _USE_CLASSIFIER_FOR_POOL:
        pool = _archetype_pool(state, opp_idx)
        if pool is not None:
            return pool
    opp = state.players[opp_idx]
    return list(opp.deck) + list(opp.hand)


def expected_counter_per_card(state: GameState, opp_idx: int) -> float:
    """opp の deck+hand プール上での 1 枚あたり期待カウンター値。

    例: プールに [2000, 1000, 0, 0, 1000] のカウンター値なら平均 800。
    既にトラッシュに行ったカウンター持ちカードは自動的に除外される。
    """
    pool = _opponent_pool(state, opp_idx)
    if not pool:
        return 0.0
    return sum(c.counter for c in pool) / len(pool)


def expected_counter_total(state: GameState, opp_idx: int) -> int:
    """opp の手札に期待されるカウンター総量。"""
    opp = state.players[opp_idx]
    return int(expected_counter_per_card(state, opp_idx) * len(opp.hand))


def probability_of_blocker_in_hand(state: GameState, opp_idx: int) -> float:
    """opp の手札に少なくとも 1 枚ブロッカーがある確率 (ハイパージオメトリック)。

    プール N 枚中ブロッカー K 枚、手札 h 枚として、
    P(>=1 blocker) = 1 - C(N-K, h) / C(N, h)
                   = 1 - Π_{i=0}^{h-1} (N-K-i) / (N-i)
    """
    opp = state.players[opp_idx]
    pool = _opponent_pool(state, opp_idx)
    h = len(opp.hand)
    n_pool = len(pool)
    if h == 0 or n_pool == 0:
        return 0.0
    n_blocker = sum(1 for c in pool if c.is_blocker)
    if n_blocker == 0:
        return 0.0
    if n_blocker >= n_pool:
        return 1.0
    if h >= n_pool:
        return 1.0
    p_zero = 1.0
    for i in range(h):
        denom = n_pool - i
        if denom <= 0:
            return 1.0
        p_zero *= (n_pool - n_blocker - i) / denom
        if p_zero <= 0.0:
            return 1.0
    return 1.0 - p_zero


def counter_total_pmf(state: GameState, opp_idx: int) -> dict[int, float]:
    """opp 手札の counter 合計の確率分布 (pmf、 Phase 7B + 7I 改修)。

    Returns: `{counter_total: probability}` 辞書。 確率の総和 = 1.0。

    ## 計算原理 (= ハイパージオメトリック分布 + 既知カード分離 [Phase 7I])

    Phase 7I 改修: opp.known_hand_card_ids (= 公開済 hand card) は確定情報として扱い、
    未知部分のみ ハイパージオメトリック分布で計算。

    分離計算:
    - known_counter = Σ (known カードの counter 値)  ← 確定
    - unknown_count = hand_size - len(known_card_ids)
    - 未知 pool = deck + hand - (既知カード分)
    - 未知 pmf を超幾何分布で計算
    - total pmf = (known_counter で shift した unknown pmf)

    プール空 / 手札空: `{0: 1.0}` を返す。
    """
    opp = state.players[opp_idx]
    hand_size = len(opp.hand)
    if hand_size == 0:
        return {0: 1.0}

    # Phase 7I: 既知カード分の固定 counter + 未知カード分の pmf を計算
    known_ids = list(opp.known_hand_card_ids)
    # known_ids が hand_size を超えてる場合は片側削減 (normalize で防がれるが念のため)
    known_ids = known_ids[:hand_size]

    # known カードを hand から探して counter 値を取得
    # 同 card_id が複数ある場合、 先頭分を 1 ずつ「消費」 する
    hand_copy = list(opp.hand)
    known_counter = 0
    matched_indices: list[int] = []
    for cid in known_ids:
        for i, c in enumerate(hand_copy):
            if i in matched_indices:
                continue
            if c.card_id == cid:
                known_counter += c.counter
                matched_indices.append(i)
                break

    known_count = len(matched_indices)
    unknown_count = hand_size - known_count
    if unknown_count == 0:
        # 全て既知 → 確定 pmf
        return {known_counter: 1.0}

    # 未知 pool 構築 (= deck + hand から 既知分を除外)
    full_pool = _opponent_pool(state, opp_idx)
    # 既知 hand card object も pool から引く必要あり (= hand に存在する known カード)
    known_hand_cards = [opp.hand[i] for i in matched_indices]
    # pool から既知 hand card を引く (= 同じカード参照を 1 つずつ除外)
    remaining_pool = list(full_pool)
    for known_card in known_hand_cards:
        try:
            remaining_pool.remove(known_card)
        except ValueError:
            # 引けない場合 (= pool に既知カードが含まれない、 edge case)
            pass

    if len(remaining_pool) < unknown_count:
        # 残プール不足 → 確定 pmf
        return {known_counter: 1.0}

    # 未知 portion の pmf を超幾何で計算
    groups = _Counter(c.counter for c in remaining_pool)
    n_total = len(remaining_pool)
    norm = comb(n_total, unknown_count)
    if norm == 0:
        return {known_counter: 1.0}

    unknown_pmf: dict[int, float] = {}
    items = list(groups.items())

    def _enumerate(idx: int, remaining: int, total: int, numerator: int) -> None:
        if idx == len(items):
            if remaining == 0:
                unknown_pmf[total] = unknown_pmf.get(total, 0.0) + numerator / norm
            return
        val, count = items[idx]
        max_take = min(count, remaining)
        for n in range(max_take + 1):
            new_num = numerator * comb(count, n)
            _enumerate(idx + 1, remaining - n, total + val * n, new_num)

    _enumerate(0, unknown_count, 0, 1)

    # known_counter で shift して総 pmf を構築
    pmf: dict[int, float] = {}
    for unknown_total, p in unknown_pmf.items():
        pmf[unknown_total + known_counter] = pmf.get(unknown_total + known_counter, 0.0) + p
    return pmf


def probability_counter_total_at_least(
    state: GameState, opp_idx: int, threshold: int,
) -> float:
    """opp 手札の counter 合計が threshold 以上である確率 (Phase 7B 追加)。

    リーサル判定で「相手がこのダメージを止められる確率」 として使う:
        P_block = P(counter_total >= damage)
        P_lethal = 1 - P_block

    threshold ≤ 0 なら 1.0 (= 常に成立)。
    """
    if threshold <= 0:
        return 1.0
    pmf = counter_total_pmf(state, opp_idx)
    return sum(p for total, p in pmf.items() if total >= threshold)


def counter_total_quantile(
    state: GameState, opp_idx: int, q: float,
) -> int:
    """opp 手札の counter 合計の q-分位点 (Phase 7B 追加)。

    Returns: 「累積確率 q 以上に達する最小の counter 合計値」。
    例: q=0.5 で中央値、 q=0.9 で 「90% の確率でこれ以下」 (= 強気の見積)。

    プール空 / 手札空: 0 を返す。
    """
    q = max(0.0, min(1.0, q))
    pmf = counter_total_pmf(state, opp_idx)
    if not pmf:
        return 0
    sorted_totals = sorted(pmf.keys())
    cumulative = 0.0
    for total in sorted_totals:
        cumulative += pmf[total]
        if cumulative >= q:
            return total
    return sorted_totals[-1]


def estimate_hand(state: GameState, opp_idx: int) -> EstimatedHand:
    """opp.hand を直視せず、 公開情報のみから期待値推定。 分布値込み (Phase 7B)。"""
    opp = state.players[opp_idx]
    per_card = expected_counter_per_card(state, opp_idx)
    pmf = counter_total_pmf(state, opp_idx)
    q50 = counter_total_quantile(state, opp_idx, 0.5)
    q90 = counter_total_quantile(state, opp_idx, 0.9)
    return EstimatedHand(
        hand_count=len(opp.hand),
        counter_per_card=per_card,
        counter_total=int(per_card * len(opp.hand)),
        blocker_prob=probability_of_blocker_in_hand(state, opp_idx),
        counter_pmf=pmf,
        counter_q50=q50,
        counter_q90=q90,
    )


def sample_opponent_hand(
    state: GameState,
    opp_idx: int,
    rng: Optional[random.Random] = None,
) -> list[CardDef]:
    """opp の hand_count 枚を deck + hand プールから無作為にサンプル。

    決定論的 AI の評価では opp.hand を見ずに、 残カードから推定したいケースで使う。
    プール = opp.deck (山札) + opp.hand (= 既に手札にあるが非公開と仮定して plundered)
    実際には deck だけでなく現 hand も対象に含めたい (= 50枚デッキ完成形のうち場/トラッシュ以外)。
    """
    if rng is None:
        rng = state.rng or random.Random()
    opp = state.players[opp_idx]
    pool = list(opp.deck) + list(opp.hand)
    n = min(len(opp.hand), len(pool))
    if n == 0:
        return []
    return rng.sample(pool, n)


def estimate_counter_total(state: GameState, opp_idx: int) -> int:
    """期待カウンター総量 (旧 API、 `expected_counter_total` へのエイリアス)。"""
    return expected_counter_total(state, opp_idx)


# Phase 7H: archetype 別 counter event 多用度 factor。
# 1.0 が基準。 アグロは counter event 少 → low、 コントロールは多 → high。
# bluff factor を 1.0 から離して掛けると、 「ブラフを ちぎる / 真に受ける」 判断が変わる:
#   < 1.0: bluff_counter 縮小 → effective_excess 増加 → リーサル成立しやすい (= ブラフ ちぎる)
#   > 1.0: bluff_counter 拡大 → effective_excess 縮小 → リーサル諦め (= 真に受ける)
_ARCHETYPE_BLUFF_FACTOR: dict[str, float] = {
    "アグロ": 0.4,         # アグロ系は counter event を入れず DON は攻撃用
    "ミッドレンジ": 0.7,   # 中量、 一部入れる
    "コントロール": 1.3,   # 受け重視、 counter event 多用
    "ランプ": 1.0,         # 中間
}


def archetype_bluff_factor(archetype: Optional[str]) -> float:
    """archetype 名から counter event 多用度 factor を返す (Phase 7H)。"""
    if not archetype:
        return 1.0
    return _ARCHETYPE_BLUFF_FACTOR.get(archetype, 1.0)


def _is_counter_event_card(card) -> bool:
    """カードが counter event (= opp アタック時に活用できる event) か判定 (Phase 7I)。

    判定基準: category == EVENT かつ counter > 0
    (= 通常 counter step に discard で打てる event は counter event とみなす)。
    """
    try:
        from .core import Category
        return card.category == Category.EVENT and card.counter > 0
    except Exception:
        return False


def expected_counter_from_don_bluff(
    state: GameState,
    opp_idx: int,
    don_value_per_unit: int = 1000,
    max_event_don: int = 2,
    use_archetype_factor: bool = True,
) -> int:
    """opp の visible active DON から counter event の期待寄与を見積 (Phase 7G + 7H + 7I)。

    OPTCG では event カード (= 「魔法のキャベツ」 等の counter event) が DON を消費して
    opp アタック時に発動できる。 visible active DON があれば、 これらの event を打たれる
    可能性が高まり、 リーサル計算の counter 総量推定 を上方修正する必要がある。

    Phase 7H: archetype 別の bluff factor を加味 (= アグロは低、 コントロールは高)。
    Phase 7I: known/unknown 分離。 既知に counter event があれば確定脅威 (= 1.0)、
              無ければ unknown 部分のみで確率推定。

    計算式 (Phase 7I 後):
        if 既知 hand に counter event があれば:
            P(counter event play) = 1.0  # 確定脅威
        elif unknown_count > 0:
            P = min(1.0, unknown_count × 0.1)
        else:
            P = 0.0  # 全 known で counter event 無し → bluff 無効
        expected_base = P × min(active_don, max_event_don) × don_value_per_unit
        expected = expected_base × archetype_factor

    Returns: 追加期待 counter 量 (= 0 以上の整数)
    """
    opp = state.players[opp_idx]
    visible_active_don = opp.don_active
    if visible_active_don <= 0:
        return 0
    hand_size = len(opp.hand)
    if hand_size == 0:
        return 0

    # Phase 7I: known cards に counter event があるか check
    known_event_count = 0
    matched_indices: set[int] = set()
    for cid in opp.known_hand_card_ids:
        for i, c in enumerate(opp.hand):
            if i in matched_indices:
                continue
            if c.card_id == cid:
                if _is_counter_event_card(c):
                    known_event_count += 1
                matched_indices.add(i)
                break
    known_count = len(matched_indices)
    unknown_count = hand_size - known_count

    if known_event_count > 0:
        # 既知 counter event 1+ あり → 確定脅威
        p_has_event = 1.0
    elif unknown_count > 0:
        # 未知部分にのみ counter event の可能性
        p_has_event = min(1.0, unknown_count * 0.1)
    else:
        # 全 known で counter event 無し → bluff 不発
        return 0

    usable_don = min(visible_active_don, max_event_don)
    expected = p_has_event * usable_don * don_value_per_unit

    if use_archetype_factor:
        # Phase 7H: archetype 別 factor を取得 (= matchup_model 経由で classifier 結果を使う)
        try:
            from . import matchup_model
            opp_archetype = matchup_model.infer_opponent_archetype(state, opp_idx)
            factor = archetype_bluff_factor(opp_archetype)
            expected *= factor
        except Exception:
            pass

    return int(expected)


def _is_lethal_counter_event(card) -> bool:
    """attacker を KO する counter event か判定 (= 雷迎相当)。

    判定基準: category == EVENT かつ counter > 0 かつ text に「アタック」 + 「KO/ＫＯ」 を含む。
    雷迎 (= OP09-077) 等の attacker KO 効果を拾う簡易判定。
    精度向上は Step 9 反復で card_effects.json primitive 解析に置換予定。
    """
    try:
        from .core import Category
        if card.category != Category.EVENT:
            return False
        if card.counter <= 0:
            return False
        text = card.text or ""
        return "アタック" in text and ("KO" in text or "ＫＯ" in text)
    except Exception:
        return False


def probability_life_trigger_lethal_counter(
    state: GameState,
    me_idx: int,
    n_attacks: int,
) -> float:
    """関数 8 (= 2026-05-16): n_attacks 回 leader にアタック時、 ライフトリガーで
    attacker KO される確率 (= 雷迎リスク)。

    計算: opp.life のうち未公開部分から「雷迎相当 counter event」 を引く確率を
    ハイパージオメトリックで算出。
    """
    if n_attacks <= 0:
        return 0.0

    opp_idx = 1 - me_idx
    opp = state.players[opp_idx]
    n_life_unknown = len(opp.life)
    if n_life_unknown == 0:
        return 0.0

    # opp.life + deck から「雷迎相当」 を引く想定 (= プール = deck + hand + life の未公開部分)
    pool = _opponent_pool(state, opp_idx)
    n_lethal = sum(1 for c in pool if _is_lethal_counter_event(c))
    if n_lethal == 0:
        return 0.0

    n_pool = len(pool)
    n_draw = min(n_attacks, n_life_unknown, n_pool)
    if n_pool < n_draw:
        return 1.0

    # ハイパージオメトリック: P(zero) = Π (n_pool - n_lethal - i) / (n_pool - i)
    p_zero = 1.0
    for i in range(n_draw):
        denom = n_pool - i
        if denom <= 0:
            return 1.0
        p_zero *= (n_pool - n_lethal - i) / denom
        if p_zero <= 0.0:
            return 1.0
    return 1.0 - p_zero


def update_belief_from_action(
    state: GameState,
    opp_idx: int,
    opp_action,
    prior_pmf: dict[int, float],
    n_samples: int = 200,
) -> dict[int, float]:
    """関数 12 (= 2026-05-16): opp の actual action 観測で counter pmf を Bayesian 更新。

    `P(hand | action) ∝ P(action | hand) × P(hand)` を MC sampling で近似。

    Args:
        state: GameState
        opp_idx: opp プレイヤー idx
        opp_action: 観測した opp の action
        prior_pmf: 既存の counter_total pmf (= counter_total_pmf 出力)
        n_samples: MC sample 数 (default 200)

    Returns:
        posterior_pmf (= {counter_total: probability})
        likelihood ≈ 0 なら prior_pmf をそのまま返す (= 更新失敗 fallback)。
    """
    import random as _random
    rng = state.rng or _random.Random()

    samples: list[tuple[list, float]] = []
    try:
        from . import opponent_action_model
    except Exception:
        return prior_pmf

    for _ in range(n_samples):
        hand_sample = sample_opponent_hand(state, opp_idx, rng)
        try:
            lk = opponent_action_model.action_likelihood(state, opp_idx, opp_action, hand_sample)
        except Exception:
            lk = 1.0 / 10  # uniform fallback
        samples.append((hand_sample, lk))

    total_weight = sum(lk for _, lk in samples)
    if total_weight <= 0:
        return prior_pmf  # 全 likelihood ≈ 0 → prior 維持

    posterior_pmf: dict[int, float] = {}
    for hand_sample, lk in samples:
        counter_total = sum(int(getattr(c, "counter", 0)) for c in hand_sample)
        posterior_pmf[counter_total] = posterior_pmf.get(counter_total, 0.0) + lk / total_weight

    return posterior_pmf


def determinize_state(
    state: GameState,
    opp_idx: int,
    rng: Optional[random.Random] = None,
) -> None:
    """state を「完全情報化」: opp.hand を deck からのランダムサンプルで置換。

    MCTSAI の rollout / Lookahead の評価で、 opp.hand を見ない (= 公正な) 探索に使う。
    呼出し前に state を deepcopy しておくこと (本物を壊さないため)。
    """
    if rng is None:
        rng = state.rng or random.Random()
    opp = state.players[opp_idx]
    pool = list(opp.deck) + list(opp.hand)
    n = len(opp.hand)
    if n == 0 or not pool:
        return
    sampled = rng.sample(pool, n)
    # 残りはデッキ
    remaining = [c for c in pool if c not in sampled]
    # rng.sample は順序ランダム、 remaining はデッキ底順 (= 元順序維持)
    opp.hand = sampled
    opp.deck = remaining
