#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式テキストの 「その後、」 と overlay の `do` 配列の **順序** が一致しているか監査する。

なぜ要るか:
  公式テキストで 「A。 その後、 B」 と書かれていれば **A → B の順** に解決する。
  overlay の `do` は配列順に実行されるので、 順序が逆だと解決順が変わる。 順序が効くのは:
    - 前段が盤面を変えると後段の対象が変わる (KO → 残りにパンプ 等)
    - 前段のトリガー (on_self_life_to_hand 等) が後段より先に走る
    - 人間の選択 modal の提示順が変わる
  実例 (2026-08-04): ST15-004 サッチ 「相手のキャラ1枚までをパワー-2000。 **その後**、
  自分のライフの上から1枚を手札に加える」 の overlay が `[life_to_hand, power_pump]` と
  逆順だった。

判定:
  公式テキストを 「その後、」 で前半/後半に割り、 各半分に現れる **効果の語** を primitive 名に
  写して、 overlay の do 順と突き合わせる。 ⚠ 自然言語なので **候補提示** であり自動修正はしない。
  誤検出を減らすため、 前半・後半それぞれで一意に決まる語だけを使う。

  .venv/bin/python scripts/audit_sonogo_order.py
  .venv/bin/python scripts/audit_sonogo_order.py --assert   # 疑い>0 で exit 1 (ack 済は除外)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 公式テキストの語 → overlay primitive 名。 一意に決まるものだけを載せる
# (「登場させる」 のように複数 primitive に散るものは誤検出源なので入れない)。
PHRASE_TO_PRIM = [
    (re.compile(r"ライフの上から\d*枚?を?手札に加え"), {"life_to_hand", "life_top_or_bottom_to_hand"}),
    (re.compile(r"カード\d*枚?を?引く"), {"draw"}),
    (re.compile(r"パワー[+\-−]\d"), {"power_pump"}),
    (re.compile(r"KOする"), {"ko", "ko_multi"}),
    (re.compile(r"レストにする"), {"rest", "rest_multi"}),
    (re.compile(r"アクティブにする"), {"untap", "untap_chara", "untap_don"}),
    (re.compile(r"持ち主の手札に戻す"), {"return_to_hand", "return_to_hand_multi"}),
    (re.compile(r"デッキの下に置く"), {"return_to_deck_bottom", "return_to_deck_bottom_multi"}),
    (re.compile(r"コスト[+\-−]\d"), {"cost_minus"}),
]

# 調査済で 「順序はこのままで正しい」 と確認したもの (再掲しない)。 理由を必ず書く。
ACKNOWLEDGED: dict[str, str] = {}


def prims_in(do: list) -> list[str]:
    """do 配列の primitive 名を順番に (ネストは見ない = 先頭キーのみ)。"""
    out = []
    for p in do or []:
        if isinstance(p, dict):
            for k in p:
                if not k.startswith("_"):
                    out.append(k)
                    break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}

    suspects = []
    checked = 0
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list) or cid.startswith("_") or cid in ACKNOWLEDGED:
            continue
        card = cards.get(cid)
        if not card:
            continue
        # ⚠ 【トリガー】は `text` ではなく **`trigger` フィールド** に入っている (820 枚)。
        #   `text` だけ見ると trigger 効果の順序が丸ごと未監査になる (2026-08-04 に判明)。
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            text = (card.get(src) or "")
            if "その後" not in text:
                continue
            head, _, tail = text.partition("その後")
            do = eff.get("do")
            if not isinstance(do, list) or len(do) < 2:
                continue
            order = prims_in(do)
            if len(order) < 2:
                continue
            checked += 1
            # 前半にしか現れない prim / 後半にしか現れない prim を集める
            head_prims: set[str] = set()
            tail_prims: set[str] = set()
            for rx, prims in PHRASE_TO_PRIM:
                in_h, in_t = bool(rx.search(head)), bool(rx.search(tail))
                if in_h and not in_t:
                    head_prims |= prims
                elif in_t and not in_h:
                    tail_prims |= prims
            if not head_prims or not tail_prims:
                continue
            # do 配列上で 「後半のはずの prim」 が 「前半のはずの prim」 より先に来ていたら疑い
            first_head = next((i for i, k in enumerate(order) if k in head_prims), None)
            first_tail = next((i for i, k in enumerate(order) if k in tail_prims), None)
            if first_head is None or first_tail is None:
                continue
            if first_tail < first_head:
                suspects.append((cid, card.get("name", "?"), order,
                                 sorted(head_prims & set(order)), sorted(tail_prims & set(order)),
                                 text.replace("\n", " / ")[:110]))

    print(f"「その後」 を含む効果 {checked} 件を点検")
    print(f"\n=== ⚠ 順序が公式と逆の疑い: {len(suspects)} 件 ===")
    for cid, name, order, hp, tp, text in suspects:
        print(f"  {cid} {name}")
        print(f"     公式: {text}")
        print(f"     do順: {order}   (前半のはず={hp} / 後半のはず={tp})")
    if args.do_assert and suspects:
        sys.exit(1)


if __name__ == "__main__":
    main()
