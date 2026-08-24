#!/usr/bin/env python
"""**選択列挙 ON** で Python engine と Rust engine の bit 一致を検証する。

⭐ なぜ要るか: 通常の `rust_parity_check.py` は列挙 OFF でしか回せない
   (ON だと Python が halt して比較が飛ぶ)。 だが学習は **選択込みの self-play** で
   回すので、 そのモードで両エンジンが一致することを証明しないと
   **学習データの正しさが保証できない**。

不変条件は通常時と同じ: Rust は 「Python と bit 一致」 か 「明示 bail」 の二択。
未移植 kind に当たった bail は正常 (= 追従候補)。 MISMATCH のみが違反。

  .venv/bin/python scripts/rust_choice_parity.py --games 8
  .venv/bin/python scripts/rust_choice_parity.py --assert   # MISMATCH>0 で exit 1
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import optcg_engine as eng
except ImportError:
    print("ERROR: optcg_engine (Rust) 未ビルド。 "
          "`.venv/bin/maturin develop --release --manifest-path rust_engine/Cargo.toml`")
    sys.exit(2)

from engine.core import reset_iid  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.game import apply_action, legal_actions, play_until_main, setup_game  # noqa: E402
from engine.state_snapshot import full_dump, state_digest  # noqa: E402

# action encoder は差分ハーネスと共用 (instance_id → index の畳み込み)
from scripts.rust_parity_check import _enc  # noqa: E402


# 選択肢の何番目を採るか。 0 は既存ヒューリスティック順の先頭 (= 自動解決とほぼ同じ) なので
# **1 以上** を使い、 選択の差が状態に出るようにする。
POLICY_K = 1


def run(games: int, seed: int, max_steps: int) -> Counter:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    decks = [p for p in sorted((ROOT / "decks").glob("cardrush_*.json"))
             if ".analysis." not in p.name and ".target_v" not in p.name][:6]
    stat: Counter = Counter()
    bail_kinds: Counter = Counter()

    for gi in range(games):
        a = decks[gi % len(decks)]
        b = decks[(gi + 1) % len(decks)]
        reset_iid()
        st = setup_game(DeckList.from_json(str(a), repo), DeckList.from_json(str(b), repo),
                        rng=random.Random(seed + gi), first_player=gi % 2,
                        effects_overlay=overlay)
        play_until_main(st)
        st.choice_enumeration = True   # ⭐ 両エンジンを選択列挙で走らせる

        for _ in range(max_steps):
            if st.game_over:
                break
            acts = legal_actions(st)
            if not acts:
                break
            # 選択が絡む局面を厚く踏むため、 候補が複数なら 2 番目を選ぶ
            act = acts[min(1, len(acts) - 1)]
            enc = _enc(st, act)
            if enc.get("t") == "?":
                stat["skip(未対応 action)"] += 1
                try:
                    apply_action(st, act)
                except Exception:
                    break
                continue
            js = json.dumps(full_dump(st))
            rust_digest = None
            try:
                # ⭐ 両エンジンが **同じ方針で選択を自己解決** した後の状態を比べる。
                #   pending_choice は Python (dict) と Rust (struct) で表現が違い state に
                #   載せて転送できないので、 per-action で往復させる従来方式は成立しない
                #   (Rust 側に解決すべき選択が無く no-op になる)。
                rust_digest = eng.apply_action_choice_policy(js, json.dumps(enc), POLICY_K)
            except Exception as e:  # noqa: BLE001
                stat["bail"] += 1
                msg = str(e)
                key = (msg.split("未対応: ")[-1].split()[0] if "未対応" in msg
                       else msg[:44])
                bail_kinds[key] += 1
            try:
                apply_action(st, act)
                # Python 側も同じ方針で解決しきる
                guard = 0
                while st.pending_choice is not None and guard < 40:
                    guard += 1
                    opts = legal_actions(st)
                    if not opts:
                        st.pending_choice = None
                        break
                    apply_action(st, opts[POLICY_K % len(opts)])
            except Exception:
                break
            if rust_digest is not None:
                if rust_digest == state_digest(st):
                    stat["match"] += 1
                else:
                    stat["MISMATCH"] += 1

    print(f"=== 選択列挙 ON の Python↔Rust 差分 ({games} game) ===")
    print(f"  match     = {stat['match']}")
    print(f"  bail(Err) = {stat['bail']}   (= Rust 未移植 = 追従候補)")
    print(f"  MISMATCH  = {stat['MISMATCH']}   ← 0 でなければ違反")
    print(f"  skip      = {stat['skip(未対応 action)']}")
    total = stat["match"] + stat["bail"] + stat["MISMATCH"]
    if total:
        print(f"  correctness (match+bail) = {(stat['match'] + stat['bail']) / total:.2%}")
    if bail_kinds:
        print("  bail 内訳 (移植の優先順位):")
        for k, v in bail_kinds.most_common(12):
            print(f"     {v:5d}  {k}")
    return stat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()
    stat = run(args.games, args.seed, args.max_steps)
    if args.do_assert and stat["MISMATCH"] > 0:
        print("NG: 選択列挙 ON で Python と Rust が食い違っている", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
