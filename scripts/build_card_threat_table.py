"""データ駆動の相手キャラ脅威テーブルを corpus 集計から作る — 2026-07-25。

opp_threat._char_threat は現状 pros02 名指し + 粗い効果ラベル bucket (0.2/0.45/0.5/0.6/1.0)
で脅威度を返す = ハンドキュレート。 これを **corpus の実 outcome** で grounding する:

  card_timing_stats.json の `faced` = 「相手がこのカードを場に持つと hero 勝率がどう動くか」の lift。
  負の lift (= 対面すると hero が負けやすい) が大きいほど脅威 → 優先除去/攻撃すべき。

  threat(cid) = clamp(-faced_lift / SCALE, 0, 1)   (SCALE=0.20 = 実測の脅威上限)

⚠ faced は相関 (逆因果 = hero が負けてる→相手盤面が厚い→faced 多い、 も混じる) が、
  (1) median≈0 で card 間を判別しており一様バイアスでない (2) 決定層の **相対** ランキング
  bonus として使う (どの駒を優先攻撃するか) なので絶対値でなく順序が効く (3) 最終採否は arena A/B。
  = 因果的に完璧である必要はなく、 coarse ラベルより良い順序を与えれば良い (gate が保証)。

CHARACTER のみ (= _char_threat が場のキャラに対してのみ引く) + n>=MIN_N で信頼できる行のみ採用。
それ以外は既存の coarse ラベル挙動に fallback (= 純追加、 no-harm)。

  .venv/bin/python scripts/build_card_threat_table.py
  → db/eiv1/card_threat_table.json  ({card_id: {threat, faced_lift, n}})
"""
from __future__ import annotations
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "db" / "eiv1" / "card_timing_stats.json"
CARDS = ROOT / "db" / "cards.json"
OUT = ROOT / "db" / "eiv1" / "card_threat_table.json"

MIN_N = 200          # 信頼できる faced サンプル下限
SCALE = 0.20         # faced_lift = -0.20 を threat=1.0 に写す (実測の脅威上限)


def _base(cid: str) -> str:
    return cid.split("_")[0] if cid else cid


def main() -> None:
    stats = json.loads(STATS.read_text(encoding="utf-8"))
    faced = stats.get("faced", {})
    cat = {c["card_id"]: c.get("category") for c in json.loads(CARDS.read_text(encoding="utf-8"))}

    # phase 跨ぎで base card_id に n 重み集計
    agg: dict[str, list] = collections.defaultdict(lambda: [0.0, 0])
    for k, v in faced.items():
        cid = _base(k.split("|")[0])
        agg[cid][0] += float(v.get("lift", 0.0)) * int(v.get("n", 0))
        agg[cid][1] += int(v.get("n", 0))

    table: dict[str, dict] = {}
    for cid, (s, n) in agg.items():
        if n < MIN_N:
            continue
        if cat.get(cid) != "CHARACTER":     # _char_threat は場のキャラにのみ引く
            continue
        lift = s / n
        threat = min(1.0, max(0.0, -lift / SCALE))
        if threat <= 0.0:                   # 脅威でない (= 対面 hero 有利/中立) は載せない
            continue
        table[cid] = {"threat": round(threat, 4), "faced_lift": round(lift, 4), "n": n}

    ranked = sorted(table.items(), key=lambda kv: -kv[1]["threat"])
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {OUT.relative_to(ROOT)} — {len(table)} CHARACTER 脅威エントリ (n>={MIN_N})")
    print("=== 脅威 TOP15 ===")
    for cid, r in ranked[:15]:
        print(f"  {cid}: threat={r['threat']:.3f} (faced_lift={r['faced_lift']:+.4f}, n={r['n']})")


if __name__ == "__main__":
    main()
