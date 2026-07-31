# Python↔Rust 差分 MISMATCH キュー (自動生成)

> `scripts/rust_mismatch_scan.py` が広域差分スイープで検出した **silent MISMATCH**
> (= Rust が黙って Python と違う状態を作った箇所) の一覧。 不変条件 = MISMATCH0
> (Rust は「Python と bit 一致」 か 「明示 bail」 の二択のみ)。 空なら「不一致なし」。
> 消化 = skill `onepiece-rust-parity-fix` の diagnose→fix→verify→commit ループ。
>   各 MISMATCH は Rust を Python 挙動に bit 一致 or 明示 bail に落として潰す。

**合計: 3 件** (scan seeds=18-37, 3 seeds × 全デッキ × 3 ペア構成)

## 1. `ActivateMain` : `OP14-079` (seed=18)

- 再現: cardrush_1385 vs cardrush_1478 / seed=18
- field 差分 (path, python, rust):
    - `.players[0].hand[0]`  py=`OP14-091`  rust=`OP14-120`
- 直前 log:
    - T15 P0:   起動メインコスト: 自KO Mr.2・ボン・クレー(ベンサム)
    - T15 P0:   効果: 手札から登場 → Mr.5(ジェム)
    - T15 P0:   効果: ドロー 2
    - T15 P0:   効果: 自手札 1 枚 トラッシュ
    - T15 P0:   効果: コスト-10 (turn) → ['ニコ・ロビン']
    - T15 P0:   効果: self mill 2 → ['高級仕立パッチ★ワーク', 'ミス・バレンタイン(ミキータ)']

## 2. `AttackLeader` : `?` (seed=37)

- 再現: cardrush_1491 vs tcgportal_op13_luffy / seed=37
- field 差分 (path, python, rust):
    - `.players[1].chara_ko_taken_this_turn`  py=`1`  rust=`0`
    - `.players[1].characters[len]`  py=`2`  rust=`3`
    - `.players[1].characters[1]._act_used`  py=`True`  rust=`False`
    - `.players[1].characters[1].card`  py=`OP10-030`  rust=`OP13-031`
    - `.players[1].characters[1].rested`  py=`True`  rust=`False`
    - `.players[1].characters[1].static_granted_keywords[len]`  py=`0`  rust=`1`
- 直前 log:
    - T13 P0:   cost: キッド＆キラー をトラッシュに置く
    - T13 P0:   効果: パワー+2000 → ['ジュラキュール・ミホーク']
    - T13 P0: atk宣言: シャンクス(P=12000) -> ジュラキュール・ミホーク
    - T13 P0: atk: シャンクス(P=12000) -> トラファルガー・ロー(P=6000)
    - T13 P0:   KO: トラファルガー・ロー

## 3. `PlayCharacter` : `OP14-084` (seed=31)

- 再現: pros02_zoro_g vs cardrush_1385 / seed=31
- field 差分 (path, python, rust):
    - `.players[0].trash[24]`  py=`OP14-088`  rust=`OP05-094`
    - `.players[0].trash[25]`  py=`OP05-094`  rust=`OP14-083`
    - `.players[0].trash[26]`  py=`OP14-083`  rust=`OP14-120`
    - `.players[0].trash[27]`  py=`OP14-120`  rust=`OP14-088`
- 直前 log:
    - T9 P0: play: ミス・オールサンデー (cost 7 pay 7)
    - T9 P0:   効果: トラッシュから登場 → ミス・バレンタイン(ミキータ)
    - T9 P0:   差替 (3-7-6-1): ミス・メリークリスマス(ドロフィー) をトラッシュへ (KO ではないため【KO時】不発動)
    - T9 P0:   効果: トラッシュから登場 → ミス・ゴールデンウィーク(マリアンヌ)
    - T9 P0:   効果: search_top_n → 手札
    - T9 P0:   効果: search_top_n 残り3枚 → トラッシュ

