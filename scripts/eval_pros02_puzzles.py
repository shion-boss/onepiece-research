"""pros02 pro-line 評価ベンチ (詰将棋型)。

pros02 由来の「このデッキ vs このデッキのこの場面ではこう行動すべき」を engine 上に局面再構成
(db/pros02_puzzles.json) → 配備 ExploitBeam に解かせ → プロの手と一致するか採点する。

- 防御は独立した強い AI (play_one_action 経由) が最善防御を行う (攻撃者の甘い想定でなく本物)。
- kind=lethal: opp を詰ませられたか (客観)。 nosuicide: 自滅しないか (客観)。
- kind=judge: AI の攻撃(パワー/回数)を記録 → Claude/人間 が pro-line 一致を採点。

用途: mirror 勝率では測れない「AI がプロの手を打つか」を直接測る評価軸 + 弱点検出オラクル。
    run: .venv/bin/python scripts/eval_pros02_puzzles.py
"""
from __future__ import annotations
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core import GameState, InPlay, Phase, Player
from engine.deck import CardRepository, DeckList
from engine.effects import load_effect_overlay
from engine.game import EndPhase
from engine.ai import play_one_action
from engine.exploit_beam_ai import ExploitBeamAI
from engine.harness import _try_load_deck_analysis

ROOT = Path(__file__).resolve().parent.parent
_repo = CardRepository.from_json(str(ROOT / "db" / "cards.json"))
_overlay = load_effect_overlay(str(ROOT / "db" / "card_effects.json"))
_ATK = re.compile(r"atk: .+?\(P=(\d+)\) -> (.+)")


def _inplay(spec: dict) -> InPlay:
    ip = InPlay.of(_repo.get(spec["cid"]), sickness=spec.get("sick", False))
    ip.attached_dons = int(spec.get("dons", 0))
    ip.rested = bool(spec.get("rested", False))
    return ip


def _make_state(p: dict) -> GameState:
    me = Player(name="ME", leader=InPlay.of(_repo.get(p["my_leader"]), sickness=False))
    opp = Player(name="OPP", leader=InPlay.of(_repo.get(p["opp_leader"]), sickness=False))
    me.characters = [_inplay(c) for c in p.get("my_chars", [])]
    opp.characters = [_inplay(c) for c in p.get("opp_chars", [])]
    me.hand = [_repo.get(h) for h in p.get("my_hand", [])]
    opp.hand = [_repo.get(h) for h in p.get("opp_hand", [])]
    me.life = [_repo.get("ST01-004")] * int(p.get("my_life", 3))
    opp.life = [_repo.get("ST01-004")] * int(p["opp_life"])
    me.deck = [_repo.get("ST01-004")] * 20
    opp.deck = [_repo.get("ST01-004")] * 20
    opp.trash = [_repo.get(t) for t in p.get("opp_trash", [])]
    me.don_active = int(p["my_don"])
    opp.don_active = int(p.get("opp_don", 0))
    st = GameState(players=[me, opp], phase=Phase.MAIN, rng=random.Random(7), effects_overlay=_overlay)
    st.turn_player_idx = 0
    st.turn_number = 5
    try:
        from engine.game import _recompute_static
        _recompute_static(st)
    except Exception:
        pass
    return st


def _ai(slug: str) -> ExploitBeamAI:
    try:
        dl = DeckList.from_json(str(ROOT / "decks" / f"{slug}.json"), _repo)
        da = _try_load_deck_analysis(dl) or {}
    except Exception:
        da = {}
    da.setdefault("deck_slug", slug)
    return ExploitBeamAI(rng=random.Random(7), deck_analysis=da)


def solve(p: dict):
    """局面を配備 AI に1ターン解かせ、 (攻撃列, opp残life, game_over, winner) を返す。"""
    st = _make_state(p)
    me_ai = _ai(p.get("my_deck_slug", "cardrush_1454"))
    def_ai = _ai(p.get("def_deck_slug", "cardrush_1385"))
    me_ai.set_ai_opp(def_ai)   # 攻撃者の sim も本物の防御 AI を使う
    seen = 0
    atks: list[tuple[int, str]] = []
    for _ in range(60):
        if st.game_over or st.turn_player_idx != 0 or st.phase != Phase.MAIN:
            break
        a = play_one_action(st, me_ai, def_ai)
        for line in st.log[seen:]:
            m = _ATK.search(line)
            if m:
                atks.append((int(m.group(1)), m.group(2)[:8]))
        seen = len(st.log)
        if isinstance(a, EndPhase):
            break
    return atks, len(st.players[1].life), st.game_over, getattr(st, "winner", None)


def main() -> None:
    data = json.loads((ROOT / "db" / "pros02_puzzles.json").read_text(encoding="utf-8"))
    puzzles = data["puzzles"]
    n_lethal = n_lethal_pass = 0
    divergences = []
    for p in puzzles:
        atks, opp_life, over, winner = solve(p)
        lethal = (opp_life == 0) or (over and winner == 0)
        lost = over and winner == 1
        kind = p["kind"]
        print(f"=== {p['name']} [{kind}] ===")
        print(f"  プロ: {p['pro_answer']}")
        print(f"  AI攻撃: {atks} / opp life={opp_life} / over={over}")
        if kind == "lethal":
            n_lethal += 1
            n_lethal_pass += 1 if lethal else 0
            print(f"  判定: {'PASS 詰めた' if lethal else '★FAIL 詰め逃し'}")
        elif kind == "nosuicide":
            print(f"  判定: {'PASS 自滅せず' if not lost else '★FAIL 自滅'}")
        else:
            print("  → judge (Claude/人間 が pro-line 一致を採点)")
        print()

    print("========== 集計 ==========")
    print(f"検証可能リーサル: {n_lethal_pass}/{n_lethal} PASS")
    print("judge 問題は上の挙動を pro_answer と突き合わせて採点 (弱点=採点者ループのターゲット候補)")


if __name__ == "__main__":
    main()
