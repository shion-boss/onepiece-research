# -*- coding: utf-8 -*-
"""未踏の防御サブフローを突く エンジンバグ hunt (= 2026-06-05)。

⭐ 教訓 ([[project_human_play_auto_qa]] / hunt_policies.py): **seed 変更 < bot 戦術変更**。
既存 fuzzer (fuzz_human_play / hunt_policies / hunt_both_paths) は 防御で
  - apply_human_defense (ブロッカー + counter 値カード)
  - apply_human_use_opp_attack_effect (【相手のアタック時】効果)
の 2 経路しか踏まない。 **`apply_human_use_counter_event` (= 【カウンター】 EVENT を
防御 modal で click 即時発動 → discard/target modal 解決 → defense modal 再構築) は
全 fuzzer が未踏** (grep 0 件)。 この再入可能フロー (hand pop で idx ずれ + DON cost rest +
attacker_power 再評価 + _rebuild_defense_payload) は bug の温床。

tactics:
  ce_spam    : counter event を 撃てるだけ撃つ (= 再入 defense modal を反復、 hand idx shift)
  ce_mix     : counter event + opp_attack 効果 + blocker + counter 値 を 混ぜて 1 防御で連発
  ce_then_blk: counter event 1 発 → その後 blocker (= attacker_power 変動後の block 判定)
  greedy_block: 毎回 blocker 立てる + counter 値 全部 (= 旧経路だが 最大消費で 別分布)

検出: STUCK (同 sig 100+) / INV1 保存則 / INV2 instance 重複 / PY_EXC / ENGINE_ERROR / NO_ACT。

  python scripts/hunt_counter_tactics.py [N_PER_PAIR] [tactic|all]
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import fuzz_human_play as F  # noqa: E402

F._setup()
DECKS = F.DECKS
INIT = 100

TACTICS = ("ce_spam", "ce_mix", "ce_then_blk", "greedy_block")


def _maindeck_total(state):
    t = 0
    for p in state.players:
        t += (len(p.deck) + len(p.hand) + len(p.trash) + len(p.life)
              + len(p.characters) + len(p.stages))
    return t


def _inst_dup(state):
    ids = []
    for p in state.players:
        ids.append(p.leader.instance_id)
        ids.extend(ip.instance_id for ip in [*p.characters, *p.stages])
    if len(ids) != len(set(ids)):
        return sorted({i for i in ids if ids.count(i) > 1})
    return None


def _don_sanity(state):
    """DON 会計 不変条件 (= INV1/INV2 が DON を除外しているため別途検査)。
    DON は 10 枚デッキ。 在場 DON = don_active + don_rested + Σ attached_dons。
    過払い (= 負) / 複製 (= 在場 > 10) を 捕捉。 ※ rest_opp_don/add_don 等で 在場枚数は
    変動しうるが、 1 プレイヤーの 物理 DON は 常に 0..10。 負・>10 は engine バグの確証。"""
    for pi, p in enumerate(state.players):
        attached = sum(getattr(ip, "attached_dons", 0) or 0
                       for ip in [p.leader, *p.characters])
        if p.don_active < 0 or p.don_rested < 0 or attached < 0:
            return (f"DON負: p{pi} active={p.don_active} rested={p.don_rested} "
                    f"attached={attached}")
        total = p.don_active + p.don_rested + attached
        if total > 10:
            return (f"DON複製: p{pi} 在場 {total}>10 "
                    f"(active={p.don_active} rested={p.don_rested} attached={attached})")
    return None


def modal_pick(pl, rng):
    k = pl.get("kind")
    lim = int(pl.get("limit", 1) or 1)
    if k in ("mulligan_confirm", "mulligan_redrawn"):
        return [0]
    if k in ("optional_cost_confirm", "replace_ko_optional", "reveal_top_play_confirm",
             "on_attack_optional", "on_opp_attack_optional", "end_of_turn_optional",
             "life_taken_choice", "view_life_top_choose_position", "option_pick"):
        return [rng.choice([0, 1])]
    if k in ("search_top_n_bottom_reorder", "scry_life_reorder", "scry_deck_reorder"):
        cs = pl.get("candidates") or pl.get("cards") or []
        o = list(range(len(cs)))
        rng.shuffle(o)
        return o
    cs = pl.get("candidates") or pl.get("cards") or pl.get("options") or []
    return list(range(min(lim, len(cs)))) if cs else []


def do_defense(s, pl, rng, tactic):
    """tactic 別 防御。 何か行動したら True (= apply_* を1回呼んで pause が更新される)。"""
    ce = pl.get("counter_event_idxs") or []
    avail = pl.get("available_opp_attack_effects") or []
    blk = pl.get("legal_blocker_iids") or []
    cnt = pl.get("legal_counter_card_idxs") or []
    # counter 値カード (= event 以外): legal_counter_card_idxs - counter_event_idxs
    cnt_val = [i for i in cnt if i not in ce]

    if tactic in ("ce_spam", "ce_mix", "ce_then_blk") and ce:
        # 再入フローの本丸: counter event を click 発動 (hand idx)。 再構築で idx 再計算されるので
        # 常に先頭を撃つ (= 撃つたび hand pop → 次ループで残りが出る)。
        s.apply_human_use_counter_event(ce[0])
        return True
    if tactic == "ce_mix" and avail and rng.random() < 0.7:
        e = avail[0]
        s.apply_human_use_opp_attack_effect(e["source_iid"], e["effect_idx"])
        return True
    # 残り: blocker + counter 値カード で 確定
    if tactic == "greedy_block":
        s.apply_human_defense(blk[0] if blk else None, cnt_val)  # 全 counter 値
        return True
    if tactic == "ce_then_blk":
        s.apply_human_defense(blk[0] if blk else None, cnt_val[:1])
        return True
    if tactic == "ce_mix":
        bid = blk[0] if blk and rng.random() < 0.5 else None
        s.apply_human_defense(bid, cnt_val[:2])
        return True
    # ce_spam: counter event 尽きたら 素受け (= 防御を確定させ進行)
    s.apply_human_defense(None, [])
    return True


def play(a, b, seed, hf, tactic):
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    last = None
    same = 0
    while not s.state.game_over and steps < 3000:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        sig = (pk, pl.get("kind"), s.state.turn_number,
               len(pl.get("available_opp_attack_effects") or []),
               len(pl.get("counter_event_idxs") or []),
               len(s.state.players[0].hand), len(s.state.players[1].hand))
        if sig == last:
            same += 1
            if same > 100:
                return ("STUCK", steps, sig)
        else:
            same = 0
            last = sig
        try:
            if pk == "action":
                t = _maindeck_total(s.state)
                if t != INIT:
                    return ("INV", steps, f"INV1 maindeck {t}!={INIT}")
                dup = _inst_dup(s.state)
                if dup:
                    return ("INV", steps, f"INV2 iid dup {dup}")
                don_v = _don_sanity(s.state)
                if don_v:
                    return ("INV", steps, f"INV3 {don_v}")
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None)
                # キャラ展開を 厚めに (= 場を埋めて 防御候補/【相手のアタック時】を増やす)
                non_end = [x for x in acts if x.get("kind") != "EndPhase"]
                plays = [x for x in non_end if x.get("kind") in ("PlayCharacter", "PlayStage")]
                if plays and rng.random() < 0.6:
                    pick = rng.choice(plays)
                elif non_end and rng.random() < 0.85:
                    pick = rng.choice(non_end)
                else:
                    pick = next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])
                s.apply_human_action(pick["idx"])
            elif pk == "choice":
                s.apply_human_choice(modal_pick(pl, rng))
            elif pk == "defense":
                do_defense(s, pl, rng, tactic)
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps,
                    f"{type(e).__name__}: {str(e)[:80]} | {traceback.format_exc().splitlines()[-2][:80]}")
    # 終局: engine error (= advance_until_pause が握り潰した in-game 例外) を log 走査
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90])
    t = _maindeck_total(s.state)
    if t != INIT:
        return ("INV", steps, f"INV1(final) maindeck {t}!={INIT}")
    return ("OK", steps, None)


def _pairs():
    ps = [(d, d) for d in DECKS]
    for i, d in enumerate(DECKS):
        for j in (1, 2):
            ps.append((d, DECKS[(i + j) % len(DECKS)]))
    return ps


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    n = nums[0] if nums else 6
    want = next((a for a in sys.argv[1:] if a in TACTICS), None)
    tactics = (want,) if want else TACTICS
    pairs = _pairs()
    bugs = []
    res = Counter()
    total = 0
    for tactic in tactics:
        for a, b in pairs:
            for sd in range(n):
                gs = 70000 + sd * 13
                st, steps, info = play(a, b, gs, sd % 2 == 0, tactic)
                res[(tactic, st)] += 1
                total += 1
                if st != "OK":
                    bugs.append((tactic, a, b, gs, sd % 2 == 0, st, info))
        print(f"tactic={tactic} done | total {total} | bugs {len(bugs)}", flush=True)
    print(f"\n=== counter-tactics hunt {total} 試合 ===")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭40):")
        for tac, a, b, sd, hf, st, info in bugs[:40]:
            print(f"  ★[{tac}/{st}] {a} vs {b} seed={sd} hf={hf}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
