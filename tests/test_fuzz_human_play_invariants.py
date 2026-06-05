# -*- coding: utf-8 -*-
"""人間vsAI ファズ不変条件 を CI ゲート化 (= 機械がプレイして断言する)。

`scripts/fuzz_human_play.py` の play_one を 少数 game 決定論的に走らせ、
カード保存則 (INV1) / instance_id 重複なし (INV2) / crash/stuck/NO_ACT が
無いことを 毎 pytest で 検証する。 人間の目視に頼らず、 状態破壊バグの退行を
即捕捉する (= シュガー複製・search 欠落クラス)。

大規模 sweep は `python scripts/fuzz_human_play.py 200` で別途。 ここは速度優先の
ゲート (= 決定論的な少数 game)。
"""
from __future__ import annotations

import random

import pytest

import scripts.fuzz_human_play as fz


@pytest.fixture(scope="module", autouse=True)
def _setup_repo():
    fz._setup()


# 決定論的な (deck_a, deck_b, seed) ケース (= 多色 + 効果リッチを選ぶ)
CASES = [
    ("cardrush_1342", "cardrush_1385", 1001, True),
    ("tcgportal_op13_luffy", "tcgportal_hancock", 1002, False),
    ("cardrush_1392", "tcgportal_coby", 1003, True),
    ("tcgportal_op11_luffy", "cardrush_1385", 1004, False),
    ("cardrush_1455", "tcgportal_corazon", 1005, True),
    ("cardrush_1456", "cardrush_1453", 1006, False),
    ("tcgportal_bonney", "tcgportal_calgara", 1007, True),
    ("cardrush_1439", "cardrush_1399", 1008, False),
    # 2026-06-05 人間×環境デッキ fuzz が検出した crash の退行ガード (= 修正前は ENGINE_ERROR /
    # PY_EXC で落ちた)。 「アタック対象が防御中に自身の opp_attack 効果で消える」 + 「提示後に
    # 払えなくなった opp_attack 効果」。 self-play、 seed/human_first は検出時と同一。
    ("cardrush_1456", "cardrush_1456", 3007, False),
    ("cardrush_1453", "cardrush_1453", 3019, False),
    ("tcgportal_coby", "tcgportal_coby", 3002, True),
    ("cardrush_1399", "cardrush_1399", 3005, False),
]


@pytest.mark.parametrize("deck_a,deck_b,seed,human_first", CASES)
def test_fuzz_invariants_hold(deck_a, deck_b, seed, human_first):
    """1 試合を bot で完走し、 不変条件 違反 / crash / stuck が無いこと。"""
    rng = random.Random(seed)
    seen: set[str] = set()
    status, steps, info = fz.play_one(deck_a, deck_b, seed, human_first, rng, seen)
    assert status == "OK", (
        f"{deck_a} vs {deck_b} seed={seed}: status={status} info={info} "
        f"(再現: python scripts/fuzz_human_play.py --replay-case "
        f"{deck_a} {deck_b} {seed} {int(human_first)})"
    )
