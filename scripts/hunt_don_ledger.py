# -*- coding: utf-8 -*-
"""DON 台帳 保存則 で エンジンバグ hunt (= 2026-06-05、 新オラクル)。

⭐ 着想: 既存オラクル (INV1 メインデッキ札 / INV2 instance 重複 / SemanticReferee) は
**DON を全く検査していない** (= 別資源として除外)。 だが DON にも厳密な保存則がある:

  各プレイヤーの DON 台帳:
    L(p) = don_active + don_rested + Σ attached_dons(leader+全キャラ) + don_remaining_in_deck
  は **常に deck_size に等しい** (= 標準 10、 紫エネル等の set_don_deck_size で 6 等)。

  なぜ不変か: 全ての正当な DON 操作が台帳内の移動でしかない —
    - DON フェイズ加算 / add_don / add_rested_don : remaining → active/rested
    - pay_don / 「ドンデッキに戻す」              : active/rested → remaining
    - attach_don                                  : active → attached
    - キャラ離脱時の付与ドン返却 (公式6-5-5-4)     : attached → rested
    - REFRESH                                      : rested → active
  どれも L(p) を変えない。 ⇒ **L(p) ≠ baseline は engine バグの確証** (DON 複製 or 喪失)。
  log 解析不要・false-positive ゼロ。 「付与ドンを返さない離脱パス」 を即検出する。

baseline は 各 player の最初の settled 点 (= 全 DON が deck) で確定。

  python scripts/hunt_don_ledger.py [N_PER_PAIR]
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


def ledger(p):
    att = sum(getattr(ip, "attached_dons", 0) or 0 for ip in [p.leader, *p.characters])
    return p.don_active + p.don_rested + att + p.don_remaining_in_deck


def _detail(p):
    att = sum(getattr(ip, "attached_dons", 0) or 0 for ip in [p.leader, *p.characters])
    return f"active={p.don_active} rested={p.don_rested} attached={att} remaining={p.don_remaining_in_deck}"


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


def do_defense(s, pl, rng):
    """カウンターイベント + opp_attack 効果 + ブロッカー + counter 値を最大消費 (= DON を動かす)。"""
    ce = pl.get("counter_event_idxs") or []
    avail = pl.get("available_opp_attack_effects") or []
    blk = pl.get("legal_blocker_iids") or []
    cnt = pl.get("legal_counter_card_idxs") or []
    cnt_val = [i for i in cnt if i not in ce]
    if ce and rng.random() < 0.8:
        s.apply_human_use_counter_event(ce[0])
        return
    if avail and rng.random() < 0.6:
        e = avail[0]
        s.apply_human_use_opp_attack_effect(e["source_iid"], e["effect_idx"])
        return
    s.apply_human_defense(blk[0] if blk and rng.random() < 0.5 else None, cnt_val[:2])


def play(a, b, seed, hf):
    s = F._build_session(a, b, seed, hf)
    rng = random.Random(seed)
    steps = 0
    base = [None, None]  # per-player baseline
    last = None
    same = 0
    while not s.state.game_over and steps < 3000:
        steps += 1
        pk = s.pending_kind
        pl = s.pending_payload or {}
        # 進行不能検出
        sig = (pk, pl.get("kind"), s.state.turn_number, len(s.state.players[0].hand),
               len(s.state.players[1].hand))
        if sig == last:
            same += 1
            if same > 120:
                return ("STUCK", steps, None)
        else:
            same = 0
            last = sig
        # settled (= action 点) で DON 台帳 検査
        if pk == "action":
            for pi, p in enumerate(s.state.players):
                L = ledger(p)
                if base[pi] is None:
                    base[pi] = L
                elif L != base[pi]:
                    # 直近 log から 文脈 (= どの効果/KO 後にズレたか)
                    ctx = " | ".join(s.state.log[-4:])[-160:]
                    return ("DON_LEAK" if L < base[pi] else "DON_DUP", steps,
                            f"p{pi} L={L}!=base{base[pi]} ({_detail(p)}) turn{s.state.turn_number} :: {ctx}")
        try:
            if pk == "action":
                acts = s.legal_actions_for_human()
                if not acts:
                    return ("NO_ACT", steps, None)
                non_end = [x for x in acts if x.get("kind") != "EndPhase"]
                # attach/character 系を厚めに (= DON を場に動かす)
                pref = [x for x in non_end if x.get("kind") in
                        ("PlayCharacter", "AttachDonToCharacter", "AttachDonToLeader",
                         "ActivateMain", "AttackLeader", "AttackCharacter")]
                if pref and rng.random() < 0.7:
                    pick = rng.choice(pref)
                elif non_end and rng.random() < 0.85:
                    pick = rng.choice(non_end)
                else:
                    pick = next((x for x in acts if x.get("kind") == "EndPhase"), acts[0])
                s.apply_human_action(pick["idx"])
            elif pk == "choice":
                s.apply_human_choice(modal_pick(pl, rng))
            elif pk == "defense":
                do_defense(s, pl, rng)
            else:
                break
        except Exception as e:  # noqa: BLE001
            import traceback
            return ("PY_EXC", steps,
                    f"{type(e).__name__}: {str(e)[:70]} | {traceback.format_exc().splitlines()[-2][:70]}")
    # 終局でも 台帳 検査 (= 最終 settled)
    for pi, p in enumerate(s.state.players):
        if base[pi] is not None and ledger(p) != base[pi]:
            return ("DON_LEAK" if ledger(p) < base[pi] else "DON_DUP", steps,
                    f"p{pi}(final) L={ledger(p)}!=base{base[pi]} ({_detail(p)})")
    for ln in s.state.log:
        if "engine error" in ln:
            return ("ENGINE_ERROR", steps, ln.split("engine error:")[-1].strip()[:90])
    return ("OK", steps, None)


def _pairs():
    ps = [(d, d) for d in DECKS]
    for i, d in enumerate(DECKS):
        for j in (1, 2, 3):
            ps.append((d, DECKS[(i + j) % len(DECKS)]))
    return ps


def main():
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    n = nums[0] if nums else 8
    pairs = _pairs()
    bugs = []
    res = Counter()
    total = 0
    for a, b in pairs:
        for sd in range(n):
            gs = 80000 + sd * 7
            st, steps, info = play(a, b, gs, sd % 2 == 0)
            res[st] += 1
            total += 1
            if st != "OK":
                bugs.append((a, b, gs, sd % 2 == 0, st, info))
        if pairs.index((a, b)) % 8 == 0:
            print(f"  ... {a} vs {b} | total {total} bugs {len(bugs)}", flush=True)
    print(f"\n=== DON 台帳 hunt {total} 試合 ===")
    for k, c in res.most_common():
        print(f"  {k}: {c}")
    if bugs:
        print(f"\n!!! 問題 {len(bugs)} 件 (先頭30):")
        for a, b, sd, hf, st, info in bugs[:30]:
            print(f"  ★[{st}] {a} vs {b} seed={sd} hf={hf}: {info}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
