"""Rust シャドウ検証 — Python が回す実ゲームを毎回 Rust に後追いさせ、 乖離を記録に残す (2026-07-31)。

`ONEPIECE_RUST_SHADOW=1` の時、 `game.apply_action` の各手で:
  ① action 適用前の full_dump を capture
  ② Python が普通に適用 (実ゲーム進行は無改変)
  ③ Rust `apply_action_digest(dump, action)` を回し、 Python 適用後の state_digest と比較
  ④ 一致 → 何もしない / bail(Rust未対応=Err) → skip / **MISMATCH (黙って違う)** → 記録に append

記録 (append-only、 unique action:card で dedup):
  - `db/rust_divergence_log.jsonl` : {key, action, card, diffs(上位), log, dump_file, first_seen}
  - `db/rust_divergence/<key>.json` : 再現用の {dump, action} (fix agent が load→apply_action_blob→diff で厳密再現)

= サンプル型 `rust_mismatch_scan.py` の継続版: self-play/テスト/対戦で **実際に走った局面** が全部差分検証になり、
  乖離が repo に貯まる。 fix ルーティン (skill onepiece-rust-parity-fix) がこの記録を消化する。

⚠ **シャドウの失敗は実ゲームを絶対に壊さない** (全例外を握りつぶす)。 disabled 時は env チェックのみで無コスト。
⚠ static-diff (evaluate_static のズレ) は別軸なので skip。 rng は dump の _rng_state を Rust が使う = 実 state と
   同じ rng 起点で進むため clone 不要 (整合)。
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
_LOG = _ROOT / "db" / "rust_divergence_log.jsonl"
_DUMP_DIR = _ROOT / "db" / "rust_divergence"

_ENABLED: Optional[bool] = None
_SEEN_KEYS: Optional[set] = None  # このプロセスで既に記録した key (再 append 抑止)
_eng = None
_enc_fn = None


def enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        _ENABLED = os.environ.get("ONEPIECE_RUST_SHADOW", "") not in ("", "0", "false", "no")
        # ⛔ **選択列挙モードでは Rust を使わない**。 Rust には pending_choice / continuation
        #   機構が無く (= 自動 pick が 89 箇所インライン)、 Python が選択を列挙している間
        #   Rust は従来どおり自動解決する = **黙って別のゲームを進める**。
        #   parity は 「bit 一致 か 明示 bail」 が不変条件なので、 追従するまでは経路ごと止める。
        #   ⚠ ここを外すと self-play の学習データが静かに汚染される。
        if _ENABLED and choice_search_env_on():
            print("⚠ ONEPIECE_CHOICE_SEARCH が有効 → Rust シャドウ検証を無効化 "
                  "(Rust は選択列挙に未追従)", file=sys.stderr)
            _ENABLED = False
        if _ENABLED:
            _load()
    return _ENABLED


def choice_search_env_on() -> bool:
    """`ONEPIECE_CHOICE_SEARCH` が有効か (= 効果中の選択を探索に載せるモード)。"""
    v = (os.environ.get("ONEPIECE_CHOICE_SEARCH") or "").strip().lower()
    return bool(v) and v not in ("0", "off", "false")


def assert_rust_safe_for_choice_search(context: str = "") -> None:
    """Rust 経路を使う前に呼ぶガード。 選択列挙モードなら **例外で止める**。

    Rust は選択列挙に未追従なので、 このモードで Rust self-play / parity を回すと
    Python と違うゲームを生成する。 学習データが静かに汚染されるより落ちる方が良い。
    """
    if choice_search_env_on():
        raise RuntimeError(
            f"ONEPIECE_CHOICE_SEARCH が有効な状態で Rust 経路 ({context or '?'}) は使えない。"
            " Rust は pending_choice / continuation を未実装で、 Python が選択を列挙する間"
            " Rust は自動解決する = 黙って別のゲームになる。"
            " 追従するまでは env を外して実行すること。"
        )


def _load() -> None:
    """Rust module + action encoder + 既知 key を遅延ロード (import 循環回避)。"""
    global _eng, _enc_fn, _SEEN_KEYS
    try:
        import optcg_engine as eng  # noqa
        _eng = eng
    except Exception:
        _eng = None
        return
    # ⚠ Rust overlay (global OnceLock) を必ずロード。 未ロードだと execute_card_effects が全カード
    #   no-op → 効果カード全部が false MISMATCH になる。 二重 load は Rust 側で無視 (OnceLock)。
    try:
        _eng.load_overlay(str(_ROOT / "db" / "card_effects.json"))
    except Exception:
        pass
    try:
        # action → Rust JSON エンコーダは差分ハーネスに実装済 (再利用)
        from scripts.rust_parity_check import _enc  # noqa
        _enc_fn = _enc
    except Exception:
        _enc_fn = None
    _SEEN_KEYS = set()
    if _LOG.exists():
        try:
            for ln in _LOG.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    _SEEN_KEYS.add(json.loads(ln).get("key"))
        except Exception:
            pass


def before(state: Any, action: Any) -> Optional[dict]:
    """action 適用**前**に呼ぶ。 shadow 有効かつ入力が static-consistent なら
    (dump, encoded_action, card) の token を返す。 それ以外は None (post は no-op)。"""
    if not enabled() or _eng is None or _enc_fn is None:
        return None
    try:
        from engine.state_snapshot import full_dump, state_digest
        e = _enc_fn(state, action)
        if e.get("t") == "?":
            return None
        dump = json.dumps(full_dump(state))
        # 入力の静的効果が Rust recompute と一致していなければ (別軸) skip
        if _eng.recompute_static_digest(dump) != state_digest(state):
            return None
        return {"dump": dump, "action": json.dumps(e), "e": e, "card": _card_of(state, action, e)}
    except Exception:
        return None  # shadow の準備失敗は実ゲームに影響させない


def after(token: Optional[dict], state_after: Any) -> None:
    """action 適用**後**に呼ぶ。 Rust に後追いさせ、 MISMATCH なら記録に append。"""
    if token is None or _eng is None:
        return
    try:
        from engine.state_snapshot import state_digest
        if getattr(state_after, "pending_choice", None) is not None:
            return  # 人間 pick 待ちは比較対象外 (rust_parity_check と同じ)
        try:
            dr = _eng.apply_action_digest(token["dump"], token["action"])
        except Exception:
            return  # Rust が Err = bail (未対応、 誤りでない) → MISMATCH でない
        py = state_digest(state_after)
        if dr == py:
            return  # bit 一致 = 正常
        _record(token, state_after)
    except Exception:
        return  # shadow 比較の失敗は実ゲームに影響させない


def _card_of(state: Any, action: Any, e: dict) -> str:
    tp = state.players[state.turn_player_idx]
    hi = getattr(action, "hand_idx", None)
    if hi is not None and 0 <= hi < len(tp.hand):
        return tp.hand[hi].card_id
    for attr in ("source_iid", "target_iid"):
        iid = getattr(action, attr, None)
        if iid is not None:
            for ip in [tp.leader, *tp.characters, *tp.stages]:
                if getattr(ip, "instance_id", None) == iid:
                    return ip.card.card_id
    return "?"


def _record(token: dict, state_after: Any) -> None:
    """unique な MISMATCH を記録 (log 1 行 + 再現 dump ファイル)。"""
    global _SEEN_KEYS
    key = f"{token['e']['t']}:{token['card']}"
    if _SEEN_KEYS is None:
        _SEEN_KEYS = set()
    if key in _SEEN_KEYS:
        return  # 既知 (このプロセス or 過去 log) → 再 append しない
    _SEEN_KEYS.add(key)
    diffs, log, py_after = [], [], None
    try:
        from engine.state_snapshot import canonical_state, diff_canonical
        py_after = canonical_state(state_after)
        blob = json.loads(_eng.apply_action_blob(token["dump"], token["action"]))
        diffs = [list(d) for d in diff_canonical(py_after, blob)[:6]]
        log = [ln for ln in getattr(state_after, "log", [])[-8:]
               if any(x in ln for x in ("効果", "TRIGGER", "登場", "KO", "レスト", "ドロー",
                                        "差替", "公開", "付与", "hit", "atk", "cost"))][-6:]
    except Exception:
        pass
    safe_key = key.replace("/", "_").replace(":", "_")
    dump_file = f"db/rust_divergence/{safe_key}.json"
    try:
        _DUMP_DIR.mkdir(parents=True, exist_ok=True)
        # dump = 適用前 state / action = その action / py_after = 期待する Python 適用後 canonical。
        # fix agent は Rust 修正後に apply_action_blob(dump, action) == py_after を厳密照合できる
        # (ゲーム再生不要の高速 fix-verify ループ)。
        (_ROOT / dump_file).write_text(
            json.dumps({"dump": json.loads(token["dump"]), "action": token["e"],
                        "py_after": py_after}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        dump_file = None
    rec = {
        "key": key, "action": token["e"]["t"], "card": token["card"],
        "diffs": diffs, "log": log, "dump_file": dump_file,
        "first_seen": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
