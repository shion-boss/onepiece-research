#!/usr/bin/env python3
"""人間vsAI UX fuzzer: 人間が実際にカードをプレイ + 全 modal を解決 + 防御で
ブロッカー/カウンター/【相手のアタック時】効果発動まで行い、多数 game を走らせて
crash / stuck (同 pending が進まない) / NO_ACT (action 待ち だが legal 空) / 例外 を検出。

全 pending_choice kind + 防御サブ操作を exercise して human-play UX バグを炙り出す。
末尾で「踏んだ choice kind」 を集計し、 未到達 kind を報告する (稀少 kind は
scripts/verify_rare_pending_kinds.py で決定論的に別途検証)。

使い方:
  python scripts/fuzz_human_play.py [N_GAMES]            # 既定: RandomAI 相手 (高速)
  python scripts/fuzz_human_play.py [N_GAMES] --prod     # 本番 GoalDirectedAI 相手 (低速・実 session builder)

UX (人間側 modal 解決) は相手 AI 非依存なので、 既定は RandomAI で多数 game を回し、
盤面の多様性 (= 候補が多い → modal 多発) を稼ぐ。 --prod は本番セッション構築経路の smoke。
"""
import json
import os
import random
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DECKS = ["cardrush_1342", "cardrush_1385", "cardrush_1392", "cardrush_1399",
         "cardrush_1439", "cardrush_1453", "cardrush_1454", "cardrush_1455",
         "cardrush_1456", "tcgportal_bonney", "tcgportal_calgara", "tcgportal_coby",
         "tcgportal_corazon", "tcgportal_hancock", "tcgportal_op11_luffy", "tcgportal_op13_luffy"]

# engine が立てうる全 pending_choice kind (coverage 報告用)
ALL_KINDS = {
    "activate_main_cost_pick", "activate_main_discard_pick", "counter_discard_pick",
    "end_of_turn_optional", "field_full_select_trash", "hand_to_life_pick",
    "life_taken_choice", "mulligan_confirm", "mulligan_redrawn", "on_attack_optional",
    "on_opp_attack_optional", "option_pick", "optional_cost_confirm",
    "play_event_from_hand_pick", "play_from_hand_or_trash_pick", "play_from_hand_pick",
    "play_from_trash_pick", "replace_ko_optional", "reveal_top_play_confirm",
    "scry_deck_reorder", "scry_life_reorder", "search_from_trash_pick", "search_pick",
    "search_top_n", "search_top_n_bottom_reorder", "self_hand_discard_pick",
    "summon_from_deck_pick", "target_pick", "view_life_top_choose_position",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_GAMES = next((int(a) for a in sys.argv[1:] if a.isdigit()), 40)
PROD = "--prod" in sys.argv

# lazy import (engine は重い)
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.human_session import HumanSession  # noqa: E402

_repo = None
_ov = None


def _setup():
    global _repo, _ov
    _repo = CardRepository.from_json(os.path.join(ROOT, "db", "cards.json"))
    _ov = load_effect_overlay(os.path.join(ROOT, "db", "card_effects.json"))


def _analysis(slug):
    p = os.path.join(ROOT, "decks", f"{slug}.analysis.json")
    return json.load(open(p)) if os.path.exists(p) else None


def _build_session(a, b, seed, human_first):
    if PROD:
        from api.main import _build_human_session, HumanSessionSpec
        return _build_human_session(HumanSessionSpec(deck_a_slug=a, deck_b_slug=b,
                                                     seed=seed, human_first=human_first))
    from engine.ai import RandomAI

    def _rand_factory(rng, deck_analysis=None):
        return RandomAI(rng=rng)
    return HumanSession(
        deck_a=DeckList.from_json(os.path.join(ROOT, "decks", f"{a}.json"), _repo),
        deck_b=DeckList.from_json(os.path.join(ROOT, "decks", f"{b}.json"), _repo),
        ai_factory=_rand_factory, seed=seed, effects_overlay=_ov,
        deck_a_analysis=_analysis(a), deck_b_analysis=_analysis(b), human_first=human_first)


def pick_for(payload, rng):
    """pending_choice payload を解決する picks を返す (= 全 kind を踏むよう多様に)。"""
    kind = payload.get("kind")
    lim = int(payload.get("limit", 1) or 1)
    if kind == "mulligan_confirm":
        return [1] if rng.random() < 0.25 else [0]  # 25% 引き直し → mulligan_redrawn 到達
    if kind == "mulligan_redrawn":
        return [0]
    if kind in ("optional_cost_confirm", "replace_ko_optional", "reveal_top_play_confirm",
                "on_attack_optional", "on_opp_attack_optional", "end_of_turn_optional",
                "life_taken_choice", "view_life_top_choose_position", "option_pick"):
        return [rng.choice([0, 1])]
    if kind in ("self_hand_discard_pick", "counter_discard_pick", "activate_main_discard_pick",
                "field_full_select_trash", "hand_to_life_pick", "activate_main_cost_pick"):
        cs = payload.get("candidates", []) or payload.get("cards", [])
        return list(range(min(lim, len(cs)))) if rng.random() < 0.7 else []
    if kind == "search_top_n":
        cs = payload.get("cards", [])
        matching = [c["idx"] for c in cs if c.get("matches_filter")]
        return matching[:lim] if matching else ([cs[0]["idx"]] if cs and rng.random() < 0.5 else [])
    if kind in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        return []  # ID順 fallback
    cs = payload.get("candidates") or payload.get("cards") or []
    return [rng.choice(range(len(cs)))] if cs and rng.random() < 0.8 else []


def play_one(a, b, seed, human_first, rng, seen):
    s = _build_session(a, b, seed, human_first)
    steps = 0
    last_sig = None
    same_count = 0
    while not s.state.game_over and steps < 2500:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        ck = pl.get("kind")
        if pk == "choice" and ck:
            seen.add(ck)
        sig = (pk, ck, s.state.turn_number, len(pl.get("available_opp_attack_effects") or []))
        if sig == last_sig:
            same_count += 1
            if same_count > 50:
                return ("STUCK", steps, (pk, ck, pl.get("primitive_kind")))
        else:
            same_count = 0
            last_sig = sig
        if pk == "choice":
            s.apply_human_choice(pick_for(pl, rng))
        elif pk == "action":
            acts = s.legal_actions_for_human()
            if not acts:
                return ("NO_ACT", steps, (s.state.phase.name if hasattr(s.state.phase, "name") else str(s.state.phase)))
            non_end = [x for x in acts if x.get("kind") != "EndPhase"]
            if non_end and rng.random() < 0.8:
                a_pick = rng.choice(non_end)
            else:
                a_pick = next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])
            s.apply_human_action(a_pick["idx"])
        elif pk == "defense":
            avail = pl.get("available_opp_attack_effects") or []
            if avail and rng.random() < 0.6:
                # 【相手のアタック時】効果 を click 発動 (= meta 防御 UX、 OP13-002 等)
                e = rng.choice(avail)
                seen.add("on_opp_attack_optional")
                s.apply_human_use_opp_attack_effect(e["source_iid"], e["effect_idx"])
            else:
                blk = pl.get("legal_blocker_iids") or []
                cnt = pl.get("legal_counter_card_idxs") or []
                bid = rng.choice(blk) if blk and rng.random() < 0.5 else None
                cids = [rng.choice(cnt)] if cnt and rng.random() < 0.4 else []
                s.apply_human_defense(bid, cids)
        else:
            break
    return ("OK" if s.state.game_over else "TIMEOUT", steps, None)


def main():
    _setup()
    rng = random.Random(7)
    crashes = []
    seen = set()
    results = {"OK": 0, "TIMEOUT": 0, "STUCK": 0, "NO_ACT": 0, "CRASH": 0}
    for g in range(N_GAMES):
        a = DECKS[g % len(DECKS)]
        b = rng.choice([d for d in DECKS if d != a])
        seed = rng.randint(1, 10**6)
        hf = rng.random() < 0.5
        try:
            status, steps, info = play_one(a, b, seed, hf, rng, seen)
            results[status] = results.get(status, 0) + 1
            if status != "OK":
                crashes.append((status, a, b, seed, hf, steps, info))
            print(f"  game {g+1}/{N_GAMES} {status} {a} vs {b} steps={steps}", flush=True)
        except Exception as e:
            results["CRASH"] += 1
            crashes.append(("CRASH", a, b, seed, hf, str(e), traceback.format_exc()))
            print(f"  game {g+1}/{N_GAMES} CRASH {a} vs {b} seed={seed} hf={hf}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
    print(f"=== fuzz {N_GAMES} games ({'prod GoalDirectedAI' if PROD else 'RandomAI'}) ===")
    print("results:", results)
    missing = sorted(ALL_KINDS - seen)
    print(f"exercised choice kinds: {len(seen)}/{len(ALL_KINDS)}")
    if missing:
        print(f"  未到達 (= verify_rare_pending_kinds.py で別途検証): {missing}")
    if crashes:
        print(f"\n!!! 問題 {len(crashes)} 件:")
        for c in crashes[:15]:
            print("  ", c[:7])
            if c[0] == "CRASH" and len(c) > 6:
                print("    ", c[6].splitlines()[-1])
        sys.exit(1)
    print("\n✓ crash/stuck/NO_ACT なし")


if __name__ == "__main__":
    main()
