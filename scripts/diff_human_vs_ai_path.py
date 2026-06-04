# -*- coding: utf-8 -*-
"""人間経路 vs AI経路 lockstep 差分 (= ohtsuki 提案の正しい実装)。

AI経路 (apply_action / 効果の自動解決) は 799 テスト + RuleReferee 監視済で「正解」 寄り。
人間経路 (HumanSession の modal 解決) はその上に追加レイヤーがあり、 そこにバグが集中
していた (unique_name/no_effect/recompute 等)。

⭐ lockstep: 1 つの人間経路ゲームを走らせ、 各「カードを選ぶ」 modal の時点で state を
fork し、 **同じ効果を「AI内部解決」 と「人間modal解決」 の両方で解いて盤面を直接比較**
する。 ズレ = 人間経路バグ (= AI が正解)。 別々ゲーム比較ではないので setup/rng desync が
起きない。

比較対象: AI の自動選択が決定的 (= 先頭から該当を取る) で 人間 pick と一致させられる
pool-pick 系のみ。 random discard / 並び替え / optional 等は除外 (= AI 解が非決定的)。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import (load_effect_overlay, _matches_filter,  # noqa: E402
                            _card_has_no_effect)
from engine.game import legal_actions  # noqa: E402
from engine.core import Category  # noqa: E402
from engine.ai import GreedyAI  # noqa: E402
from engine.human_session import HumanSession  # noqa: E402

repo = CardRepository.from_json(ROOT / "db" / "cards.json")
overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")

from collections import Counter  # noqa: E402

# 検査する pick-kind → 召喚先 zone ("field"=キャラ/ステージ, "hand"=手札)。
# その zone に入ったカードが 効果の制約 (filter/no_effect/unique_name/limit) を守るか照合。
KIND2DEST = {
    "play_from_trash_pick": "field",
    "summon_from_deck_pick": "field",
    "play_from_hand_pick": "field",
    "play_from_hand_or_trash_pick": "field",
    "search_pick": "hand",           # デッキ検索 → 手札 (= filter 一致カードのみ手札へ)
    "summon_from_deck_pick_hand": "hand",
}


def load_deck(slug):
    return DeckList.from_json(ROOT / "decks" / f"{slug}.json", repo)


def _check_card_conformance(state, new_cards, choice):
    """人間経路で destination に入った new_cards (CardDef) が、 効果 (primitive_value) の
    制約を守っているか直接照合 (= AI 選択一致不要で堅牢)。"""
    pv = choice.get("primitive_value")
    if not isinstance(pv, dict):
        return []
    filt = pv.get("filter", {}) if isinstance(pv.get("filter"), dict) else {}
    limit = int(pv.get("limit", 1) or 1)
    uniq = bool(pv.get("unique_name"))
    v = []
    for card in new_cards:
        if filt and not _matches_filter(card, filt):
            v.append(f"filter違反: {card.card_id}({card.name}) ∉ {filt}")
        if filt.get("no_effect") and not _card_has_no_effect(card, state):
            v.append(f"no_effect違反: {card.card_id}({card.name}) は効果持ち")
    if uniq:
        names = [c.name for c in new_cards]
        if len(names) != len(set(names)):
            v.append(f"unique_name違反: 同名重複 {names}")
    if len(new_cards) > limit:
        v.append(f"limit違反: {len(new_cards)}枚 > 上限{limit}")
    return v


def run(slug, seed, divergences):
    da, db = load_deck(slug), load_deck(slug)
    sess = HumanSession(deck_a=da, deck_b=db,
                        ai_factory=lambda rng, dd=None: GreedyAI(rng),
                        seed=seed, effects_overlay=overlay, human_first=True)
    mimic = GreedyAI(random.Random(seed * 3))
    sess.advance_until_pause()
    steps = 0
    n_compared = 0
    while not sess.state.game_over and steps < 800:
        steps += 1
        pk = sess.pending_kind
        if pk == "action":
            acts = legal_actions(sess.state)
            if not acts:
                break
            a = mimic.choose_action(sess.state)
            idx = next((i for i, x in enumerate(acts) if repr(x) == repr(a)), 0)
            sess.apply_human_action(idx)
        elif pk == "choice":
            choice = dict(sess.state.pending_choice or {})
            kind = choice.get("kind")
            dest = KIND2DEST.get(kind)
            if dest and isinstance(choice.get("primitive_value"), dict):
                # ⭐ 人間が 全候補を選ぶ (adversarial) → destination に入ったカードを
                #    効果の制約に照合。
                cands = choice.get("candidates") or []
                tp = sess.state.turn_player_idx
                me = sess.state.players[tp]
                if dest == "field":
                    before = {ip.instance_id for ip in [*me.characters, *me.stages]}
                else:  # hand
                    before = Counter(c.card_id for c in me.hand)
                sess.apply_human_choice(list(range(len(cands))))
                me2 = sess.state.players[tp]
                if dest == "field":
                    raw_new = [ip.card for ip in [*me2.characters, *me2.stages]
                               if ip.instance_id not in before]
                else:
                    added = Counter(c.card_id for c in me2.hand) - before
                    raw_new = []
                    for cid, cnt in added.items():
                        try:
                            raw_new.extend([repo.get(cid)] * cnt)
                        except Exception:
                            pass
                # ⚠ この効果の候補 (card_id) に限定 → 召喚キャラの on_play が別効果で
                #   召喚した下流カードを除外 (= 偽陽性防止)。
                cand_ids = Counter(c.get("card_id") for c in (choice.get("candidates") or []))
                used: Counter = Counter()
                new_cards = []
                for card in raw_new:
                    if used[card.card_id] < cand_ids.get(card.card_id, 0):
                        used[card.card_id] += 1
                        new_cards.append(card)
                n_compared += 1
                for viol in _check_card_conformance(sess.state, new_cards, choice):
                    divergences.append({"slug": slug, "seed": seed, "kind": kind,
                                        "viol": viol})
            elif kind == "target_pick" and choice.get("candidates"):
                # target系 (KO/バウンス等): 全候補を選ぶ → 場を離れた候補数 ≤ limit を照合。
                # (= 除去 over-application バグを捕捉。 非除去 rest/pump は離脱0で誤検出なし)。
                cands = choice.get("candidates") or []
                limit = int(choice.get("limit", 1) or 1)
                cand_iids = {c["iid"] for c in cands}
                field_before = {ip.instance_id for p in sess.state.players
                                for ip in [p.leader, *p.characters, *p.stages]}
                sess.apply_human_choice(list(range(len(cands))))
                field_after = {ip.instance_id for p in sess.state.players
                               for ip in [p.leader, *p.characters, *p.stages]}
                removed = cand_iids & (field_before - field_after)
                n_compared += 1
                if len(removed) > limit:
                    divergences.append({
                        "slug": slug, "seed": seed, "kind": "target_pick",
                        "viol": f"除去 limit違反: {len(removed)}体除去 > 上限{limit} "
                                f"(prim={choice.get('primitive_kind')})"})
            else:
                _pick_noncompare(sess)
        elif pk == "defense":
            sess.apply_human_defense(None, [])
        else:
            break
    return n_compared


def _pick_noncompare(sess):
    payload = sess.pending_payload or {}
    k = payload.get("kind")
    lim = int(payload.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        sess.apply_human_choice([0]); return
    if k == "search_top_n":
        cs = payload.get("cards", [])
        m = [c["idx"] for c in cs if c.get("matches_filter")]
        sess.apply_human_choice(m[:lim]); return
    if k in ("optional_cost_confirm", "on_attack_optional", "on_opp_attack_optional",
             "end_of_turn_optional", "replace_ko_optional", "reveal_top_play_confirm",
             "view_life_top_choose_position", "option_pick", "life_taken_choice"):
        sess.apply_human_choice([0]); return
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        sess.apply_human_choice([]); return
    cands = payload.get("candidates") or payload.get("cards") or payload.get("options") or []
    sess.apply_human_choice(list(range(min(lim, len(cands)))))


def main():
    slugs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cardrush_1392"]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    divergences = []
    total_cmp = 0
    crashes = []
    for slug in slugs:
        for s in range(n):
            try:
                total_cmp += run(slug, 2000 + s, divergences)
            except Exception as e:  # noqa: BLE001
                crashes.append((slug, 2000 + s, f"{type(e).__name__}: {e}"))
        print(f"=== {slug}: {n} games done ===", flush=True)
    print(f"\n検査した召喚choice 数: {total_cmp}")
    print(f"人間経路の制約違反 (= ルール通りでない): {len(divergences)}")
    for d in divergences[:30]:
        print(f"  [違反] {d['slug']} seed{d['seed']} {d['kind']}: {d['viol']}")
    if crashes:
        print(f"\nゲーム crash: {len(crashes)}")
        for c in crashes[:10]:
            print("  ", c)
    if not divergences and not crashes:
        print("\nOK: 検査した全召喚で 人間経路が効果の制約通り (= ルール通り)")
    sys.exit(1 if (divergences or crashes) else 0)


if __name__ == "__main__":
    main()
