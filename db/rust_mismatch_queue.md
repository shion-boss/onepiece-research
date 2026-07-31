# Python↔Rust 差分 MISMATCH キュー (自動生成)

> `scripts/rust_mismatch_scan.py` が広域差分スイープで検出した **silent MISMATCH**
> (= Rust が黙って Python と違う状態を作った箇所) の一覧。 不変条件 = MISMATCH0
> (Rust は「Python と bit 一致」 か 「明示 bail」 の二択のみ)。 空なら「不一致なし」。
> 消化 = skill `onepiece-rust-parity-fix` の diagnose→fix→verify→commit ループ。
>   各 MISMATCH は Rust を Python 挙動に bit 一致 or 明示 bail に落として潰す。

**合計: 0 件** (scan seeds=1-30, 30 seeds × 全デッキ × 3 ペア構成)

不一致なし (この広域サンプルでは Python↔Rust 完全一致)。
