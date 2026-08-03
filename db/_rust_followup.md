# Rust 追従待ちバックログ (自動生成 + 手動)

> `scripts/effect_bugfix_gate.sh` が **`engine/` を変更したのに `rust_engine/src/` が無変更** の
> commit を検出したら 1 行追記する。 Python engine の挙動変更に Rust ミラーが追従していない可能性
> (= Rust が黙って別挙動になる) を、 差分ハーネス (MISMATCH) が拾えない場合でも残すための受け皿。
>
> 消化: skill [[onepiece-rust-parity-fix]] / cron `optcg-rust-parity-fix`、 もしくは session で
> 「Rust の追従やって」。 検証は下の 3 gate:
>
> ```bash
> .venv/bin/pytest tests/test_rust_overlay_coverage.py -q   # ビルド不要 (静的網羅)
> .venv/bin/pytest tests/test_rust_parity.py -q             # 要ビルド (MISMATCH + self-play bail)
> .venv/bin/python scripts/scan_overlay_engine_gaps.py      # 詳細レポート
> ```

現在追従待ちなし ✅
- [ ] 2026-08-03T09:19:14Z `engine/` を変更したが `rust_engine/src/` は無変更
  - 変更ファイル: engine/effects.py 
  - commit 予定: fix(engine): return_to_hand_multi に自陣キャラbounce分岐追加 (ST26-001 おそばマスク) (auto)
  - 対応: Rust を同じ挙動に追従させる (skill onepiece-rust-parity-fix)。
    検証 = `pytest tests/test_rust_parity.py tests/test_rust_overlay_coverage.py -q`
