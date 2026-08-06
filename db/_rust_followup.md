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
- [x] 2026-08-06 `scripts/rust_parity_sweep.py --games 2` (全カード合成デッキ 329 種) で MISMATCH=3 検出
  - **根本原因 (2 件、 同型): 静的効果ハンドラ `apply_static_primitive` の catch-all `_ => {}` が
    未実装 primitive を黙って no-op していた** (= execute_effect (動的 context) にしか実装が無い
    primitive が on_attached_don 静的発火経路で黙って落ちる。 「明示 bail すべきを黙って無視」型の
    MISMATCH で、 静的網羅 audit (scan_overlay_engine_gaps.py) は execute_effect 側しか見ておらず
    この穴を検出できていなかった)。
    1. `set_base_power_copy` (OP14-053 ビスタ「相手のターン中+手札7以下、 自分のパワー=リーダーの
       パワー」、 EndPhase 後の on_attached_don 再計算で base_power_override が py=5000/rust=None)。
    2. `set_ko_immune_timed` (ST14-009、 duration="turn" で ko_immune_until_turn_end)。 スイープでは
       未検出 (該当カード未踏) だが同型の穴として発見時に一緒に追従。
  - **追従済 (2026-08-06)**: `rust_engine/src/effects.rs::apply_static_primitive` に両 primitive を
    追加 (Python `engine/effects.py` の `set_base_power_copy`/`set_ko_immune_timed` 実装を移植、
    resolve_target 経由の from/to 解決 + duration 分岐は execute_effect 版と同ロジック)。
  - **もう 1 件: on_self_trigger_fired の除外漏れ** (AttackLeader:OP12-041_p1、 OP13-106 コニー
    「自分の【トリガー】発動時にブロッカーを得る」)。 Python (`trigger_lifecard_trigger`) は
    ライフトリガーの do 実行 **前** の場のインスタンス集合を snapshot し (`pre_trigger_field_iids`)、
    その【トリガー】自身が `play_self` で場に出したばかりのカードを on_self_trigger_fired の対象から
    除外する (公式 cardqa: 「いいえ、できません」)。 Rust の `fire_field_when` は呼び出し時点の盤面を
    毎回スキャンする実装だったため、 do 実行後 (= 新カードが場に出た後) に呼ぶと新カードも巻き込んで
    誤発火していた。 → `fire_field_when` を `snapshot_field_toks` + `fire_field_when_with_toks` に
    分離し、 `fire_life_trigger` が do 実行 **前** にタグ済トークンを保持して on_self_trigger_fired
    だけそれを使うように修正 (opp_event_or_trigger_fired は従来通り都度スキャンで変更なし、
    Python が only_iids を付けるのはこの 1 経路だけなので対称)。
  - 検証 = 対象 3 MISMATCH 個別 blob-diff で diff 0 件 / `rust_parity_check --assert` default
    2083・broad 6137 共に MISMATCH 0 / `rust_effect_smoke_parity --assert` 5083/0/0 (静的 527/0/0
    含む) / `rust_parity_sweep --games 2` (329 デッキ再走) match 40739 bail 1 MISMATCH 0
    static_skip 0 (旧 6 件も解消) / フル `pytest tests/ -q` exit 0
- [x] 2026-08-03T09:19:14Z `engine/` を変更したが `rust_engine/src/` は無変更
  - 変更ファイル: engine/effects.py 
  - commit: fix(engine): return_to_hand_multi に自陣キャラbounce分岐追加 (ST26-001 おそばマスク) (auto)
  - **追従済 (2026-08-03)**: rust_engine/src/effects.rs の return_to_hand_multi に
    `pi != opp_idx` 分岐を実装 (自陣キャラは置換を通さず 付与ドンをレストへ戻して手札へ)。
    従来は 「Python は opp.characters のみ処理」 というコメント付きで skip していた。
    検証 = ST26-001 の直接発火差分 match / 16 デッキ差分 MISMATCH 0 / 効果スモーク 100%
- [x] 2026-08-03T16:47:34Z `engine/` を変更したが `rust_engine/src/` は無変更
  - 変更ファイル: engine/effects.py 
  - commit: fix(engine): ST30-009 リトルオーズJr. replace_leave 条件漏れ 人間レビュー行きバグ修正 (auto)
  - **追従済 (2026-08-04)**: try_replace_ko の extra_cond 除外リスト (EXCL) に
    `target_cost_ge` / `target_truly_original_power_eq` を追加。 除外し忘れると victim を
    知らない eval_condition に回って **常に false** = 置換が不発になる。
    Python 側の除外リストと 15 種 1:1 で一致することを確認済。
    検証 = 16 デッキ差分 MISMATCH 0 / 直接発火差分 MISMATCH 0 / 効果スモーク 100%
