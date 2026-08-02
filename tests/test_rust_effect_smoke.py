# -*- coding: utf-8 -*-
"""全カード効果スモークの CI ゲート (要 Rust ビルド)。

self-play 掃引は「デッキに入っていても引かれない / その when が起きない」で 100% には届かない。
このスモークは **全 4,262 枚の全効果を直接発火** させ、 Rust が最後まで実行できるか (bail 0)、
panic せず保存則を壊さないかを見る。 self-play (深いが局面依存) との 2 枚で網羅する。

不変条件: bail 0 / panic 0 / 保存則違反 0 / 全カードが 1 回以上実行される。
詳細: python scripts/rust_effect_smoke.py
"""
import pytest

pytest.importorskip("optcg_engine", reason="Rust engine 未ビルド (maturin develop)")


def test_all_card_effects_execute():
    from scripts.rust_effect_smoke import run_smoke

    res, bails, fired, n_cards = run_smoke()
    assert res.get("PANIC", 0) == 0, f"panic {res['PANIC']} 件: {list(bails)[:3]}"
    assert res.get("inv", 0) == 0, f"保存則違反 {res['inv']} 件: {list(bails)[:3]}"
    assert res.get("bail", 0) == 0, (
        f"Rust が実行できない効果 {res['bail']} 件 (= 未実装): {list(bails)[:5]}"
    )
    assert res.get("skip(when)", 0) == 0, (
        f"スモークが state を作れない when が {res['skip(when)']} 件 = 網羅漏れ"
    )
    assert fired == n_cards, f"実行できたカード {fired}/{n_cards} (全カードを踏めていない)"
