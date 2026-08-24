#!/usr/bin/env python
"""`rust_parity_sweep.py` が残した MISMATCH dump を **zone 単位で差分表示** する。

⭐ なぜ要るか: sweep は 「どの action で digest が食い違ったか」 しか出さない。
   dump には (before, action, py_after) が入っているので、 Rust に同じ action を
   適用して **py_after と field ごとに突き合わせれば** 乖離箇所が一発で出る。

  .venv/bin/python scripts/rust_sweep_mismatch_diag.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402


def _fp(pl: dict) -> dict:
    """1 プレイヤー分の粗い指紋 (card_id 列)。"""
    def ids(zone):
        out = []
        for c in pl.get(zone) or []:
            cid = c.get("card_id") if isinstance(c, dict) else c
            out.append(cid)
        return out

    def chars(key):
        out = []
        for ip in pl.get(key) or []:
            c = ip.get("card") or {}
            cid = c.get("card_id") if isinstance(c, dict) else c
            flags = "".join([
                "R" if ip.get("rested") else "",
                f"+{ip.get('attached_dons')}" if ip.get("attached_dons") else "",
            ])
            out.append(f"{cid}{'(' + flags + ')' if flags else ''}")
        return out

    return {
        "hand": ids("hand"),
        "deck_n": len(pl.get("deck") or []),
        "trash": ids("trash"),
        "life_n": len(pl.get("life") or []),
        "characters": chars("characters"),
        "stages": chars("stages"),
        "don": [pl.get("don_active"), pl.get("don_rested"), pl.get("don_remaining_in_deck")],
        "leader_rested": (pl.get("leader") or {}).get("rested"),
        "leader_dons": (pl.get("leader") or {}).get("attached_dons"),
    }


def main() -> None:
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    data = json.loads((ROOT / "db" / "rust_selfplay" / "parity_sweep.json").read_text())
    dumps = data.get("mismatch_dumps") or []
    if not dumps:
        print("MISMATCH dump なし (= sweep が緑)")
        return
    for m in dumps:
        cid, act = m.get("card_id"), m.get("action")
        print(f"=== {cid}  action={json.dumps(act, ensure_ascii=False)}")
        before, py_after = m["dump"], m["py_after"]
        try:
            rs_blob = eng.apply_action_blob(json.dumps(before), json.dumps(act))
        except Exception as e:  # noqa: BLE001
            print(f"  rust bail: {e}")
            continue
        rs = json.loads(rs_blob)
        # ⚠ py_after は **生の full_dump** (CardDef が dict / rng や choice フラグ入り) で、
        #   rs は **canonical blob** (CardDef を card_id に畳み digest 対象外を落とす)。
        #   そのまま比べると全部が偽の差分になるので、 Python 側も Rust に
        #   canonicalize させてから突き合わせる (= digest が見ているものと同じ土俵)。
        py_canon = json.loads(eng.canonical_blob(json.dumps(py_after)))
        for pi in (0, 1):
            a, b = _fp(py_canon["players"][pi]), _fp(rs["players"][pi])
            for k in a:
                if a[k] != b.get(k):
                    print(f"  ≠ P{pi}.{k}:\n      py={a[k]}\n      rs={b.get(k)}")
        # canonical 同士の全 field 再帰 diff (指紋に載らない field を取りこぼさない)
        for path, pv, rv in _walk_diff(py_canon, rs):
            print(f"  ≠ {path}: py={str(pv)[:110]} rs={str(rv)[:110]}")
        print()


def _walk_diff(a, b, path: str = ""):
    """canonical JSON 同士の再帰差分 (path, py 値, rust 値) を yield する。"""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from _walk_diff(a.get(k), b.get(k), f"{path}.{k}" if path else k)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield (f"{path}[len]", len(a), len(b))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            yield from _walk_diff(x, y, f"{path}[{i}]")
    elif a != b:
        yield (path, a, b)


if __name__ == "__main__":
    main()
