#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""overlay のキーを Python / Rust どちらが読むかを突き合わせ、 **片側にしか無いキー** を出す。

なぜ要るか (2026-08-03 の実例):
  - `feature_filter`: Rust が読んでいたが overlay に一度も存在しない **死にキー** で、
    Python は `feature` (target の兄弟キー) を読んでいた。 結果 power_pump の特徴フィルタが
    Rust で効かず 全キャラに buff していた (OP02-019 ラクヨウ)。 しかも Rust には power_pump が
    静的/非静的の **2 実装** あり、 1 箇所直しても もう 1 箇所が残った。
  - `power_eq` / `no_effect` / `feature_or_name` / `name_exclude` / `card_id`:
    Rust の matches_filter に無く、 **未知キー → 不一致扱い → 対象 0 → 効果ごと不発**。
  - `cost_le_self_plus_opp_life`: **どちらのエンジンにも無い** キーで、 Python は
    「未知キーは無視」 = 制限なし、 Rust は 「未知キーは不一致」 = 不発 と両方向に壊れていた。

この非対称は差分ハーネスでも 「その局面に到達しないと出ない」 ため、 静的に洗うのが速い。

判定の注意:
  片側にしか無くても **人間操作経路のキー** (optional / up_to / actor / label / description 等)
  は self-play 差分には影響しない。 出力では分けて表示する。

  .venv/bin/python scripts/scan_engine_key_asymmetry.py
  .venv/bin/python scripts/scan_engine_key_asymmetry.py --assert   # AI 経路の非対称>0 で exit 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 人間操作 (pending_choice modal) 専用のキー = AI 経路の差分には出ない。
HUMAN_ONLY = {
    "optional", "label", "description", "actor", "up_to",
    "_iid_picks", "_picked_hand_idxs", "_full_options",
    # or_to_life: human は 「登場 / ライフの上」 を modal で選ぶが AI は常に登場
    # (effects.py に明記)。 Rust が読まなくても self-play 挙動は一致する。
    "or_to_life",
}

# 調査済で実害なしと確認したキー (再調査の手間を省く。 新規に出たものだけ見ればよい)。
KNOWN_BENIGN = {
    # play_self の {"from": "trash"} は冗長: Python は me.trash → me.hand を自動で探すので
    # 指定が無くても同じ挙動 (effects.py の play_self)。
    "from",
    # keep_opp_rested_inplay_next_refresh の target_rest は Python も **値を使わず**
    # opp.leader + rested characters を直接組む (effects.py に明記)。 Rust も同じ。
    "target_rest",
    # overlay の _meta 側メタデータ (ゲームプレイに無関係)。
    "version",
}

# Rust に primitive 自体が無い → 実経路では **明示 bail** する (= 不変条件は守られる)。
# その sub-key が片側にしか無くても 「黙って違う」 ことにはならないので別枠。
RUST_UNIMPLEMENTED_PRIMITIVES = {
    "reveal_hand_play_split": ("reveal_limit", "extra_rested_cost_le"),
    "schedule_self_return_to_deck_bottom_at_battle_end": (),
}


def overlay_keys() -> Counter:
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    keys: Counter = Counter()

    def walk(x, depth=0):
        if isinstance(x, dict):
            for k, v in x.items():
                if depth > 0:            # depth 0 は card_id なので数えない
                    keys[k] += 1
                walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)

    walk(ov)
    return keys


def optional_cost_keys() -> Counter:
    """`optional_cost_then` の cost に現れるキー (= 「〜することができる：」 の支払い)。

    Python はこれを **`execute_effect` の primitive として** 払う (effects.py:9155 の汎用パス)。
    Rust は `pay_cost_one` の explicit arm → 無ければ同じく `execute_effect` へ委譲する。
    つまり **explicit arm も primitive も無いキーだけ** が Rust で払えず bail する。
    実例: `stage_to_deck_bottom` は cost 専用の概念で primitive が無く、 explicit arm も
    無かったので OP06-102 カマキリの起動メインが丸ごと bail していた (2026-08-04)。
    """
    ov = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    keys: Counter = Counter()

    def walk(x):
        if isinstance(x, dict):
            oc = x.get("optional_cost_then")
            if isinstance(oc, dict):
                for cs in oc.get("cost") or []:
                    if isinstance(cs, dict):
                        for k in cs:
                            keys[k] += 1
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(ov)
    return keys


def rust_cost_gaps(rs: str) -> list[tuple[str, int]]:
    """Rust で払えない optional cost キー (explicit arm も primitive も無い) を返す。"""
    try:
        i = rs.index("fn pay_cost_one(")
        pay = rs[i:rs.index("\n}\n", i)]
    except ValueError:
        return []
    prim = set(re.findall(r'"([a-z0-9_]+)"\s*(?:\|\s*"[a-z0-9_]+"\s*)*=>', rs))
    return [(k, n) for k, n in optional_cost_keys().most_common()
            if f'"{k}"' not in pay and k not in prim]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    keys = overlay_keys()
    # ⚠ engine/effects.py だけ見ると誤検出する (auto_attach_to_leader は game.py 側)。
    py = "".join(f.read_text(encoding="utf-8") for f in sorted((ROOT / "engine").glob("*.py")))
    rs = "".join((ROOT / "rust_engine" / "src" / f).read_text(encoding="utf-8")
                 for f in ("effects.rs", "rules.rs", "state.rs"))

    def has(src: str, k: str) -> bool:
        return f'"{k}"' in src or f"'{k}'" in src

    ai_gap, human_gap, both_missing, bail_gap = [], [], [], []
    for k, n in keys.most_common():
        if k.startswith("_"):
            continue
        p, r = has(py, k), has(rs, k)
        if p and r:
            continue
        row = (k, n, p, r)
        if k in KNOWN_BENIGN:
            continue
        if not p and not r:
            both_missing.append(row)
        elif k in HUMAN_ONLY:
            human_gap.append(row)
        elif k in RUST_UNIMPLEMENTED_PRIMITIVES or any(
            k in subs for subs in RUST_UNIMPLEMENTED_PRIMITIVES.values()
        ):
            bail_gap.append(row)
        else:
            ai_gap.append(row)

    def show(title, rows):
        print(f"\n=== {title}: {len(rows)} 種 ===")
        for k, n, p, r in rows:
            who = "Rust に無い" if p else ("Python に無い" if r else "**両方に無い**")
            print(f"  {k:<44}{n:>5} 箇所  {who}")

    print(f"overlay の実キー {len(keys)} 種を点検")
    show("⚠ 両エンジンに無い (= overlay のキー名誤り の可能性)", both_missing)
    show("⚠ AI 経路に効く非対称", ai_gap)
    show("人間操作経路のみ (self-play 差分には出ない)", human_gap)
    show("Rust に primitive 自体が無い (実経路では明示 bail = 不変条件は守られる)", bail_gap)

    cost_gaps = rust_cost_gaps(rs)
    print(f"\n=== ⚠ Rust が払えない optional_cost (= その効果ごと bail): {len(cost_gaps)} 種 ===")
    for k, n in cost_gaps:
        print(f"  {k:<44}{n:>5} 箇所  pay_cost_one に arm 無し + primitive も無し")

    if args.do_assert and (ai_gap or both_missing or cost_gaps):
        sys.exit(1)


if __name__ == "__main__":
    main()
