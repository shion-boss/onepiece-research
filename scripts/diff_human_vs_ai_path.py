# -*- coding: utf-8 -*-
"""人間経路 vs AI経路 差分ハーネス (= ohtsuki 提案: AI経路を正解にして差分を見る)。

AI経路 (apply_action) は 799 テスト + RuleReferee 監視済で「正解」 寄り。 人間経路
(HumanSession の modal 解決) は その上に追加レイヤーがあり、 そこにバグが集中していた
(unique_name/no_effect/recompute 等)。

そこで: **同じ deck・同じ seed で、 人間 bot が AI と同じ手を打つ** ように人間経路を走らせ、
同条件の AI 経路ゲームと **盤面 signature を毎手照合**。 ズレた所 = 人間経路バグ候補。

人間 bot の方針: 行動は GreedyAI.choose_action と同じ (= legal_actions の同 index)、
選択 modal は「AI の自動解決と等価」 になるよう deterministic に解く。 防御も同様。

出力: deck/seed ごとに 「最初に signature がズレた手番 + 両盤面」 を報告。

⚠ WIP (2026-06-04): 現状は AI経路ゲームと 人間経路ゲームを **別々に** 走らせて比較して
いるが、 両者は setup/rng/mulligan の消費が異なるため **同一ゲームになっておらず**、
勝敗のズレは「別ゲームだから」 であってバグとは限らない (= ノイズ)。 真に有効にするには
**1 つのゲームを各 choice で fork し、 AI内部解決 vs 人間modal解決 の盤面だけを直接比較**
する lockstep 化が必要。 ここが残作業。 ohtsuki 提案の正しい実装形。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.game import setup_game, legal_actions, apply_action, play_until_main  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.human_session import HumanSession  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")


def load_deck(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", repo)


def board_sig(state):
    """両プレイヤーの盤面要約 (= 経路非依存の確定情報)。"""
    out = []
    for p in state.players:
        out.append((
            len(p.life), len(p.hand),
            tuple(sorted(c.card.card_id for c in p.characters)),
            tuple(sorted(c.card.card_id for c in p.stages)),
            len(p.trash),
            p.don_active + p.don_rested
            + sum(getattr(c, "attached_dons", 0) for c in [*p.characters, p.leader]),
        ))
    return tuple(out)


def run_ai_path(deck_a, deck_b, seed):
    """両プレイヤー AI (apply_action 経路)。 手ごとの board_sig を記録。"""
    rng = random.Random(seed)
    state = setup_game(deck_a, deck_b, rng=rng, first_player=0,
                       effects_overlay=overlay)
    ais = [GreedyAI(random.Random(seed * 3 + i)) for i in range(2)]
    sigs = []
    steps = 0
    while not state.game_over and steps < 800:
        steps += 1
        play_until_main(state)  # refresh/draw/don を進めて MAIN へ (= 人間経路と同等の進行)
        if state.game_over:
            break
        acts = legal_actions(state)
        if not acts:
            break
        a = ais[state.turn_player_idx].choose_action(state)
        apply_action(state, a)
        sigs.append(board_sig(state))
    return {"winner": state.winner, "turns": state.turn_number, "sigs": sigs,
            "over": state.game_over}


def _pick_choice(payload, _rng):
    """modal を AI 自動解決と等価に解く (= 自然な「該当を取る」)。"""
    k = payload.get("kind")
    lim = int(payload.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]  # keep (= setup の AI 既定と揃える)
    if k == "search_top_n":
        cs = payload.get("cards", [])
        m = [c["idx"] for c in cs if c.get("matches_filter")]
        return m[:lim]
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        return []  # 元順
    if k in ("optional_cost_confirm", "on_attack_optional", "on_opp_attack_optional",
             "end_of_turn_optional", "replace_ko_optional", "reveal_top_play_confirm",
             "view_life_top_choose_position", "option_pick", "life_taken_choice"):
        return [0]
    cands = payload.get("candidates") or payload.get("cards") or payload.get("options") or []
    return list(range(min(lim, len(cands))))


def run_human_path(deck_a, deck_b, seed):
    """player0 を 人間経路 (HumanSession) で、 GreedyAI を真似て操作。 board_sig 記録。"""
    sess = HumanSession(deck_a=deck_a, deck_b=deck_b,
                        ai_factory=lambda rng, da=None: GreedyAI(rng),
                        seed=seed, effects_overlay=overlay, human_first=True)
    mimic = GreedyAI(random.Random(seed * 3 + 0))  # player0 = human、 AI path と同 seed
    sess.advance_until_pause()
    sigs = []
    rng = random.Random(seed)
    steps = 0
    while not sess.state.game_over and steps < 800:
        steps += 1
        pk = sess.pending_kind
        if pk == "action":
            acts = legal_actions(sess.state)
            if not acts:
                break
            a = mimic.choose_action(sess.state)
            # AI が選んだ Action の index を legal_actions から特定
            idx = next((i for i, x in enumerate(acts) if repr(x) == repr(a)), 0)
            sess.apply_human_action(idx)
            sigs.append(board_sig(sess.state))
        elif pk == "choice":
            sess.apply_human_choice(_pick_choice(sess.pending_payload or {}, rng))
            sigs.append(board_sig(sess.state))
        elif pk == "defense":
            sess.apply_human_defense(None, [])
            sigs.append(board_sig(sess.state))
        else:
            break
    return {"winner": sess.state.winner, "turns": sess.state.turn_number,
            "sigs": sigs, "over": sess.state.game_over}


def diff_one(slug, seed):
    da, db = load_deck(slug), load_deck(slug)
    try:
        ai = run_ai_path(da, db, seed)
        hu = run_human_path(da, db, seed)
    except Exception as e:
        return {"slug": slug, "seed": seed, "crash": f"{type(e).__name__}: {e}"}
    # 最終 winner / turns の一致 (= 粗い signal)
    same_final = (ai["winner"] == hu["winner"] and ai["over"] == hu["over"])
    return {"slug": slug, "seed": seed,
            "ai": (ai["winner"], ai["turns"], len(ai["sigs"])),
            "hu": (hu["winner"], hu["turns"], len(hu["sigs"])),
            "same_final": same_final}


def main():
    slugs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cardrush_1392"]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    mism = 0
    for slug in slugs:
        for s in range(n):
            r = diff_one(slug, 1000 + s)
            if r.get("crash"):
                print(f"  [CRASH] {slug} seed{1000+s}: {r['crash']}")
                mism += 1
            elif not r["same_final"]:
                print(f"  [DIFF] {slug} seed{1000+s}: AI={r['ai']} HUMAN={r['hu']}")
                mism += 1
        print(f"=== {slug}: {n} seeds, {mism} mismatch ===")
    print(f"\n総 mismatch/crash: {mism}")


if __name__ == "__main__":
    main()
