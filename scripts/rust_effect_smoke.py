"""Rust 全カード効果スモーク — self-play では踏めない効果を **直接発火** させて実行可否を測る。

背景 (2026-08-01):
  全カード合成デッキの self-play 掃引 (scripts/rust_fullsweep.py) は、 4,263 枚中 **約 60% しか
  効果が発火しない** ところで頭打ちになった (16 game/deck に増やしても +43 枚)。 理由は
  「デッキに入っていても引かれない / コストが払えず出せない / その when が起きない」 で、
  試合数を増やしても解決しない。

  → 未発火 = **実装済みかどうかも分かっていない** ので、 保証には届かない。 そこで Python の
    smoke_test_card_effects.py と同じ最小 state を作り、 **Rust に直接効果を実行させる**。
    self-play (深いが 60%) と スモーク (浅いが 100%) の 2 枚で網羅する。

測るもの (Rust 単独、 Python は state 生成にのみ使う):
  - ok    : Rust が最後まで実行できた
  - bail  : Rust が「再現できない」と降参した (= 未実装の在処、 理由付き)
  - inv   : 実行後に保存則 (カード枚数 / ドン総数) が壊れていないか

  .venv/bin/python scripts/rust_effect_smoke.py              # 全カード
  .venv/bin/python scripts/rust_effect_smoke.py --limit 200  # 先頭 200 枚 (試走)

結果は db/rust_selfplay/effect_smoke.json に保存。
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402
import scripts.rust_parity_check as P  # noqa: E402
from engine.core import Category, InPlay, reset_iid  # noqa: E402
from engine.state_snapshot import full_dump  # noqa: E402
from scripts.smoke_test_card_effects import make_state  # noqa: E402

OUT = ROOT / "db" / "rust_selfplay" / "effect_smoke.json"

# when → Rust 側の発火経路。 src slot は state の作り方に合わせる。
#   field : src を自場キャラ/ステージに置いてから発火 (on_play/activate_main/on_attack/...)
#   detached: 場に置かず発火 (main イベント / counter / trigger / on_ko = source-gone)
FIELD_WHENS = {
    "on_play", "activate_main", "on_attack", "on_block", "opp_attack", "opp_attack_on_leader",
    "opp_attack_on_chara", "end_of_turn", "opp_end_of_turn", "on_turn_start", "opp_turn_start",
    "on_self_chara_played", "on_opp_chara_played", "on_self_chara_ko", "on_opp_chara_ko",
    "on_self_life_taken", "on_opp_life_taken", "on_self_life_to_hand", "on_self_life_to_trash",
    "on_self_hand_discarded", "on_self_event_played", "on_self_rested", "on_self_trigger_fired",
    "on_opp_event_or_trigger_fired", "on_self_chara_leave_by_self_effect",
    "on_self_don_returned_to_deck", "on_opp_blocker_use", "on_life_zero",
}
DETACHED_WHENS = {"main", "counter", "trigger", "on_ko"}


def build_state_json(repo, overlay, card_id: str, when: str) -> tuple[str, int]:
    """最小 state を作り (full_dump JSON, src_char_idx) を返す。 src_char_idx=-1 は場に置かない。"""
    reset_iid()
    st = make_state(repo, overlay, card_id)
    card = repo._by_id[card_id]
    idx = -1
    if when in FIELD_WHENS and card.category in (Category.CHARACTER, Category.STAGE):
        ip = InPlay.of(card, sickness=False)
        if card.category == Category.CHARACTER:
            st.players[0].characters.append(ip)
            idx = len(st.players[0].characters) - 1
        else:
            st.players[0].stages.append(ip)
            idx = -2  # stage slot 0
    return json.dumps(full_dump(st)), idx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report-sec", type=float, default=10.0)
    args = ap.parse_args()

    repo, overlay_py = P._load()
    overlay = json.loads((ROOT / "db" / "card_effects.json").read_text(encoding="utf-8"))
    cards = [(cid, effs) for cid, effs in overlay.items()
             if isinstance(effs, list) and effs and cid in repo._by_id]
    cards.sort()
    if args.limit:
        cards = cards[: args.limit]
    total_eff = sum(len(e) for _, e in cards)
    print(f"対象 {len(cards)} 枚 / 効果 {total_eff} 件", flush=True)

    eng.reset_coverage_stats(True)
    res = Counter()
    bails = Counter()
    per_when = Counter()
    fired_cards = set()
    t0 = time.time()
    last = t0
    for n, (cid, effs) in enumerate(cards):
        for idx, eff in enumerate(effs):
            when = eff.get("when") or ""
            if when not in FIELD_WHENS and when not in DETACHED_WHENS:
                res["skip(when)"] += 1
                continue
            try:
                sj, sidx = build_state_json(repo, overlay_py, cid, when)
            except Exception as e:
                res["skip(state)"] += 1
                bails[f"state 構築失敗: {type(e).__name__} {str(e)[:60]}"] += 1
                continue
            try:
                out = json.loads(eng.fire_effect_smoke(sj, cid, when, idx, sidx))
                if out.get("ok"):
                    res["ok"] += 1
                    fired_cards.add(cid)
                    per_when[when] += 1
                    if out.get("invariant_violations"):
                        res["inv"] += 1
                        bails[f"保存則違反 @{cid} [{when}]"] += 1
                else:
                    res["bail"] += 1
                    bails[str(out.get("err", "?"))[:120]] += 1
            except BaseException as e:
                kind = "PANIC" if "Panic" in type(e).__name__ else type(e).__name__
                res[kind] += 1
                bails[f"{kind}: {str(e)[:100]}"] += 1
        now = time.time()
        if now - last >= args.report_sec or n == len(cards) - 1:
            done = sum(res.values())
            print(f"[{n+1}/{len(cards)} 枚 | {done} 効果 | {now-t0:.0f}s] "
                  f"ok {res['ok']} / bail {res['bail']} / panic {res.get('PANIC',0)}", flush=True)
            last = now

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "cards": len(cards), "effects": total_eff, "result": dict(res),
        "fired_cards": len(fired_cards),
        "bails": dict(bails.most_common(400)),
        "per_when": dict(per_when.most_common()),
        "sec": time.time() - t0,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 結果 ===")
    tot = res["ok"] + res["bail"] + res.get("PANIC", 0)
    print(f"実行 {tot} 効果: ok {res['ok']} ({res['ok']/max(tot,1):.1%}) / "
          f"bail {res['bail']} / panic {res.get('PANIC',0)} / 保存則違反 {res.get('inv',0)}")
    print(f"1 回以上実行できたカード: {len(fired_cards)}/{len(cards)}")
    print(f"skip: when 対象外 {res.get('skip(when)',0)} / state 構築失敗 {res.get('skip(state)',0)}")
    # optional_cost_then など「外側は実装済だが内側で落ちた」内訳 ([oct_pay]/[oct_effect] 等)
    cv = json.loads(eng.coverage_stats())
    inner = {k: v for k, v in (cv.get("unknown_conditions") or {}).items() if k.startswith("[")}
    if inner:
        print("\n内側の未対応 (optional_cost_then 等) top15:")
        for k, v in sorted(inner.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {v:6d}  {k}")
    print("\nbail 理由 top20:")
    for k, v in bails.most_common(20):
        print(f"  {v:6d}  {k}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
