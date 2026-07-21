#!/usr/bin/env python3
"""決定点スキャナ — 『同じ採点法で AI 強化 + 人間教材』の共有フロントエンド。

ohtsuki 方針 (2026-07-21): 手を採点する方法 (= engine/training_grader) で AI を強化し、
その副産物として人間向け学習コンテンツを用意する。 検出器は 1 つで、 基準(reference)を
差し替えるだけで両方を生む:
  - 人間教材: 基準 = 配備AI (人間 < AI → AI 最善が手本)
  - AI 強化 : 基準 = 配備AIより強いもの (pro line / rollout オラクル / 深い探索 → AIの間違い検出)

このスキャナは各決定点で {配備AIの手(value+事実), 基準(pro line), 乖離} を **共有レコード**
(db/decision_points.json) に出力する。 このレコードは:
  (A) AI 強化 = 乖離を detection-discipline で検証 → 真の悪手なら residual feature → A/B gate → 配備
  (B) 人間教材 = そのまま /training コース (盤面 + AI最善 + 事実 + プロ定石)

現状 source = pros02 コース (pro = 強い基準)。 self-play + rollout 基準は次段で足す
(= [[project_rollout_teacher_loop]] の既存オラクルを reference に差す)。

run: .venv/bin/python scripts/scan_decision_points.py
"""
from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.main import (  # noqa: E402
    HumanSessionSpec,
    _build_default_ai_factory,
    _build_human_session,
)
from engine.ai import play_one_action  # noqa: E402
from engine.training_grader import turn_facts, value_pwin  # noqa: E402


def _ai_line(spec: HumanSessionSpec, max_actions: int = 40):
    """配備 AI に人間ターンを打たせ、 (終局面 state, 開始 state) を返す。"""
    start = _build_human_session(spec)
    start.advance_until_pause()
    start_state = copy.deepcopy(start.state)
    hidx = start.human_idx

    sess = _build_human_session(spec)
    sess.advance_until_pause()
    hai = _build_default_ai_factory(spec.deck_a_slug, spec.deck_b_slug)(random.Random(11))
    oai = _build_default_ai_factory(spec.deck_b_slug, spec.deck_a_slug)(random.Random(12))
    for _ in range(max_actions):
        if sess.state.turn_player_idx != hidx or sess.state.game_over:
            break
        try:
            play_one_action(sess.state, hai, oai)
        except Exception:
            break
    return sess.state, start_state, hidx


def _divergence(pro_summary: str, pro_actions: list, facts: dict) -> dict:
    """AI の事実 vs プロの意図 の粗い乖離検出 (= 検証待ちの candidate flag、 断定でない)。"""
    text = (pro_summary or "") + " " + " ".join(pro_actions or [])
    pro_attacks = any(k in text for k in ("顔", "アタック", "殴る", "攻撃"))
    pro_develops = any(k in text for k in ("展開", "ブロッカー", "登場", "並べ"))
    ai_dealt = facts.get("opp_life_dealt", 0)
    ai_added = facts.get("my_chars_added", 0)

    if pro_attacks and not pro_develops and ai_dealt == 0 and ai_added > 0:
        return {"flag": True, "kind": "aggro_vs_develop",
                "note": "プロは攻めるが AI は展開 (顔ダメージ0)。 レース vs 盤面の判断が要検証。"}
    if pro_develops and not pro_attacks and ai_added == 0 and ai_dealt > 0:
        return {"flag": True, "kind": "develop_vs_aggro",
                "note": "プロは展開するが AI は攻めた (展開0)。 盤面作りの遅れが要検証。"}
    return {"flag": False, "kind": "aligned",
            "note": "AI の手はプロの意図と概ね整合 (乖離なし)。"}


def scan_courses() -> list:
    data = json.loads((ROOT / "db" / "pros02_courses.json").read_text(encoding="utf-8"))
    records = []
    for course in data["courses"]:
        for si, step in enumerate(course["steps"]):
            st = dict(step["state"])
            st["turn"] = step["turn"]
            spec = HumanSessionSpec(
                seed=7, deck_a_slug=course["my_deck"], deck_b_slug=course["opp_deck"],
                human_first=True, puzzle_state_override=st, single_turn=True,
            )
            ai_end, start_state, hidx = _ai_line(spec)
            facts = turn_facts(start_state, ai_end, hidx)
            pwin = value_pwin(ai_end, hidx)
            div = _divergence(step.get("ideal_summary", ""), step.get("ideal_actions", []), facts)
            records.append({
                "source": "pros02_course",
                "course_id": course["course_id"],
                "step": si,
                "turn": step["turn"],
                "my_deck": course["my_deck"],
                "opp_deck": course["opp_deck"],
                "ai_line": {
                    "value_pwin": None if pwin is None else round(pwin, 3),
                    "facts": facts,
                },
                "reference": {
                    "kind": "pro",
                    "summary": step.get("ideal_summary"),
                    "actions": step.get("ideal_actions", []),
                    "reasoning": step.get("reasoning"),
                },
                "divergence": div,
                "content_ready": True,   # 全レコードは /training コンテンツとして使える
            })
    return records


def main() -> None:
    records = scan_courses()
    out = ROOT / "db" / "decision_points.json"
    out.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2), encoding="utf-8")

    diverging = [r for r in records if r["divergence"]["flag"]]
    print(f"決定点 {len(records)} 件をスキャン → {out.name}")
    print(f"  AI強化 candidate (プロと乖離、 要検証): {len(diverging)} 件")
    print(f"  人間教材 content-ready: {len(records)} 件 (全件)")
    print()
    for r in records:
        d = r["divergence"]
        mark = "⚠乖離" if d["flag"] else "整合"
        pw = r["ai_line"]["value_pwin"]
        f = r["ai_line"]["facts"]
        print(f"[{r['course_id']} T{r['turn']}] {mark} ({d['kind']}) | AI: P(win)={pw} "
              f"攻撃ライフ{f['opp_life_dealt']}/展開{f['my_chars_added']}体/DON残{f['don_unused']}")
        print(f"    プロ: {r['reference']['summary']}")
        if d["flag"]:
            print(f"    → {d['note']}")


if __name__ == "__main__":
    main()
