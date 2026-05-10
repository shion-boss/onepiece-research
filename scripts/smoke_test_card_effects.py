# -*- coding: utf-8 -*-
"""
全カード効果スモークテスト
==========================

目的:
    `db/card_effects.json` に登録された全カードについて、 各効果を最小ステートで
    発火させ、 「state に観測可能な変化が起きたか」 を検査する。

    観測可能な変化が無い (NO_CHANGE) or 例外発生 (ERROR) のカードは、 効果が
    実装されていないか overlay と engine の DSL が乖離している証拠。

使い方:
    .venv/bin/python scripts/smoke_test_card_effects.py
    # → db/effect_smoke_test.md (人間向けレポート)
    # → db/effect_smoke_test.json (機械向け、 全件)

カバー範囲:
    各 overlay effect の `when` フィールドに応じて適切な trigger を呼ぶ:
    - on_play, on_attack, on_block, opp_attack, on_ko: 該当 trigger 関数
    - activate_main: fire_activate_main
    - end_of_turn, opp_end_of_turn: trigger_end_of_turn
    - on_turn_start, opp_turn_start: trigger_turn_start
    - trigger: trigger_lifecard_trigger (auto_fire=True)
    - main: trigger_main_event (eventCard 用)
    - on_attached_don: evaluate_static_effects
    - replace_ko: try_replace_ko (簡易ケースで叩く)

判定:
    - PASS: 効果発動後に hand/deck/trash/life/don/characters/static_buff いずれかが変化
    - NO_CHANGE: state 全体に変化なし
    - ERROR: 例外発生 (= 致命バグ)
    - SKIPPED: テスト困難 (= main イベント効果で hand に該当カードが必須など)

サンプル synthetic state:
    - turn player (me): 場にこのカード本体 (もしくは hand に持つ)、 don 8、
      hand 5 (1〜3 コストキャラ等)、 deck 30、 trash に 5 枚 (種類豊富)、 life 4
    - opp: 場に 2 キャラ、 hand 4、 don 6、 deck 30、 trash 3、 life 4

注: 「変化が起きた」 ≠ 「正しい挙動」 だが、 「変化が起きない」 は確実にバグ
    (もしくは条件節が strict すぎて発動できないケース)。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import traceback
from collections import Counter
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import Category, GameState, InPlay, Phase, Player
from engine.deck import CardRepository
from engine.effects import (
    CardEffectBundle,
    evaluate_static_effects,
    fire_activate_main,
    load_effect_overlay,
    trigger_end_of_turn,
    trigger_lifecard_trigger,
    trigger_main_event,
    trigger_on_attack,
    trigger_on_block,
    trigger_on_ko,
    trigger_on_opp_attack,
    trigger_on_play,
    trigger_turn_start,
    try_replace_ko,
)


CARDS_JSON = ROOT / "db" / "cards.json"
OVERLAY_JSON = ROOT / "db" / "card_effects.json"
OUTPUT_MD = ROOT / "db" / "effect_smoke_test.md"
OUTPUT_JSON = ROOT / "db" / "effect_smoke_test.json"


# テスト用 「ダミー」 カード ID 群 (種類豊富にしておく):
DUMMY_HAND = ["OP01-013", "OP01-016", "OP01-001", "OP02-002", "OP01-006"]
DUMMY_DECK = ["OP01-013"] * 8 + ["OP01-016"] * 8 + ["OP02-002"] * 8 + ["OP04-046"] * 6
DUMMY_TRASH = ["OP01-013", "OP01-016", "OP02-002", "OP04-046", "OP01-006"]
DUMMY_OPP_CHARACTERS = ["OP01-013", "OP01-016"]


def make_state(repo: CardRepository, overlay: dict, src_card_id: str) -> GameState:
    """テスト用合成 state を生成。 me に src_card がある状態 + 標準的な手札・場・トラッシュ。"""
    src = repo._by_id[src_card_id]
    leader = repo._by_id["OP01-001"]  # ロロノア・ゾロ (汎用)
    p1 = Player(name="P0", leader=InPlay.of(leader, sickness=False))
    p2 = Player(name="P1", leader=InPlay.of(repo._by_id["OP01-002"], sickness=False))
    p1.don_active = 8
    p1.don_rested = 2
    p1.hand = [repo._by_id[cid] for cid in DUMMY_HAND if cid in repo._by_id]
    # src 本体をhand にも積んでおく (effect が手札参照することがある)
    if src.category != Category.LEADER:
        p1.hand.append(src)
    p1.deck = [repo._by_id[cid] for cid in DUMMY_DECK if cid in repo._by_id]
    p1.trash = [repo._by_id[cid] for cid in DUMMY_TRASH if cid in repo._by_id]
    p1.life = [repo._by_id["OP01-013"]] * 4

    p2.don_active = 6
    p2.don_rested = 1
    p2.hand = [repo._by_id[cid] for cid in DUMMY_HAND if cid in repo._by_id]
    p2.deck = [repo._by_id[cid] for cid in DUMMY_DECK if cid in repo._by_id]
    p2.trash = [repo._by_id[cid] for cid in DUMMY_TRASH if cid in repo._by_id]
    p2.life = [repo._by_id["OP01-013"]] * 4
    # opp 側: 1 体 rested、 1 体 active の混在 (= 「相手のレストキャラ」 「相手のアクティブキャラ」 両 target に応える)
    opp_chars: list[InPlay] = []
    for i, cid in enumerate(DUMMY_OPP_CHARACTERS):
        if cid not in repo._by_id:
            continue
        ip = InPlay.of(repo._by_id[cid], sickness=False)
        if i == 0:
            ip.rested = True  # 1 体目は rested
        opp_chars.append(ip)
    # コスト幅を持たせる (コスト1〜5 をカバー): 大型キャラを追加
    for cid in ("OP04-046",):
        if cid in repo._by_id:
            ip = InPlay.of(repo._by_id[cid], sickness=False)
            ip.attached_dons = 1  # 付与ドン持ちを 1 体 (= attached_don 関連 effect 用)
            opp_chars.append(ip)
    p2.characters = opp_chars

    state = GameState(
        players=[p1, p2],
        turn_player_idx=0,
        turn_number=3,
        phase=Phase.MAIN,
        rng=random.Random(0),
        effects_overlay=overlay,
    )
    return state


def state_signature(state: GameState) -> tuple:
    """state の主要フィールドを hashable signature 化。 比較で「変化があったか」 判定する。"""
    sigs = []
    for p in state.players:
        chars = tuple(
            (c.card.card_id, c.power, c.rested, c.attached_dons, c.static_buff,
             c.turn_buff, c.battle_buff, c.cannot_attack_until_turn_end,
             c.ko_immune_until_turn_end, c.stay_rested_next_refresh,
             c.summoning_sickness, c.cost_minus_until_turn_end,
             c.granted_keywords and frozenset(c.granted_keywords))
            for c in p.characters
        )
        leader_sig = (
            p.leader.card.card_id, p.leader.power, p.leader.rested,
            p.leader.attached_dons, p.leader.static_buff, p.leader.turn_buff,
        )
        sigs.append((
            tuple(c.card_id for c in p.hand),
            tuple(c.card_id for c in p.deck[:5]),  # deck 上 5 枚で十分
            tuple(c.card_id for c in p.trash),
            tuple(c.card_id for c in p.life),
            p.don_active, p.don_rested,
            chars, leader_sig,
        ))
    return tuple(sigs)


WHEN_TYPES = [
    "on_play", "on_attack", "on_block", "opp_attack", "on_ko",
    "activate_main", "end_of_turn", "opp_end_of_turn",
    "on_turn_start", "opp_turn_start", "trigger", "main",
    "on_attached_don", "replace_ko",
]


def fire_one_effect(
    state: GameState,
    src_card,
    src_inplay: InPlay,
    eff: dict,
    repo: CardRepository,
) -> str:
    """1 つの effect を発火させて、 state に反映させる。 戻り値はステータス文字列。"""
    when = eff.get("when")
    me = state.players[0]
    opp = state.players[1]
    overlay = state.effects_overlay

    if when == "on_play":
        # src を場に出した想定で trigger_on_play
        trigger_on_play(state, me, opp, src_inplay, overlay)
    elif when == "on_attack":
        # src がアタッカーとして
        trigger_on_attack(state, me, opp, src_inplay, overlay)
    elif when == "on_block":
        # src がブロッカーとして発動
        trigger_on_block(state, me, opp, src_inplay, overlay)
    elif when == "opp_attack":
        # opp 視点: relevant trigger は opp 側で発動するが、
        # ここでは me が src を持ってる想定で me 視点 trigger
        trigger_on_opp_attack(state, me, opp, opp.leader, overlay)
    elif when == "on_ko":
        # src が KO された想定 (= trash に既に行ってる)
        if src_inplay in me.characters:
            me.characters.remove(src_inplay)
            me.trash.append(src_inplay.card)
        trigger_on_ko(state, me, opp, src_inplay.card, overlay)
    elif when == "activate_main":
        # cost を強制無視で発動
        try:
            fire_activate_main(state, me, opp, src_inplay, eff)
        except Exception:
            return "ERROR"
    elif when == "end_of_turn":
        trigger_end_of_turn(state, overlay)
    elif when == "opp_end_of_turn":
        # me を turn_player にすると opp_end_of_turn は opp 側で発動
        trigger_end_of_turn(state, overlay)
    elif when == "on_turn_start":
        trigger_turn_start(state, overlay)
    elif when == "opp_turn_start":
        trigger_turn_start(state, overlay)
    elif when == "trigger":
        # ライフ→手札の代わりに trigger 発動
        trigger_lifecard_trigger(state, opp, me, src_card, overlay, auto_fire=True)
    elif when == "main":
        # メインイベントカード: 手札にあれば発動
        if src_card.category == Category.EVENT and src_card in me.hand:
            trigger_main_event(state, me, opp, src_card, overlay)
        else:
            return "SKIPPED"
    elif when == "on_attached_don":
        # 静的効果の評価 (= ドンが付与されている前提)
        src_inplay.attached_dons = max(src_inplay.attached_dons, 2)
        evaluate_static_effects(state, overlay)
    elif when == "replace_ko":
        # opp が me のキャラを KO する仮想シナリオ
        # me.characters に dummy victim を置いて、 try_replace_ko を呼ぶ
        if me.characters:
            victim = me.characters[0]
            try_replace_ko(state, me, opp, victim, overlay, by_opp_effect=True)
        else:
            return "SKIPPED"
    else:
        return "SKIPPED"
    return "OK"


def test_card(repo: CardRepository, overlay: dict, card_id: str) -> dict:
    """1 カードについて全 effect を smoke test。 結果サマリを返す。"""
    card = repo._by_id[card_id]
    bundle = overlay.get(card_id)
    if not bundle or not bundle.effects:
        return {"card_id": card_id, "name": card.name, "effects": [], "skipped_vanilla": True}

    results: list[dict] = []
    for idx, eff in enumerate(bundle.effects):
        when = eff.get("when", "?")
        # state を毎回 fresh に作る
        state = make_state(repo, overlay, card_id)
        me = state.players[0]
        # src を場に置く (リーダーなら leader、 キャラ/ステージなら characters/stages)
        if card.category == Category.LEADER:
            src_inplay = me.leader  # 既存 leader を上書きしない、 別途確保
            # leader を src 自身に置き換え (= テスト前提)
            me.leader = InPlay.of(card, sickness=False)
            src_inplay = me.leader
        elif card.category == Category.STAGE:
            src_inplay = InPlay.of(card, sickness=False)
            me.stages.append(src_inplay)
        elif card.category == Category.EVENT:
            # event は inplay 化しない、 hand に持たせる (既に DUMMY_HAND に追加済)
            if card not in me.hand:
                me.hand.append(card)
            src_inplay = InPlay.of(card, sickness=False)  # placeholder
        else:  # CHARACTER
            src_inplay = InPlay.of(card, sickness=False)
            me.characters.append(src_inplay)

        sig_before = state_signature(state)
        try:
            status = fire_one_effect(state, card, src_inplay, eff, repo)
            error_msg = None
        except Exception as e:
            status = "ERROR"
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        sig_after = state_signature(state)

        if status == "OK":
            if sig_before == sig_after:
                outcome = "NO_CHANGE"
            else:
                outcome = "PASS"
        else:
            outcome = status

        # do の primitive サマリ
        prims: list[str] = []
        for p in eff.get("do", []):
            if isinstance(p, dict):
                prims.extend(p.keys())
        results.append({
            "idx": idx,
            "when": when,
            "do_keys": prims,
            "outcome": outcome,
            "error": error_msg,
            "text": eff.get("_text", ""),
        })
    return {
        "card_id": card_id,
        "name": card.name,
        "category": card.category.value if hasattr(card.category, "value") else str(card.category),
        "effects": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-issues", type=int, default=80,
                        help="MD レポートに出す issue 件数")
    parser.add_argument("--card-id", type=str,
                        help="特定 1 カードのみテスト (デバッグ用)")
    args = parser.parse_args()

    repo = CardRepository.from_json(CARDS_JSON)
    overlay = load_effect_overlay(OVERLAY_JSON)

    if args.card_id:
        result = test_card(repo, overlay, args.card_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 全カードテスト
    results: list[dict] = []
    target_cards = [
        cid for cid in repo._by_id
        if cid in overlay and overlay[cid].effects
    ]
    print(f"対象: {len(target_cards)} カード × 各 effect")

    for i, cid in enumerate(target_cards):
        if (i + 1) % 500 == 0:
            print(f"  進行: {i+1}/{len(target_cards)}")
        try:
            result = test_card(repo, overlay, cid)
        except Exception as e:
            result = {
                "card_id": cid, "name": repo._by_id[cid].name,
                "effects": [],
                "card_level_error": f"{type(e).__name__}: {str(e)[:200]}",
            }
        results.append(result)

    # 集計
    outcome_counter: Counter = Counter()
    when_outcome: dict = {}
    issues: list[dict] = []
    for r in results:
        if r.get("card_level_error"):
            outcome_counter["CARD_ERROR"] += 1
            issues.append(r)
            continue
        for e in r.get("effects", []):
            outcome_counter[e["outcome"]] += 1
            key = (e["when"], e["outcome"])
            when_outcome[key] = when_outcome.get(key, 0) + 1
            if e["outcome"] in ("ERROR", "NO_CHANGE"):
                issues.append({
                    "card_id": r["card_id"],
                    "name": r["name"],
                    "category": r.get("category", ""),
                    **e,
                })

    print("\n=== outcome 集計 ===")
    for k, v in outcome_counter.most_common():
        print(f"  {k}: {v}")

    print("\n=== when × outcome 集計 (NO_CHANGE/ERROR のみ) ===")
    when_problem: dict = {}
    for (w, o), n in when_outcome.items():
        if o in ("NO_CHANGE", "ERROR"):
            when_problem.setdefault(w, {"NO_CHANGE": 0, "ERROR": 0})[o] = n
    for w in sorted(when_problem):
        print(f"  {w:<20}: NO_CHANGE={when_problem[w]['NO_CHANGE']:4} / ERROR={when_problem[w]['ERROR']:4}")

    # JSON 出力 (全件)
    OUTPUT_JSON.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # MD 出力
    out = OUTPUT_MD.open("w", encoding="utf-8")
    out.write(f"# 全カード効果スモークテストレポート\n\n")
    out.write(f"- 対象 (overlay 効果あり): {len(target_cards)}\n")
    out.write(f"- 効果総数 (when 単位): {sum(len(r.get('effects', [])) for r in results)}\n\n")
    out.write("## outcome 集計\n\n")
    for k, v in outcome_counter.most_common():
        out.write(f"- **{k}**: {v}\n")
    out.write("\n## when × NO_CHANGE/ERROR 集計\n\n")
    out.write("| when | NO_CHANGE | ERROR |\n|---|---|---|\n")
    for w in sorted(when_problem):
        out.write(
            f"| `{w}` | {when_problem[w]['NO_CHANGE']} | {when_problem[w]['ERROR']} |\n"
        )
    out.write("\n## ERROR 件 (致命バグ候補)\n\n")
    error_issues = [i for i in issues if i.get("outcome") == "ERROR"]
    for issue in error_issues[:args.top_issues]:
        out.write(
            f"### `{issue['card_id']}` {issue['name']} ({issue.get('category', '')})\n\n"
            f"- when: `{issue['when']}` | do: `{issue['do_keys']}`\n"
            f"- error: `{issue['error']}`\n"
            f"- text: {issue.get('text', '')}\n\n"
        )

    out.write(f"\n## NO_CHANGE 件 (effect 無効化候補) - 上位 {args.top_issues}\n\n")
    no_change = [i for i in issues if i.get("outcome") == "NO_CHANGE"]
    for issue in no_change[:args.top_issues]:
        out.write(
            f"### `{issue['card_id']}` {issue['name']} ({issue.get('category', '')})\n\n"
            f"- when: `{issue['when']}` | do: `{issue['do_keys']}`\n"
            f"- text: {issue.get('text', '')}\n\n"
        )

    out.close()
    print(f"\n出力: {OUTPUT_MD}")
    print(f"     {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
