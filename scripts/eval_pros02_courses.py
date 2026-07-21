"""pros02 マッチアップ操縦コース (形C) の実行/検証ハーネス。

db/pros02_courses.json の各コース = (自デッキ vs 相手デッキ) のターン毎ステップ。
各ステップで盤面をロード → 配備 AI に1ターン打たせ → 「プロの理想手 + 理由」と AI の実手を並べる。

用途:
  - コンテンツ検証 (盤面が妥当にロードでき、 AI が動くか)
  - 教育比較 / 弱点 surface (各ターンで プロ line vs 配備AI の乖離を見る)
盤面は形C の on-rails (ユーザーのズレを引きずらず 各ターンは プロの盤面から)。

  run: .venv/bin/python scripts/eval_pros02_courses.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.eval_pros02_puzzles import solve  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    data = json.loads((ROOT / "db" / "pros02_courses.json").read_text(encoding="utf-8"))
    for course in data["courses"]:
        print("=" * 70)
        print(f"■ {course['title']}")
        print(f"  出典: {course['source']}")
        print(f"  マッチアップ方針: {course['matchup_note']}")
        print("=" * 70)
        for step in course["steps"]:
            p = dict(step["state"])
            p["my_deck_slug"] = course["my_deck"]
            p["def_deck_slug"] = course["opp_deck"]
            atks, plays, opp_life, over, winner = solve(p)
            print(f"\n--- {course['title'].split(' vs')[0]} {step['turn']}ターン目 ---")
            print(f"  【プロの理想手】 {step['ideal_summary']}")
            print(f"  【理由】 {step['reasoning']}")
            print(f"  【参考: 配備AIの手】 攻撃={atks} / プレイ={plays} / opp life {p['opp_life']}→{opp_life}")
        print()


if __name__ == "__main__":
    main()
