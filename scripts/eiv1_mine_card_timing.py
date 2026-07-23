"""corpus から「いつ・どのカードを出すと勝つか / 相手に何が居ると負けるか」を掘る — 2026-07-24。

corpus は行動を保存していないが、 **同じ席の連続スナップショットの差分**で復元できる:
  board(t2) − board(t1) = そのターンに出した (or 効果で出た) カード
  board(t1) − board(t2) = そのターンに失った カード

⚠ デッキ交絡の除去: 「カード X を出したゲームは勝率が高い」の大半は「X を積むデッキが強い」。
そこで **同じ hero デッキの平均勝率をベースラインに引く** (= デッキ内での lift)。
これで「そのデッキの中で、 X を T ターン目に出せた展開は勝ちやすいか」になる。

⚠ それでも相関であって因果ではない (X を 3 ターン目に出せた = 事故らなかった、 のかもしれない)。
因果が要る所は rollout で測る。 ここは候補を炙り出す第 1 段。

  .venv/bin/python scripts/eiv1_mine_card_timing.py --sample 200000 --min-n 40
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "db" / "eiv1" / "corpus.jsonl"
OUT = ROOT / "db" / "eiv1" / "card_timing_stats.json"


def _bucket(turn: int) -> str:
    if turn <= 4:
        return "序盤(1-4)"
    if turn <= 7:
        return "中盤(5-7)"
    if turn <= 10:
        return "終盤(8-10)"
    return "長期(11+)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=200000)
    ap.add_argument("--min-n", type=int, default=40, help="この回数以上出現したものだけ report")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    lines = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if len(lines) > a.sample:
                lines.pop(0)

    # game_id → seat → [(turn, my_board, opp_board, y, hero_deck)]
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
                [c["card_id"] for c in (me.get("field") or []) if c.get("card_id")],
                [c["card_id"] for c in (opp.get("field") or []) if c.get("card_id")],
                int(d["y"]), d.get("hero") or "?",
            ))
        except Exception:
            continue

    deck_n: dict = defaultdict(int)
    deck_w: dict = defaultdict(int)
    played: dict = defaultdict(lambda: [0, 0])   # (card, bucket) → [n, wins]
    faced: dict = defaultdict(lambda: [0, 0])    # 相手の場に居た
    lost_: dict = defaultdict(lambda: [0, 0])    # 自分が失った
    for gid, seats in games.items():
        for hi, rows in seats.items():
            rows.sort(key=lambda r: r[0])
            if not rows:
                continue
            y, deck = rows[-1][3], rows[-1][4]
            deck_n[deck] += 1
            deck_w[deck] += y
            prev_my: list = []
            seen_faced = set()
            for turn, my, opp_b, _y, _d in rows:
                from collections import Counter
                new = Counter(my) - Counter(prev_my)
                gone = Counter(prev_my) - Counter(my)
                b = _bucket(turn)
                for cid, k in new.items():
                    e = played[(cid, b, deck)]
                    e[0] += 1
                    e[1] += y
                for cid, k in gone.items():
                    e = lost_[(cid, b, deck)]
                    e[0] += 1
                    e[1] += y
                for cid in set(opp_b):
                    key = (cid, b, deck)
                    if key in seen_faced:
                        continue
                    seen_faced.add(key)
                    e = faced[key]
                    e[0] += 1
                    e[1] += y
                prev_my = my

    base = {d: (deck_w[d] / deck_n[d]) for d in deck_n if deck_n[d] > 0}

    def _agg(tbl):
        """(card, bucket) 単位に集約し、 デッキ baseline を引いた lift を出す。"""
        acc: dict = defaultdict(lambda: [0, 0.0])
        for (cid, b, deck), (n, w) in tbl.items():
            if deck not in base or n <= 0:
                continue
            e = acc[(cid, b)]
            e[0] += n
            e[1] += w - n * base[deck]      # 期待勝ち数からの超過
        return {k: (n, lift / n) for k, (n, lift) in acc.items() if n >= a.min_n}

    res = {"played": _agg(played), "faced": _agg(faced), "lost": _agg(lost_)}
    cards = json.loads((ROOT / "db" / "cards.json").read_text(encoding="utf-8"))
    if isinstance(cards, dict):
        cards = cards.get("cards", cards)
    nm = {c["card_id"]: c.get("name", "") for c in cards if isinstance(c, dict)}

    print(f"game 数 {len(games):,} / デッキ {len(base)} / 解析行 {len(lines):,}\n")
    for tag, title in (("played", "■ このタイミングで出すと勝つ (デッキ平均比)"),
                       ("faced", "■ 相手の場にこれが居ると負ける (デッキ平均比)"),
                       ("lost", "■ このタイミングで失うと負ける (デッキ平均比)")):
        rows = sorted(res[tag].items(), key=lambda kv: -kv[1][1])
        rows = rows if tag == "played" else sorted(res[tag].items(), key=lambda kv: kv[1][1])
        print(title)
        for (cid, b), (n, lift) in rows[:a.top]:
            print(f"   {b:<10} {cid:<10} {nm.get(cid, '')[:16]:<18} n={n:>5}  lift={lift * 100:+.1f}pt")
        print()
    OUT.write_text(json.dumps(
        {t: {f"{c}|{b}": {"n": n, "lift": lf} for (c, b), (n, lf) in v.items()}
         for t, v in res.items()}, ensure_ascii=False), encoding="utf-8")
    print(f"→ {OUT} に保存")


if __name__ == "__main__":
    main()
