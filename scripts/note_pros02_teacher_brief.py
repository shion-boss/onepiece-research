#!/usr/bin/env python3
"""Render distilled pros_02 piloting JSON into human-readable teacher briefs.

For each db/note_pros02/distilled/<slug>.json, write a concise piloting brief to
db/note_pros02/teacher_briefs/<deck_slug>.md (gitignored) that the Claude teacher
(scripts/claude_play.py / cloud agent) reads before piloting that deck, so the
teacher demonstrates the pros_02-recommended lines. Those good-move games then
distill into the per-deck GBM value (the proven lever that actually changes the
deployed ExploitBeam AI — [[project_claude_teacher_data_collection]] /
[[project_selfplay_self_improvement_engine]]).

Paid-derived => output stays under db/note_pros02/ (gitignored, never committed).

Usage: .venv/bin/python scripts/note_pros02_teacher_brief.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISTILLED = ROOT / "db" / "note_pros02" / "distilled"
BRIEFS = ROOT / "db" / "note_pros02" / "teacher_briefs"
# distilled slug -> deck slug (mirror of note_pros02_apply.DECK_MAP; None = new deck TBD)
from importlib import util as _u
_spec = _u.spec_from_file_location("_apply", ROOT / "scripts" / "note_pros02_apply.py")
_apply = _u.module_from_spec(_spec); _spec.loader.exec_module(_apply)
DECK_MAP = _apply.DECK_MAP


def _fmt_list(items, bullet="- "):
    return "\n".join(f"{bullet}{x}" for x in items) if items else "(なし)"


def render(dj: dict) -> str:
    L = []
    L.append(f"# 教師ブリーフ: {dj.get('leader','?')} (pros_02 piloting)")
    L.append("")
    L.append("> このデッキを操縦する時は以下の pros_02(競技勢)の方針に従って良手を demonstrate せよ。")
    L.append("> 目的 = pros_02流の指し手を記録し per-deck GBM value に蒸留すること。")
    L.append("")
    L.append(f"**アーキタイプ**: {dj.get('archetype','')}")
    L.append(f"**勝ち筋**: {dj.get('win_condition','')}")
    L.append("")
    L.append("## 全体戦略")
    L.append(dj.get("strategy_summary", ""))
    L.append("")
    L.append("## AIへの最重要指針 (notes_for_ai)")
    L.append(dj.get("notes_for_ai", ""))
    L.append("")
    L.append("## リーダー効果の使い方")
    L.append(dj.get("leader_effect_usage", ""))
    L.append("")
    L.append("## DON付与のコツ")
    L.append(dj.get("don_attach_notes", ""))
    L.append("")
    L.append("## 理想展開 (ターン毎)")
    L.append(_fmt_list(dj.get("turn_plan", [])))
    L.append("")
    L.append("## マリガン")
    mull = dj.get("mulligan", {})
    L.append("keep(全般): " + ", ".join(mull.get("keep_general", [])))
    for mk, mv in (mull.get("keep_by_matchup", {}) or {}).items():
        L.append(f"- {mk}: " + ", ".join(mv))
    L.append("")
    L.append("## キーカード")
    for kc in dj.get("key_cards", []):
        cid = kc.get("card_id")
        idtag = f" [{cid}]" if cid else ""
        L.append(f"- **{kc.get('name','')}**{idtag} ({kc.get('role','')}): {kc.get('why','')}")
    L.append("")
    L.append("## マッチアップ別立ち回り")
    for m in dj.get("matchups", []):
        L.append(f"### vs {m.get('vs','')} — {m.get('favor','')}")
        L.append(m.get("plan", ""))
        for kd in m.get("key_decisions", []):
            L.append(f"- {kd}")
        L.append("")
    L.append("## 詰め (リーサル)")
    L.append(dj.get("lethal_setup", ""))
    L.append("")
    L.append("## やりがちなミス (回避せよ)")
    L.append(_fmt_list(dj.get("common_mistakes", [])))
    L.append("")
    L.append(f"_source: pros_02 note keys {dj.get('source_keys', [])}_")
    return "\n".join(L)


def main() -> None:
    BRIEFS.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(DISTILLED.glob("*.json")):
        dslug = f.stem
        dj = json.loads(f.read_text("utf-8"))
        deck_slug = DECK_MAP.get(dslug) or dslug  # fall back to distilled slug for new decks
        (BRIEFS / f"{deck_slug}.md").write_text(render(dj), encoding="utf-8")
        n += 1
        print(f"  {dslug:14s} -> teacher_briefs/{deck_slug}.md ({len(dj.get('matchups',[]))} matchups)")
    print(f"generated {n} teacher briefs -> {BRIEFS.relative_to(ROOT)}/ (gitignored)")


if __name__ == "__main__":
    main()
