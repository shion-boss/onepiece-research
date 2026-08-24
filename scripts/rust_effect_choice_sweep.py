#!/usr/bin/env python
"""**候補を増やした state** で全カードの効果を両エンジン突合する検出器 (2026-08-24 新設)。

⭐ なぜ要るか — 既存の 「効果ありカード 4,308 枚 bit 一致証明」 は **過大主張** だった。

  `rust_effect_smoke_parity` は各カードの効果を **最小 state から 1 回** 撃つ。 その state の
  手札/盤面には、 そのカードの filter に合う札が **たかだか 1 枚** しか無い。 すると
  「候補が 2 枚以上ある時だけ走る分岐」 (= 選択・ソート・上限 cap) が **一度も実行されない**
  まま 「一致」 と記録される。

  実例 (2026-08-24): `play_from_hand_choice` (OP11-024/035) の候補ソート比較子が
  **コスト昇順** (= 一番弱い札を選ぶ) に壊れていた。 Python はコスト降順。 それでも
  OP11-024 は 「proven_cards」 に入っていた — smoke state の手札に 「魚人族/人魚族 cost≤6」 が
  **自分 1 枚だけ** で `候補 > limit` が成立せず、 壊れたソートが走らなかったから。

このスクリプトは効果 entry から filter を抜き出し、 **合致する実カードを 3 枚ずつ**
手札 / 自場 / 相手場 / トラッシュ / デッキ上 / ライフ上 に積んでから撃つ。 それ以外
(発火手順・比較・診断) は `rust_effect_smoke_parity` の実装をそのまま使う (= 二重実装しない)。

⚠ **両エンジンに同一の state を渡す**。 Python 側で組んだ state を `full_dump` して
  Rust にもそれを渡す (別々に組むと 「builder の差」 が MISMATCH に化ける)。

  .venv/bin/python scripts/rust_effect_choice_sweep.py            # 全カード
  .venv/bin/python scripts/rust_effect_choice_sweep.py --limit 300
  .venv/bin/python scripts/rust_effect_choice_sweep.py --assert    # MISMATCH>0 で exit 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import Category, InPlay  # noqa: E402
from engine.effects import _matches_filter  # noqa: E402
from engine.state_snapshot import full_dump  # noqa: E402

import scripts.rust_effect_smoke as S  # noqa: E402
import scripts.rust_effect_smoke_parity as P  # noqa: E402

N_PER_ZONE = 3          # 各ゾーンに積む 「filter 合致カード」 の枚数
_state_cache: dict[tuple[str, str], object] = {}
_src_cache: dict[tuple[str, str], object] = {}


def _collect_filters(node, out: list[dict]) -> None:
    """効果 entry から filter dict を再帰収集する。"""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("filter", "name_filter") and isinstance(v, dict):
                out.append(v)
            _collect_filters(v, out)
    elif isinstance(node, list):
        for x in node:
            _collect_filters(x, out)


_pool_cache: dict[str, list] = {}


def _match_pool(repo, filt: dict, n: int) -> list:
    """filter に合致する実カードを最大 n 枚返す (card_id 昇順 = 決定論的)。

    ⚠ 全カード走査なので **filter 単位でメモ化** する (無いと 4,300 カード × 4 filter ×
      4,776 走査 で実用時間に収まらない)。
    """
    key = json.dumps(filt, sort_keys=True, ensure_ascii=False) + f"|{n}"
    hit = _pool_cache.get(key)
    if hit is not None:
        return hit
    out = []
    for cid in sorted(repo._by_id):
        c = repo._by_id[cid]
        if c.category == Category.LEADER:
            continue
        try:
            if _matches_filter(c, filt):
                out.append(c)
        except Exception:
            continue
        if len(out) >= n:
            break
    _pool_cache[key] = out
    return out


def _enrich(st, repo, eff: dict) -> int:
    """効果の filter に合致するカードを各ゾーンに積む。 積んだ総枚数を返す。

    ⚠ 発動元の位置 (characters の index) を **動かさない** ため、 追加は必ず末尾 append。
    """
    filts: list[dict] = []
    _collect_filters(eff, filts)
    # filter が無い効果も 「対象が複数ある盤面」 で撃つ価値があるので、 空 filter を足す
    filts.append({})
    added = 0
    me, opp = st.players[0], st.players[1]
    # ⚠ **非合法な state を作らない**。 場のキャラは公式上 5 枚が上限 (3-7-6-1) で、
    #   6 枚の盤面は実戦で起こり得ない。 そこで両エンジンの 「上限超え時の振る舞い」 が
    #   食い違うと、 **実戦で踏めない乖離** を MISMATCH として報告してしまう
    #   (2026-08-24: OP16-059 でこれを踏んだ)。 ライフも公式上限に合わせる。
    MAX_CHARA = 5
    MAX_LIFE = 5
    for filt in filts[:4]:                     # 1 entry あたり 4 filter まで (走査時間の上限)
        pool = _match_pool(repo, filt, N_PER_ZONE)
        if not pool:
            continue
        for c in pool:
            me.hand.append(c)
            opp.hand.append(c)
            me.trash.append(c)
            opp.trash.append(c)
            me.deck.insert(0, c)
            opp.deck.insert(0, c)
            added += 6
            if c.category == Category.CHARACTER:
                for pl in (me, opp):
                    if len(pl.characters) < MAX_CHARA:
                        pl.characters.append(InPlay.of(c, sickness=False))
                        added += 1
        # ライフは **カードと表向きフラグを対で** 操作する (片方だけ触ると位置がずれる)
        for c in pool:
            for pl in (me, opp):
                if len(pl.life) < MAX_LIFE:
                    pl.life.insert(0, c)
                    pl.life_face_up.insert(0, False)
                    added += 1
    return added


def install_hooks(repo, overlay) -> None:
    """`rust_effect_smoke_parity` の state builder を 「候補リッチ版」 に差し替える。"""
    orig_py_state = P._py_state
    orig_build = S.build_state_json

    def py_state(repo_, overlay_, card_id: str, when: str):
        st, src_ip = orig_py_state(repo_, overlay_, card_id, when)
        bundle = overlay_.get(card_id)
        effs = getattr(bundle, "effects", []) if bundle else []
        for e in effs:
            if e.get("when") == when:
                _enrich(st, repo_, e)
                break
        _state_cache[(card_id, when)] = st
        _src_cache[(card_id, when)] = src_ip
        return st, src_ip

    def build_state_json(repo_, overlay_, card_id: str, when: str):
        # ⚠ **dump と src index は同じ state から取る**。 元 builder の sidx を流用すると
        #   「Python 側 state の発動元」 と 「Rust に伝える発動元スロット」 が食い違い、
        #   両エンジンが **別のカードの効果として** 解決して偽 MISMATCH になる
        #   (2026-08-24: これで P-081 / OP03-021 を誤検出した)。
        st = _state_cache.get((card_id, when))
        if st is None:
            return orig_build(repo_, overlay_, card_id, when)
        src_ip = _src_cache.get((card_id, when))
        me = st.players[0]
        if src_ip is None:
            sidx = -1                                  # 場に置かない (Detached)
        elif src_ip is me.leader:
            sidx = -3                                  # 自リーダー
        elif any(x is src_ip for x in me.stages):
            sidx = -2                                  # ステージ (index 0 前提 = 元 builder と同じ)
        else:
            sidx = next((i for i, c in enumerate(me.characters) if c is src_ip), -1)
        return json.dumps(full_dump(st)), sidx

    P._py_state = py_state
    S.build_state_json = build_state_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭 N カードだけ (0=全部)")
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    from engine.deck import CardRepository
    from engine.effects import load_effect_overlay

    repo = CardRepository.from_json(ROOT / "db" / "cards.json")
    overlay = load_effect_overlay(ROOT / "db" / "card_effects.json")
    install_hooks(repo, overlay)
    # ⚠ 既存スモークの成果物 (db/rust_selfplay/effect_smoke_parity.json) を上書きしない
    #   = 「最小 state の結果」 と 「候補リッチの結果」 を別々に残す。
    P.OUT = ROOT / "db" / "rust_selfplay" / "effect_choice_sweep.json"

    print("=== 候補リッチ state での 効果 parity 掃引 ===")
    print(f"    各ゾーンに filter 合致カードを {N_PER_ZONE} 枚ずつ積む "
          f"(手札/相手手札/トラッシュ×2/デッキ上×2/自場/相手場/ライフ×2)")
    # `rust_effect_smoke_parity.main()` は argparse を自前で読むので argv を差し替えて呼ぶ
    # (発火手順・比較・診断・JSON 出力を二重実装しないため)。
    argv = [sys.argv[0]]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    if args.do_assert:
        argv += ["--assert"]
    old_argv = sys.argv
    sys.argv = argv
    try:
        P.main()
    except SystemExit as e:                     # --assert の gate をそのまま伝播
        return int(e.code or 0)
    finally:
        sys.argv = old_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
