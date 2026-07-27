# -*- coding: utf-8 -*-
"""deck-eval 信頼度較正 (2026-07-28、 ohtsuki「操縦できないのにデッキ作れるのか」への honest 回答)。

配備 AI の matrix 勝率(= 生の deck 評価)は AI-vs-AI 環境の archetype 偏りを継承する:
環境が aggro 有利・slow control を罰する(実証: 現実 tier A の紫ドフラが AI 最下位、 しかもプロ線強制でも
直らない = piloting でなく environment 要因、 project_deck_eval_pilot_bias)。
→ 生勝率をそのまま「デッキの強さ」と出さず、 (1) archetype ベースの信頼度フラグ (2) 現実 tier との乖離 を
併記して「この評価は信じてよい/過小評価の疑い」を明示する = ツールが嘘をつかない形にする。

出力: db/deck_eval_confidence.json + 人間可読レポート。
  .venv/bin/python scripts/deck_eval_confidence.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(p):
    return json.loads((ROOT / p).read_text(encoding="utf-8"))


def main():
    m = _load("db/matchup_matrix.json")
    tt = _load("db/tier_truth.json").get("tiers", {})
    meta = set(_load("db/meta_decks.json").get("meta_deck_slugs", []))

    # AI 平均勝率 (matrix、 mirror=None 除外)
    ai = {}
    names = {d["slug"]: d["name"] for d in m["decks"]}
    for row in m["matrix"]:
        wrs = [c["winrate"] for c in row["row"] if c["winrate"] is not None]
        if wrs:
            ai[row["deck_a"]] = sum(wrs) / len(wrs)
    ai_rank = {s: i + 1 for i, s in enumerate(sorted(ai, key=lambda s: -ai[s]))}

    report = []
    for slug in sorted(ai, key=lambda s: -ai[s]):
        # archetype / speed
        conf, note = "medium", ""
        try:
            a = _load(f"decks/{slug}.analysis.json")
            arch = a.get("archetype", "?"); speed = a.get("speed", "?")
        except Exception:
            arch, speed = "?", "?"
        # 信頼度ルール。 tier_truth があればそれを authority に、 無ければ archetype ヒューリスティック。
        slow = ("コントロール" in arch) or ("低速" in str(speed))
        fast = ("アグロ" in arch) or ("高速" in str(speed))
        wr = ai[slug]
        real = tt.get(slug)
        divergence = ""
        if real:  # 現実 tier で照合できる(= authority)
            rt = real["tier"]
            divergence = f"現実 {rt}/{real['expected_winrate']}"
            if wr < 0.45 and rt in ("S", "A", "B"):
                conf = "low"; divergence += " ⚠AI過小評価(現実は上位)"
                note = "現実上位なのに AI 下位 = bot 環境が slow deck を罰する典型。 実戦はより強い"
            elif wr > 0.55 and rt in ("C", "D"):
                conf = "medium"; divergence += " ⚠AI過大評価(現実は下位)"
                note = "AI が過大評価。 実戦はより弱い可能性"
            else:
                conf = "high"; note = "AI 評価が現実 tier と整合 = 信頼できる"
        else:  # 現実 tier 無し = 未照合(tier_truth は 5/24 しかカバーしない)
            if fast:
                conf = "high"; note = "aggro/高速 = AI 環境と整合、 評価は信頼できる(実 tier 未照合)"
            elif slow and wr < 0.45:
                conf = "medium"; note = "control/低速 + AI 低評価 = 過小評価の疑い(bot は slow deck を罰する)。 実 tier 未照合で未確定"
            else:
                conf = "medium"; note = "要照合(実 tier データ無し)"
        report.append({
            "slug": slug, "name": names.get(slug, slug), "is_meta": slug in meta,
            "ai_winrate": round(ai[slug], 3), "ai_rank": ai_rank[slug],
            "archetype": arch, "speed": speed,
            "eval_confidence": conf, "real_tier": divergence or None, "note": note,
        })

    (ROOT / "db" / "deck_eval_confidence.json").write_text(
        json.dumps({"_comment": "deck-eval 信頼度較正。 ai_winrate は生の AI 評価、 eval_confidence で信頼度を明示。",
                    "decks": report}, ensure_ascii=False, indent=1), encoding="utf-8")

    # レポート
    print(f"=== deck-eval 信頼度較正 ({len(report)} decks) ===")
    print(f"{'順':>2} {'deck':20} {'AI勝率':>6} {'信頼度':>7}  現実tier / 注記")
    for r in report:
        cf = {"high": "信頼◎", "medium": "中△", "low": "要注意✗"}[r["eval_confidence"]]
        mm = "★" if r["is_meta"] else " "
        print(f"{r['ai_rank']:>2}{mm}{r['name'][:18]:20} {r['ai_winrate']*100:5.0f}% {cf:>7}  {r['real_tier'] or ''}")
    lo = sum(1 for r in report if r["eval_confidence"] == "low")
    print(f"\n信頼度: 高 {sum(1 for r in report if r['eval_confidence']=='high')} / "
          f"中 {sum(1 for r in report if r['eval_confidence']=='medium')} / 低(過小評価疑い) {lo}")
    print(f"→ db/deck_eval_confidence.json")


if __name__ == "__main__":
    main()
