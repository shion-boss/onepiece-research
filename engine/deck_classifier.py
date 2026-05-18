# -*- coding: utf-8 -*-
"""
ベイズデッキ分類器 (Phase 7C / 2026-05-14)
==========================================

opp leader と 観測カード (= 場 / トラッシュ / ステージ 等) から、
相手のデッキ archetype の確率分布を推定する Naive Bayes 分類器。

学習データ:
- `decks/cardrush_*.json` + `decks/tcgportal_*.json` (= active 16 アーキタイプ)
- `decks/_archive/cardrush_raw/*.json` (= 過去 3 ヶ月の個別優勝 88+ 件)

合計 18 archetype × 106 recipe からカード採用率を学習。

## ベイズ式

```
P(archetype | obs) ∝ P(archetype) × Π P(obs_i | archetype)
```

- prior P(archetype): tcg-portal の使用率 (= meta-analysis ランキング由来)
- likelihood P(card | archetype): archetype 内 recipe での「カード採用率」
  = (採用 recipe 数 + α) / (recipe 総数 + 2α) Laplace smoothing

leader は **強い signal**: archetype の leader と一致なら 0.999、 不一致なら 0.001 の
likelihood で扱う (= 通常 1 archetype = 1 leader)。

## 公開 API

- `DeckClassifier.build(...)`: 学習 (= ディレクトリから recipes 読込)
- `DeckClassifier.classify(observed, leader)`: 確率分布を返す
- `DeckClassifier.classify_from_state(state, opp_idx)`: state から抽出 + classify
- `get_default_classifier()`: プロジェクト標準の lazy-init インスタンス
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import log
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .core import GameState

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# tcg-portal /meta-analysis 上位 16 + 過去 archetype の priors (= 2026-05-14 時点)。
# 値は使用率 (%) で渡す。 build() 内で正規化される。
# historical archetype (= 圏外) は 0.005 を default で割り当てる。
DEFAULT_PRIORS: dict[str, float] = {
    "紫エネル": 12.7,
    "赤青ルーシー": 11.3,
    "青黄ハンコック": 9.8,
    "青黄ナミ": 8.5,
    "黄ルフィ（OP15）": 5.4,
    "空島ルフィ": 5.4,           # cardrush 表記
    "緑ミホーク": 5.3,
    "赤青エース": 4.5,
    "黒イム": 3.6,
    "黒クロコダイル": 3.4,
    "紫ドフラミンゴ": 3.1,
    "青紫ルフィ": 2.5,
    "赤黄ボニー": 2.3,
    "黄カルガラ": 2.2,
    "赤緑ルフィ（OP13）": 2.2,
    "赤黒コビー": 2.0,
    "紫黄ロシナンテ": 2.0,
}

# 各 archetype の代表 archetype slug (= 公式準拠の primary 表記)。
# 重複 (= 空島ルフィ ↔ 黄ルフィ(OP15)) を内部的に統合するための alias。
ARCHETYPE_ALIASES: dict[str, str] = {
    "空島ルフィ": "黄ルフィ（OP15）",  # cardrush → tcg-portal 正規名
}


@dataclass
class DeckClassifier:
    """Naive Bayes デッキ分類器。

    学習: archetype 別 recipe からカード採用率を計算 (= Laplace smoothing)。
    推論: 観測カード + leader からベイズ更新で P(archetype | obs) を出力。

    Phase 8 拡張 (= 2026-05-16): leader 内 variant の 2 階層分類を追加。
    `classify_with_variant` で {leader_slug: {variant_id: P(variant | obs)}} を出す。
    """

    # P(archetype) prior (= 正規化済、 sum = 1.0)
    priors: dict[str, float] = field(default_factory=dict)
    # P(card_id | archetype) per archetype (Laplace smoothing 済)
    card_probs: dict[str, dict[str, float]] = field(default_factory=dict)
    # archetype → 代表 leader card_id
    archetype_leader: dict[str, str] = field(default_factory=dict)
    # vocab size (= 全 card_id の数、 smoothing 用)
    vocab_size: int = 0
    # 学習 recipe 数 (= 学習統計、 debug 用)
    n_recipes: int = 0

    # === Phase 8 (= 2026-05-16): variant 対応 ===
    # leader card_id → list of variant dicts (= variant_id, card_set, prior_share)
    variant_data: dict[str, list[dict]] = field(default_factory=dict)
    # leader card_id → leader_slug (= decks/<slug>/variant_*.json の slug 名)
    leader_slug_map: dict[str, str] = field(default_factory=dict)
    # P(card_id | variant) per (leader_id, variant_id)
    variant_card_probs: dict[str, dict[int, dict[str, float]]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        recipes_dirs: list[Path],
        priors: Optional[dict[str, float]] = None,
        alpha: float = 0.5,
        archetype_aliases: Optional[dict[str, str]] = None,
        historical_prior_pct: float = 0.5,
    ) -> "DeckClassifier":
        """ディレクトリ群から学習。

        Args:
            recipes_dirs: 走査するディレクトリのリスト
            priors: 指定 archetype → 使用率 (%)。 未指定なら均等
            alpha: Laplace smoothing 係数 (= 0.5 で軽い、 0 でも動く)
            archetype_aliases: archetype 名の正規化マップ (= 重複統合用)
            historical_prior_pct: priors 未登録の archetype に割り当てる使用率 (%)
        """
        aliases = archetype_aliases or {}

        # archetype → recipes 収集
        archetype_recipes: dict[str, list[dict]] = defaultdict(list)
        archetype_leaders: dict[str, set[str]] = defaultdict(set)

        for d in recipes_dirs:
            d_path = Path(d)
            if not d_path.exists():
                continue
            for p in sorted(d_path.glob("*.json")):
                if ".analysis" in p.name or p.name.startswith("_"):
                    continue
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                raw_arch = rec.get("name") or ""
                if not raw_arch:
                    continue
                # alias 正規化
                arch = aliases.get(raw_arch, raw_arch)
                archetype_recipes[arch].append(rec)
                leader = rec.get("leader")
                if leader:
                    archetype_leaders[arch].add(leader)

        if not archetype_recipes:
            return cls()

        # vocabulary
        all_cards: set[str] = set()
        for recipes in archetype_recipes.values():
            for rec in recipes:
                for c in rec.get("main", []):
                    cid = c.get("card_id", "")
                    if cid:
                        all_cards.add(cid)
                if rec.get("leader"):
                    all_cards.add(rec["leader"])
        vocab_size = len(all_cards)

        # P(card | archetype) 計算
        card_probs: dict[str, dict[str, float]] = {}
        for arch, recipes in archetype_recipes.items():
            denom = len(recipes)
            # 各 card_id の 「recipe 採用回数」 をカウント
            card_count: Counter[str] = Counter()
            for rec in recipes:
                seen = set()
                for c in rec.get("main", []):
                    cid = c.get("card_id", "")
                    if cid and cid not in seen:
                        card_count[cid] += 1
                        seen.add(cid)
            # Laplace smoothing: (count + alpha) / (denom + 2*alpha)
            probs: dict[str, float] = {}
            for cid in all_cards:
                count = card_count.get(cid, 0)
                probs[cid] = (count + alpha) / (denom + 2 * alpha)
            card_probs[arch] = probs

        # priors 構築
        actual_priors: dict[str, float] = {}
        if priors is None:
            for arch in archetype_recipes:
                actual_priors[arch] = 1.0
        else:
            # priors の archetype 名も alias 正規化
            normalized_priors = {
                aliases.get(k, k): v for k, v in priors.items()
            }
            for arch in archetype_recipes:
                actual_priors[arch] = normalized_priors.get(arch, historical_prior_pct)
        # 正規化
        total = sum(actual_priors.values())
        if total > 0:
            actual_priors = {k: v / total for k, v in actual_priors.items()}

        # archetype → 代表 leader (= 最初の leader を使用)
        archetype_leader_map: dict[str, str] = {}
        for arch, leaders in archetype_leaders.items():
            if leaders:
                archetype_leader_map[arch] = sorted(leaders)[0]

        return cls(
            priors=actual_priors,
            card_probs=card_probs,
            archetype_leader=archetype_leader_map,
            vocab_size=vocab_size,
            n_recipes=sum(len(r) for r in archetype_recipes.values()),
        )

    def classify(
        self,
        observed_card_ids: list[str],
        opp_leader_id: Optional[str] = None,
    ) -> dict[str, float]:
        """観測カード + opp leader から P(archetype | obs) を softmax で返す。

        Args:
            observed_card_ids: 観測カード ID リスト (= 場 / trash / stage 等)
            opp_leader_id: opp leader の card_id (= 強 signal)

        Returns:
            {archetype: probability} (sum = 1.0)。 学習データなしなら空 dict。
        """
        if not self.card_probs:
            return {}

        # log-likelihood + log-prior
        scores: dict[str, float] = {}
        for arch in self.card_probs:
            log_prior = log(max(self.priors.get(arch, 1e-9), 1e-9))
            log_lik = 0.0

            # leader は強い signal (= 0.999 / 0.001 の二値化)
            if opp_leader_id:
                expected_leader = self.archetype_leader.get(arch)
                if expected_leader:
                    if opp_leader_id == expected_leader:
                        log_lik += log(0.999)
                    else:
                        log_lik += log(0.001)

            # 観測カードごとに likelihood 加算
            for cid in observed_card_ids:
                p_card = self.card_probs[arch].get(cid)
                if p_card is None:
                    # vocab 外 (= 学習データに無いカード): smoothing と同じ低確率
                    p_card = 0.005
                log_lik += log(max(p_card, 1e-9))

            scores[arch] = log_prior + log_lik

        # softmax (numerically stable)
        max_score = max(scores.values())
        exp_scores = {arch: math.exp(s - max_score) for arch, s in scores.items()}
        total = sum(exp_scores.values())
        if total == 0:
            n = len(scores)
            return {arch: 1.0 / n for arch in scores}
        return {arch: v / total for arch, v in exp_scores.items()}

    def classify_from_state(
        self,
        state: "GameState",
        opp_idx: int,
    ) -> dict[str, float]:
        """state から opp の可視カードを抽出 → classify。

        可視カード:
        - opp.characters (= 場のキャラ)
        - opp.stages
        - opp.trash (= 公開済)
        - opp.leader (= 強 signal)

        手札 / デッキ底 / 未公開ライフは含めない。
        """
        opp = state.players[opp_idx]
        observed: list[str] = []
        for ip in opp.characters:
            observed.append(ip.card.card_id)
        for ip in opp.stages:
            observed.append(ip.card.card_id)
        for c in opp.trash:
            observed.append(c.card_id)
        opp_leader_id = opp.leader.card.card_id if opp.leader else None
        return self.classify(observed, opp_leader_id=opp_leader_id)

    def load_variants(
        self,
        status_path: Optional[Path] = None,
        decks_root: Optional[Path] = None,
        alpha: float = 0.5,
    ) -> None:
        """variant データを `db/data_layer_64_status.json` + `decks/<slug>/variant_*.json` から学習。

        Phase 8 (= 2026-05-16) ユーザ要件で追加。 既存 archetype 学習を壊さず、
        leader 内の variant 識別のため P(card | variant) を別途学習する。

        各 variant は 1 recipe (= medoid 代表) から学習するので、 card 採用は binary。
        Laplace smoothing で 0/1 確率を回避: 採用 = (1+α)/(1+2α)、 未採用 = α/(1+2α)。
        """
        if status_path is None:
            status_path = _PROJECT_ROOT / "db" / "data_layer_64_status.json"
        if decks_root is None:
            decks_root = _PROJECT_ROOT / "decks"

        if not status_path.exists():
            return

        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            return

        leaders_status = status.get("leaders", {})
        for leader_id, info in leaders_status.items():
            slug = info.get("slug")
            n_variants = info.get("n_variants", 0)
            if not slug or n_variants <= 0:
                continue

            self.leader_slug_map[leader_id] = slug
            variant_list: list[dict] = []
            variant_probs: dict[int, dict[str, float]] = {}

            for vid in range(n_variants):
                vpath = decks_root / slug / f"variant_{vid}.json"
                if not vpath.exists():
                    continue
                try:
                    vrec = json.loads(vpath.read_text(encoding="utf-8"))
                except Exception:
                    continue

                card_set: set[str] = set()
                for entry in vrec.get("main", []):
                    cid = entry.get("card_id")
                    if cid:
                        card_set.add(cid)

                variant_list.append({
                    "variant_id": vid,
                    "card_set": card_set,
                    "size": vrec.get("cluster_size", 1),
                    "source": vrec.get("source", "unknown"),
                })

                # P(card | variant) = Laplace smoothing
                probs: dict[str, float] = {}
                # 採用カード
                in_prob = (1.0 + alpha) / (1.0 + 2.0 * alpha)
                out_prob = alpha / (1.0 + 2.0 * alpha)
                for cid in card_set:
                    probs[cid] = in_prob
                # vocab 全体に対する default は out_prob (= classify 時 fallback)
                probs["__default__"] = out_prob
                variant_probs[vid] = probs

            if variant_list:
                self.variant_data[leader_id] = variant_list
                self.variant_card_probs[leader_id] = variant_probs

    def classify_with_variant(
        self,
        observed_card_ids: list[str],
        opp_leader_id: str,
    ) -> dict[int, float]:
        """opp leader が指定された時、 同 leader 内の variant 確率分布を返す。

        Phase 8 (= 2026-05-16): 関数 7 `classify_with_variant` 実装。

        Returns:
            {variant_id: P(variant | observations, leader)}
            学習データなし / leader 未登録なら空 dict。
        """
        if opp_leader_id not in self.variant_card_probs:
            return {}

        variants = self.variant_data.get(opp_leader_id, [])
        probs_per_variant = self.variant_card_probs[opp_leader_id]

        if not variants:
            return {}
        # variant prior = uniform (= 学習データなし、 将来 self-play で更新)
        # cluster_size に応じた weighting (= archive 由来の variant は size > 1)
        sizes = {v["variant_id"]: max(v["size"], 1) for v in variants}
        size_sum = sum(sizes.values())
        priors_v = {vid: s / size_sum for vid, s in sizes.items()}

        # log-likelihood + log-prior
        scores: dict[int, float] = {}
        for v in variants:
            vid = v["variant_id"]
            log_prior = log(max(priors_v[vid], 1e-9))
            log_lik = 0.0
            v_probs = probs_per_variant[vid]
            default_p = v_probs.get("__default__", 0.1)
            for cid in observed_card_ids:
                p = v_probs.get(cid, default_p)
                log_lik += log(max(p, 1e-9))
            scores[vid] = log_prior + log_lik

        # softmax (numerically stable)
        max_score = max(scores.values())
        exp_scores = {vid: math.exp(s - max_score) for vid, s in scores.items()}
        total = sum(exp_scores.values())
        if total == 0:
            n = len(scores)
            return {vid: 1.0 / n for vid in scores}
        return {vid: v / total for vid, v in exp_scores.items()}

    def classify_with_variant_from_state(
        self,
        state: "GameState",
        opp_idx: int,
    ) -> dict[int, float]:
        """state から observed_cards + opp_leader を抽出して classify_with_variant 呼出。"""
        opp = state.players[opp_idx]
        if not opp.leader:
            return {}
        opp_leader_id = opp.leader.card.card_id
        observed: list[str] = []
        for ip in opp.characters:
            observed.append(ip.card.card_id)
        for ip in opp.stages:
            observed.append(ip.card.card_id)
        for c in opp.trash:
            observed.append(c.card_id)
        return self.classify_with_variant(observed, opp_leader_id)

    def top_archetype(
        self,
        observed_card_ids: list[str],
        opp_leader_id: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> Optional[tuple[str, float]]:
        """最も確率の高い archetype と確率を返す (= 信頼度フィルタ付き)。

        min_confidence 以上の確率が無ければ None。
        """
        probs = self.classify(observed_card_ids, opp_leader_id)
        if not probs:
            return None
        best_arch, best_prob = max(probs.items(), key=lambda x: x[1])
        if best_prob < min_confidence:
            return None
        return best_arch, best_prob


# プロジェクト標準のキャッシュ済 classifier
_DEFAULT_CLASSIFIER: Optional[DeckClassifier] = None


def get_default_classifier() -> DeckClassifier:
    """プロジェクト標準の DeckClassifier (= lazy init + cache)。

    learning data:
    - decks/cardrush_*.json + decks/tcgportal_*.json (= active 16)
    - decks/_archive/cardrush_raw/cardrush_*.json (= 過去 88+ 件)

    priors = DEFAULT_PRIORS (= tcg-portal 上位 16 + historical 0.5%)
    """
    global _DEFAULT_CLASSIFIER
    if _DEFAULT_CLASSIFIER is not None:
        return _DEFAULT_CLASSIFIER

    decks_dir = _PROJECT_ROOT / "decks"
    archive_dir = _PROJECT_ROOT / "decks" / "_archive" / "cardrush_raw"

    _DEFAULT_CLASSIFIER = DeckClassifier.build(
        recipes_dirs=[decks_dir, archive_dir],
        priors=DEFAULT_PRIORS,
        alpha=0.5,
        archetype_aliases=ARCHETYPE_ALIASES,
    )
    # Phase 8 (= 2026-05-16): variant データ load
    _DEFAULT_CLASSIFIER.load_variants()
    return _DEFAULT_CLASSIFIER


def reset_default_classifier() -> None:
    """キャッシュリセット (= test / refresh 用)。"""
    global _DEFAULT_CLASSIFIER
    _DEFAULT_CLASSIFIER = None
