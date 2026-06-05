# -*- coding: utf-8 -*-
"""lockstep human-vs-AI board-equality diff (= 2026-06-05、 memory「人間経路バグ根絶の本命」)。

構造オラクル (保存則/DON/RuleReferee) は「カードが複製/消失しない」 は見るが、 **人間 modal 解決が
AI 内部解決と違う結果 (= 間違ったカード/対象/プレイヤーの zone を操作)** は見ない (= 保存則は
「正しいカードが動いたか」 を問わない)。 これを直接捕捉する。

⭐ 手法: 人間ゲームの各 pool-pick modal (= 候補から選んで召喚/検索) の時点で state を **fast_clone**
で fork し、 fork 上で **AI inline 解決** (= forced_human_actor_idx=-1 で modal を出さず auto-pick)
を実行 → 参照盤面を得る。 本体は **人間 modal 解決** で AI と **同じカード** を pick。 両盤面の
digest (= 各プレイヤーの hand/deck/trash/life/characters/stages/DON の card_id 集合) を直接比較。
ズレ = 人間経路バグ (= AI 経路が正解、 799 test + RuleReferee 監視済)。

対象 = modal が **mutation 前** に立つ 5 pick kind (= fork→inline 再実行が安全):
  play_from_hand_pick / play_from_trash_pick / summon_from_deck_pick /
  play_from_hand_or_trash_pick / search_pick

  python scripts/lockstep_human_vs_ai.py [SLUGS] [N]
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay, execute_effect  # noqa: E402
from engine.game import legal_actions, _recompute_static  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.human_session import HumanSession  # noqa: E402
from engine.plan_search import fast_clone  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

POOL_PICK = {
    "play_from_hand_pick", "play_from_trash_pick", "summon_from_deck_pick",
    "play_from_hand_or_trash_pick", "search_pick",
}

# choice.kind → primitive 名 (= AI inline 再実行で使う)
KIND2PRIM = {
    "play_from_hand_pick": "play_from_hand",
    "play_from_trash_pick": "play_from_trash",
    "summon_from_deck_pick": "summon_from_deck",
    "play_from_hand_or_trash_pick": "play_from_hand_or_trash",
    "search_pick": "search",
}


def _load(slug):
    import json
    dl = DeckList.from_json(ROOT / "decks" / f"{slug}.json", repo)
    ap = ROOT / "decks" / f"{slug}.analysis.json"
    ana = json.load(open(ap)) if ap.exists() else None
    return dl, ana


def board_digest(state):
    """盤面を card_id 集合レベルで digest (= deck shuffle 順や RNG に非依存、 zone/player/枚数に敏感)。"""
    out = []
    for p in state.players:
        chars = tuple(sorted(
            (ip.card.card_id, int(ip.power), bool(ip.rested), int(ip.attached_dons))
            for ip in p.characters))
        out.append((
            tuple(sorted(c.card_id for c in p.hand)),
            tuple(sorted(c.card_id for c in p.deck)),
            tuple(sorted(c.card_id for c in p.trash)),
            len(p.life),
            chars,
            tuple(sorted(s.card.card_id for s in p.stages)),
            (p.don_active, p.don_rested, p.don_remaining_in_deck),
            p.leader.card.card_id,
        ))
    return tuple(out)


def _resolve_inline_on_fork(state, choice):
    """fork 上で AI inline 解決 (= modal を出さず auto-pick)。 解決後の state を返す。"""
    kind = choice.get("kind")
    prim = KIND2PRIM[kind]
    prim_val = choice.get("primitive_value")
    actor_idx = choice.get("_actor_idx")
    if actor_idx is None or not isinstance(prim_val, (dict, int)):
        return None
    me = state.players[actor_idx]
    opp = state.players[1 - actor_idx]
    source_iid = choice.get("source_iid")
    self_inplay = None
    if source_iid is not None:
        for ip in [*me.characters, me.leader, *me.stages, *opp.characters, opp.leader, *opp.stages]:
            if ip.instance_id == source_iid:
                self_inplay = ip
                break
    # AI モード強制 (= modal を出さず inline auto-pick)
    state.forced_human_actor_idx = -1
    state.pending_choice = None
    # primitive_value は filter/limit を持つ元 spec (= _picks なし)。 dict を copy して再実行。
    spec = dict(prim_val) if isinstance(prim_val, dict) else prim_val
    if isinstance(spec, dict):
        for k in ("_picks", "_picks_idx", "_picked_deck_idxs", "_picked_hand_idxs"):
            spec.pop(k, None)
    try:
        execute_effect({prim: spec}, state, me, opp, self_inplay)
        # ⭐ multi-do 効果 (= OP14-084 の 2連続 play_from_trash 等): modal は最初の do で立つが、
        #   人間側は resolve_pending_choice の _continuation で **残り do も実行** する。 S_ai でも
        #   同じく continuation を実行しないと「第2 do 欠落」 で偽の盤面差になる。
        cont = choice.get("_continuation")
        if cont is not None:
            from engine.effects import _run_continuation
            _run_continuation(state, cont)
    except Exception as e:  # noqa: BLE001
        return ("ERR", f"inline 再実行 例外: {type(e).__name__}: {str(e)[:60]}")
    _recompute_static(state)
    return state


def _human_picks_matching(choice, ref_state, pre_digest):
    """AI inline (ref_state) が実際に動かしたカードに揃う 人間 candidate index を返す。

    ⚠ **登場先 zone の gained のみ** を見る (= play系は characters+stages、 search は hand)。
    かつ **candidate に存在する card_id に限定**。 これで then_life_to_hand 等の hand 副作用や
    on_play cascade 召喚 (= candidate 外) が wanted を汚染して誤 pick するのを防ぐ
    (2026-06-05 calgara カルガラ then_life_to_hand で誤検出 → 修正)。"""
    actor_idx = choice.get("_actor_idx")
    pre = pre_digest[actor_idx]
    post = board_digest(ref_state)[actor_idx]
    cands = choice.get("candidates", [])
    cand_ids = Counter(c.get("card_id") for c in cands)
    if choice.get("kind") == "search_pick":
        gained = Counter(post[0]) - Counter(pre[0])  # deck → hand
    else:
        gained = ((Counter(cid for cid, *_ in post[4]) + Counter(post[5]))
                  - (Counter(cid for cid, *_ in pre[4]) + Counter(pre[5])))  # → field
    limit = int(choice.get("limit", 1) or 1)
    picks = []
    used = Counter()
    for i, c in enumerate(cands):
        if len(picks) >= limit:
            break
        cid = c.get("card_id")
        if used[cid] < min(gained.get(cid, 0), cand_ids.get(cid, 0)):
            used[cid] += 1
            picks.append(i)
    return picks


def run(slug_a, slug_b, seed, divergences, stats):
    da, aa = _load(slug_a)
    db, ab = _load(slug_b)
    sess = HumanSession(deck_a=da, deck_b=db,
                        ai_factory=lambda rng, d=None: GreedyAI(rng),
                        seed=seed, effects_overlay=overlay,
                        deck_a_analysis=aa, deck_b_analysis=ab, human_first=True)
    rng = random.Random(seed * 3 + 1)
    sess.advance_until_pause()
    steps = 0
    while not sess.state.game_over and steps < 800:
        steps += 1
        pk = sess.pending_kind
        if pk == "action":
            acts = sess.legal_actions_for_human()
            if not acts:
                break
            # play-heavy: カード展開/効果発動/起動メインを優先 (= pool-pick modal を多く誘発)。
            # action は fork しない (= choice 時のみ fork して比較) ので policy は何でも良い。
            prefer = [x for x in acts if x.get("kind") in
                      ("PlayCharacter", "PlayEvent", "PlayStage", "ActivateMain")]
            non_end = [x for x in acts if x.get("kind") != "EndPhase"]
            if prefer and rng.random() < 0.85:
                idx = rng.choice(prefer)["idx"]
            elif non_end and rng.random() < 0.6:
                idx = rng.choice(non_end)["idx"]
            else:
                idx = next((x["idx"] for x in acts if x.get("kind") == "EndPhase"), acts[0]["idx"])
            sess.apply_human_action(idx)
        elif pk == "choice":
            choice = dict(sess.state.pending_choice or {})
            kind = choice.get("kind")
            if kind in POOL_PICK and isinstance(choice.get("primitive_value"), (dict, int)) \
                    and choice.get("_actor_idx") is not None:
                pre_digest = board_digest(sess.state)
                # ⭐ 同一 state から 2 fork (= fast_clone の deepcopy で rng も同一 state)。
                #   S_ai:    AI inline 解決 (human_player_idx=None なので auto-pick)
                #   S_human: 人間 modal 解決 (resolve_pending_choice、 AI と同じカードを pick)
                #   両 fork は rng 同一 ⇒ on_play の draw/mill/shuffle cascade も同一
                #   ⇒ 盤面差 = **人間 modal 解決 path 固有のバグ** (= AI inline が正解)。
                S_ai = fast_clone(sess.state)
                ref = _resolve_inline_on_fork(S_ai, choice)
                if isinstance(ref, tuple) and ref and ref[0] == "ERR":
                    divergences.append({"slug": f"{slug_a} vs {slug_b}", "seed": seed,
                                        "kind": kind, "div": ref[1]})
                    sess.apply_human_choice([]); continue
                if ref is None:
                    sess.apply_human_choice([]); continue
                stats["compared"] += 1
                picks = _human_picks_matching(choice, ref, pre_digest)
                # S_human: 人間 modal path で同じカードを解決 (fast_clone は AI モードだが
                #   resolve_pending_choice は picks をそのまま適用するので 人間解決 path を通る)。
                from engine.effects import resolve_pending_choice
                S_human = fast_clone(sess.state)
                try:
                    resolve_pending_choice(S_human, picks)
                except Exception as e:  # noqa: BLE001
                    divergences.append({"slug": f"{slug_a} vs {slug_b}", "seed": seed,
                                        "kind": kind, "div": f"人間解決 例外: {type(e).__name__}: {str(e)[:60]}"})
                    sess.apply_human_choice([]); continue
                h_dig = board_digest(S_human)
                r_dig = board_digest(ref)
                if h_dig != r_dig:
                    diff = []
                    znames = ["hand", "deck", "trash", "life", "chars", "stages", "don", "leader"]
                    for pi in range(2):
                        for zi, zn in enumerate(znames):
                            if h_dig[pi][zi] != r_dig[pi][zi]:
                                diff.append(f"p{pi}.{zn}({h_dig[pi][zi]} vs {r_dig[pi][zi]})"
                                            if zi in (3, 6) else f"p{pi}.{zn}")
                    divergences.append({"slug": f"{slug_a} vs {slug_b}", "seed": seed,
                                        "kind": kind, "picks": picks,
                                        "div": f"盤面差: {' '.join(diff)[:180]}"})
                # 原ゲームは 人間 modal で進める (= 進行用、 比較は fork で済)
                sess.apply_human_choice(picks)
            else:
                _pick_noncompare(sess)
        elif pk == "defense":
            sess.apply_human_defense(None, [])
        else:
            break


def _pick_noncompare(sess):
    pl = sess.pending_payload or {}
    k = pl.get("kind")
    lim = int(pl.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        sess.apply_human_choice([0]); return
    if k == "search_top_n":
        cs = pl.get("cards", [])
        m = [c["idx"] for c in cs if c.get("matches_filter")]
        sess.apply_human_choice(m[:lim]); return
    if k in ("optional_cost_confirm", "on_attack_optional", "on_opp_attack_optional",
             "end_of_turn_optional", "replace_ko_optional", "reveal_top_play_confirm",
             "view_life_top_choose_position", "option_pick", "life_taken_choice"):
        sess.apply_human_choice([0]); return
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        sess.apply_human_choice([]); return
    cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    sess.apply_human_choice(list(range(min(lim, len(cs)))) if cs else [])


def main():
    args = [a for a in sys.argv[1:]]
    slugs = (args[0].split(",") if args and not args[0].isdigit()
             else ["cardrush_1385", "cardrush_1392", "cardrush_1453", "tcgportal_op11_luffy",
                   "cardrush_1342", "cardrush_1456", "tcgportal_op13_luffy", "cardrush_1454"])
    n = next((int(a) for a in args if a.isdigit()), 15)
    divergences = []
    stats = {"compared": 0}
    crashes = []
    for i, a in enumerate(slugs):
        b = slugs[(i + 1) % len(slugs)]
        for s in range(n):
            try:
                run(a, b, 3000 + s, divergences, stats)
            except Exception as e:  # noqa: BLE001
                import traceback
                crashes.append((a, b, 3000 + s, f"{type(e).__name__}: {e}",
                                traceback.format_exc().splitlines()[-1]))
        print(f"=== {a} vs {b}: {n} games | compared {stats['compared']} | div {len(divergences)} ===", flush=True)
    print(f"\n比較した pool-pick 解決: {stats['compared']}")
    print(f"人間経路 vs AI経路 盤面ズレ: {len(divergences)}")
    for d in divergences[:30]:
        print(f"  [ズレ] {d['slug']} seed{d['seed']} {d['kind']}: {d['div']}")
    if crashes:
        print(f"\ncrash: {len(crashes)}")
        for c in crashes[:10]:
            print("  ", c[:4], "|", c[4])
    sys.exit(1 if (divergences or crashes) else 0)


if __name__ == "__main__":
    main()
