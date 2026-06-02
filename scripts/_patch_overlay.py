#!/usr/bin/env python3
"""Reusable overlay patcher for the full-DB audit grind.

Reads a JSON file mapping {card_id: <new overlay list>} and writes it into
db/card_effects.json preserving the canonical format (indent=2, ensure_ascii=False,
trailing newline). _text fields are preserved automatically from the existing
entry when the patch entry omits them (matched positionally is NOT done; instead
each patch entry should carry its own _text, or we keep the old one if counts match).

Usage:
  python scripts/_patch_overlay.py patches.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFF = ROOT / "db" / "card_effects.json"


def main(patch_path: str) -> None:
    patches = json.loads(Path(patch_path).read_text(encoding="utf-8"))
    eff = json.loads(EFF.read_text(encoding="utf-8"))
    for cid, new_overlay in patches.items():
        if cid not in eff:
            print(f"  ! {cid} not in overlay — skipped")
            continue
        eff[cid] = new_overlay
        print(f"  patched {cid} ({len(new_overlay)} entries)")
    EFF.write_text(json.dumps(eff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {EFF}")


if __name__ == "__main__":
    main(sys.argv[1])
