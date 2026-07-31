---
name: onepiece-rust-parity-fix
description: >-
  Python↔Rust エンジンの **差分 MISMATCH (Rust が黙って Python と違う状態を作る箇所) を検出→自動修正**
  する運用ループ。 ohtsuki が「不一致を修正して」「MISMATCH を潰して」「Python と Rust の差を直して」
  「差分を自動修正して」「Rust の一致度を上げて」「エンジン一致を維持して」 等と言ったら (個別スクリプト名が
  無くても) このスキルを使う。 cron ルーティン (optcg-rust-parity-fix) からも起動される。 不変条件 =
  **MISMATCH=0 (Rust は「Python と bit 一致」か「明示 bail」の二択のみ、 黙って間違えない)**。
---

# Python↔Rust 差分 MISMATCH 自動修正ループ

> **狙い**: self-play 高速化ミラー (Rust) が正 (Python、 公式準拠100%検証済) と **黙って違う状態を作る
> (silent MISMATCH)** のを 0 に保つ。 見つけたら Rust を Python 挙動に **bit 一致** させる、 それが困難なら
> **明示 bail** に落とす (= 降参、 誤りでない)。 どちらも「黙って間違えない」を維持。
> 背景・実証: memory `project_rust_engine.md`。 詳細規約: `rust_engine/CLAUDE.md`。

## 大前提 (自動修正の限界と現実)

- **機械的な無思考変換では直らない**。 各 MISMATCH は「Python がなぜその状態を作るか」の診断が要る
  (実例: total_don が付与ドン未算入 / source-gone opp_attack は do 不発 / CardDef は repository 共有 instance)。
  = **エージェントの推論** (このスキル) が必要。 単純 diff→patch では無理。
- **診断できたものは全て直せる** (構造的な壁は無い、 実証済)。 「原理的に不可能」に見えても Python の実挙動を
  理解すれば解ける。 難しいのは「未理解」であって「不可能」ではない。
- 潰せない (診断に時間が要る) ものは **queue に残す** (= 黙って放置しない、 effect_bugfix_escalate と同型)。

## ループ (1 MISMATCH = 1 サイクル)

```
1. 検出 → 2. 診断 → 3. 修正 (bit一致 or bail) → 4. 検証 → 5. commit / escalate
        └──────────────── 次の MISMATCH ────────────────┘
```

### 0. 準備 (毎回)

```bash
source ~/.cargo/env
.venv/bin/maturin develop --manifest-path rust_engine/Cargo.toml --release   # Rust 最新化
```

### 1. 検出 — 広域スキャンで MISMATCH キューを再生成

```bash
.venv/bin/python scripts/rust_mismatch_scan.py --seeds 1-30
```
→ `db/rust_mismatch_queue.md` に各 MISMATCH の **{action, card, field 差分, 再現 pair/seed, log}**。
0 件なら完了 (この広域サンプルでは完全一致)。 ⚠ サンプルなので「別 seed 範囲で 0」≠「全状態で 0」。

### 2. 診断 — 1 件を選び根本原因を pinpoint

キューの上から 1 件。 `db/rust_mismatch_queue.md` の field 差分 + log で当たりを付け、 **再現して blob-diff**:
- 再現ハーネス: `scratchpad/*.py` (mmscan/wyper/croco/kiku を雛形にコピー)。 特定 seed/pair で MISMATCH 手まで
  進め、 `eng.apply_action_blob(dump, action)` (Rust) と `canonical_state(c)` (Python) を `diff_canonical` で
  field 単位に落とす。
- **「Rust がなぜ違うか」を Python 実装で確定させる**: 該当 primitive/condition/target の Python (`engine/effects.py`)
  を読み、 Rust (`rust_engine/src/effects.rs` / `rules.rs`) と挙動を突き合わせる。 必要なら Python 側に一時 print を
  仕込んで実挙動を観測 (使い終わったら必ず削除)。

**このセッションで判明した典型 root cause (最初に疑う)**:
- **集計の欠落**: Rust の合計計算が Python と違う (例 `total_don` が付与ドン未算入 → self_don_ge/le が AttachDon で
  誤発火)。 → 対応する Python の集計式 (`engine/effects.py`) と完全一致させる。
- **source-gone の挙動**: cost で発動元が場を離れる (trash_self/ko_self) → Python は `_execute_event` が
  self_inplay=None で **早期 return** する when (opp_attack/on_attack/on_play 等、 on_ko/main/counter/trigger 以外) は
  **do を発火しない**。 Rust が発火すると MISMATCH。 → trash して do 不発、 or allow-list を Python に合わせる。
- **CardDef の共有 instance**: repository は同名カードに同一 object を返す → Python の `_c is taken` (identity) は
  trash 内の任意の同名 cid に一致。 = Rust は **position ベース (先頭 cid を pop→routing)** で一致 (枚数/count 判定でなく)。
- **trigger resolution ordering**: resolving 中に発火した trigger を Python は enqueue→末尾 drain (deferred)。 Rust の
  即時発火とズレる。 順序非依存なら digest 一致、 依存なら deferred モデリングか bail。
- **dynamic attr (setattr) の canonical 除外**: Python の setattr フラグは digest 除外で Rust 不可視 → ターン跨ぎ状態は
  canonical field 化 (core.py + state.rs 両方)。
- **AI 選択基準の相違**: target 解決の sort key (opp_value / _threat_key=power 降順 / worst_hand_idx=counter→cost→
  power→known) を Python と完全一致させる (tie-break 含む)。
- **静的効果の condition/n gate**: on_attached_don の `conditions` (if だけでなく conditions リストも AND)、 n=0 gate、
  give_keyword → static_granted_keywords。

### 3. 修正 — Rust を Python に bit 一致 or 明示 bail

- **bit 一致**: Python の該当ロジックを Rust に忠実移植。 primitive は `execute_effect`、 target は `resolve_target`、
  condition は `eval_condition`、 静的は `apply_static_primitive`/`evaluate_static_effects`。 ⚠ **配備 Python を変えたら
  (新カード効果修正等) Python 側も直す** = 両エンジン同時 (共有 `card_effects.json` はデータ変更で自動両対応)。
- **明示 bail**: bit 一致が困難 (稀な相互作用/複雑 cascade) なら Err で bail (= 未対応で降参、 誤りでない)。
  値型 CardDef の identity や rng harness 制約など、 差分では原理的に難しいものは bail 維持が正しい。
- ⚠ **net-zero の複雑化は commit しない** (revert)。 MISMATCH を消しても別 MISMATCH が出たら即 revert。

### 4. 検証 (必須、 これを通すまで完了としない)

```bash
source ~/.cargo/env; .venv/bin/maturin develop --manifest-path rust_engine/Cargo.toml --release
# ① ゲート (回帰なし) + broad で MISMATCH=0
.venv/bin/python -c "import scripts.rust_parity_check as P; \
d,_,dm=P.run_parity(); b,_,bm=P.run_parity(seeds=(1,7,13,21,42,99)); \
print('default',d['match'],d['bail'],d['MISMATCH'],'broad',b['match'],b['bail'],b['MISMATCH']); \
print('MM',dict(dm.most_common(3)),dict(bm.most_common(3)))"
# ② 対象 MISMATCH が消えたか (該当 seed/pair で再スキャン)
.venv/bin/python scripts/rust_mismatch_scan.py --seeds <対象seed>
# ③ 該当カードの機能テスト (可能なら scratchpad で 単体再現→期待値 assert)
.venv/bin/pytest tests/test_rust_parity.py -q
```
不変条件: **default 2037/0/0 維持 / broad MISMATCH=0 / 対象 MISMATCH 消滅 / 新 MISMATCH ゼロ**。
どれか崩れたら修正を **revert** (correctness 絶対、 silent MISMATCH より bail が正しい)。

### 5. commit / escalate

- 検証を通ったら **1 fix = 1 commit** (`fix(rust): <card> の <root cause> 解消 (MISMATCH=0)`、 診断内容を本文に)。
  一時 print/scratchpad は削除済を確認。 `rust_engine/CLAUDE.md` の落とし穴 checklist に非自明パターンを追記。
- 診断が難航し当セッションで直せないものは **queue に残す** (`rust_mismatch_scan.py` を再実行してキュー更新)。
  = 黙って放置せず、 常に最新の MISMATCH 一覧を repo に出す。

## 自律運用 (cron)

- session cron (CronCreate) は揮発。 **恒久運用は cloud cron `optcg-rust-parity-fix`** をこのスキルで起動する
  (= optcg-effect-bugfix と同型)。 cron prompt 例:
  > 「/onepiece-rust-parity-fix を実行。 rust_mismatch_scan で MISMATCH を検出し、 上から 1 件ずつ診断→
  >  Rust を Python に bit 一致 or bail→検証 (broad MISMATCH=0 + 回帰なし)→commit。 潰せないものは queue に残す。
  >  ゲートが崩れる変更は revert。」
- CI ゲート: `tests/test_rust_parity.py` が変更毎に **MISMATCH=0 を assert** (回帰検出)。 広域強化するなら
  `test_rust_parity_no_mismatch_broad` の seed を広げる (35s/実行、 [[project_rust_engine]])。

## ツール早見

| 用途 | コマンド |
|---|---|
| MISMATCH 広域検出 → キュー | `python scripts/rust_mismatch_scan.py --seeds 1-30` |
| CI 検出 (exit 1) | `python scripts/rust_mismatch_scan.py --assert` |
| 差分 summary + bail 内訳 | `python scripts/rust_parity_check.py` |
| ゲート pytest | `pytest tests/test_rust_parity.py` |
| blob-diff pinpoint | `eng.apply_action_blob(dump, action)` + `diff_canonical(canonical_state(c), blob)` |

関連: [[project_rust_engine]] (両運用の全体像・fix 実績) / `rust_engine/CLAUDE.md` (同期落とし穴 checklist)。
