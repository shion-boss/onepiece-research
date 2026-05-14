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
    return _DEFAULT_CLASSIFIER


def reset_default_classifier() -> None:
    """キャッシュリセット (= test / refresh 用)。"""
    global _DEFAULT_CLASSIFIER
    _DEFAULT_CLASSIFIER = None
