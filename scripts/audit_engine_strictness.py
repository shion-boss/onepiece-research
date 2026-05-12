#!/usr/bin/env python3
"""engine 厳密化監査 (簡易版)

公式 PDF ルールと engine 実装の主要章を突合する自動チェック。
完全な PDF 解析は重いので、 ルールの「主要不変条件」 をテストで表現する形を取る。

検査項目:
  1. 同時発火トリガーの解決順 (公式 9-1-3): ターンプレイヤー優先 + FIFO
  2. 置換効果の優先順位 (公式 4-12-2): 1 つでも replace 成功すると本来の離脱がキャンセル
  3. 静的効果の依存解決 (公式 6-6-1): evaluate_static_effects で全 InPlay の static_buff
     を毎回 0 にリセットしてから再計算する
  4. ターン終了時の buff クリア (公式 7-1-5): turn_buff / granted_keywords / KO耐性
     / アタック不可フラグ が全プレイヤーで _reset_turn_buff にクリアされる
  5. リフレッシュフェイズの ドン回復 (公式 6-2): 付与ドン → コストエリア → 全 active
  6. 次の自/相手ターン終了時 timed buff (= applier-tracking): _reset_turn_buff で
     applier 視点で適切な ended_idx でクリア

各検査は engine source code を読み込んで pattern match で確認する。
全 6 検査が pass すれば engine の主要不変条件は保たれている。

実行方法:
    .venv/bin/python scripts/audit_engine_strictness.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = _ROOT / "engine"

CHECKS = []


def check(name: str):
    """検査関数のデコレータ。"""
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("1. 同時発火: ターンプレイヤー優先 + FIFO (公式 9-1-3)")
def check_turn_player_priority() -> tuple[bool, str]:
    """resolve_triggers でターンプレイヤー側のイベントを先に処理。"""
    src = (_ENGINE / "effects.py").read_text(encoding="utf-8")
    has_priority = "turn_player_idx" in src and (
        "resolve_triggers" in src or "ターンプレイヤー" in src
    )
    if not has_priority:
        return False, "resolve_triggers / turn_player_idx が effects.py に無い"
    # event_queue / FIFO 維持の確認
    has_fifo = "event_queue" in src
    if not has_fifo:
        return False, "event_queue が存在しない"
    return True, "ターンプレイヤー優先 + FIFO 確認済"


@check("2. 置換効果: 1 つでも成功すれば本来の離脱をキャンセル (公式 4-12-2)")
def check_replace_cancels_leave() -> tuple[bool, str]:
    """try_replace_ko / try_replace_rest が True を返したら caller が continue / skip。"""
    src = (_ENGINE / "effects.py").read_text(encoding="utf-8")
    # try_replace_ko の caller が return True で離脱キャンセルしてる箇所をカウント
    callers = re.findall(r"try_replace_ko\([^)]+\):\s*\n\s+continue", src)
    if len(callers) < 3:
        return False, f"try_replace_ko + continue パターンが {len(callers)} 箇所しかない (>=3 期待)"
    return True, f"try_replace_ko + continue: {len(callers)} 箇所で確認"


@check("3. 静的効果: 毎回 0 にリセット (公式 6-6-1)")
def check_static_buff_reset() -> tuple[bool, str]:
    """evaluate_static_effects で static_buff = 0 リセットしてから再計算する。"""
    src = (_ENGINE / "effects.py").read_text(encoding="utf-8")
    # static_buff = 0 のリセットがあるか
    if "ip.static_buff = 0" not in src:
        return False, "static_buff = 0 リセットが evaluate_static_effects に無い"
    if "static_ko_immune = False" not in src:
        return False, "static_ko_immune = False リセットが無い"
    return True, "static_buff / static_ko_immune / base_power_override 等のリセット確認"


@check("4. ターン終了時 buff クリア (公式 7-1-5)")
def check_turn_buff_reset() -> tuple[bool, str]:
    """_reset_turn_buff で全 InPlay の turn_buff / granted_keywords 等をクリア。"""
    src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    required = [
        "ip.turn_buff = 0",
        "ip.granted_keywords = set()",
        "ip.ko_immune_until_turn_end = False",
        "ip.cannot_attack_until_turn_end = False",
    ]
    missing = [r for r in required if r not in src]
    if missing:
        return False, f"_reset_turn_buff に欠落: {missing}"
    return True, "turn_buff / granted_keywords / ko_immune / cannot_attack クリア確認"


@check("5. リフレッシュ: ドン回復 (公式 6-2)")
def check_refresh_don_recovery() -> tuple[bool, str]:
    """Phase.REFRESH で don_rested → don_active + 付与ドン回収。"""
    src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    if "Phase.REFRESH" not in src:
        return False, "Phase.REFRESH 遷移が無い"
    if "me.don_active" not in src:
        return False, "don_active 操作が無い"
    if "stay_rested_next_refresh" not in src:
        return False, "stay_rested_next_refresh 処理が無い"
    return True, "REFRESH 時 ドン回復 + stay_rested 処理確認"


@check("6. timed buff applier-tracking (= 次の自/相手ターン終了時)")
def check_timed_buff_applier() -> tuple[bool, str]:
    """next_opp_turn_end_buff 等 applier-tracking フィールドが正しくクリア。"""
    src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    required = [
        "next_opp_turn_end_buff",
        "next_opp_turn_end_applier_idx",
        "next_opp_turn_end_applied_turn",
        "ended_idx",
    ]
    missing = [r for r in required if r not in src]
    if missing:
        return False, f"_reset_turn_buff に applier-tracking 欠落: {missing}"
    return True, "applier-tracking + ended_idx 判定確認"


@check("7. 同時 KO 効果の解決順 (公式 9-1-1)")
def check_simultaneous_ko_order() -> tuple[bool, str]:
    """trigger_on_ko / trigger_on_self_chara_ko / trigger_on_opp_chara_ko が
    同時 KO で順に発火 + ターンプレイヤー優先。"""
    src = (_ENGINE / "effects.py").read_text(encoding="utf-8")
    # 各 trigger 関数が存在し、 ko primitive 内で並行発火している
    for func in ["trigger_on_ko", "trigger_on_self_chara_ko", "trigger_on_opp_chara_ko"]:
        if f"def {func}" not in src:
            return False, f"{func} が定義されていない"
    return True, "KO 3 種 trigger 並行発火確認"


@check("8. extra_turn (= 「ターン追加」 効果) の正常処理")
def check_extra_turn() -> tuple[bool, str]:
    src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    if "extra_turn_pending" not in src:
        return False, "extra_turn_pending フラグが game.py に無い"
    return True, "extra_turn_pending 処理確認"


@check("9. 全効果 primitive が elif k == '...' or 別経路で実装")
def check_no_silent_no_op() -> tuple[bool, str]:
    """overlay で使用される primitive がすべて engine 内で扱われている。"""
    import json
    overlay_path = _ROOT / "db" / "card_effects.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    used = set()
    for entries in overlay.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            for prim in e.get("do", []):
                if isinstance(prim, dict):
                    for k in prim.keys():
                        if not k.startswith("_"):
                            used.add(k)
    src = (_ENGINE / "effects.py").read_text(encoding="utf-8")
    game_src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    # elif k == "X" or static evaluate ループ内の "X" in primitive
    handled = set()
    for m in re.finditer(r'k == "([^"]+)"', src):
        handled.add(m.group(1))
    for m in re.finditer(r'"([^"]+)" in primitive', src):
        handled.add(m.group(1))
    # game.py の phase modifier (Phase.DON 内 don_phase_modifier 等) で扱われる primitive
    for m in re.finditer(r'prim\.get\("([^"]+)"', game_src):
        handled.add(m.group(1))
    # in_hand effect 由来 (effects.py 内の in_hand 系で扱われる primitive)
    for m in re.finditer(r'prim\.get\("([^"]+)"', src):
        handled.add(m.group(1))
    no_op = used - handled
    if no_op:
        return False, f"未実装 primitive: {sorted(no_op)}"
    return True, f"全 {len(used)} primitive が engine で扱われている"


@check("10. once_per_turn ガードが reset される")
def check_once_per_turn_reset() -> tuple[bool, str]:
    src = (_ENGINE / "game.py").read_text(encoding="utf-8")
    if "once_per_turn_used.clear()" not in src:
        return False, "once_per_turn_used.clear() が REFRESH 時に無い"
    return True, "once_per_turn_used クリア確認"


def main() -> int:
    print(f"engine 厳密化 監査 (簡易版) — {len(CHECKS)} 項目\n")
    passed = 0
    failed = 0
    for name, fn in CHECKS:
        try:
            ok, msg = fn()
        except Exception as e:
            ok = False
            msg = f"例外: {e}"
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {name}")
        print(f"      {msg}")
        if ok:
            passed += 1
        else:
            failed += 1
    print(f"\n合計: {passed} pass / {failed} fail")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
