#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python ↔ Rust 差分パリティ を **全カード合成デッキ** で回す (証明範囲の拡張)。

背景 (2026-08-03):
  「Rust が self-play で正しい」 の根拠は 2 種類あり、 強さが全く違う。

    (a) 差分ハーネス (scripts/rust_parity_check.py)
        Rust の状態が Python と **bit 一致** することを証明する。 唯一 「黙って違う状態を
        作る」 を検出できる。 ただし 16 メタデッキ = 効果カード **177/4,263 (4.2%)** しか
        通っていなかった。
    (b) 単独掃引 (scripts/rust_fullsweep.py) / 効果スモーク (scripts/rust_effect_smoke.py)
        全カードを踏むが **Rust 単独の自己検査** (bail / 保存則 / panic)。 クラッシュと
        「実装してません」 は捕まえるが、 **Python と違う正しそうな状態** は捕まえられない。

  → (a) の証明範囲を (b) の網羅性まで広げるのがこのスクリプト。 (b) の合成デッキ
    (効果カード全 4,263 枚がどこかに載る 329 デッキ) を、 (a) の per-action bit 比較で回す。

不変条件 (rust_engine/CLAUDE.md と同じ):
  Rust は任意の action に対し 「Python と bit 一致」 か 「Err で明示 bail」 の二択のみ。
  **MISMATCH = 0 が合格ライン**。 bail は未実装の在処であって誤りではない。

  .venv/bin/python scripts/rust_parity_sweep.py                 # 全 329 デッキ
  .venv/bin/python scripts/rust_parity_sweep.py --limit 20      # 先頭 20 デッキ (試走)
  .venv/bin/python scripts/rust_parity_sweep.py --resume        # 中断から再開
  .venv/bin/python scripts/rust_parity_sweep.py --assert        # MISMATCH>0 で exit 1 (CI)

結果は db/rust_selfplay/parity_sweep.json に逐次 checkpoint。
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

# ⛔ 選択列挙モード (ONEPIECE_CHOICE_SEARCH) では Rust を使わない。
#   Rust は pending_choice / continuation 未実装なので Python と別のゲームになる。
from engine.rust_shadow import assert_rust_safe_for_choice_search  # noqa: E402
assert_rust_safe_for_choice_search("rust_parity_sweep.py")

import scripts.rust_fullsweep as FS  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.core import reset_iid  # noqa: E402
from engine.deck import make_deck_from_dict  # noqa: E402
from engine.game import (AttackCharacter, AttackLeader, apply_action,  # noqa: E402
                         play_until_main, setup_game)
from engine.plan_search import fast_clone  # noqa: E402
from engine.state_snapshot import full_dump, state_digest  # noqa: E402

OUT = ROOT / "db" / "rust_selfplay" / "parity_sweep.json"
CHECKPOINT_EVERY = 5          # デッキ何個ごとに checkpoint を書くか
PROGRESS_EVERY = 10.0         # 進捗表示の秒間隔


def _reset_iid():
    """instance_id カウンタを試合ごとに戻す (digest を安定させる)。"""
    reset_iid()


def _deck_list(d: dict):
    """合成デッキ dict (main = card_id の生リスト) → DeckList。"""
    repo, _ = P._load()
    return make_deck_from_dict(
        {"name": d["name"], "leader": d["leader"],
         "main": [{"card_id": c, "count": 1} for c in d["main"]]},
        repo,
    )


def _source_card_id(st, act, e: dict) -> str:
    """MISMATCH を 「どのカードの効果か」 に帰属させる。

    action だけでは 「ActivateMain:?」 「EndPhase:?」 のように潰れてしまい 作業リストとして
    使えない。 発動元 (ActivateMain の source / アタッカー / ドン付与先) を引き、 EndPhase は
    ターン終了時効果を持つ自陣カードを列挙して 候補を出す。
    """
    me, opp = st.turn_player, st.opponent
    t = e.get("t")
    try:
        if t in ("PlayCharacter", "PlayEvent", "PlayStage"):
            if 0 <= act.hand_idx < len(me.hand):
                return me.hand[act.hand_idx].card_id
        elif t == "ActivateMain":
            k, i = e.get("source_kind"), e.get("source_idx")
            pool = {"leader": [me.leader], "char": me.characters, "stage": me.stages}.get(k, [])
            if k == "leader":
                return f"{me.leader.card.card_id}#am{e.get('effect_index')}"
            if 0 <= i < len(pool):
                return f"{pool[i].card.card_id}#am{e.get('effect_index')}"
        elif t in ("AttackLeader", "AttackCharacter"):
            k, i = e.get("attacker_kind"), e.get("attacker_idx")
            if k == "leader":
                return f"{me.leader.card.card_id}#atk"
            if 0 <= i < len(me.characters):
                return f"{me.characters[i].card.card_id}#atk"
        elif t == "AttachDonToCharacter":
            i = e.get("target_idx")
            if 0 <= i < len(me.characters):
                return f"{me.characters[i].card.card_id}#don"
        elif t == "AttachDonToLeader":
            return f"{me.leader.card.card_id}#don"
        elif t == "EndPhase":
            # ターン終了時に発火しうる自陣カード (= 犯人候補)。 1 枚に絞れないので連結。
            ov = P._load()[1]
            names = []
            for ip in [me.leader, *me.characters, *me.stages]:
                b = ov.get(ip.card.card_id)
                if b and any(x.get("when") in ("end_of_turn", "opp_end_of_turn")
                             for x in b.effects):
                    names.append(ip.card.card_id)
            if names:
                return "EOT:" + "+".join(sorted(set(names))[:3])
    except Exception:
        pass
    return "?"


def run_one_game(deck_a: dict, deck_b: dict, seed: int, max_turns: int, stats: dict) -> None:
    """1 試合を Python で進めつつ、 各 action を Rust と bit 比較する。

    stats を in-place 更新: tot (Counter) / bail (Counter) / mismatch (Counter) /
    cards_seen (set) / cards_mismatch (set)。
    """
    _, ov = P._load()
    _reset_iid()
    st = setup_game(_deck_list(deck_a), _deck_list(deck_b),
                    rng=random.Random(seed), first_player=seed % 2, effects_overlay=ov)
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
            dump = json.dumps(full_dump(st))
            # ⚠ 静的効果 (recompute_static) が食い違う局面は action 比較を丸ごと飛ばす。
            #   これを黙って飛ばすと 「静的効果の乖離」 が **MISMATCH にも bail にも出ず、
            #   match 数がこっそり減るだけ** で見えない (2026-08-04 に計器の穴として発覚)。
            #   飛ばす方針自体は rust_parity_check と揃えるが、 **必ず数えて報告する**。
            _static_ok = eng.recompute_static_digest(dump) == state_digest(st)
            if not _static_ok:
                stats["tot"]["static_skip"] += 1
                stats["static_skip"][
                    f"{st.turn_player.leader.card.card_id} vs {st.opponent.leader.card.card_id}"
                ] += 1
            if _static_ok:
                c = fast_clone(st)
                # Rust が入力に使う _rng_state に Python 側 clone も揃える
                _src = getattr(st, "rng", None)
                if _src is not None and hasattr(_src, "getstate"):
                    _r = random.Random()
                    _r.setstate(_src.getstate())
                    c.rng = _r
                cid = _source_card_id(st, act, e)
                try:
                    apply_action(c, act)
                    ok = c.pending_choice is None
                except Exception:
                    ok = False
                # ⚠ Python が pending_choice で止まった / 例外を投げた局面も比較不能で skip。
                #   数えないと 「ゲームが壊れて比較点が消えた」 のを MISMATCH=0 のまま見逃す。
                if not ok:
                    stats["tot"]["py_skip"] += 1
                if ok:
                    dpy = state_digest(c)
                    try:
                        dr = eng.apply_action_digest(dump, json.dumps(e))
                    except BaseException as ex:      # noqa: BLE001
                        # ⚠ pyo3 の PanicException は BaseException 直下 で、 かつ
                        #    モジュール pyo3_runtime は動的生成のため import できない
                        #    (= except Exception でも from pyo3_runtime import でも拾えず、
                        #      掃引が panic で毎回死んでいた)。 型名で判定する。
                        if isinstance(ex, (KeyboardInterrupt, SystemExit)):
                            raise
                        if type(ex).__name__ == "PanicException":
                            # panic は 「bit 一致 or 明示 bail」 の不変条件違反そのもの。
                            # bail (= Err で降参) とは別カテゴリで数える。
                            stats["tot"]["PANIC"] += 1
                            stats["panic"][f"{str(ex).splitlines()[0][:60]} @{e['t']}:{cid}"] += 1
                            if len(stats["dumps"]) < stats["dump_limit"]:
                                stats["dumps"].append({
                                    "kind": "panic", "action": e, "card_id": cid,
                                    "err": str(ex).splitlines()[0][:200],
                                    "dump": json.loads(dump),
                                    "py_after": json.loads(json.dumps(full_dump(c))),
                                })
                        else:
                            stats["tot"]["bail"] += 1
                            stats["bail"][str(ex).splitlines()[0][:200]] += 1
                    else:
                        if dr == dpy:
                            stats["tot"]["match"] += 1
                            if cid not in ("?",) and "#" not in cid and not cid.startswith("EOT:"):
                                stats["cards_ok"].add(cid)
                        else:
                            stats["tot"]["MISMATCH"] += 1
                            stats["mismatch"][f"{e['t']}:{cid}"] += 1
                            if cid not in ("?",) and "#" not in cid and not cid.startswith("EOT:"):
                                stats["cards_bad"].add(cid)
                            # 再現材料を残す (診断は blob-diff で行う)。
                            # ⚠ 単純な先頭 N 件だと card_id 順の先頭側に偏り、 頻度上位クラスの
                            #   dump が 1 件も残らない。 1 カードあたり 2 件までに制限して散らす。
                            stats["dump_seen"][cid] = stats["dump_seen"].get(cid, 0) + 1
                            if (len(stats["dumps"]) < stats["dump_limit"]
                                    and stats["dump_seen"][cid] <= 2):
                                stats["dumps"].append({
                                    "action": e,
                                    "card_id": cid,
                                    "dump": json.loads(dump),
                                    "py_after": json.loads(json.dumps(full_dump(c))),
                                })
        if not st.game_over:
            try:
                apply_action(st, act)
            except Exception:
                break


def save(stats: dict, done: list[str], elapsed: float) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "tot": dict(stats["tot"]),
        "bail_top": stats["bail"].most_common(40),
        "panic_top": stats["panic"].most_common(40),
        "mismatch_top": stats["mismatch"].most_common(60),
        "static_skip_top": stats["static_skip"].most_common(40),
        "cards_proven": sorted(stats["cards_ok"]),
        "cards_mismatch": sorted(stats["cards_bad"]),
        "decks_done": done,
        "mismatch_dumps": stats.get("dumps", []),
        "elapsed_sec": round(elapsed, 1),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=2, help="1 デッキあたりの試合数")
    ap.add_argument("--limit", type=int, default=None, help="先頭 N デッキだけ (試走)")
    ap.add_argument("--max-turns", type=int, default=220)
    ap.add_argument("--resume", action="store_true", help="前回の checkpoint から再開")
    ap.add_argument("--assert", dest="do_assert", action="store_true",
                    help="MISMATCH>0 で exit 1 (CI 用)")
    ap.add_argument("--dump-limit", type=int, default=5,
                    help="MISMATCH の再現 dump を何件まで保存するか")
    ap.add_argument("--diag", action="store_true",
                    help="Rust 診断モード (= bail の **内側の理由** を unknown_conditions に集計)。"
                         " 外側メッセージ (「on_play primitive 未対応: X」) は内側の Err を潰すので、"
                         " 追従作業ではこれを付けて根本原因を見る")
    args = ap.parse_args()

    P._load()  # repo + overlay (Rust 側 load_overlay も含む)
    if args.diag:
        eng.reset_coverage_stats(True)
    decks = FS.build_synthetic_decks()
    if args.limit:
        decks = decks[:args.limit]

    stats = {"tot": Counter(), "bail": Counter(), "mismatch": Counter(),
             "panic": Counter(), "static_skip": Counter(),
             "cards_ok": set(), "cards_bad": set(),
             "dumps": [], "dump_limit": args.dump_limit, "dump_seen": {}}
    done: list[str] = []

    if args.resume and OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        stats["tot"] = Counter(prev.get("tot", {}))
        stats["bail"] = Counter(dict(prev.get("bail_top", [])))
        stats["panic"] = Counter(dict(prev.get("panic_top", [])))
        stats["mismatch"] = Counter(dict(prev.get("mismatch_top", [])))
        stats["cards_ok"] = set(prev.get("cards_proven", []))
        stats["cards_bad"] = set(prev.get("cards_mismatch", []))
        stats["static_skip"] = Counter(dict(prev.get("static_skip_top", [])))
        done = list(prev.get("decks_done", []))
        print(f"[resume] {len(done)} デッキ済 / match={stats['tot'].get('match', 0)}")

    todo = [d for d in decks if d["name"] not in set(done)]
    print(f"合成デッキ {len(decks)} 種 (未処理 {len(todo)}) × {args.games} game")

    t0 = time.time()
    last = t0
    for i, d in enumerate(todo):
        # 相手は 1 つずらしたデッキ (自分と別のカード群を踏ませる)
        opp = decks[(decks.index(d) + 1) % len(decks)]
        for g in range(args.games):
            run_one_game(d, opp, seed=1 + g * 7 + i, max_turns=args.max_turns, stats=stats)
        done.append(d["name"])
        now = time.time()
        if now - last >= PROGRESS_EVERY:
            t = stats["tot"]
            print(f"[{len(done)}/{len(decks)} deck | {int(now - t0)}s] "
                  f"match={t.get('match', 0)} bail={t.get('bail', 0)} "
                  f"MISMATCH={t.get('MISMATCH', 0)} / 証明カード {len(stats['cards_ok'])}",
                  flush=True)
            last = now
        if (i + 1) % CHECKPOINT_EVERY == 0:
            save(stats, done, time.time() - t0)

    save(stats, done, time.time() - t0)
    t = stats["tot"]
    total = t.get("match", 0) + t.get("bail", 0) + t.get("MISMATCH", 0)
    print("\n=== 結果 ===")
    print(f"match={t.get('match', 0)}  bail(Err)={t.get('bail', 0)}  "
          f"MISMATCH={t.get('MISMATCH', 0)}  PANIC={t.get('PANIC', 0)}  "
          f"static_skip={t.get('static_skip', 0)}  py_skip={t.get('py_skip', 0)}")
    if total:
        ok = t.get("match", 0) + t.get("bail", 0)
        print(f"correctness (match+bail、 黙って間違えない) = {100 * ok / total:.2f}%")
    print(f"bit 一致を 1 度以上 証明できたカード: {len(stats['cards_ok'])}")
    if stats["mismatch"]:
        print("\n=== MISMATCH top ===")
        for k, n in stats["mismatch"].most_common(30):
            print(f"  {n:5d}  {k}")
    if stats["static_skip"]:
        # ⚠ 静的効果の乖離。 action 比較は飛ばしているので MISMATCH には出ないが、
        #   **黙って違う状態** の一種なので必ず目に入れる。
        print("\n=== ⚠ static_skip (静的効果が Python と食い違う局面) top ===")
        for k, n in stats["static_skip"].most_common(20):
            print(f"  {n:5d}  {k}")
    if stats["bail"]:
        print("\n=== bail 理由 top ===")
        for k, n in stats["bail"].most_common(20):
            print(f"  {n:5d}  {k}")
    if args.diag:
        cv = json.loads(eng.coverage_stats())
        unk = sorted((cv.get("unknown_conditions") or {}).items(), key=lambda kv: -kv[1])
        if unk:
            print("\n=== bail の内側の理由 (--diag) ===")
            for k, v in unk[:40]:
                print(f"  {v:5d}  {k}")
    print(f"\n→ {OUT}")

    if stats["panic"]:
        print("\n=== PANIC (不変条件違反) top ===")
        for k, n in stats["panic"].most_common(20):
            print(f"  {n:5d}  {k}")
    if args.do_assert and (t.get("MISMATCH", 0) > 0 or t.get("PANIC", 0) > 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
