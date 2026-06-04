# -*- coding: utf-8 -*-
"""人間vsAI UI 契約リンタ を CI ゲート化。

`scripts/lint_human_ui_contracts.py` を 毎 pytest で 実行し、 dead component /
未対応 pending kind / payload キー不一致 を 静的に 退行検出する (= ブロッカーの
dead DefenseOverlay・シュガーの cards/candidates 不一致 類型)。 headless fuzzer が
見られない React レンダリング層の契約を守る。
"""
from __future__ import annotations

import scripts.lint_human_ui_contracts as lint


def test_human_ui_contracts_clean():
    rc = lint.main()
    assert rc == 0, "UI 契約 違反あり (= 上の出力参照)。 dead component / kind 未対応 / payload キー不一致"
