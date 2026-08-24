#!/usr/bin/env python
"""選択列挙 ON の MISMATCH を **原因別に分類** する診断ツール。

⭐ なぜ要るか: `rust_choice_parity.py` は件数しか出さないが、 列挙 ON の MISMATCH は
   「Python が選択を立てたのに Rust が立てていない (= 中断していない)」 型が支配的で、
   **両エンジンの選択列 (kind / 候補数 / 候補の中身) を並べない限り原因が特定できない**。
   2026-08-21 の MISMATCH 62 → 0 はこの分類なしには辿り着けなかった。

出すもの:
  - 原因分類 (中断していない / 候補数が違う / 選択列が違う / 同形なのに乖離 …)
  - `--check-off`: 同じ局面を **列挙 OFF** でも突合 → 「選択固有」 と 「元からの
    parity バグ」 を分ける。 実際これで Python 側の実バグ (アタック対象変更の持ち越し) が出た
  - `--show N`: 個別サンプル (両engineの選択列 + zone 単位の差分 + 直前の盤面 + Python ログ)
  - `--dump DIR`: 乖離局面の (state, action) を保存 → `rust_choice_probe.py` で
    Rust 単体の ON/OFF 比較ができる

  .venv/bin/python scripts/rust_choice_diag.py --games 6
  .venv/bin/python scripts/rust_choice_diag.py --games 6 --show 20 --check-off
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import optcg_engine as eng  # noqa: E402

from engine.core import reset_iid  # noqa: E402
from engine.deck import CardRepository, DeckList  # noqa: E402
from engine.effects import load_effect_overlay  # noqa: E402
from engine.game import apply_action, legal_actions, play_until_main, setup_game  # noqa: E402
from engine.state_snapshot import full_dump, state_digest  # noqa: E402
from scripts.rust_parity_check import _enc  # noqa: E402

POLICY_K = 1


def _py_choice_row(st) -> dict:
    """Python の pending_choice を Rust trace と同じ形に畳む。"""
    pc = st.pending_choice or {}
    cands = pc.get("candidates")
    if not isinstance(cands, list):
        cands = pc.get("cards")
    ids: list[str] = []
    if isinstance(cands, list):
        for c in cands:
            ids.append(str(c.get("card_id") or c.get("idx") or "?") if isinstance(c, dict) else str(c))
    return {
        "kind": str(pc.get("kind") or ""),
        "n_cands": len(cands) if isinstance(cands, list) else 0,
        "limit": int(pc.get("limit", 1) or 1),
        "cands": ids,
    }


def _py_fp(st) -> list[dict]:
    """Rust 側の指紋と同じ形を Python から作る (どの zone が食い違うかの特定用)。"""
    out = []
    for p in st.players:
        out.append({
            "hand": [c.card_id for c in p.hand],
            "deck_n": len(p.deck),
            "deck_top": [c.card_id for c in p.deck[:5]],
            "trash": [c.card_id for c in p.trash],
            "life_n": len(p.life),
            "chars": [f"{c.card.card_id}{'(R)' if c.rested else ''}" for c in p.characters],
            "don": [p.don_active, p.don_rested],
        })
    return out


def fp_diff(py: list[dict], rs: list[dict]) -> list[str]:
    diffs: list[str] = []
    for pi, (a, b) in enumerate(zip(py, rs)):
        for k in a:
            if a[k] != b.get(k):
                diffs.append(f"P{pi}.{k}: py={a[k]} rs={b.get(k)}")
    return diffs


def classify(py_tr: list[dict], rs_tr: list[dict]) -> str:
    """MISMATCH の原因を Python/Rust の選択列の差から名付ける。"""
    pk = [r["kind"] for r in py_tr]
    rk = [r["kind"] for r in rs_tr]
    if pk and not rk:
        return f"Rust が中断していない: {'/'.join(pk[:2])}"
    if rk and not pk:
        return f"Rust だけ中断: {'/'.join(rk[:2])}"
    if pk != rk:
        return f"選択列が違う: py={'/'.join(pk[:2])} rs={'/'.join(rk[:2])}"
    for p, r in zip(py_tr, rs_tr):
        if p["n_cands"] != r["n_cands"]:
            return f"候補数が違う ({p['kind']}): py={p['n_cands']} rs={r['n_cands']}"
        if p["limit"] != r["limit"]:
            return f"limit が違う ({p['kind']}): py={p['limit']} rs={r['limit']}"
    if not pk:
        return "選択なしで乖離 (= 選択と無関係の差)"
    return f"選択列は同形なのに乖離: {'/'.join(pk[:2])}"


def run(games: int, seed: int, max_steps: int, show: int,
        dump_dir: Path | None = None, check_off: bool = False) -> None:
    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    decks = [p for p in sorted((ROOT / "decks").glob("cardrush_*.json"))
             if ".analysis." not in p.name and ".target_v" not in p.name][:6]
    causes: Counter = Counter()
    by_action: Counter = Counter()
    samples: list[dict] = []
    stat: Counter = Counter()
    off_stat: Counter = Counter()

    for gi in range(games):
        a = decks[gi % len(decks)]
        b = decks[(gi + 1) % len(decks)]
        reset_iid()
        st = setup_game(DeckList.from_json(str(a), repo), DeckList.from_json(str(b), repo),
                        rng=random.Random(seed + gi), first_player=gi % 2,
                        effects_overlay=overlay)
        play_until_main(st)
        st.choice_enumeration = True

        for _ in range(max_steps):
            if st.game_over:
                break
            acts = legal_actions(st)
            if not acts:
                break
            act = acts[min(1, len(acts) - 1)]
            enc = _enc(st, act)
            if enc.get("t") == "?":
                try:
                    apply_action(st, act)
                except Exception:
                    break
                continue
            js = json.dumps(full_dump(st))
            log_before = len(getattr(st, "log", []) or [])
            fp_before = _py_fp(st)
            redirect_before = getattr(st, "pending_attack_redirect", None)
            st_off = act_off = None
            if check_off:
                try:
                    st_off = copy.deepcopy(st)
                    st_off.choice_enumeration = False
                    act_off = legal_actions(st_off)[min(1, len(acts) - 1)]
                except Exception:  # noqa: BLE001
                    st_off = act_off = None
            rs = None
            try:
                rs = json.loads(eng.apply_action_choice_policy_trace(js, json.dumps(enc), POLICY_K))
            except Exception as e:  # noqa: BLE001
                rs = {"err": str(e)}
            # Python 側: 同じ方針で解決しきりつつ選択列を記録
            py_tr: list[dict] = []
            try:
                apply_action(st, act)
                guard = 0
                while st.pending_choice is not None and guard < 40:
                    guard += 1
                    py_tr.append(_py_choice_row(st))
                    opts = legal_actions(st)
                    if not opts:
                        st.pending_choice = None
                        break
                    apply_action(st, opts[POLICY_K % len(opts)])
            except Exception:
                break
            if rs is None or "err" in rs:
                stat["bail"] += 1
                continue
            if rs["digest"] == state_digest(st):
                stat["match"] += 1
                continue
            stat["MISMATCH"] += 1
            # ⭐ 同じ局面を **列挙 OFF** でも突き合わせ、 「選択列挙固有の乖離」 と
            #   「元からの parity バグ」 を切り分ける (ON の diff だけ見ていると
            #   「選択と無関係の差」 で分類が止まる)。 Python state は full_dump から
            #   復元できないので、 apply の **前** に取った deepcopy を使う。
            off_note = ""
            off_fp: list[str] = []
            if st_off is not None:
                try:
                    rs_off = json.loads(eng.apply_action_choice_policy_trace(
                        json.dumps(full_dump(st_off)), json.dumps(enc), POLICY_K))
                    apply_action(st_off, act_off)
                    if "err" in rs_off:
                        off_note = f"OFF=bail({rs_off['err'][:40]})"
                    else:
                        if rs_off["digest"] == state_digest(st_off):
                            off_note = "OFF=match"
                        else:
                            off_note = "OFF=MISMATCH"
                            off_fp = fp_diff(_py_fp(st_off), rs_off.get("fp") or [{}, {}])
                except Exception as e:  # noqa: BLE001
                    off_note = f"OFF=err({str(e)[:40]})"
            off_stat[off_note] += 1
            if dump_dir is not None:
                # ⭐ 「列挙 ON 固有か」 を切り分けるため、 乖離した局面の (state, action) を
                #   そのまま落とす。 同じ state を choice_enumeration=false で流せば、
                #   選択と無関係の素の parity バグかどうかが 1 発で判る。
                dump_dir.mkdir(parents=True, exist_ok=True)
                (dump_dir / f"mm_{gi}_{stat['MISMATCH']:03d}.json").write_text(
                    json.dumps({"state": json.loads(js), "action": enc}), encoding="utf-8")
            rs_tr = rs.get("trace") or []
            c = classify(py_tr, rs_tr)
            causes[c] += 1
            by_action[enc.get("t", "?")] += 1
            if len(samples) < show:
                samples.append({"game": gi, "action": enc, "py": py_tr, "rs": rs_tr, "cause": c,
                                "off": off_note,
                                "enum_on": rs.get("enum_on"), "susp": rs.get("suspend_calls"),
                                "tl": rs.get("tl_before"), "rdr": redirect_before,
                                "fp": fp_diff(_py_fp(st), rs.get("fp") or [{}, {}]),
                                "off_fp": off_fp,
                                "before": [{k: v for k, v in p.items() if k in
                                            ("deck_n", "deck_top", "hand", "chars", "don")}
                                           for p in fp_before],
                                "log": [str(x) for x in (getattr(st, "log", []) or [])[log_before:]][:14]})

    print(f"=== MISMATCH 原因分類 ({games} game) ===")
    print(f"  match {stat['match']} / bail {stat['bail']} / MISMATCH {stat['MISMATCH']}")
    print("\n原因別:")
    for k, v in causes.most_common(30):
        print(f"  {v:4d}  {k}")
    if off_stat:
        print("\n列挙 OFF で同じ局面を流した結果 (= 選択固有かの切り分け):")
        for k, v in off_stat.most_common(10):
            print(f"  {v:4d}  {k or '(未計測)'}")
    print("\naction 別:")
    for k, v in by_action.most_common(10):
        print(f"  {v:4d}  {k}")
    if samples:
        print("\n個別サンプル:")
        for s in samples:
            print(f"  [g{s['game']}] {s['action'].get('t')} :: {s['cause']}"
                  f"  [{s.get('off') or '-'}] (rust enum_on={s.get('enum_on')} suspend_calls={s.get('susp')} tl_before={s.get('tl')} redirect_before={s.get('rdr')})")
            print(f"      py={s['py']}")
            print(f"      rs={s['rs']}")
            for pi, b in enumerate(s.get("before", [])):
                print(f"      before P{pi}: deck_n={b['deck_n']} top={b['deck_top']} "
                      f"chars={b['chars']} don={b['don']}")
            for d in s.get("fp", []):
                print(f"      ≠ {d}")
            for d in s.get("off_fp", []):
                print(f"      OFF≠ {d}")
            for ln in s.get("log", []):
                print(f"        | {ln}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--seed", type=int, default=500)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--check-off", action="store_true",
                    help="乖離局面を列挙 OFF でも突合し 選択固有か素の parity バグかを分ける")
    ap.add_argument("--dump", default=None, help="MISMATCH 局面の (state, action) を落とす dir")
    args = ap.parse_args()
    run(args.games, args.seed, args.max_steps, args.show,
        Path(args.dump) if args.dump else None, args.check_off)


if __name__ == "__main__":
    main()
