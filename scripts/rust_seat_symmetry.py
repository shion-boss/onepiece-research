#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rust engine の **座席入替対称性** (metamorphic テスト) — Python をオラクルにしない検証。

なぜ要るか:
  差分ハーネス (rust_parity_check / rust_parity_sweep) は 「Python が正」 を前提にしている。
  つまり **Python が間違っていれば Rust も同じ間違いをして差分は沈黙する**。
  実際 2026-08-04 に、 両エンジンが同じ間違いをしていたバグが 2 件見つかった
  (「トラッシュに置く」 を KO 扱い / 表向きライフ枚数の未正規化)。 どちらも差分では見えず、
  別の観測軸 (公式テキスト突合・保存則) が見つけた。

このスクリプトの観測軸:
  **「実装が何であれ、 席が入れ替わっても同じことが起きるはず」**
  盤面 S の 2 人を丸ごと入れ替えた S' を作り、 同じ action を両方に適用して
  「apply(S) を入れ替えたもの」 と 「apply(S') 」 が **bit 一致** するかを見る。

  action の JSON は 「手番プレイヤー視点」 (attacker_idx = 自分の場、 target_idx = 相手の場)
  なので、 席を入れ替えて turn_player_idx も反転させれば **同じ action がそのまま使える**。

  一致しなければ、 どちらかの席でしか通らない経路 = **player index の取り違え**がある。
  これは Python を一切参照せずに検出できる (= 独立した正しさの根拠)。

  .venv/bin/python scripts/rust_seat_symmetry.py                # メタ 16 デッキ
  .venv/bin/python scripts/rust_seat_symmetry.py --synthetic 60 # 全カード合成デッキ 60
  .venv/bin/python scripts/rust_seat_symmetry.py --assert       # 非対称>0 で exit 1
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402
import scripts.rust_fullsweep as FS  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.core import reset_iid  # noqa: E402
from engine.deck import make_deck_from_dict  # noqa: E402
from engine.game import (AttackCharacter, AttackLeader, apply_action,  # noqa: E402
                         play_until_main, setup_game)
from engine.state_snapshot import full_dump  # noqa: E402

OUT = ROOT / "db" / "rust_selfplay" / "seat_symmetry.json"

# プレイヤー添字を値として持つ field (= 席を入れ替えたら 0↔1 を反転させる必要がある)。
# ⚠ 新しく `*_applier_idx` 系を足したらここにも足すこと。 漏れると 「入れ替えたのに元のまま」 で
#   偽の非対称として出る (= 気づける方向のミスなので安全側)。
PLAYER_IDX_FIELDS = {
    "owner_idx",
    "attack_cost_discard_hand_applier_idx",
    "cannot_be_rested_applier_idx",
    "granted_keywords_through_opp_turn_applier_idx",
    "next_opp_turn_end_applier_idx",
    "next_opp_turn_end_base_cost_override_applier_idx",
    "next_opp_turn_end_base_power_override_applier_idx",
    "next_self_turn_end_applier_idx",
    # ⚠ dict 値の中に入っているプレイヤー添字。 struct field ではないので state.rs の
    #   grep では出てこない (= 取りこぼしやすい)。 last_peeked_opp_deck_top は
    #   {"viewer_idx": int, "card_ids": [...]} (core.py:866)。
    "viewer_idx",
}


def _flip_idx(v):
    """プレイヤー添字を反転 (負値 = 「未設定」 なのでそのまま)。"""
    return v if not isinstance(v, int) or v < 0 else 1 - v


def swap_seats(dump: dict) -> dict:
    """盤面の 2 人を丸ごと入れ替える (= 鏡像を作る)。 元は壊さない。"""
    d = json.loads(json.dumps(dump))
    d["players"] = [d["players"][1], d["players"][0]]
    d["turn_player_idx"] = 1 - int(d.get("turn_player_idx", 0))
    if isinstance(d.get("winner"), int):
        d["winner"] = 1 - d["winner"]

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in PLAYER_IDX_FIELDS:
                    x[k] = _flip_idx(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(d)
    return d


def check_action(dump_json: str, action_json: str, stats: Counter, detail: Counter, cid: str) -> None:
    """1 action について 「入替 → 適用」 と 「適用 → 入替」 の digest 一致を見る。"""
    dump = json.loads(dump_json)
    try:
        after_a = json.loads(eng.apply_action_blob(dump_json, action_json))   # 適用 → (後で入替)
    except BaseException:                                                    # noqa: BLE001
        stats["bail"] += 1
        return
    try:
        after_b = json.loads(eng.apply_action_blob(json.dumps(swap_seats(dump)), action_json))
    except BaseException as e:                                               # noqa: BLE001
        if type(e).__name__ == "PanicException":
            stats["PANIC"] += 1
            detail[f"PANIC(swapped) @{cid}: {str(e).splitlines()[0][:70]}"] += 1
        else:
            # ⚠ 片方だけ bail するのも非対称 (= 席依存の未実装)。 見逃さず数える。
            stats["asym_bail"] += 1
            detail[f"片席だけ bail @{cid}: {str(e).splitlines()[0][:70]}"] += 1
        return
    # 「適用 → 入替」 と 「入替 → 適用」 を比較する。
    # ⚠ `canonical_digest` は Python の full_dump 形式 (CardDef が構造体) を期待するが、
    #   `apply_action_blob` の出力は **card_id 文字列に畳んだ canonical 形式** なので
    #   digest 関数には戻せない。 両方とも同じ serializer の出力なので、 key ソートした
    #   JSON 文字列を直接比較すればよい (どちらも同じ形式 = 比較が公平)。
    da = json.dumps(swap_seats(after_a), sort_keys=True, ensure_ascii=False)
    db = json.dumps(after_b, sort_keys=True, ensure_ascii=False)
    if da == db:
        stats["match"] += 1
    else:
        stats["ASYM"] += 1
        detail[f"座席非対称 @{cid}"] += 1


def run_game(deck_a, deck_b, seed: int, max_turns: int, stats: Counter, detail: Counter) -> None:
    _, ov = P._load()
    reset_iid()
    st = setup_game(deck_a, deck_b, rng=random.Random(seed), first_player=seed % 2,
                    effects_overlay=ov)
    play_until_main(st)
    ais = [GreedyAI(rng=random.Random(seed * 3 + 1)), GreedyAI(rng=random.Random(seed * 5 + 2))]
    for _ in range(max_turns):
        if st.game_over:
            break
        mi = st.turn_player_idx
        act = ais[mi].choose_action(st)
        if act is None:
            break
        if isinstance(act, (AttackLeader, AttackCharacter)):
            act = P._defended(st, act, ais[1 - mi])
        e = P._enc(st, act)
        if e.get("t") != "?":
            dump_json = json.dumps(full_dump(st))
            cid = f"{e['t']}"
            check_action(dump_json, json.dumps(e), stats, detail, cid)
        try:
            apply_action(st, act)
        except Exception:                                                    # noqa: BLE001
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=2)
    ap.add_argument("--synthetic", type=int, default=0,
                    help="全カード合成デッキを先頭 N 個使う (0 = メタ 16 デッキ)")
    ap.add_argument("--max-turns", type=int, default=220)
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    repo, _ = P._load()
    if args.synthetic:
        decks = [make_deck_from_dict(
            {"name": d["name"], "leader": d["leader"],
             "main": [{"card_id": c, "count": 1} for c in d["main"]]}, repo)
            for d in FS.build_synthetic_decks()[:args.synthetic]]
    else:
        # ⚠ decks/ には `<slug>.analysis.json` / `<slug>.target_v1.json` も同居するので、
        #   glob の stem をそのまま使うと deck でないファイルを掴む。 leader を持つものだけ拾う。
        import glob
        slugs = []
        for f in sorted(glob.glob(str(ROOT / "decks" / "cardrush_*.json"))):
            try:
                if "leader" in json.loads(Path(f).read_text(encoding="utf-8")):
                    slugs.append(Path(f).stem)
            except Exception:  # noqa: BLE001
                continue
        decks = [P._dl(s) for s in slugs]

    stats: Counter = Counter()
    detail: Counter = Counter()
    t0 = time.time()
    for i, d in enumerate(decks):
        opp = decks[(i + 1) % len(decks)]
        for g in range(args.games):
            run_game(d, opp, seed=1 + g * 7 + i, max_turns=args.max_turns,
                     stats=stats, detail=detail)

    tot = stats["match"] + stats["ASYM"]
    print("\n=== 座席入替対称性 (Python 非依存) ===")
    print(f"デッキ {len(decks)} × {args.games} game")
    print(f"match={stats['match']}  **ASYM={stats['ASYM']}**  "
          f"片席だけ bail={stats['asym_bail']}  両席 bail={stats['bail']}  PANIC={stats['PANIC']}")
    if tot:
        print(f"対称性 = {100 * stats['match'] / tot:.2f}%")
    if detail:
        print("\n=== 内訳 top ===")
        for k, v in detail.most_common(20):
            print(f"  {v:5d}  {k}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"stats": dict(stats), "detail_top": detail.most_common(60),
                               "elapsed_sec": round(time.time() - t0, 1)},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n→ {OUT}")
    if args.do_assert and (stats["ASYM"] or stats["PANIC"] or stats["asym_bail"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
