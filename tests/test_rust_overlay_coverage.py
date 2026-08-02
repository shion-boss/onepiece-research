# -*- coding: utf-8 -*-
"""overlay のキーを Rust engine が全て実装しているかの静的ゲート。

⚠ **Rust のビルドを必要としない** (rust_engine/src/*.rs をテキストとして読むだけ)。
これが重要: cloud の効果自動修正ルーティン (optcg-effect-bugfix) は Rust 未ビルド環境で走るため、
`importorskip("optcg_engine")` を持つ tests/test_rust_parity.py はモジュールごと skip される。
Python engine だけ直して Rust が取り残されるのを **ビルド無しで** 止めるのがこのファイルの役割。

差分ハーネス (MISMATCH) との違い: あちらは「サンプルに現れた action」しか見ないので、 新しい
primitive / spec 変種 / trigger が入ってもサンプルに出なければ 0 のまま = 見逃す。
詳細レポート: python scripts/scan_overlay_engine_gaps.py
"""
import pytest


def test_rust_covers_all_overlay_keys():
    """overlay (db/card_effects.json) の primitive / condition / when を Rust が **全て実装済** か。

    ⚠ この gate が要る理由: 差分ハーネス (MISMATCH) は **小規模サンプルに現れた action しか見ない**。
    Python 側に新しい primitive / spec 変種 / trigger が入っても、 そのカードがサンプルに出なければ
    MISMATCH は 0 のまま = **Rust が黙って効果を落としている状態を見逃す**。 実例:
      - 静的効果 15 種が Rust 未実装 (= 常在効果が黙って消える、 2026-08-02 に発見)
      - when 3 種が Rust で未発火 (on_self_don_attached / don_phase_modifier / setup_modifier)
      - play_from_hand_named_with_dynamic_cost の name_filter 追加 (Python だけ修正され Rust 未追従)
    Python engine を直したら **同じ commit で Rust も直す** ことを機械的に強制する。
    詳細レポート: python scripts/scan_overlay_engine_gaps.py
    """
    import json
    import pathlib as _pl

    root = _pl.Path(__file__).resolve().parents[1]
    ov = json.loads((root / "db" / "card_effects.json").read_text(encoding="utf-8"))
    rs = ""
    for name in ("effects.rs", "rules.rs", "setup.rs", "selfplay.rs"):
        f = root / "rust_engine" / "src" / name
        if f.exists():
            rs += f.read_text(encoding="utf-8")
    if not rs:
        pytest.skip("rust_engine/src が見つからない")

    prim: dict[str, set[str]] = {}
    cond: dict[str, set[str]] = {}
    when: dict[str, set[str]] = {}
    for cid, effs in ov.items():
        if not isinstance(effs, list):
            continue
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            if eff.get("when"):
                when.setdefault(eff["when"], set()).add(cid)
            for p in eff.get("do", []) or []:
                if isinstance(p, dict):
                    for k in p:
                        if not k.startswith("_"):
                            prim.setdefault(k, set()).add(cid)
            for ck in ("if", "conditions", "unless"):
                c = eff.get(ck)
                if isinstance(c, dict):
                    for k in c:
                        if not k.startswith("_"):
                            cond.setdefault(k, set()).add(cid)

    # deck の don_deck_size 経由で反映するため Rust ソースには現れない when。
    when_ok = {"setup_modifier"}

    missing = []
    for label, used, allow in (
        ("primitive", prim, set()),
        ("condition", cond, set()),
        ("when", when, when_ok),
    ):
        for k, cids in sorted(used.items(), key=lambda kv: -len(kv[1])):
            if k in allow:
                continue
            if f'"{k}"' not in rs:
                missing.append(f"{label}:{k} ({len(cids)} card, e.g. {sorted(cids)[:2]})")

    assert not missing, (
        "Rust が overlay のキーを実装していない (= 該当カードの効果が黙って消える):\n  "
        + "\n  ".join(missing)
        + "\nPython を直したら同じ commit で rust_engine/ も直すこと。 "
        "詳細: python scripts/scan_overlay_engine_gaps.py"
    )
