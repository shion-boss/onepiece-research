# -*- coding: utf-8 -*-
"""
公式 FAQ (cardqa) を期待値とする統合テスト雛形
==============================================

長期プロジェクト 「全 4,518 枚を公式通り動かす」 の一部として、 公式 Q&A の
回答を engine 実装の **期待値** に変換するためのテスト雛形を提供する。

各テストは現状 ``pytest.skip("placeholder — implementation pending")`` で
スキップされ、 後続フェーズで個別に Arrange / Act / Assert を実装していく。

設計方針
--------
- ``scripts/extract_faq_test_cases.extract_test_cases`` で 200 件抽出 →
  ``@pytest.mark.parametrize`` で個別 test 関数化。
- 各 test は ``case_id`` で識別可能 (例: ``op_15#042``)。
- テスト ID にトップタグを混ぜることで pytest -k "negation" 等での絞り込みが効く。
- cardqa が見つからない環境 (worktree 等、 ``db/faq/*.json`` が gitignore) では、
  モジュール collect 時に全件 skip する (既存テストを壊さない)。

公式テキスト忠実主義
--------------------
CLAUDE.md より:
    自動近似 / fallback **禁止**。 cardqa の回答に書かれていることを誠実に
    assertion 化する。 解釈不可な効果は ``[]`` (空) もしくは ``_unimplemented``
    でマークする。

→ 実装時は ``a`` の文面を assertion へ翻訳する。 例:
    A: 「いいえ、 されません。」  → ``assert <effect_did_not_fire>``
    A: 「はい、 されます。」      → ``assert <effect_fired>``
    A: 長文の解説               → 解説に書かれた状態が再現できているか確認

参照
----
- ``scripts/extract_faq_test_cases.py``: 抽出ロジック / CLI / スコアリング
- ``db/faq/cardqa_*.json``: 公式 Q&A 一次情報 (gitignore 済み、 scraper 取得)
- ``db/faq/INDEX.md``: cardqa の弾別 件数一覧
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# プロジェクトルートを sys.path に通す (conftest.py と同じ。 import の安定化)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.extract_faq_test_cases import (  # noqa: E402
    FaqCase,
    extract_test_cases,
)


# テストケース全件 (モジュール collect 時に 1 度だけロード)
# limit=200 は task で指定された目標サイズ。 後で 500 にしたいときは
# ``FAQ_TEST_LIMIT`` 環境変数で上書き可能 (将来の拡張用)。
import os  # noqa: E402

_LIMIT = int(os.environ.get("FAQ_TEST_LIMIT", "200"))
_CASES: list[FaqCase] = extract_test_cases(limit=_LIMIT)


def _case_id(case: FaqCase) -> str:
    """pytest -k で読みやすい ID を生成。

    例: ``op_15-042-negation_trigger_timing`` (全タグ underscore 結合)。
    こうしておくと ``pytest -k "negation"`` や ``pytest -k "trigger_timing"`` で
    タグ別の placeholder を絞り込めるようになる。
    """
    tag_str = "_".join(case.tags) if case.tags else "untagged"
    safe_slug = case.case_id.replace("#", "-").replace("/", "-")
    return f"{safe_slug}-{tag_str}"


# 雛形なので parametrize を 1 つにまとめる。
# 200 個の individual test ID が pytest 上で列挙される。
_pytest_params = (
    [
        pytest.param(c, id=_case_id(c))
        for c in _CASES
    ]
    if _CASES
    else [
        pytest.param(
            None,
            id="_no_cardqa_available",
            marks=pytest.mark.skip(
                reason=(
                    "cardqa が見つかりません (db/faq/cardqa_*.json)。 "
                    "scraper/scrape_official_faq.py で取得してください。"
                )
            ),
        )
    ]
)


@pytest.mark.parametrize("case", _pytest_params)
def test_faq_case(case: FaqCase | None) -> None:
    """単一の cardqa エントリを期待値とする統合テスト雛形。

    現状は ``pytest.skip`` で placeholder。 後続フェーズで個別実装:

    1. **Arrange**: ``case.series_slug`` / ``case.q`` から問題のカード文脈を再現:
        - リーダーを選択 (シリーズの代表 leader を使うか、 Q 中の「特徴」 から推定)
        - 手札 / トラッシュ / ライフ等を Q の条件節に合わせてセットアップ
        - ``case.referenced_card_ids`` が空でなければ、 そのカードを場 / 手札に配置
    2. **Act**: 該当タイミング (登場時 / アタック時 等) を発火:
        - ``engine.effects.trigger_on_play`` / ``fire_activate_main`` 等を呼ぶ
        - またはルールエンジンの相当する遷移を実行 (``engine.game.apply_action``)
    3. **Assert**: ``case.a`` の主張と実 state を突合:
        - 「いいえ、 ~ されません。」  → 期待される副作用が **発生していない** ことを確認
        - 「はい、 ~ されます。」      → 期待される副作用が **発生している** ことを確認
        - 長文回答は 「~の場合は X、 ~の場合は Y」 のような分岐を 個別 case で検証

    case_id: cardqa の安定 ID (例: ``op_15#042``)。
    """
    if case is None:
        pytest.skip("no cardqa loaded")

    # ---- 実装時のヒント (現状はコメントのみ) -------------------
    # tags = case.tags
    # q, a = case.q, case.a
    # repo = CardRepository.from_json(_ROOT / "db" / "cards.json")
    # overlay = load_effect_overlay(_ROOT / "db" / "card_effects.json")
    # state = _build_state_from_case(case, repo, overlay)
    # _act(state, case)
    # _assert_matches_official_answer(state, case)
    # ------------------------------------------------------

    pytest.skip("placeholder — implementation pending")


# ---------------------------------------------------------------- #
# メタテスト: 抽出ロジックが期待通り 200 件を返すこと
# (placeholder が空のときの sanity check)
# ---------------------------------------------------------------- #


def test_faq_extract_returns_expected_count() -> None:
    """``extract_test_cases(limit=200)`` が 0 or 200 件を返す。

    - cardqa が利用不可な環境 (worktree / 初回 clone 直後 等) では 0 件で skip。
    - 利用可能な環境では 200 件 (重複なし) が返る。
    """
    cases = extract_test_cases(limit=200)
    if not cases:
        pytest.skip("cardqa unavailable (db/faq/cardqa_*.json missing)")

    assert len(cases) == 200, f"expected 200 cases, got {len(cases)}"

    # case_id が unique
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case_id detected"

    # 全件で q と a が非空
    for c in cases:
        assert c.q, f"empty q for {c.case_id}"
        assert c.a, f"empty a for {c.case_id}"
        assert c.tags, f"untagged case sneaked in: {c.case_id}"


def test_faq_extract_is_stable() -> None:
    """同じ入力で extract_test_cases が同じ順序を返すこと (再現性)。"""
    cases1 = extract_test_cases(limit=50)
    cases2 = extract_test_cases(limit=50)
    if not cases1:
        pytest.skip("cardqa unavailable")
    assert [c.case_id for c in cases1] == [c.case_id for c in cases2]


def test_faq_extract_respects_limit() -> None:
    """limit パラメータが効くこと。"""
    cases_50 = extract_test_cases(limit=50)
    cases_100 = extract_test_cases(limit=100)
    if not cases_50:
        pytest.skip("cardqa unavailable")
    assert len(cases_50) == 50
    assert len(cases_100) == 100
    # スコア降順なので先頭 50 件は一致する筈
    assert [c.case_id for c in cases_50] == [c.case_id for c in cases_100[:50]]
