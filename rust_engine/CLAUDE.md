# Rust engine — Python 準拠 self-play 高速ミラー

> Python engine (`engine/`) が **正 (公式準拠 100% 検証済)**。 Rust (`rust_engine/`、 PyO3 module
> `optcg_engine`) は self-play を 30-100x 高速化するための**忠実ミラー**。 配備 AI・人間対戦・API は
> Python のまま。 詳細背景は memory `project_rust_engine.md`。

## 不変条件 (絶対に守る)

**Rust は任意の action に対し「Python と bit 一致」か「Err で明示 bail」の二択のみ。 黙って間違った状態を作らない
(= MISMATCH=0)。** bail は「未実装なので降参」であり誤りではない。 差分検証がこれを保証する。

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

## ツール

| 用途 | コマンド |
|---|---|
| 差分 summary + bail 内訳 | `python scripts/rust_parity_check.py` |
| CI/pre-commit ガード | `python scripts/rust_parity_check.py --assert` (MISMATCH>0 で exit 1) |
| standalone 完走の壁 観測 | `python scripts/rust_parity_check.py --wall` |
| pytest 自動ガード | `pytest tests/test_rust_parity.py` |

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
