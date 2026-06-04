# -*- coding: utf-8 -*-
"""人間経路のルール適合 CI ゲート (= ohtsuki 案: AI経路を正解に差分を見る、 の堅牢版)。

`scripts/diff_human_vs_ai_path.py` の run() で 人間経路の召喚解決を効果の制約
(filter/no_effect/unique_name/limit) に直接照合し、 違反0 を毎 pytest で保証する。

人間 modal 経路だけ制約が抜けるバグ class (unique_name/no_effect/limit/recompute) を
機械で退行検出する。 大規模 sweep は
`python scripts/diff_human_vs_ai_path.py <decks> <n>` で別途。
"""
from __future__ import annotations

import pytest

import scripts.diff_human_vs_ai_path as conf

# 召喚効果を踏みやすい代表 deck (= play_from_trash/hand 系を持つ)
CASES = [
    ("cardrush_1385", 5),   # play_from_trash
    ("cardrush_1455", 5),   # play_from_hand
    ("cardrush_1392", 4),   # イム / 五老星
    ("cardrush_1342", 5),   # target_pick (KO) 多い
    ("tcgportal_op13_luffy", 4),
]


@pytest.mark.parametrize("slug,n", CASES)
def test_human_path_summon_conformance(slug, n):
    """deck の n 試合を人間経路で走らせ、 召喚が効果の制約を全て守ること。"""
    divergences: list[dict] = []
    for s in range(n):
        conf.run(slug, 3000 + s, divergences)
    assert not divergences, (
        f"{slug}: 人間経路の制約違反 {len(divergences)} 件 "
        f"(例: {divergences[:3]})"
    )
