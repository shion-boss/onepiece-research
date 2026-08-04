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
    # 2026-08-04: 盤面トリガー系も raw 実行で比較できる (Rust の execute_one_effect が
    # 同じ do 配列を同じ src で回すため)。 これを入れる前は 「self-play で到達しない
    # field-when しか持たないカード」 が一度も bit 一致を証明されずに残っていた。
    "on_self_chara_played", "on_opp_chara_played", "on_self_chara_ko", "on_opp_chara_ko",
    "on_self_life_taken", "on_opp_life_taken", "on_self_life_to_hand", "on_self_life_to_trash",
    "on_self_hand_discarded", "on_self_event_played", "on_self_rested", "on_self_trigger_fired",
    "on_self_chara_leave_by_self_effect", "on_self_don_returned_to_deck", "on_opp_blocker_use",
    "on_life_zero", "opp_event_or_trigger_fired", "on_self_chara_rested_by_self_effect",
    "on_self_battled", "on_self_chara_leave_by_opp_effect", "on_self_don_attached",
    "on_self_battle_ko", "on_opp_chara_returned_to_hand_by_self_effect",
    "on_self_draw_non_draw_phase", "on_turn_start", "opp_turn_start", "game_start",
    "opp_attack_on_leader", "opp_attack_on_chara",
}


def _py_state(repo, overlay_py, card_id: str, when: str):
    """rust_effect_smoke.build_state_json と **同一** の最小 state を Python 側に作る。"""
    reset_iid()
    st = S.make_state(repo, overlay_py, card_id)
    card = repo._by_id[card_id]
    src_ip = None
    if when in S.FIELD_WHENS and card.category == Category.LEADER:
        # make_state が対象 LEADER を自リーダーに据えている (2026-08-04)。 発動元はそれ。
        src_ip = st.players[0].leader
    elif when in S.FIELD_WHENS and card.category in (Category.CHARACTER, Category.STAGE):
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
        "static_proven_cards": [],   # run_static が後から埋める
        "elapsed_sec": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res, detail, proven, mismatch_cards


def run_static(limit: int = 0, quiet: bool = False):
    """**静的効果** (on_attached_don / in_hand / setup_modifier) を両エンジンで比較する。

    静的効果は 「発火」 ではなく盤面から毎回再計算される (Python evaluate_static_effects /
    Rust recompute_static)。 do 配列を直接叩く上の経路では踏めないので専用パスを持つ。

    ⚠ この軸が無いと、 静的効果しか持たないカード (リーダーの【ドン‼×N】等) は
      **一度も bit 一致を証明されない**。 実戦掃引 (rust_parity_sweep) は毎 action
      recompute_static_digest を突き合わせるが、 場に出なかったカードは当然通らない。

    手順: 対象カードを場 (or 手札) に置いた最小 state を作り、 Python 側で
    evaluate_static_effects → state_digest、 Rust 側で recompute_static_digest を取って比較。
    """
    from engine.effects import evaluate_static_effects

    repo, overlay_py = P._load()
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    targets = sorted(
        cid for cid, effs in overlay.items()
        if isinstance(effs, list) and cid in repo._by_id
        and any(isinstance(e, dict) and e.get("when") in S.STATIC_WHENS for e in effs)
    )
    if limit:
        targets = targets[:limit]

    res: Counter = Counter()
    detail: Counter = Counter()
    proven: set[str] = set()
    bad: set[str] = set()
    for cid in targets:
        card = repo._by_id[cid]
        try:
            reset_iid()
            st = S.make_state(repo, overlay_py, cid)
            if card.category == Category.CHARACTER:
                st.players[0].characters.append(InPlay.of(card, sickness=False))
            elif card.category == Category.STAGE:
                st.players[0].stages.append(InPlay.of(card, sickness=False))
            # LEADER は make_state が自リーダーに据えている。 EVENT は手札のみ (in_hand 用)。
            evaluate_static_effects(st, overlay_py)
            dump = json.dumps(full_dump(st))
            dpy = state_digest(st)
        except Exception as e:                       # noqa: BLE001
            res["skip(state)"] += 1
            detail[f"skip(state) @{cid}: {type(e).__name__}"] += 1
            continue
        try:
            dr = eng.recompute_static_digest(dump)
        except BaseException as e:                   # noqa: BLE001
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            if type(e).__name__ == "PanicException":
                res["PANIC"] += 1
                detail[f"PANIC @{cid}: {str(e).splitlines()[0][:70]}"] += 1
            else:
                res["bail"] += 1
                detail[f"bail @{cid}: {str(e).splitlines()[0][:70]}"] += 1
            continue
        if dr == dpy:
            res["match"] += 1
            proven.add(cid)
        else:
            res["MISMATCH"] += 1
            bad.add(cid)
            detail[f"MISMATCH(static) @{cid}"] += 1
    if not quiet:
        print(f"\n=== 静的効果 (on_attached_don / in_hand / setup_modifier) ===")
        print(f"対象 {len(targets)} 枚: match={res['match']}  bail={res['bail']}  "
              f"MISMATCH={res['MISMATCH']}  PANIC={res['PANIC']}  "
              f"skip={res['skip(state)']}")
        for k, v in detail.most_common(20):
            print(f"  {v:5d}  {k}")
    return res, proven, bad


def run_replace(limit: int = 0, quiet: bool = False):
    """**置換効果** (replace_ko / replace_leave / replace_rest) を両エンジンで比較する。

    置換は 「場を離れる直前に割り込む」 特殊経路 (try_replace_ko) で、 do 配列の直接実行でも
    静的再計算でもないため、 上の 2 パスでは踏めない。 ここを埋めないと置換効果カードだけが
    **一度も bit 一致を証明されない** (2026-08-04 時点で未証明 18 枚が全部これだった)。

    手順: holder (= 効果保有カード) を自場 idx0 に置き、 それ自身を victim として
    try_replace_ko を両エンジンで呼び、 digest を比較する。
    """
    from engine.effects import try_replace_ko

    repo, overlay_py = P._load()
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    targets = []
    for cid, effs in sorted(overlay.items()):
        if not isinstance(effs, list) or cid not in repo._by_id:
            continue
        for e in effs:
            if isinstance(e, dict) and e.get("when") in S.REPLACE_WHENS:
                targets.append((cid, e["when"]))
                break
    if limit:
        targets = targets[:limit]

    res: Counter = Counter()
    detail: Counter = Counter()
    proven: set[str] = set()
    bad: set[str] = set()
    for cid, when in targets:
        kind = {"replace_ko": "ko", "replace_rest": "rest"}.get(when, "return_to_hand")
        try:
            sj, vidx = S.build_replace_state_json(repo, overlay_py, cid)
        except Exception as e:                        # noqa: BLE001
            res["skip(state)"] += 1
            detail[f"skip(state) @{cid}: {type(e).__name__}"] += 1
            continue
        try:
            out = json.loads(eng.replace_effect_smoke(sj, 0, vidx, True, kind))
        except BaseException as e:                    # noqa: BLE001
            if isinstance(e, (KeyboardInterrupt, SystemExit)):
                raise
            k = "PANIC" if type(e).__name__ == "PanicException" else "bail"
            res[k] += 1
            detail[f"{k} @{cid} [{when}]: {str(e).splitlines()[0][:70]}"] += 1
            continue
        if not out.get("ok"):
            res["bail"] += 1
            detail[f"bail @{cid} [{when}]: {str(out.get('err'))[:80]}"] += 1
            continue
        # Python 側を **同一の最小 state** で走らせる (build_replace_state_json と同手順)。
        try:
            reset_iid()
            st = S.make_state(repo, overlay_py, cid)
            holder = InPlay.of(repo._by_id[cid], sickness=False)
            st.players[0].characters.append(holder)
            for c in st.players[0].hand:
                if str(getattr(c.category, "value", c.category)).upper().find("CHARACTER") >= 0:
                    st.players[0].characters.append(InPlay.of(c, sickness=False))
                    break
            try_replace_ko(st, st.players[0], st.players[1], holder, overlay_py,
                           by_opp_effect=True, leave_kind=kind)
            if st.pending_choice is not None:
                res["skip(pending)"] += 1
                continue
            dpy = state_digest(st)
        except Exception as e:                        # noqa: BLE001
            res["skip(py_err)"] += 1
            detail[f"skip(py_err) @{cid}: {type(e).__name__} {str(e)[:60]}"] += 1
            continue
        if out.get("digest") == dpy:
            res["match"] += 1
            proven.add(cid)
        else:
            res["MISMATCH"] += 1
            bad.add(cid)
            detail[f"MISMATCH(replace) @{cid} [{when}]"] += 1
    if not quiet:
        print("\n=== 置換効果 (replace_ko / replace_leave / replace_rest) ===")
        print(f"対象 {len(targets)} 枚: match={res['match']}  bail={res['bail']}  "
              f"MISMATCH={res['MISMATCH']}  PANIC={res['PANIC']}  "
              + "  ".join(f"{k}={v}" for k, v in sorted(res.items()) if k.startswith("skip")))
        for k, v in detail.most_common(20):
            print(f"  {v:5d}  {k}")
    return res, proven, bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    res, detail, proven, bad = run(args.limit)
    sres, sproven, sbad = run_static(args.limit)
    rres, rproven, rbad = run_replace(args.limit)
    # 静的パスの結果を JSON に追記 (run() が書いた内容を保ったまま)
    _d = json.loads(OUT.read_text(encoding="utf-8"))
    _d["static_res"] = dict(sres)
    _d["static_proven_cards"] = sorted(sproven)
    _d["static_mismatch_cards"] = sorted(sbad)
    _d["replace_res"] = dict(rres)
    _d["replace_proven_cards"] = sorted(rproven)
    _d["replace_mismatch_cards"] = sorted(rbad)
    OUT.write_text(json.dumps(_d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tot = res["match"] + res["bail"] + res["MISMATCH"] + res["PANIC"]
    print("\n=== 結果 ===")
    print(f"match={res['match']}  bail={res['bail']}  MISMATCH={res['MISMATCH']}  PANIC={res['PANIC']}")
    if tot:
        ok = res["match"] + res["bail"]
        print(f"correctness (match+bail、 黙って間違えない) = {100 * ok / tot:.2f}%")
    print(f"bit 一致を証明できたカード: {len(proven | sproven | rproven)} "
          f"(直接発火 {len(proven)} + 静的 {len(sproven)} + 置換 {len(rproven)})")
    print("skip: " + "  ".join(f"{k}={v}" for k, v in sorted(res.items()) if k.startswith("skip")))
    if detail:
        print("\n=== 内訳 top ===")
        for k, v in detail.most_common(30):
            print(f"  {v:5d}  {k}")
    print(f"\n→ {OUT}")
    if args.do_assert and (res["MISMATCH"] > 0 or res["PANIC"] > 0
                           or sres["MISMATCH"] > 0 or sres["PANIC"] > 0
                           or rres["MISMATCH"] > 0 or rres["PANIC"] > 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
