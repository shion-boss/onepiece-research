# Rust engine — Python 準拠 self-play 高速ミラー

> Python engine (`engine/`) が **正 (公式準拠 100% 検証済)**。 Rust (`rust_engine/`、 PyO3 module
> `optcg_engine`) は self-play を 30-100x 高速化するための**忠実ミラー**。 配備 AI・人間対戦・API は
> Python のまま。 詳細背景は memory `project_rust_engine.md`。

## 現状 (2026-08-10): Python との bit 一致を **効果カード全数** で証明済 + **全ハーネス bail 0**

| 検証 | 結果 |
|---|---|
| 差分ハーネス 16 デッキ (`rust_parity_check --assert`) | match 2,115 / **bail 0** / **MISMATCH 0** / static_skip 0 / py_skip 0 |
| 差分 全カード合成デッキ 329 (`rust_parity_sweep`) | match 40,708 / **bail 0** / **MISMATCH 0 / PANIC 0** |
| 効果差分 3 パス (`rust_effect_smoke_parity --assert`) | 直接発火 3,909 + 静的 532 + 置換 108 / bail 0 / **MISMATCH 0** |
| **効果ありカード 4,262 枚の bit 一致証明** | **100%** |
| Rust 単独掃引 (`rust_fullsweep`、 60 デッキ / 360 game) | action 1,505,877 中 **bail 0**、 保存則違反 0、 中断 0 |
| overlay 網羅 | primitive / condition / when / target spec が **全て実装済 (未対応 0)** |

### ⭐ 「意図的な」 bail 2 種を **実装で解消** (2026-08-10)

どちらも公式 Q&A 起点で Python に 「同時性 / 本人参加」 の意味論を入れた結果、 逐次処理の Rust が
追従できず bail していた箇所。 **Rust に同じ意味論を実装して bail 0 にした**。

1. **同時離脱バッチ** (`SIMULTANEOUS_LEAVE_PRIMS` + `state.rust_leave_batch_holders/paid`)
   — Python `_LeaveBatch` の移植。 ① 置換 holder は **バッチ開始時の盤面** から決める
   (順序非依存、 cardqa_op_10 / OP10-032 たしぎ) ② 同じ holder の置換コストは **1 回だけ**
   (cardqa_op_15 / OP15-090 ペローナ)。 holder はトークンで追い、 `try_replace_ko` が
   スナップショットを走査する。 従来の `board_has_replace_holder` 一律 bail は撤去。
   ⚠ **残る bail は 1 種類だけ**: holder 自身がバッチ内で既に場を離れた場合
   (Python は object 参照で場外 holder も扱えるが Rust は場外 InPlay を持たない) → 明示 Err。
2. **`on_self_chara_leave_by_self_effect` の 「離脱本人」 発動** (`note_public_departure` +
   `fire_leave_by_self_effect`) — 公式 cardqa_op_08 (OP08-046 シャクヤク): 場を離れた本人も
   **行き先が公開領域 (トラッシュ / 表向きライフ)** なら発動できる。 Python `_note_public_departure`
   の台帳 (`state.rust_departed_to_public`) を移植し、 場のカードの反応 + 本人の反応を発火する。
   記録サイトは Python と 1:1 (`trash_self` コスト / `trash_all_self_chara` / `ko_self_chara` /
   `chara_to_trash` / `chara_to_self_life` の face_up)。
   ⚠ 「キャラが」 の文面なので **CHARACTER のみ** 記録する (STAGE は対象外)。

### ⭐【ターン終了時】/【ターン開始時】も Python と同じ 2 相モデルに (2026-08-10、 解消済)

Python `trigger_end_of_turn` は **① 両陣営を走査して コストを払い、 カード単位でイベントを
enqueue → ② 最後に 1 回ドレインして do を実行** の 2 相。 Rust は カードごとに
「コスト → do」 を **その場で** 実行していたので、

- 先行カードの **do** が 後続カードの **コスト判定 (payability / 条件)** より先に走る (Python は後)
- do が誘発した効果と 後続カードの end_of_turn の相対順序

の 2 点で乖離しうる (= 公式 8-4-1-3〜5 「コスト支払いは発動、 do は解決」 の系)。
→ `fire_end_of_turn_batch` (effects.rs) で Python と同じ 2 相にした。 ターン開始時も同型なので
`enqueue_turn_start` で 両陣営 enqueue → 1 回ドレインに揃えた (rules.rs)。

⚠ **EOT cost の `ko_self_with_filter` は明示 bail**。 Python は `trigger_on_ko` (= enqueue +
即ドレイン) なので 「既に積んだカードイベントごと解決される」 が、 Rust の on_ko は inline 発火で
キューを持たず同順を作れない。 overlay 全走査で **該当カード 0 枚** (cost 付き EOT は `pay_don` の
OP09-068 / OP16-073 のみ) なので実質デッドコード。

**⭐ bail 0 到達 (2026-08-04)**。 最後まで残っていた 2 primitive を実装した:
- `schedule_self_return_to_deck_bottom_at_battle_end` (OP02-064 ボン・クレー)
- `reveal_hand_play_split` (OP10-058 レベッカ)

⚠ 前者の実装中に **Python 側のバグ** も見つかった: 「このバトル終了時」 の flush が
`AttackCharacter` 分岐にだけ書かれており、 **リーダーへアタックした場合フラグが残留** して
後続の別バトル終了時に誤爆しうる状態だった。 公式は 「このバトル終了時」 = リーダー戦もバトル
なので、 バトル終了フック本体 (`game.py:_reset_battle_buffs`、 公式 7-1-5-1) に移して全経路を
カバーした。 Rust も同じ位置 (`rules.rs:reset_battle_buffs`) で flush する。

**証明範囲の 3 パス** (自己検査でなく **Python との bit 比較**):
1. 直接発火 — 効果の `do` を両エンジンで実行して digest 比較。 発動元が LEADER の時は
   `src_idx=-3` (= `Slot::Leader`) を渡す。
2. 静的 — `on_attached_don` / `in_hand` / `setup_modifier` は発火でなく盤面からの再計算なので
   Python `evaluate_static_effects` vs Rust `recompute_static_digest` で比較。
3. 置換 — `replace_ko` / `replace_leave` / `replace_rest` は `try_replace_ko` を両側で呼んで比較。

⚠ **計器の穴に注意**: 差分ハーネスは 「静的効果が食い違う局面」 と 「Python が pending_choice /
例外で止まった局面」 で比較を飛ばす。 飛ばすこと自体は妥当だが **数えないと乖離が MISMATCH にも
bail にも出ず match 数が減るだけで不可視**。 `static_skip` / `py_skip` として計上している
(現状どちらも 0)。 新しい skip パスを足す時も必ず数えること。

## self-play 速度 (2026-08-04 実測、 cardrush_1342 ミラー)

| | ms/game |
|---|---|
| Rust `self_play` greedy | **48.8** |
| Rust `self_play` beam(8,12) | 576.4 |
| Python `run_matchup` greedy (harness 込み) | 226.4 |

= greedy で約 **4.6x**。 Python 側は harness のオーバーヘッドを含むので下限値。

**アタッカーの離場**: on_attack/opp_attack の解決中にアタッカー自身が場を離れても、 Python は
attacker を **object 参照** で持つのでバトルを続行する。 Rust は位置 index なので、 離場直前の
`InPlay` を `state.rust_detached_src` (cost 支払い / do ループ / optional_cost_then) と
`atk_pre_opp` (opp_attack 発火前) に退避し、 タグで見失った時にそれで解決する。

**発動元 (self_inplay) 追跡の一意トークン**: Python は `self_inplay` を object 参照で持つので盤面が
動いても発動元を見失わない。 Rust は位置 index なので `InPlay.rust_src_tag: Vec<u64>` (serde skip) に
一意トークンを打ち、 各段で `find_tagged` で引き直す (`tag_src`/`find_tagged`/`peek_tagged`)。
⚠ **スタック (Vec) でないと入れ子で壊れる** — do 内の `optional_cost_then` 等で内側の `tag_src` が
外側のトークンを上書きし、 外側が発動元を見失う。 適用箇所: optional_cost_then の cost 後 /
when-effect・activate_main の do ループ各段 / アタッカー / ブロッカー / fire_field_when の走査 /
pending trigger (drain 時の発火元復元) / ko・return_to_hand 系の逐次 victim 処理。

**iid キーの【ターン1回】は Python 側に canonical mirror を足して追跡**: `once_per_turn_used`
(動的属性・digest 対象外) だけだと Rust から見えないので、 `_FIELD_WHEN_ONCE_MIRROR` に
`on_play`/`on_block`/`end_of_turn`/`opp_end_of_turn`/`opp_event_or_trigger_fired` を追加し、
`on_self_battled` / `on_self_battle_ko` / `on_self_draw_non_draw_phase` / end_of_turn cost /
ライフトリガー (card_id キー) でも `mark_event_once` / `once_shared_used` へ並行記録する。
**Python の判定ロジックは変えていない (= 挙動不変)。 記録が増えるだけ**。

## 不変条件 (絶対に守る)

**Rust は任意の action に対し「Python と bit 一致」か「Err で明示 bail」の二択のみ。 黙って間違った状態を作らない
(= MISMATCH=0)。** bail は「未実装なので降参」であり誤りではない。 差分検証がこれを保証する。

## ⭐ 選択列挙 ON (choice_enumeration) のパリティ (2026-08-21 に MISMATCH=0 到達)

学習は **選択込みの self-play** で回すので、 列挙 ON でも一致を証明しないと
「公式準拠を検証した Python と違う盤面を学ぶ」 事故になる。 専用ハーネスは
`scripts/rust_choice_parity.py` (件数) と `scripts/rust_choice_diag.py` (原因分類)。
`pytest tests/test_rust_parity.py::test_rust_choice_enumeration_no_mismatch` が CI ガード。

| 検証 | 結果 |
|---|---|
| 列挙 ON 差分 6 game | match 283 / bail 67 / **MISMATCH 0** |
| 列挙 ON 差分 16 game (別 seed) | match 727 / bail 160 / **MISMATCH 0** |

### ⚠ 「MISMATCH 0」 ≠ 「学習に使える」 — 候補 bail 率を必ず併せて見る (2026-08-22)

`scripts/rust_choice_selfplay_probe.py` で Rust self-play を実測した結果:

| | 完走率 | **候補 action の bail 率** | ms/game |
|---|---|---|---|
| 列挙 **OFF** | 100% | **0.00%** (24 / 3,630,932) | 4,085 |
| 列挙 **ON** | 100% | **27.1%** (12,705 / 46,814) | 143 |

⭐ **完走率だけ見ると罠**。 方策 (`greedy_action` / `defended_move`) は **bail した候補を
黙って捨てる** (`is_err() → continue`) ので、 試合は最後まで進むが
**Rust が実行できない手を避けた結果の対局** になる。 bail の過半が `defense |` =
防御候補なので、 このまま学習を回すと **「無防御への静かな回帰」** を教えてしまう。
= 列挙 ON はまだ学習データ生成に使えない (OFF は 0.00% なので問題なし)。

bail の内訳 (= 移植の優先順位。 `eng.reset_coverage_stats(True)` + `coverage_stats()`):
`optional_discard_hand_for_battle_buff` 約 11% / 発動コストの選択 約 7% /
ResolveChoice の残り do・`redirect_attack`・`on_self_rested`・`attach_rested_don` 各 1-2%。

⚠ `optional_discard_hand_for_battle_buff` は **移植済だが denylist に戻してある**。
解禁すると `fire_self_main` (効果コピー) 連鎖で Python が 「前段の選択を上書きして捨てる」
挙動になり MISMATCH が出た。 **Python 側の choice 上書きセマンティクスを確定させるのが先**。

### 中断・再開のモデル (Python の 2 段構造を写すこと)

- 選択サイトは `note_choice_suspend` で **フラグ + 候補** を残して no-op で返る。
- do 配列ループの `suspend_if_choice` が ① フラグが立っていれば `PendingChoice` を確定し
  **フラグを降ろす** ② 既に確定済 (内側) なら **上書きせず true を返すだけ**。
  - ⚠ フラグを立てっぱなしにすると後続の選択サイトが全部素通りする。 Python は
    「選択が立っている」 状態を `state.pending_choice` で持ち、 **後の選択サイトが上書きする**。
  - ⚠ 逆に毎階層で作り直すと、 候補を消費済の外側が **候補ゼロの幽霊選択** で上書きし、
    ResolveChoice が同じ primitive を無限に再実行する。
- `execute_card_effects` の bundle ループは `pending_choice.is_some()` で break
  (Python `_execute_event` の early return と同形)。
- **深い所からの bail は `note_choice_bail`** (thread-local) で `apply_action` の出口へ運ぶ。
  `&mut GameState` しか持てない場所 (場 5 枚差し替え等) から明示 bail を出すため。

### 落とし穴 (この 4 件で MISMATCH 62 → 0)

1. **Python の 「中断するか」 条件を近似しない**。 `search_top_n` は 「filter 一致が 1 枚以上」
   で中断し候補は **見た N 枚全部**。 起動メインの発動コストは種別ごとに条件がバラバラで、
   候補 1 件でも訊くものがある (`discard_hand` は手札 1 枚でも / `rest_own_card` は
   リーダーとステージも数える)。
2. **再開 (replay) は Python の `resolve_pending_choice` を写す** — auto 経路と違う。
   `search_top_n` の human 経路は STAGE を登場させず手札へ / `top_or_bottom` は一律デッキ底 /
   `known_bottom_card_ids` を触らない。
3. **候補の並び順は Python と同じ 「盤面順」**。 Python は `_maybe_request_target_pick` に
   **sort 前** の候補を渡し、 AI 評価の sort はその後。 Rust が先に sort していたため
   「候補数は同じなのに k 番目が別のカード」 になっていた (`board_order`)。
4. **注入した picks (`FORCED_PICKS`) は必ず使い切って捨てる** (Drop guard)。 残ると次の
   action の別 primitive が **他人の picks を replay と誤認** して選択サイトを素通りする。

## Python ↔ Rust を同期させながら更新する手順 (重要)

Python engine (特に `engine/effects.py` / `engine/game.py` / `engine/core.py`) を変更したら:

1. Rust を再ビルド: `.venv/bin/maturin develop --manifest-path rust_engine/Cargo.toml`
2. パリティ確認: `python scripts/rust_parity_check.py --assert`
   - **MISMATCH>0** が出たら Python 変更に Rust が追従できていない。 → Rust 側 (下記マップ) を同じ挙動に修正するか、
     その効果を Err bail にする (どちらも「黙って間違えない」を維持)。 MISMATCH=0 に戻すまで完了としない。
   - bail が増えるのは OK (新機能=Rust 未実装)。 後で追従実装すればよい。
3. `pytest tests/test_rust_parity.py` が CI/ローカルで小規模版を自動実行 (MISMATCH=0 を assert)。

### canonical state を変える変更に注意

Python dataclass に **field を追加/削除** したら、 Rust `state.rs` の対応 struct field も追加/削除する
(serde rename/default で吸収)。 動的属性 (setattr) は state_snapshot._EXCLUDE で digest 除外されるため
Rust から見えない → **ターンを跨いで持続する状態は必ず canonical field 化する** (例: `_act_used` /
`attack_once_used` の InPlay field 昇格)。 mutable な list/set field は Rust InPlay の `__deepcopy__` 相当
(state.rs) に明示 copy を足す (fast_clone のクロス汚染防止)。

RNG 依存効果は `rng.rs` (MT19937、 CPython `random` の bit 再現) を使い、 `full_dump` の `_rng_state` から
復元する (digest には rng を含めない = _EXCLUDE)。

### 実装済みの落とし穴 (効果追従時に踏みやすい非自明パターン)

過去に MISMATCH / 追従漏れを起こした「一見無害だが digest に効く」挙動。 新 primitive を書く時に確認する:

- **when 発火は Python では原則すべて「enqueue して return」、 do 実行は resolve_triggers の中
  (resolving=true) で走る** (`trigger_on_ko` / `trigger_on_attack` / `trigger_on_play` /
  `fire_self_life_to_hand` / `_fire_opp_life_left_by_effect` 等、 いずれも docstring に「〜を
  enqueue」と明記されている)。 Rust で `fire_on_ko` / `fire_on_attack` のように **収集した do を
  その場で直接 `execute_effect`/`fire_gated_do` する実装** は、 `state.rust_resolving` を
  save→true→(do 実行)→restore→(nested でなければ) `maybe_resolve()` の 4 点セットで包まないと、
  do の中でネストして起きる別カードの登場 (`execute_on_play`/`execute_stage_on_play` が
  enqueue+`maybe_resolve()` を呼ぶ) が **即座に drain (inline 実行)** され、 外側の do-list の
  残り (draw/ban 等) より **先に** 発火する。 これは field-only の diff (digest 不一致) ではなく
  **手札から特定カードが消える/増える** ような conservation 違反として現れることが多く、 位置
  index 起因の #1 と誤診しやすい (2026-08-07、 OP14-091 Mr.2 ボン・クレー の on_ko →
  play_from_hand_or_trash の手札走査ループが nested execute_on_play の inline drain で 1 枚喪失、
  OP08-098 カルガラ leader の on_attack → play_from_hand(then_life_to_hand) → wyper on_play →
  stage on_play が draw/block_self_draw_turn より先に走りデッキを消費、 の 2 件で発覚)。
  `fire_life_trigger` は既にこのパターンで正しく実装されているので、 新しい when 発火経路を書く
  ときは **必ずそれを雛形にする**。
- **【起動メイン】の発動コストで誘発したトリガーは 「本体の do の後」 に発火する** (公式
  8-4-1-3〜8-4-1-5 + cardqa_op_14 / OP14-080、 2026-08-09)。 Python は
  `_cost_trigger_buffer` (= 支払い中の enqueue を退避 → 本体 enqueue → キューへ流す)。
  Rust は **キューを介さず** `DeferredCostTrigger` (`fire_activate_main` 内) —
  支払い時に反応集合 (`snapshot_field_toks`) を snapshot し、 do-list の後に発火する。
  ⚠ **キューに積む実装は 5 回失敗している**: Rust の `fire_field_when` は **drain 時に場を
  走査** するので、 Python の 「enqueue 時にカード単位でスナップショット」 と粒度が食い違い、
  cost → do → drain の間に盤面が動くと反応集合がズレる。 deferred snapshot はその差の
  発生源自体を消す。 併せて **`fire_activate_main` の do-list は `rust_resolving = true` で
  実行する** (Python は本体を enqueue して resolve_triggers の中で回す = do 中の誘発は
  キュー末尾)。 KO の記録 (被KO数 / 効果無効 gate) は **即時**、 do だけ deferred
  (`note_ko_and_should_fire` / `run_on_ko_effects` の 2 段分離)。
- **`enqueue_field_when` は 「反応するカード」 を enqueue 時に **カード単位で** 積む** (2026-08-10)。
  Python `_enqueue_field_when` と同じ粒度。 以前は 1 件だけ積んで **drain 時に場を走査** していたため、
  enqueue と drain の間に盤面が動くと **反応集合そのもの** が食い違った。
  ⚠ この変更に伴い `execute_on_play` の `on_self_chara_played` / `on_opp_chara_played` は
  **`enqueue_trigger` (= 登場カードを card_id に載せた marker) ではなく `enqueue_field_when`** で
  積む。 marker のままだと 「登場カード自身の効果だけ」 を発火し、 場の反応カード (例: リーダー
  OP14-041 「相手のターン中 自分のキャラ登場時 1ドロー」) が丸ごと落ちる。
- **when 発火の合間の drain を省くと 「本体 → reactive」 の順が崩れる** (2026-08-10)。 Python の
  `trigger_lifecard_trigger` は **① トリガー本体を enqueue → `_maybe_resolve` で解決し切る →
  ② reactive (opp_event_or_trigger_fired / opp_trigger_fired / on_self_trigger_fired) を 1 つ積む
  ごとに drain** という形。 Rust は本体を `rust_resolving = true` で **inline** 実行するので、
  本体の登場が誘発した `on_play` はキューに積まれたまま残り、 呼出側が最後にまとめて drain すると
  **reactive より後** に走る。 → `drain_if_outer(state, prev_resolving)` を 本体の後と各 reactive の
  後に挟む。 発覚例: OP05-106 シュラ【トリガー】(デッキ上5枚を見て1枚手札・残りをデッキ下) の
  デッキ操作が OP05-109 パガヤ (【トリガー】発動時に2ドロー) の **後** に走り、 **引くカードが
  変わった**。 新しい when 発火経路を書く時は 「Python が `_maybe_resolve` を呼んでいる位置」 を
  そのまま drain 位置に写すこと。
- **canonical field を足したら 「リセット側」 も対で写す** (2026-08-10)。 `*_base_power_override` に
  `*_is_original` (公式 4-9-2-1 の 「元々のパワーを◯◯にする」 か) を足した時、 Rust は override 本体
  だけ None に戻して フラグを落とし忘れ、 **次のターンに 「元々のパワー」 判定だけが残留** した
  (`rules.rs` の turn reset / next_turn / next_opp_turn_end の 3 系統)。 set 側 4 箇所を写しても
  clear 側を忘れると EndPhase で MISMATCH。 grep は **set と clear の両方** で行う。
- **`find_tagged` は タグを消費する**。 1 枚のカードの複数効果を回すループや 複数 index を回す
  解決では **`peek_tagged` (非消費) を使い、 回収は最後に 1 回**。 消費すると 2 つ目以降が
  `Slot::Detached` になり、 効果が **黙って不発** になる (2026-08-10 に EOT 2 相化で踏んだ)。
- **field-when の「発火元カード無し」ヘルパーも inline 直呼びしない**: `fire_field_when(state, idx, when)`
  は即時スキャン+発火 (トップレベルから呼ぶ分には Python の enqueue+即 resolve と等価だが、
  ネストした do-list の中から呼ぶと上記と同じ理由で inline 発火してしまう)。 「自分の効果でライフが
  手札/トラッシュへ移動した」 系 (`life_to_hand` primitive / `play_from_hand` の `then_life_to_hand` /
  `mill_opp_life_to_*` / 効果ダメージ経路) は Python がすべて `fire_self_life_to_hand` /
  `_fire_opp_life_left_by_effect` という named helper (= enqueue+単一 `_maybe_resolve`) を経由する。
  Rust 側にも同名の helper (`fire_self_life_to_hand` / `fire_opp_life_left_by_effect`、 effects.rs) を
  用意したので、 on_self_life_to_hand / on_opp_life_taken / on_self_life_to_trash を発火する新しい
  primitive はこれらを使う (直接 `fire_field_when` を呼ばない)。
- **`trigger_on_play` は category 問わず `last_self_chara_played_card` を更新** (effects.py:10661)。 STAGE 登場
  (play_stage_from_hand / play_self の stage 版 / 通常 PlayStage) でも set が要る。 `on_self/opp_chara_played`
  の *発火* だけが CHARACTER 限定。 これを漏らすと stage 登場効果カード (例: OP08-110) が MISMATCH。
- **登場 primitive の hand 除去タイミング**: `play_from_hand` / `play_from_trash` / `play_self` は pop-first
  (登場前に zone から除去) だが、 **`play_from_hand_or_trash` は loop 末尾で hand を除去** (= 登場カードの
  on_play が hand をまだ観測する)。 Rust で pop-first に統一すると on_play が hand を読む効果でズレる →
  `play_from_hand_or_trash` は execute_on_play が観測を持つ場合 (登場カードに on_play / 場に
  on_self/opp_chara_played) は bail、 no-op 保証時のみ inline (effects.rs 参照)。
- **登場系の `played_from_trash`**: `play_from_trash` は True を立てるが **`play_from_hand_or_trash` は trash
  由来でも False** (Python 準拠) → `last_self_chara_played_from_trash` に効く。
- **`play_self` の消費判定は object identity** (`_c is taken`、 game.py:2133)。 Rust `CardDef` は値型で identity
  不可 → `card_id` 近似 + **trash に同名重複がある時は bail** (rules.rs、 correctness 保証)。 発動元 card は
  transient `current_source_card_id` (state.rs、 `#[serde(skip)]`、 action 境界で None) で `fire_life_trigger`
  が set/restore する。
- **source-gone (life-trigger / on_ko / KO時ライフ) の allow-list**: `fire_life_trigger` / `fire_on_ko` は
  `src=Slot::Leader` placeholder で発火するため、 player-level (src 不使用) primitive だけを allow-list に
  足す。 target/self 参照する prim を入れると placeholder=leader で誤解決 → MISMATCH。
- **once_per_turn の canonical 化**: top-level `once_per_turn` の発動済みは `once_per_turn_used` (set、
  `iid:` 依存で _EXCLUDE) では Rust から見えない。 field-when 系は InPlay の `event_once_used` field に昇格
  (`_FIELD_WHEN_ONCE_MIRROR`、 refresh で clear) して digest に載せる。
- **公式の語の書き分けは 「入口で正規化」 して 1 箇所で決める** (2026-08-04):
  - 素の 「コストN以下」 = **現在コスト** (`InPlay::base_cost()`) / 「元々のコストN以下」 =
    **印刷コスト** (`CardDef.cost`)。 `resolve_target` の入口で `_truly_original_cost_` の
    有無を見て `use_printed_cost` を決め、 以降は `cost_of(ip)` を通す。 **分岐ごとに書くと
    必ず漏れる**。
  - パワーも同型: 素の 「パワーN以下」 = **現在パワー** (`InPlay::power()`、 ドン付与/バフ込み) /
    「元々のパワー」 = **印刷パワー** (`CardDef.power`)。 入口で `_truly_original_power_` を畳んで
    `power_of(ip)` に集約。 置換条件 (`replace_ko_match`) は `target_{cost,power}_{le,ge}` =
    現在値 / `target_truly_original_*` = 印刷値。 ⚠ Rust の `replace_ko_match` は CardDef しか
    受け取っていなかったので **現在値を引数で渡す** ようにした (victim_cur_cost/victim_cur_power)。
  - 盤面 (InPlay) に対する filter は `matches_filter_ip(ip, filt)` を使う。 `matches_filter`
    (CardDef のみ) は印刷コスト固定なので、 盤面に使うと同じ裁定が *経路によって効いたり
    効かなかったり* する。 判定基準 = **`X.card` を渡していたら InPlay = ip 版に直す**。
  - 「相手の」 が無い 「キャラ1枚まで」 は **両陣営**。 `one_character_either_*` /
    `one_inplay_either_filtered` は **相手側を `opp_value` 降順で 1 枚、 居なければ自陣の先頭**
    (Python `_either_pick_one` と同順)。 ⚠ 両陣営を混ぜて power 降順にすると高パワーの
    自キャラを巻き込む (OP10-046 キュロス自己バウンス事故と同型)。
- **`matches_filter` の未知キー方針が Python と逆**: Python の `_matches_filter` は未知キーを
  **黙って無視 (= 制限なし)**、 Rust は `_ => return false` で **不一致扱い (安全側)**。 そのため
  Python 側で 「filter に書いたが _matches_filter が読まないキー」 (= `rested` / `active` /
  `no_effect` / `truly_original_power_*` 等) を target spec 側で honor する実装を足したら、
  **Rust は同じキーを filter から strip してから `matches_filter` に渡す**。 strip し忘れると
  Rust だけ 0 対象になり MISMATCH。 逆に allow-list に足すだけだと 「Python は無視・Rust も無視」
  で 制限が両方消える。 どちらが正かは 公式テキスト で決める。

## ツール

| 用途 | コマンド |
|---|---|
| 差分 summary + bail 内訳 | `python scripts/rust_parity_check.py` |
| CI/pre-commit ガード | `python scripts/rust_parity_check.py --assert` (MISMATCH>0 で exit 1) |
| standalone 完走の壁 観測 | `python scripts/rust_parity_check.py --wall` |
| pytest 自動ガード | `pytest tests/test_rust_parity.py` |
| **選択列挙 ON の差分** | `python scripts/rust_choice_parity.py --games 6 [--assert]` |
| **同 原因分類 (MISMATCH の切り分け)** | `python scripts/rust_choice_diag.py --games 6 --show 10 --check-off` |
| 乖離局面を単体で ON/OFF 比較 | `rust_choice_diag.py --dump <dir>` → `rust_choice_probe.py <dir>` |
| **全カード合成デッキ掃引 (最広)** | `python scripts/rust_parity_sweep.py [--assert]` (~4 分、 CI 済) |
| 掃引の MISMATCH を zone 単位で見る | `python scripts/rust_sweep_mismatch_diag.py` |
| **学習に使えるか (候補 bail 率)** | `python scripts/rust_choice_selfplay_probe.py --games 40 [--no-choice]` |

⚠ **16 デッキ版だけでは足りない**。 メタ 16 デッキは効果カードの 4.2% しか通らず、
2026-08-22 に見つかった 2 件はどちらも **329 合成デッキ掃引でしか出なかった**
(16 デッキ版・効果スモーク・列挙 ON 差分は **すべて緑のまま**)。

## Rust ソースマップ (機能追加時の追従先)

- `src/state.rs` — GameState/Player/InPlay/CardDef struct (canonical field)。 serde で full_dump を deserialize。
  InPlay の base_cost()/power()/base_cost 等の派生値。
- `src/effects.rs` — 効果システムの中核:
  - `eval_condition` — 条件評価 (self_life_ge / leader_feature / exists_chara_cost_0_or_ge_8 等)。 新条件はここ。
  - `resolve_target` — target spec 解決 (self/one_opponent_*/all_self_chara_filtered/one_opponent_character_filtered 等)。 新 target spec はここ。 ⚠ AI 選択基準 (opp_value/_threat_key=power降順) を Python と一致させる。
  - `execute_effect` — 非静的 primitive (draw/ko/mill/power_pump/give_keyword/…)。 新 primitive はここ。 未対応は false→呼出側 bail。
  - `cost_payable_one`/`pay_cost_one` — optional_cost_then の cost。 `try_pay_counter_cost`/`can_pay_counter_cost_full` — on_attack/opp_attack/counter cost。 `pay_on_play_cost` — on_play/main cost。
  - `on_trigger_prim_safe` — trigger/end_of_turn/field-when で発火してよい safe primitive の allow-list。 新 primitive を trigger でも使うならここに追加。
  - `fire_field_when` / `fire_on_attack` / `fire_opp_attack` / `fire_on_ko` / `fire_life_trigger` — 各種 when 発火。
  - `evaluate_static_effects` — 静的常在効果 (recompute_static)。
- `src/rules.rs` — apply_action (AttackLeader/AttackCharacter/PlayCharacter/PlayEvent/PlayStage/ActivateMain/
  AttachDon/EndPhase)、 advance_phase、 do_battle_ko、 battle 解決。
- `src/rng.rs` — MT19937 (CPython random 互換)。
- `src/setup.rs` — setup_game (pre-mulligan、 deck build+shuffle+life+deal)。
- `src/lib.rs` — PyO3 バインディング (apply_action_digest / recompute_static_digest / legal_actions_json /
  setup_pre_mulligan_digest / apply_raw_effect_digest / mt_* テスト関数)。
