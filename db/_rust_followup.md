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
- [x] 2026-08-03T09:19:14Z `engine/` を変更したが `rust_engine/src/` は無変更
  - 変更ファイル: engine/effects.py 
  - commit: fix(engine): return_to_hand_multi に自陣キャラbounce分岐追加 (ST26-001 おそばマスク) (auto)
  - **追従済 (2026-08-03)**: rust_engine/src/effects.rs の return_to_hand_multi に
    `pi != opp_idx` 分岐を実装 (自陣キャラは置換を通さず 付与ドンをレストへ戻して手札へ)。
    従来は 「Python は opp.characters のみ処理」 というコメント付きで skip していた。
    検証 = ST26-001 の直接発火差分 match / 16 デッキ差分 MISMATCH 0 / 効果スモーク 100%
