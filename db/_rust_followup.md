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
- [x] 2026-08-07 `scripts/rust_mismatch_scan.py --seeds 1-30` (広域スキャン) で MISMATCH=3 検出
  - **根本原因 (3 件とも同型): when 発火の「enqueue して return」を Rust が省略し、 収集した do を
    その場で直接実行していた** (= `state.rust_resolving` guard 無し)。 Python は `trigger_on_ko` /
    `trigger_on_attack` / `fire_self_life_to_hand` / `_fire_opp_life_left_by_effect` いずれも
    enqueue のみ行って return し、 実際の do 実行は `resolve_triggers` の中 (resolving=true) で
    走る。 その間に do の中で登場した別カードの on_play は enqueue されるだけで後回しになる。
    Rust の `fire_on_ko`/`fire_on_attack` はこの guard が無かったため、 nested な
    `execute_on_play`/`execute_stage_on_play`(が呼ぶ `maybe_resolve()`) が即座に drain して
    inline 実行され、 外側の do-list の残りより先に発火していた。
    1. `fire_on_ko`: OP14-091 Mr.2・ボン・クレー の on_ko → Mr.5(ジェム) 登場
       (`play_from_hand_or_trash`) の手札走査ループが、 Mr.5 自身の on_play (draw2+discard1) の
       inline drain で書き換わった hand を読んでしまい、 手札 1 枚が消滅 (conservation 違反、
       盤面/トラッシュは一致するため一見発見しづらい)。
    2. `fire_on_attack` + `execute_stage_on_play` (STAGE on_play が enqueue を経由せず直接発火
       していた) + `fire_field_when` の inline 直呼び 3 箇所 (`play_from_hand`(then_life_to_hand) /
       `life_to_hand` primitive / 効果ダメージ経路): OP08-098 カルガラ leader の on_attack →
       play_from_hand(then_life_to_hand) で ワイパー登場 → アッパーヤード search→stage 登場 が、
       OP12-099 カルガラ(キャラ) の on_self_life_to_hand 反応 (draw1+self_draw_ban ×2) より **先に**
       発火し、 stage 自身の search_top_n がデッキを先食いして後続 draw の対象がズレる。
    3. `fire_opp_attack`: OP11-041 ナミ leader の opp_attack (discard_hand:1 cost) が別効果で
       「効果無効」 化されている時、 Python は cost 支払い自体は無条件で先に行い (once_per_turn
       マーク含む)、 無効化ゲートは **do 実行の直前** (`_execute_event`) でのみ効く。 Rust は
       cost 支払いフェーズの手前で無効化チェックしていたため cost ごと丸ごと skip していた
       (discard/once マークが漏れる)。
  - **追従済 (2026-08-07)**: `fire_on_ko` / `fire_on_attack` に `fire_life_trigger` と同じ
    `rust_resolving` save→true→do 実行→restore→(非 nested なら) `maybe_resolve()` の 4 点セットを
    追加。 `execute_stage_on_play` を character 版 `execute_on_play` と同じ enqueue+resolve に統一。
    `fire_field_when` の inline 直呼び 4 箇所を新設 helper `fire_self_life_to_hand` /
    `fire_opp_life_left_by_effect` (Python の同名 helper と 1:1 対応、 enqueue+単一 resolve) に
    置換。 `fire_opp_attack` の無効化チェックを cost 支払いフェーズから発火フェーズ (do 実行直前) に
    移設。 詳細は `rust_engine/CLAUDE.md` の落とし穴 checklist に追記。
  - 検証 = 対象 3 MISMATCH 個別 blob-diff で diff 0 件 / `rust_parity_check --assert` default
    2083 MISMATCH 0 / `rust_effect_smoke_parity --assert` 5083/0/0 (静的 527/0/0 含む) /
    `rust_parity_sweep --games 2` (329 デッキ) match 40730 bail 11 MISMATCH 0 (bail は既存の
    未実装 primitive のみ、 新規増加なし) / 広域スキャン再走 MISMATCH 0 / シャドウ記録 0 件 /
    フル `pytest tests/ -q` exit 0
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
