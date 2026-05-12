# -*- coding: utf-8 -*-
"""
FAQ (cardqa) から統合テスト用のケース雛形を抽出するスクリプト
==============================================================

目的
----
公式 cardqa (`db/faq/cardqa_*.json`、 約 2,500 件) の Q&A から、
「期待値ベースのテストに変換しやすい」 代表 N 件を抽出し、 構造化された
JSON / Python リストとして提供する。

`tests/test_faq_integration.py` がこのスクリプトをインポートして
pytest.parametrize 経由で雛形テスト関数を生成する。
スクリプトを CLI として実行すれば JSON ファイル出力も可能。

選定方針
--------
1. **テキスト由来 only**: cardqa の各エントリは公式テキスト忠実主義に基づく一次情報。
   自動近似 / fallback は禁止 (CLAUDE.md)。 したがってここでは「公式回答に
   書かれていることを誠実に assertion 化する」 ための候補抽出のみを行う。
2. **タグ付け**: 各エントリに以下のタグを付与:
     - ``trigger_timing``: 【登場時】【アタック時】【KO時】【起動メイン】 等を質問が問う
     - ``condition``: 「リーダーが特徴X」 「ライフY以下」 等の条件節
     - ``negation``: 「いいえ」 から始まる否定回答 (誤実装検出に強い)
     - ``affirmation``: 「はい」 から始まる肯定回答
     - ``keyword``: 速攻 / ブロッカー / ダブルアタック 等のキーワード効果
     - ``exception``: 「~の場合は」 「~の時は」 等の例外規定
     - ``timing``: 「~の前に」 「~の後に」 「同時に」 等の解決順
3. **スコアリング**: タグの組合せでスコア。 短い明快な回答ほど高得点
   (「いいえ、できません。」 のような <15 字回答にボーナス)。
4. **多様性**: シリーズ単位で均等割当 (1 series あたり最大 N/series_count を超えないよう
   バランスを取る)。 単一シリーズに集中しないことで、 幅広いカード効果をカバー。

利用例
------
.. code-block:: bash

    # 200 件抽出して JSON ダンプ
    .venv/bin/python scripts/extract_faq_test_cases.py --limit 200 --dump out.json

    # 詳細統計を表示
    .venv/bin/python scripts/extract_faq_test_cases.py --limit 200 --stats

.. code-block:: python

    # テストから呼び出す
    from scripts.extract_faq_test_cases import extract_test_cases
    cases = extract_test_cases(limit=200)
    for c in cases:
        ...  # c["case_id"], c["q"], c["a"], c["tags"], ...

設計メモ
--------
- 関連 card_id は **基本付与しない**。 cardqa の Q は 「このリーダー」 「このキャラ」 を
  指す implicit 文脈で、 公式 HTML にはエントリ単位の card_id 紐付けが無い (= 1 ページ ≒ 1 弾の
  全カード Q&A をまとめて掲載)。 ただし Q/A 中に明示された card_id (例: 「OP05-119」) は
  ``referenced_card_ids`` フィールドに記録する。
- ``case_id`` は ``{series_slug}#{idx:03d}`` 形式で安定 (cardqa の items 順序が変わらない限り)。
- 後で 200 → 500 への拡張は ``--limit 500`` を指定するだけ。 スコア順なので増減は線形。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

# プロジェクトルート (worktree でも main repo でも動く)
ROOT = Path(__file__).resolve().parent.parent

# cardqa 探索順:
#   1. <ROOT>/db/faq/cardqa_*.json
#   2. <ROOT>/../../../db/faq/cardqa_*.json  (worktree の場合、 親 repo を fallback)
_FAQ_CANDIDATE_DIRS = [
    ROOT / "db" / "faq",
    ROOT.parent.parent.parent / "db" / "faq",
]


def _locate_faq_dir() -> Path | None:
    """cardqa_*.json が実在する FAQ ディレクトリを探す。

    Returns:
        Path or None: 見つからない場合は None。
    """
    for d in _FAQ_CANDIDATE_DIRS:
        try:
            if d.is_dir() and any(d.glob("cardqa_*.json")):
                return d
        except OSError:
            continue
    return None


# ---------------------------------------------------------------- #
# タグ判定 (Q+A テキストから抽出)
# ---------------------------------------------------------------- #

# トリガータイミング (【...時】 系)
TRIGGER_TAGS_PAT = re.compile(
    r"【(登場時|アタック時|KO時|起動メイン|ターン終了時|ターン開始時|ブロック時|"
    r"相手のアタック時|相手のターン中|自分のターン中|自分のターン終了時|トリガー)】"
)

# キーワード効果
KEYWORD_TAGS_PAT = re.compile(
    r"【(速攻|速攻：キャラ|ブロッカー|ダブルアタック|バニッシュ|ブロック不可|"
    r"カウンター|メイン|ターン1回)】"
)

# 条件節シグナル
CONDITION_PATTERNS = [
    re.compile(r"特徴《[^》]+》"),                  # 特徴《麦わらの一味》 等
    re.compile(r"ライフ[0-9０-９]+(枚|以下|以上)"),  # ライフ3以下 等
    re.compile(r"手札[0-9０-９]+(枚|以下|以上)"),
    re.compile(r"自分のキャラ[0-9０-９]+枚"),
    re.compile(r"相手のキャラ[0-9０-９]+枚"),
    re.compile(r"コスト[0-9０-９]+(以上|以下)"),
    re.compile(r"パワー[0-9０-９]+(以上|以下)"),
    re.compile(r"元々のコスト[0-9０-９]+(以上|以下)"),
    re.compile(r"元々のパワー[0-9０-９]+(以上|以下)"),
]

# 例外 / 解決順シグナル
EXCEPTION_PATTERNS = [
    re.compile(r"の場合は"),
    re.compile(r"の時は"),
    re.compile(r"~の前に|~の後に"),
    re.compile(r"同時に"),
    re.compile(r"打ち消され?"),
    re.compile(r"無効になる"),
]

# card_id 抽出 (Q/A 中の明示参照)
CARD_ID_PAT = re.compile(r"\b((?:OP|ST|EB|PRB)\d{2}-\d{3,4}|P-\d{3,4})\b")


def _classify(q: str, a: str) -> list[str]:
    """Q+A テキストにタグを付ける。 重複なしのソート済リストを返す。"""
    tags: set[str] = set()

    text = q + "\n" + a

    if TRIGGER_TAGS_PAT.search(text):
        tags.add("trigger_timing")
    if KEYWORD_TAGS_PAT.search(text):
        tags.add("keyword")
    if any(p.search(text) for p in CONDITION_PATTERNS):
        tags.add("condition")
    if any(p.search(text) for p in EXCEPTION_PATTERNS):
        tags.add("exception")

    a_stripped = a.strip()
    if a_stripped.startswith("いいえ"):
        tags.add("negation")
    if a_stripped.startswith("はい"):
        tags.add("affirmation")

    # 解決順タイミング (前後/同時)
    if re.search(r"(前に|後に|順番|同時に)", q):
        tags.add("timing_order")

    return sorted(tags)


# ---------------------------------------------------------------- #
# 重み付け / スコアリング
# ---------------------------------------------------------------- #

# テストに変換しやすい優先度 (= 高スコア):
#   - 短い回答 (= 二択的、 assertion 化が容易)
#   - 否定回答 (= 誤実装検出力が高い)
#   - 複数タグを持つ (= 文脈情報が豊富)
TAG_WEIGHTS = {
    "trigger_timing": 3,
    "condition": 3,
    "negation": 4,
    "affirmation": 2,
    "keyword": 2,
    "exception": 2,
    "timing_order": 3,
}


def _score(q: str, a: str, tags: list[str]) -> int:
    """テストケースとしての適合度スコア (大きいほど良い)。"""
    score = sum(TAG_WEIGHTS.get(t, 0) for t in tags)

    a_stripped = a.strip()
    # 短い明快な回答ほどテスト化しやすい
    if len(a_stripped) <= 20:
        score += 3
    elif len(a_stripped) <= 60:
        score += 1
    # 長すぎる Q (200 字超え) はコンテキストが重く解釈難
    if len(q) >= 250:
        score -= 2

    # 「~ですか？」 で終わる Q は二択型 → 高得点
    if q.rstrip().endswith("ですか？") or q.rstrip().endswith("か？"):
        score += 1

    return score


# ---------------------------------------------------------------- #
# データクラス
# ---------------------------------------------------------------- #

@dataclass
class FaqCase:
    case_id: str                       # "<series_slug>#<idx>"
    series: str                        # 「ブースターパック ROMANCE DAWN【OP-01】」
    series_slug: str                   # "op_01"
    idx: int                           # cardqa items 内 0-origin index
    q: str
    a: str
    tags: list[str] = field(default_factory=list)
    score: int = 0
    referenced_card_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- #
# メイン抽出ロジック
# ---------------------------------------------------------------- #

def _load_all_cardqa(faq_dir: Path) -> list[FaqCase]:
    """cardqa_*.json から全エントリを FaqCase へ変換。"""
    out: list[FaqCase] = []
    for path in sorted(faq_dir.glob("cardqa_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # cardqa_.json は promo (P-...) を含む。 series_slug は stem からとる
        stem = path.stem  # "cardqa_op_15"
        slug = stem[len("cardqa_") :] if stem.startswith("cardqa_") else stem
        series = data.get("series") or data.get("series_slug") or slug

        for idx, item in enumerate(data.get("items", [])):
            q = (item.get("q") or "").strip()
            a = (item.get("a") or "").strip()
            if not q or not a:
                continue
            tags = _classify(q, a)
            score = _score(q, a, tags)
            referenced = sorted(set(CARD_ID_PAT.findall(q + " " + a)))
            out.append(
                FaqCase(
                    case_id=f"{slug or '_promo'}#{idx:03d}",
                    series=series,
                    series_slug=slug or "_promo",
                    idx=idx,
                    q=q,
                    a=a,
                    tags=tags,
                    score=score,
                    referenced_card_ids=referenced,
                )
            )
    return out


#: 1 シリーズあたりの上限 (limit に依存しない固定値)。
#: 200 件抽出時に 1 弾が極端に偏らないよう、 20 件/弾 を上限とする
#: (54 弾あるので 200 件は埋まる)。 500 件に増やしても同じ上限を使う設計。
MAX_PER_SERIES = 20


def _balance_by_series(
    cases: list[FaqCase], limit: int, max_per_series: int = MAX_PER_SERIES
) -> list[FaqCase]:
    """シリーズ別に上限を設けつつスコア順に選定。

    Args:
        cases: スコア順 (降順) にソート済の候補。
        limit: 出力件数。
        max_per_series: 1 シリーズあたりの最大採用件数 (limit に依存しない固定値)。
                        ``MAX_PER_SERIES`` がデフォルト。

    Returns:
        選ばれた FaqCase リスト (スコア順 維持)。

    Note:
        ``max_per_series`` を ``limit`` に対する比率で動的に決めると
        ``extract(50)`` と ``extract(100)[:50]`` の順序が変わるため、 安定性のため
        固定値を採用している。
    """
    selected: list[FaqCase] = []
    series_count: dict[str, int] = {}

    for case in cases:
        if len(selected) >= limit:
            break
        slug = case.series_slug
        if series_count.get(slug, 0) >= max_per_series:
            continue
        selected.append(case)
        series_count[slug] = series_count.get(slug, 0) + 1
    return selected


def extract_test_cases(
    limit: int = 200,
    faq_dir: Path | None = None,
    min_tags: int = 1,
) -> list[FaqCase]:
    """cardqa から limit 件のテストケース候補を抽出する。

    Args:
        limit: 出力件数 (デフォルト 200)。
        faq_dir: cardqa 配置ディレクトリ。 None の場合は自動探索。
        min_tags: タグが min_tags 個未満のエントリは除外。

    Returns:
        スコア順 (降順) の FaqCase リスト。 cardqa が存在しない場合は空リスト。
    """
    target_dir = faq_dir or _locate_faq_dir()
    if target_dir is None:
        return []

    all_cases = _load_all_cardqa(target_dir)
    # min_tags でフィルタ
    filtered = [c for c in all_cases if len(c.tags) >= min_tags]
    # スコア降順 → 同点は case_id 昇順 (安定ソート)
    filtered.sort(key=lambda c: (-c.score, c.case_id))
    return _balance_by_series(filtered, limit=limit)


# ---------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------- #

def _print_stats(cases: list[FaqCase]) -> None:
    from collections import Counter

    print(f"  選定件数: {len(cases)}")
    tag_count: Counter[str] = Counter()
    series_count: Counter[str] = Counter()
    for c in cases:
        for t in c.tags:
            tag_count[t] += 1
        series_count[c.series_slug] += 1
    print("  タグ別:")
    for k, v in tag_count.most_common():
        print(f"    {k:18s}  {v}")
    print("  シリーズ別 (top 10):")
    for k, v in series_count.most_common(10):
        print(f"    {k:14s}  {v}")
    score_max = max((c.score for c in cases), default=0)
    score_min = min((c.score for c in cases), default=0)
    print(f"  スコア range: {score_min} ~ {score_max}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=200, help="抽出件数 (デフォルト 200)")
    p.add_argument(
        "--min-tags",
        type=int,
        default=1,
        help="このタグ数未満のエントリを除外 (デフォルト 1)",
    )
    p.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="JSON 出力先パス (省略時は stdout に統計のみ)",
    )
    p.add_argument("--stats", action="store_true", help="統計を表示")
    p.add_argument(
        "--faq-dir",
        type=Path,
        default=None,
        help="cardqa ディレクトリ (省略時は自動探索)",
    )
    args = p.parse_args(argv)

    cases = extract_test_cases(
        limit=args.limit, faq_dir=args.faq_dir, min_tags=args.min_tags
    )
    if not cases:
        print(
            "[warn] cardqa が見つからない、 または条件にマッチするエントリがありません。",
            file=sys.stderr,
        )
        print(
            f"[hint] 探索した candidate: {[str(d) for d in _FAQ_CANDIDATE_DIRS]}",
            file=sys.stderr,
        )
        return 1

    if args.stats:
        _print_stats(cases)

    if args.dump:
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        args.dump.write_text(
            json.dumps([c.to_dict() for c in cases], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[ok] {len(cases)} cases written to {args.dump}")
    elif not args.stats:
        # 何も指定が無ければ最初の 5 件をプレビュー
        print(f"[ok] {len(cases)} cases extracted (top 5 preview):")
        for c in cases[:5]:
            print(f"  - {c.case_id} score={c.score} tags={c.tags}")
            print(f"      Q: {c.q[:80]}")
            print(f"      A: {c.a[:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
