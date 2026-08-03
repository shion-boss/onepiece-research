#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全カード効果を **Python と Rust の両方** で直接発火させ、 結果を bit 比較する。

背景 (2026-08-03):
  差分パリティの証明範囲は 3 段階ある。

    (a) scripts/rust_parity_check.py   16 メタデッキ = 効果カード 177 枚 (4.2%)
    (b) scripts/rust_parity_sweep.py   全カード合成デッキ self-play = 3,100 枚 (73%)
    (c) このスクリプト                  **全 4,262 枚** を直接発火して bit 比較

  (b) で 116 枚が一度も発火しなかった。 内訳は **92 枚がイベントで 99 効果が counter** =
  「AI が防御時にカウンターイベントを選ぶ局面に self-play が到達しない」 だけで、 実装の
  問題ではない。 試合数を増やしても解決しないので、 効果を直接叩く経路で埋める。

  scripts/rust_effect_smoke.py は同じ最小 state を作って **Rust だけ** 走らせている
  (bail / panic / 保存則の観測)。 本スクリプトはそこに **Python 実行と digest 比較** を足し、
  「Rust が Python と bit 一致するか」 を全カードで問う。

不変条件は他の harness と同じ:
  Rust は 「Python と bit 一致」 か 「Err で明示 bail」 の二択のみ。 MISMATCH=0 が合格ライン。

  .venv/bin/python scripts/rust_effect_smoke_parity.py            # 全カード
  .venv/bin/python scripts/rust_effect_smoke_parity.py --limit 200
  .venv/bin/python scripts/rust_effect_smoke_parity.py --assert   # MISMATCH>0 で exit 1

結果は db/rust_selfplay/effect_smoke_parity.json に保存。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402
import scripts.rust_effect_smoke as S  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.core import Category, InPlay, reset_iid  # noqa: E402
from engine.effects import (_can_pay_counter_cost, eval_all_conditions,  # noqa: E402
                            execute_effect)
from engine.state_snapshot import full_dump, state_digest  # noqa: E402

OUT = ROOT / "db" / "rust_selfplay" / "effect_smoke_parity.json"

# 「効果の do 配列をそのまま両エンジンで実行して比べられる」 when だけを対象にする。
# 静的効果 / 置換効果 / ドンフェイズ修飾 は発火経路が特殊で raw 実行の意味が違うため除外
# (それらは rust_effect_smoke.py が Rust 単独で、 rust_parity_sweep.py が実戦で見る)。
DIRECT_WHENS = {
    "on_play", "on_attack", "opp_attack", "on_block", "counter", "trigger", "main",
    "activate_main", "end_of_turn", "opp_end_of_turn", "on_ko",
}


def _py_state(repo, overlay_py, card_id: str, when: str):
    """rust_effect_smoke.build_state_json と **同一** の最小 state を Python 側に作る。"""
    reset_iid()
    st = S.make_state(repo, overlay_py, card_id)
    card = repo._by_id[card_id]
    src_ip = None
    if when in S.FIELD_WHENS and card.category in (Category.CHARACTER, Category.STAGE):
        ip = InPlay.of(card, sickness=False)
        if card.category == Category.CHARACTER:
            st.players[0].characters.append(ip)
        else:
            st.players[0].stages.append(ip)
        src_ip = ip
    return st, src_ip


def run(limit: int = 0, quiet: bool = False):
    repo, overlay_py = P._load()
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = sorted((cid, e) for cid, e in overlay.items()
                   if isinstance(e, list) and e and cid in repo._by_id)
    if limit:
        cards = cards[:limit]

    res = Counter()
    detail = Counter()
    mismatch_cards: set[str] = set()
    proven: set[str] = set()
    t0 = time.time()
    last = t0

    for n, (cid, effs) in enumerate(cards):
        for idx, eff in enumerate(effs):
            when = eff.get("when") or ""
            if when not in DIRECT_WHENS:
                res["skip(when)"] += 1
                continue
            try:
                st, src_ip = _py_state(repo, overlay_py, cid, when)
                dump, sidx = S.build_state_json(repo, overlay_py, cid, when)
            except Exception as e:
                res["skip(state)"] += 1
                detail[f"state 構築失敗 @{cid}: {type(e).__name__}"] += 1
                continue
            # --- Rust 実行 (実経路 = execute_one_effect)。 digest 付きで返る。
            try:
                out = json.loads(eng.fire_effect_smoke(dump, cid, when, idx, sidx))
            except BaseException as e:  # noqa: BLE001
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                kind = "PANIC" if type(e).__name__ == "PanicException" else "bail"
                res[kind] += 1
                detail[f"{kind} @{cid}[{when}]: {str(e).splitlines()[0][:80]}"] += 1
                continue
            if not out.get("ok"):
                res["bail"] += 1
                detail[f"bail @{cid}[{when}]: {str(out.get('err'))[:80]}"] += 1
                continue
            # --- Python 実行 (Rust の execute_one_effect と同じ手順を辿る)
            me, opp = st.players[0], st.players[1]
            try:
                st.current_source_card_id = cid
                if not eval_all_conditions(eff, st, me, src_ip):
                    pass                                   # 条件不成立 = 発動しない
                elif when == "activate_main":
                    if src_ip is None:
                        res["skip(no_src)"] += 1
                        continue
                    # ⚠ fire_activate_main は effect を **object identity** (`e is eff`) で
                    #   探すので、 別ロードした JSON を渡すと eff_idx=None で何もせず返る。
                    #   必ず bundle 側の実体を渡す (ハーネス由来の偽 MISMATCH 11 件の原因)。
                    from engine.effects import fire_activate_main
                    bundle = overlay_py.get(cid)
                    if bundle is None or idx >= len(bundle.effects):
                        res["skip(no_bundle)"] += 1
                        continue
                    fire_activate_main(st, me, opp, src_ip, bundle.effects[idx])
                else:
                    cost = eff.get("cost") or {}
                    only_once = bool(cost) and set(cost) == {"once_per_turn"}
                    paid = True
                    if cost and not only_once:
                        paid = _can_pay_counter_cost(st, me, src_ip, cost)
                        if paid:
                            from engine.effects import _pay_counter_cost
                            _pay_counter_cost(st, me, opp, src_ip, cost)
                    if paid:
                        for prim in (eff.get("do") or []):
                            execute_effect(prim, st, me, opp, src_ip)
                st.current_source_card_id = None
                if st.pending_choice is not None:
                    res["skip(pending)"] += 1
                    continue
                dpy = state_digest(st)
            except Exception as e:
                res["skip(py_err)"] += 1
                detail[f"Python 例外 @{cid}[{when}]: {type(e).__name__} {str(e)[:50]}"] += 1
                continue
            if out.get("digest") == dpy:
                res["match"] += 1
                proven.add(cid)
            else:
                res["MISMATCH"] += 1
                mismatch_cards.add(cid)
                d0 = next(iter((eff.get("do") or [{}])[0]), "?")
                detail[f"MISMATCH @{cid}[{when}] do0={d0}"] += 1
        now = time.time()
        if not quiet and now - last >= 10.0:
            print(f"[{n + 1}/{len(cards)} 枚 | {int(now - t0)}s] "
                  f"match={res['match']} bail={res['bail']} MISMATCH={res['MISMATCH']}",
                  flush=True)
            last = now

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "res": dict(res),
        "detail_top": detail.most_common(120),
        "mismatch_cards": sorted(mismatch_cards),
        "proven_cards": sorted(proven),
        "elapsed_sec": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res, detail, proven, mismatch_cards


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    res, detail, proven, bad = run(args.limit)
    tot = res["match"] + res["bail"] + res["MISMATCH"] + res["PANIC"]
    print("\n=== 結果 ===")
    print(f"match={res['match']}  bail={res['bail']}  MISMATCH={res['MISMATCH']}  PANIC={res['PANIC']}")
    if tot:
        ok = res["match"] + res["bail"]
        print(f"correctness (match+bail、 黙って間違えない) = {100 * ok / tot:.2f}%")
    print(f"bit 一致を証明できたカード: {len(proven)}")
    print("skip: " + "  ".join(f"{k}={v}" for k, v in sorted(res.items()) if k.startswith("skip")))
    if detail:
        print("\n=== 内訳 top ===")
        for k, v in detail.most_common(30):
            print(f"  {v:5d}  {k}")
    print(f"\n→ {OUT}")
    if args.do_assert and (res["MISMATCH"] > 0 or res["PANIC"] > 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
