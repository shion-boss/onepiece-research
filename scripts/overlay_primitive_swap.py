"""overlay 内の「engine が黙って無視する primitive+param」を、 同義の既存 primitive に
機械的に差し替える deterministic fixer — 2026-07-24。

背景: overlay が engine 未対応の primitive+param を書くと、 engine は例外を出さず「無視」して
別挙動になる (例: `search` の `source:"trash"` は engine が読まず常に山札を探索 → トラッシュ
回収が不発)。 これは **engine のバグではなく overlay の primitive 選択ミス**で、 同義の既存
primitive (search_from_trash) に差し替えれば直る = ルーティンの担当領域。 だが「同義 primitive
への差し替え」は LLM 判断に依存しやすく escalate に落ちがち。 この script が **登録済みの
anti-pattern を機械的に検出・修正**して、 その class を自動 self-heal させる。

新しい anti-pattern を見つけたら RULES に 1 つ追加するだけで、 以後 routine が自動修正する。

  .venv/bin/python scripts/overlay_primitive_swap.py            # dry-run (検出のみ)
  .venv/bin/python scripts/overlay_primitive_swap.py --apply    # 修正を書き込む
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "db" / "card_effects.json"


def _swap_search_source_trash(node: dict):
    """{"search": {"source":"trash", "filter":F, "limit":L, ...}}
       → {"search_from_trash": {"filter":F, "count":L}}
    engine の `search` primitive は me.deck のみ探索し `source` を無視するため、
    トラッシュ回収は専用の `search_from_trash` (人間/AI 選択 modal + add_to_hand_publicly) を使う。
    戻り値: 置換後 dict (変更あり) か None (該当せず)。"""
    spec = node.get("search")
    if not isinstance(spec, dict) or spec.get("source") != "trash":
        return None
    new = {"filter": spec.get("filter", {}), "count": int(spec.get("limit", 1))}
    return {"search_from_trash": new}


# (name, fn): fn(node dict) → 置換後 node | None。 node は 1 primitive 相当の dict。
RULES = [
    ("search_source_trash→search_from_trash", _swap_search_source_trash),
]


def _walk(node, changes: list, path: str = ""):
    """overlay ツリーを再帰し、 primitive dict に RULES を適用。 変更を in-place で反映。"""
    if isinstance(node, dict):
        for name, fn in RULES:
            res = fn(node)
            if res is not None:
                # node を res の内容に置換 (キー入れ替え)。 dict を in-place で作り替える。
                old_keys = list(node.keys())
                for k in old_keys:
                    del node[k]
                node.update(res)
                changes.append((path, name))
                # 置換後の値も走査 (入れ子 primitive 対応)
                for k, v in list(node.items()):
                    _walk(v, changes, f"{path}.{k}")
                return
        for k, v in list(node.items()):
            _walk(v, changes, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, changes, f"{path}[{i}]")


def scan_overlay(data: dict | None = None) -> dict:
    """overlay 内の anti-pattern を検出して {card_id: [(path, rule_name), ...]} を返す。
    ⚠ in-place で node を書き換える (data を渡すとそれが修正済みになる)。 data=None なら
    ファイルをロードして検査 (呼び出し側が書き込まない限りファイルは不変)。 guard test と共有。"""
    if data is None:
        data = json.loads(OVERLAY.read_text(encoding="utf-8"))
    hit_cards: dict = {}
    for cid, entry in data.items():
        if cid == "_meta":
            continue
        ch: list = []
        _walk(entry, ch, cid)
        if ch:
            hit_cards[cid] = ch
    return hit_cards


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="修正を書き込む (既定は dry-run)")
    a = ap.parse_args()

    data = json.loads(OVERLAY.read_text(encoding="utf-8"))
    hit_cards = scan_overlay(data)

    if not hit_cards:
        print("anti-pattern なし ✅ (overlay は engine 対応 primitive のみ)")
        return 0

    total = sum(len(v) for v in hit_cards.values())
    print(f"検出: {total} 箇所 / {len(hit_cards)} カード")
    for cid, ch in sorted(hit_cards.items()):
        for path, name in ch:
            print(f"  {cid}: {name}  @ {path}")

    if not a.apply:
        print("\n(dry-run) --apply で書き込む")
        return 0

    # 書式維持: 元ファイルは json.dumps(ensure_ascii=False, indent=1) 末尾改行なし
    out = json.dumps(data, ensure_ascii=False, indent=1)
    OVERLAY.write_text(out, encoding="utf-8")
    print(f"\n✅ {total} 箇所を修正して書き込みました → {OVERLAY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
