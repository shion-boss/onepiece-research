"""「相手のエンジンを放置すると何が起きるか」を corpus から機構ごと掘る — 2026-07-24。

ohtsuki:「起動メインでサーチできるカードを放置してたら相手が手札で超えてきて不利になった、
みたいなことも気づけるはず」。

単なる相関 (「X が場に居ると負ける」) より一段強い形で測る:
  ① 相手のエンジン (起動メイン × サーチ/ドロー/展開) が **何ターン生き残ったか** (= 放置期間)
  ② 放置期間ごとの 勝率 (デッキ平均を引いた lift) → **用量反応** があるか
  ③ 同期間の **手札差の推移** → 「手札で超えられた」という機構が実際に見えるか

用量反応 (放置が長いほど悪化) + 機構 (手札差が開く) の 2 つが揃えば、 単なる相関より
因果に近い証拠になる。 ⚠ それでも「不利だから除去できなかった」逆因果は残る → 最終確認は rollout。

  .venv/bin/python scripts/eiv1_mine_engine_neglect.py --sample 200000
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"
ENGINE_LABELS = {"search", "draw", "play_accel", "ramp_don", "recursion"}


def _engine_cards() -> dict:
    """card_id → エンジン種別 (起動メインで繰り返し回るもの / 登場時一発 は除く)。"""
    from engine import card_labels as CL
    out = {}
    for cid, meta in CL.build_all().items():
        labels = set(meta.get("labels") or ())
        timings = set(meta.get("timings") or ())
        hit = labels & ENGINE_LABELS
        if hit and "t_activate_main" in timings:
            out[cid] = sorted(hit)[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200000)
    ap.add_argument("--min-n", type=int, default=30)
    a = ap.parse_args()
    eng = _engine_cards()
    print(f"起動メイン型エンジン: {len(eng)} 種 (search/draw/play_accel/ramp_don/recursion)")

    lines = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > a.sample:
                lines.pop(0)
    games: dict = defaultdict(lambda: defaultdict(list))
    for line in lines:
        try:
            d = json.loads(line)
            s = d.get("state")
            if not s or not d.get("g"):
                continue
            hi = s["hero_idx"]
            me, opp = s["players"][hi], s["players"][1 - hi]
            games[d["g"]][hi].append((
                int(s.get("turn_number") or 0),
                [c["card_id"] for c in (opp.get("field") or []) if c.get("card_id")],
                int(me.get("hand_count") or 0), int(opp.get("hand_count") or 0),
                int(d["y"]), d.get("hero") or "?",
            ))
        except Exception:
            continue

    deck_n, deck_w = Counter(), Counter()
    for gid, seats in games.items():
        for hi, rows in seats.items():
            if rows:
                deck_n[rows[-1][5]] += 1
                deck_w[rows[-1][5]] += rows[-1][4]
    base = {d: deck_w[d] / deck_n[d] for d in deck_n if deck_n[d]}

    # 放置期間 → [n, 勝ち超過, 手札差の開き]
    by_dur: dict = defaultdict(lambda: [0, 0.0, 0.0])
    by_kind: dict = defaultdict(lambda: [0, 0.0])
    for gid, seats in games.items():
        for hi, rows in seats.items():
            rows.sort(key=lambda r: r[0])
            if len(rows) < 3:
                continue
            y, deck = rows[-1][4], rows[-1][5]
            if deck not in base:
                continue
            # 相手のエンジンごとに「初めて見えたターン」と「消えたターン」を追う
            first: dict = {}
            last: dict = {}
            hand_at: dict = {}
            for i, (turn, opp_b, mh, oh, _y, _d) in enumerate(rows):
                for cid in set(opp_b):
                    if cid in eng:
                        if cid not in first:
                            first[cid] = i
                            hand_at[cid] = oh - mh      # 出現時の手札差 (相手 − 自分)
                        last[cid] = i
            for cid, i0 in first.items():
                dur = last[cid] - i0 + 1                # 自分の手番何回ぶん生き残ったか
                b = "1" if dur <= 1 else ("2" if dur == 2 else ("3" if dur == 3 else "4+"))
                d_hand = (rows[last[cid]][3] - rows[last[cid]][2]) - hand_at[cid]
                e = by_dur[b]
                e[0] += 1
                e[1] += y - base[deck]
                e[2] += d_hand
                k = by_kind[(eng[cid], b)]
                k[0] += 1
                k[1] += y - base[deck]

    print(f"\ngame 数 {len(games):,} / 観測されたエンジン出現 "
          f"{sum(v[0] for v in by_dur.values()):,} 件\n")
    print("■ 相手エンジンを放置した期間 → 自分の勝率 lift と 手札差の変化")
    print(f"   {'放置':<6} {'n':>7}  {'勝率lift':>9}  {'手札差の開き':>12}")
    for b in ("1", "2", "3", "4+"):
        n, lift, dh = by_dur[b]
        if n < a.min_n:
            continue
        print(f"   {b + 'ターン':<8} {n:>6}  {lift / n * 100:>+8.1f}pt  {dh / n:>+10.2f} 枚")
    print("\n■ エンジン種別 × 放置期間 (勝率 lift)")
    kinds = sorted({k for k, _ in by_kind})
    print(f"   {'種別':<12} " + "  ".join(f"{b + 'T':>10}" for b in ("1", "2", "3", "4+")))
    for kind in kinds:
        cells = []
        for b in ("1", "2", "3", "4+"):
            n, lift = by_kind[(kind, b)]
            cells.append(f"{lift / n * 100:>+7.1f}({n:>3})" if n >= a.min_n else f"{'-':>10}")
        print(f"   {kind:<12} " + "  ".join(cells))


if __name__ == "__main__":
    main()
