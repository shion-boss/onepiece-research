"""Rust エンジン 全カード掃引 — Python を正解にせず、Rust 単独で「正しいゲームができるか」を検証する。

背景 (2026-07-31):
  差分検証 (Python と bit 一致) は強力だが **天井が Python の正しさ** で、しかも Python 側にも
  未仕分けの穴がある。 そこで「Rust が単独で正しいゲームをできる」ことを別軸で担保する。

  ⚠ 前提の確認: メタデッキ 92 種に登場するカードは 370 枚で、 効果を持つ 4,263 枚の **8.5%** しか
  self-play で実行されていなかった。 残り 91.5% は実装済みかどうかも分かっていない。
  → 全カードを強制的にプールへ載せて踏ませるのがこのスクリプト。

3 つの計器 (全て Python 不要 = Rust 速度で回せる):
  (a) bail        — Rust が「再現できない」と降参した箇所 (= 未実装の在処)
  (b) 保存則違反   — カード保存則 / ドン保存則 / 場5枚 / ステージ1枚 / 負値。 言語非依存の絶対条件
                     なので Rust 固有の実装ミス (index ズレ / clone 汚染 / zone 移動漏れ) を単独検出
  (c) 発火率       — 「デッキに入っている」≠「効果が実行された」。 一度も発火しなかったカードは
                     何も検証できていないので、 次ラウンドで踏ませる対象として出す

合成デッキ:
  効果を持つリーダー 1 枚 + 非リーダーの効果カードを分配 (4 枚ずつ) して 50 枚。 レギュレーション
  (色一致 / 4 枚制限 / 禁止) は **意図的に無視** する。 目的は網羅であって適法なデッキ構築ではない。

  .venv/bin/python scripts/rust_fullsweep.py --games 6            # 全リーダー分 (~324 デッキ)
  .venv/bin/python scripts/rust_fullsweep.py --games 6 --limit 40 # 先頭 40 デッキだけ (試走)
  .venv/bin/python scripts/rust_fullsweep.py --resume             # 中断から再開

結果は db/rust_selfplay/fullsweep.json に逐次 checkpoint (10 秒毎に進捗表示)。
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
import scripts.rust_parity_check as P  # noqa: E402
from engine.state_snapshot import _ser_full  # noqa: E402

OUT = ROOT / "db" / "rust_selfplay" / "fullsweep.json"
DECK_SIZE = 50
COPIES = 4  # 同名 4 枚 = 引いて使われる確率を上げる (検証用なので禁止/制限は無視)


def build_synthetic_decks() -> list[dict]:
    """効果を持つ全カードがどこかのデッキに載るよう合成デッキを組む。

    返り値: [{"name": str, "leader": card_id, "main": [card_id × 50]}]
    リーダー 1 枚につき 1 デッキ。 非リーダーの効果カードを round-robin で配り、 各カード COPIES 枚。
    """
    repo, _ = P._load()
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    with_eff = [cid for cid, v in overlay.items() if isinstance(v, list) and v]

    leaders, others = [], []
    for cid in with_eff:
        try:
            cd = repo.get(cid)
        except Exception:
            continue  # cards.json に無い (overlay 側だけの id)
        cat = str(getattr(cd.category, "value", cd.category)).upper()
        (leaders if "LEADER" in cat else others).append(cid)

    leaders.sort()
    others.sort()
    per_deck = max(1, DECK_SIZE // COPIES)  # 12 種 × 4 枚 = 48 枚
    decks = []
    n_decks = max(len(leaders), (len(others) + per_deck - 1) // per_deck)
    for i in range(n_decks):
        lid = leaders[i % len(leaders)]
        # 非リーダーを round-robin で切り出す (全カードがどこかに 1 度は載る)
        chunk = [others[j] for j in range(i * per_deck, min((i + 1) * per_deck, len(others)))]
        if not chunk:
            # 余ったデッキ枠 (リーダー数 > チャンク数) には既出カードを詰めて 50 枚にする
            chunk = others[(i * per_deck) % len(others):][:per_deck] or others[:per_deck]
        main: list[str] = []
        for cid in chunk:
            main.extend([cid] * COPIES)
        while len(main) < DECK_SIZE:
            main.append(chunk[len(main) % len(chunk)])
        decks.append({"name": f"sweep_{i:04d}_{lid}", "leader": lid, "main": main[:DECK_SIZE]})
    return decks


_dv_cache: dict[str, str] = {}


def deck_value(d: dict) -> str:
    """合成デッキ → Rust 用 deck Value (decks/ にファイルを作らない)。"""
    key = d["name"]
    if key not in _dv_cache:
        repo, _ = P._load()
        _dv_cache[key] = json.dumps({
            "leader": _ser_full(repo.get(d["leader"])),
            "main": [_ser_full(repo.get(c)) for c in d["main"]],
            # マリガン判定材料は無し = Rust 側 tier3 (コスト3以下キャラの有無) で判断
        })
    return _dv_cache[key]


def rng_state(seed: int) -> str:
    return json.dumps(list(random.Random(seed).getstate()[1]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=6, help="1 デッキあたりの試合数 (ミラー)")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N デッキだけ (0=全部)")
    ap.add_argument("--seed0", type=int, default=900000)
    ap.add_argument("--report-sec", type=float, default=10.0)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    decks = build_synthetic_decks()
    if args.limit:
        decks = decks[: args.limit]
    covered = {d["leader"] for d in decks} | {c for d in decks for c in d["main"]}
    print(f"合成デッキ {len(decks)} 種 / 網羅カード {len(covered)} 枚 / "
          f"1 デッキ {args.games} game = 計 {len(decks) * args.games} game", flush=True)

    state = {"decks": len(decks), "games_per_deck": args.games, "done": 0,
             "games_ok": 0, "games_err": 0, "errors": {}, "sec": 0.0}
    if args.resume and OUT.exists():
        try:
            state = json.loads(OUT.read_text(encoding="utf-8"))
            print(f"[resume] {state['done']} デッキ済から再開", flush=True)
        except Exception as e:
            print(f"[resume] 読めず新規: {e}", flush=True)

    eng.reset_coverage_stats(True)   # diag ON = bail 理由 + 保存則 + 発火追跡
    t0 = time.time()
    last = t0
    errors = Counter(state.get("errors") or {})

    for di in range(state["done"], len(decks)):
        d = decks[di]
        dv = deck_value(d)
        for g in range(args.games):
            seed = args.seed0 + di * 1000 + g
            try:
                r = json.loads(eng.self_play(dv, dv, rng_state(seed), seed % 2,
                                             "greedy", None, 8, 12, 40, False, 80))
                state["games_ok"] += 1
                if r.get("invariant_violations"):
                    errors[f"INVARIANT in {d['name']}"] += int(r["invariant_violations"])
            except BaseException as e:
                # ⚠ pyo3 の PanicException は BaseException 派生 = Exception では捕まらない。
                #   panic は「未実装の明示 bail」ではなく **Rust の実バグ** なので、 掃引を止めずに
                #   全部集めきる (1 件で run が死ぬと残りが測れない)。
                state["games_err"] += 1
                kind = "PANIC" if "Panic" in type(e).__name__ else type(e).__name__
                # パニックは再現が要るのでデッキ名も残す (bail は原因が文字列で分かるので不要)
                where = f" @{d['name']}" if kind == "PANIC" else ""
                errors[f"{kind}: {str(e)[:160]}{where}"] += 1
        state["done"] = di + 1

        now = time.time()
        if now - last >= args.report_sec or state["done"] == len(decks):
            state["sec"] = now - t0
            state["errors"] = dict(errors.most_common(200))
            cv = json.loads(eng.coverage_stats())
            state["coverage"] = cv
            OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            acts = cv.get("actions") or {}
            ok = sum(v["ok"] for v in acts.values())
            bail = sum(v["bail"] for v in acts.values())
            print(f"[{state['done']}/{len(decks)} deck | {state['games_ok']} game | {state['sec']:.0f}s] "
                  f"bail {bail}/{ok+bail} ({bail/max(ok+bail,1):.2%}) / 中断 {state['games_err']} / "
                  f"保存則違反 {len(cv.get('invariant_violations') or {})} 種 / "
                  f"発火 {len(cv.get('fired_cards') or [])} 枚", flush=True)
            last = now

    cv = json.loads(eng.coverage_stats())
    fired = set(cv.get("fired_cards") or [])
    state["coverage"] = cv
    state["errors"] = dict(errors.most_common(500))
    state["covered_cards"] = len(covered)
    state["fired_cards_n"] = len(fired)
    state["never_fired"] = sorted(covered - fired)[:2000]
    state["sec"] = time.time() - t0
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 結果 ===", flush=True)
    acts = cv.get("actions") or {}
    ok = sum(v["ok"] for v in acts.values())
    bail = sum(v["bail"] for v in acts.values())
    print(f"完走 {state['games_ok']} game / 中断 {state['games_err']} game ({state['sec']:.0f}s)")
    print(f"action bail {bail}/{ok+bail} ({bail/max(ok+bail,1):.2%})")
    print(f"発火カード {len(fired)}/{len(covered)} ({len(fired)/max(len(covered),1):.1%})")
    inv = cv.get("invariant_violations") or {}
    print(f"\n保存則違反: {len(inv)} 種")
    for k, v in sorted(inv.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  {v:6d}  {k}")
    print(f"\nbail 理由 top20:")
    for k, v in sorted((cv.get("bail_reasons") or {}).items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {v:6d}  {k}")
    print(f"\nゲーム中断 top20:")
    for k, v in errors.most_common(20):
        print(f"  {v:6d}  {k}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
