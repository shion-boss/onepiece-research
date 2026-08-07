#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式テキストの **対象範囲** (相手のみ / 自分のみ / 両陣営) と overlay の target spec を突合する。

なぜ要るか:
  公式は 「**相手の**コスト3以下のキャラ1枚まで」 と 「コスト3以下のキャラ1枚まで」 を
  **書き分けている**。 修飾が無い場合は **両陣営** (= 自分のキャラ、 発動元自身も選べる) が公式。

  一次情報 (複数の弾で繰り返し明示 = 一般則):
    - 「この【登場時】効果で自分のキャラをデッキの下に置けますか？」 → 「はい、置くことができます。」
    - 「この【アタック時】/【メイン】/【カウンター】/【トリガー】/【ブロック時】/【起動メイン】効果で
       自分のキャラを手札に戻すことができますか？」 → 「はい、できます。」 (各弾)
    - 「この【登場時】効果で**このキャラ自身や**他の自分のキャラを手札に戻すことはできますか？」
       → 「はい、戻すことができます。」
    - 「この【KO時】効果で自分のキャラをデッキの下に置くことはできますか？」 → 「はい、できます。」
    - 「この【登場時】効果で自分のキャラを自分のライフに置くことができますか？」 → 「はい、できます。」

  対照 (= 修飾がある時はそちらだけ): OP17 の 「自分のリーダーが特徴《王下七武海》を持たない場合、
  この【登場時】効果で自分のキャラ1枚を手札に戻すことはできますか？」 → 「はい、できます。
  **この場合、相手のコスト4以下のキャラ1枚を手札に戻すことはできません。**」

  これを間違えると **選択肢が丸ごと消える** (自キャラを戻して【登場時】を撃ち直す / KO から逃がす
  等の実在ライン)。 しかも Python も Rust も同じ overlay を読むので **差分検証では永久に沈黙する**。

判定:
  公式テキストを 注釈 (括弧内) 除去 → 「。」 で文分割 → 文中で 「キャラ…枚/すべて」 の記述の
  **手前に 相手の/自分の 等の修飾が無い** ものを 「両陣営」 と判定し、 overlay の spec が
  片側限定 (one_opponent_* / all_opponent_* / one_self_* 等) なら疑いとして出す。

  ⚠ 自然言語判定なので **候補提示** であり自動修正はしない。 ACKNOWLEDGED に理由つきで除外する。

  .venv/bin/python scripts/audit_target_scope.py
  .venv/bin/python scripts/audit_target_scope.py --assert   # 疑い>0 で exit 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 片側に限定している spec の目印 (これが出ていたら 「相手のみ」 / 「自分のみ」)
OPP_ONLY = re.compile(r"\bone_opponent|\ball_opponent|\bopp_character|\ball_opp_chara")
SELF_ONLY = re.compile(r"\bone_self_character|\bone_self_chara|\ball_self_chara|\bself_character_")
# 両陣営を返す spec (= これを使っていれば OK)
EITHER = re.compile(r"either|one_inplay|_any_char")

# 「キャラ」 の対象記述。 「キャラカード」 (= 手札/デッキ/トラッシュのカード) は場のキャラでは
# ないので除く (対象範囲の話にならない)。
TARGET_RX = re.compile(r"キャラ(?!カード)(\d+枚まで|\d+枚|1枚|すべて)")
# 手前に置かれる 「所有者の修飾」。 「相手は自身の」 も 相手限定。
#   ⚠ 「このキャラ」 は コスト支払い (「このキャラをレストにできる：」) で頻出し 対象の修飾では
#      ないので入れない。 「相手は自身の…」 は 「相手は」 で捕まる。
QUALIFIER_RX = re.compile(r"相手の|自分の|相手は|自分は")

# 調査済で 「片側限定のままで正しい」 もの。 理由を必ず書く。
ACKNOWLEDGED: dict[str, str] = {}


def strip_reminder(text: str) -> str:
    """注釈 (【ブロッカー】の括弧説明 等) を除去。 中の 「相手の」 が誤って修飾に見えるため。"""
    return re.sub(r"[(（][^)）]*[)）]", "", text or "")


def suspicious_clauses(text: str) -> list[str]:
    """修飾なしで 「キャラ…枚」 を対象にしている記述を返す。"""
    t = re.sub(r"\s+", "", strip_reminder(text))
    out: list[str] = []
    for sent in re.split(r"。", t):
        if "キャラ" not in sent:
            continue
        marks = [m.start() for m in QUALIFIER_RX.finditer(sent)]
        for m in TARGET_RX.finditer(sent):
            if not any(p < m.start() for p in marks):
                out.append(sent[max(0, m.start() - 34): m.end() + 16])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    ap.add_argument("--show", type=int, default=200)
    args = ap.parse_args()

    cards = {c["card_id"]: c for c in
             json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))}
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))

    suspects = []
    checked = 0
    for cid, effs in sorted(ov.items()):
        if not isinstance(effs, list) or cid.startswith("_") or cid in ACKNOWLEDGED:
            continue
        base = cid.split("_")[0]
        if base in ACKNOWLEDGED:
            continue
        card = cards.get(cid)
        if not card:
            continue
        # ⚠ 【トリガー】は `text` ではなく **`trigger` フィールド** (820 枚)。 効果エントリごとに
        #   対応するテキスト欄と突き合わせないと trigger 側が丸ごと未監査になる (2026-08-04)。
        for eff in effs:
            if not isinstance(eff, dict):
                continue
            src = "trigger" if eff.get("when") == "trigger" else "text"
            blob = json.dumps(eff, ensure_ascii=False)
            if not (OPP_ONLY.search(blob) or SELF_ONLY.search(blob)):
                continue
            checked += 1
            cl = suspicious_clauses(card.get(src) or "")
            if cl:
                suspects.append((cid, card.get("name", "?"), cl,
                                 f"[{src}] " + re.sub(r"\s+", "", card.get(src) or "")))

    print(f"片側限定 spec を持つ効果カード {checked} 枚を点検")
    print(f"\n=== ⚠ 公式が修飾なし (= 両陣営) なのに 片側限定: {len(suspects)} 枚 ===")
    for cid, name, cl, text in suspects[:args.show]:
        print(f"  {cid} {name}")
        print(f"     公式: {text[:120]}")
        for c in cl:
            print(f"     該当: …{c}…")
    if args.do_assert and suspects:
        sys.exit(1)


if __name__ == "__main__":
    main()
