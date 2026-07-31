"""Rust シャドウ記録の自動チェック + fix 検証ヘルパ — 2026-07-31。

`engine/rust_shadow.py` が実ゲームから貯めた乖離記録 (`db/rust_divergence_log.jsonl`
+ 再現 dump `db/rust_divergence/*.json`) を **チェック / 表示 / fix 検証** する消費側。

= 自動修正ルーティン (skill onepiece-rust-parity-fix) の第 2 入力。 サンプル型 scan と違い、
  **実際に走ったゲームで起きた** 乖離なので優先度が高い + 厳密再現 dump 付き。

  .venv/bin/python scripts/rust_shadow_check.py            # 記録を表示 (agent 可読、 再現手順付き)
  .venv/bin/python scripts/rust_shadow_check.py --assert   # 記録が空でなければ exit 1 (CI 用)
  .venv/bin/python scripts/rust_shadow_check.py --verify db/rust_divergence/<key>.json
                                                           # 1 件を Rust に再適用し py_after と厳密照合
                                                           #   (fix + rebuild 後にこれで消えたか確認)
  .venv/bin/python scripts/rust_shadow_check.py --prune    # 既に一致する (=修正済) 記録を掃除
  .venv/bin/python scripts/rust_shadow_check.py --clear    # 記録全消去 (全 fix 完了後)

fix ループ: 記録を見る → 再現 dump で診断 (blob-diff) → Rust を Python に bit 一致 or bail →
rebuild → `--verify` で該当 dump が py_after に一致するか確認 → `--prune` で掃除 → commit。
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG = ROOT / "db" / "rust_divergence_log.jsonl"
DUMP_DIR = ROOT / "db" / "rust_divergence"


def load_log() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def verify(dump_file: str) -> bool:
    """再現 dump を Rust に再適用し、 記録時の期待 (py_after) と厳密一致するか。
    True = Rust が Python に一致 (= 修正済 or 元々一致) / False = まだ乖離 or bail。"""
    import optcg_engine as eng
    from engine.state_snapshot import diff_canonical
    # ⚠ Rust overlay (global OnceLock) を必ずロード。 未ロードだと全カード on_play が no-op になり
    #   false な「まだ乖離」を出す。 二重 load は OnceLock で無視。
    try:
        eng.load_overlay(str(ROOT / "db" / "card_effects.json"))
    except Exception:
        pass
    p = Path(dump_file)
    if not p.is_absolute():
        p = ROOT / dump_file
    payload = json.loads(p.read_text(encoding="utf-8"))
    py_after = payload.get("py_after")
    if py_after is None:
        print(f"  {dump_file}: py_after 無し (古い記録) — scan 経由で再検証を", file=sys.stderr)
        return False
    try:
        blob = json.loads(eng.apply_action_blob(json.dumps(payload["dump"]),
                                                json.dumps(payload["action"])))
    except Exception as exc:
        print(f"  {dump_file}: Rust bail ({exc}) — 明示 bail は誤りでない (=許容)")
        return True  # bail = 黙って間違えない を満たす → 記録から掃除してよい
    diffs = diff_canonical(py_after, blob)
    if not diffs:
        return True
    for d in diffs[:6]:
        print(f"    still-diff `{d[0]}`  py=`{d[1]}`  rust=`{d[2]}`")
    return False


def render(records: list[dict]) -> str:
    n = len(records)
    lines = [
        "# Rust シャドウ乖離記録 (実ゲームから自動収集)",
        "",
        "> `engine/rust_shadow.py` が ONEPIECE_RUST_SHADOW=1 の実ゲームで捕捉した",
        "> silent MISMATCH。 scan と違い **実際に走った局面** + **厳密再現 dump** 付き。",
        "> 消化 = skill `onepiece-rust-parity-fix` (diagnose→fix→verify→prune→commit)。",
        "",
        f"**合計: {n} 件**",
        "",
    ]
    if n == 0:
        lines.append("記録なし (実ゲームで Python↔Rust 完全一致)。")
        return "\n".join(lines) + "\n"
    for i, r in enumerate(records, 1):
        lines.append(f"## {i}. `{r['action']}` : `{r['card']}`")
        lines.append("")
        lines.append(f"- 再現 dump: `{r.get('dump_file')}`  (初回 {r.get('first_seen','?')[:19]})")
        if r.get("diffs"):
            lines.append("- field 差分 (path, python, rust):")
            for d in r["diffs"]:
                lines.append(f"    - `{d[0]}`  py=`{d[1]}`  rust=`{d[2]}`")
        if r.get("log"):
            lines.append("- 直前 log:")
            for ln in r["log"]:
                lines.append(f"    - {ln}")
        if r.get("dump_file"):
            lines.append(f"- 診断/検証: `python scripts/rust_shadow_check.py --verify {r['dump_file']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def prune() -> int:
    """既に Rust=Python (修正済 or bail) の記録を log + dump から掃除。 残件数を返す。"""
    records = load_log()
    kept = []
    for r in records:
        df = r.get("dump_file")
        if df and verify(df):
            p = ROOT / df
            if p.exists():
                p.unlink()
        else:
            kept.append(r)
    with LOG.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(kept)


def main():
    ap = argparse.ArgumentParser(description="Rust シャドウ乖離記録のチェック + fix 検証")
    ap.add_argument("--assert", dest="do_assert", action="store_true",
                    help="記録が空でなければ exit 1 (CI 用)")
    ap.add_argument("--verify", metavar="DUMP", help="再現 dump 1 件を Rust 再適用 → py_after 照合")
    ap.add_argument("--prune", action="store_true", help="既に一致する (修正済/bail) 記録を掃除")
    ap.add_argument("--clear", action="store_true", help="記録を全消去")
    args = ap.parse_args()

    if args.clear:
        if LOG.exists():
            LOG.unlink()
        for p in DUMP_DIR.glob("*.json"):
            p.unlink()
        print("記録を全消去")
        return

    if args.verify:
        ok = verify(args.verify)
        print("OK (Rust=Python or bail)" if ok else "NG (まだ乖離)")
        sys.exit(0 if ok else 1)

    if args.prune:
        remaining = prune()
        print(f"prune 完了 — 残 {remaining} 件")
        return

    records = load_log()
    print(render(records))
    if args.do_assert and records:
        print(f"FAIL: シャドウ乖離 {len(records)} 件 (実ゲームで Python↔Rust 同期崩れ)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
