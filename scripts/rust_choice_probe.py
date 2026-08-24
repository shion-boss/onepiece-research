#!/usr/bin/env python
"""`rust_choice_diag.py --dump` の局面を **Rust 単体** で ON/OFF 両方流して差を見る。

⭐ 使いどころ: 「Rust が列挙 ON の時だけ効果を実行していない」 型の切り分け。
   Python state は full_dump から復元できないが、 **Rust は同じ JSON をそのまま読める**
   ので、 `choice_enumeration` だけ書き換えて 2 回流せば ON 固有の挙動差が直に見える。

  .venv/bin/python scripts/rust_choice_probe.py <dump_dir_or_json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402

POLICY_K = 1


def probe(path: Path) -> None:
    blob = json.loads(path.read_text(encoding="utf-8"))
    st, enc = blob["state"], blob["action"]
    print(f"=== {path.name}  action={enc}")
    outs = {}
    for on in (True, False):
        st2 = dict(st)
        st2["choice_enumeration"] = on
        try:
            outs[on] = json.loads(eng.apply_action_choice_policy_trace(
                json.dumps(st2), json.dumps(enc), POLICY_K))
        except Exception as e:  # noqa: BLE001
            outs[on] = {"err": str(e)}
        o = outs[on]
        print(f"  enum={int(on)}: err={o.get('err')} suspends={o.get('suspend_calls')} "
              f"trace={[t['kind'] for t in (o.get('trace') or [])]}")
    a, b = outs[True], outs[False]
    if "err" in a or "err" in b:
        return
    for pi, (x, y) in enumerate(zip(a["fp"], b["fp"])):
        for k in x:
            if x[k] != y[k]:
                print(f"    ≠ P{pi}.{k}: ON={x[k]} OFF={y[k]}")


def main() -> None:
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    target = Path(sys.argv[1])
    files = sorted(target.glob("*.json")) if target.is_dir() else [target]
    for f in files:
        probe(f)


if __name__ == "__main__":
    main()
