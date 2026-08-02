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

## ⚠ MISMATCH だけを見ていると漏れる (2026-08-02 追加)

差分ハーネスは **サンプルに現れた action しか見ない**。 Python に新しい primitive / spec 変種 /
trigger が入っても、 そのカードがサンプルに出なければ **MISMATCH=0 のまま Rust が黙って効果を落とす**。
実際に見逃していた例:

- 静的効果 **15 種** が Rust 未実装 (= 常在効果が黙って消える)
- when **3 種** が Rust で未発火 (`on_self_don_attached` / `don_phase_modifier` / `setup_modifier`)
- `play_from_hand_named_with_dynamic_cost` の `name_filter` 追加 (Python だけ直り Rust 未追従)

→ **静的な網羅チェックを必ず併走させる**:

```bash
.venv/bin/python scripts/scan_overlay_engine_gaps.py   # overlay キー vs 両エンジン実装
.venv/bin/pytest tests/test_rust_parity.py -q          # CI gate (MISMATCH + 網羅 + self-play bail)
```

gate は 3 本:
1. `tests/test_rust_parity.py::test_rust_parity_no_mismatch(_broad)` — 差分 MISMATCH=0 **(要 Rust ビルド)**
2. `tests/test_rust_overlay_coverage.py::test_rust_covers_all_overlay_keys` — overlay の
   primitive/condition/when を Rust が全実装 **(ビルド不要 = ソースを grep するだけ)**
3. `tests/test_rust_parity.py::test_rust_selfplay_meta_pool_no_bail` — メタデッキ self-play で
   bail 0 + 保存則違反 0 **(要 Rust ビルド)**

⚠ **2 を別ファイルに置いてある理由**: `test_rust_parity.py` は先頭で `importorskip("optcg_engine")`
するので、 **Rust 未ビルドのクラウド環境ではモジュールごと skip** される。 効果自動修正ルーティン
(`optcg-effect-bugfix`) はそこで走るため、 ビルド不要の 2 が無いと「Python だけ直して push」が素通りする
(実際に `play_from_hand_named_with_dynamic_cost` の `name_filter` 追加で素通りした)。

**Python engine (`engine/`) を直したら 同じ commit で `rust_engine/` も直す**。
`scripts/effect_bugfix_gate.sh` は `engine/` 変更 + `rust_engine/src/` 無変更 を検出したら
**`db/_rust_followup.md` に追記**する (revert はしない — Python の修正自体は正しいので)。
このルーティンの入口で **まず `db/_rust_followup.md` を読み、 溜まっている項目を消化する**。

## ループ (1 MISMATCH = 1 サイクル)

```
0. `db/_rust_followup.md` を読む (Python 側が先行修正された項目) →
1. 検出 → 2. 診断 → 3. 修正 (bit一致 or bail) → 4. 検証 → 5. commit / escalate
        └──────────────── 次の MISMATCH ────────────────┘
```

### 0. 準備 (毎回)

```bash
source ~/.cargo/env
.venv/bin/maturin develop --manifest-path rust_engine/Cargo.toml --release   # Rust 最新化
```

### 1. 検出 — 2 つの入力 (両方を消化する)

**(a) シャドウ記録 (優先) — 実ゲームで捕捉した乖離**
```bash
.venv/bin/python scripts/rust_shadow_check.py          # db/rust_divergence_log.jsonl を表示
```
`engine/rust_shadow.py` (`ONEPIECE_RUST_SHADOW=1` の実ゲーム = self-play/テスト/対戦) が
**実際に走った局面**で捕捉した silent MISMATCH。 各件に **厳密再現 dump** (`db/rust_divergence/<key>.json`
= {適用前 dump, action, 期待 py_after}) が付く。 scan より優先 (実到達局面 + 再現が seed 探し不要)。

**(b) 広域スキャン — サンプル的に先回り検出**
```bash
.venv/bin/python scripts/rust_mismatch_scan.py --seeds 1-30
```
→ `db/rust_mismatch_queue.md` に各 MISMATCH の **{action, card, field 差分, 再現 pair/seed, log}**。
両方 0 件なら完了。 ⚠ どちらもサンプル/観測なので「0」≠「全状態で 0」(bit 一致の証明ではない)。

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
# ① 対象 MISMATCH が消えたか — シャドウ記録なら厳密再現 dump で高速照合 (ゲーム再生不要)
.venv/bin/python scripts/rust_shadow_check.py --verify db/rust_divergence/<key>.json   # OK=一致 or bail
#    scan 由来なら該当 seed で再スキャン: .venv/bin/python scripts/rust_mismatch_scan.py --seeds <対象seed>
# ② ゲート (回帰なし) + broad で MISMATCH=0
.venv/bin/python -c "import scripts.rust_parity_check as P; \
d,_,dm=P.run_parity(); b,_,bm=P.run_parity(seeds=(1,7,13,21,42,99)); \
print('default',d['match'],d['bail'],d['MISMATCH'],'broad',b['match'],b['bail'],b['MISMATCH']); \
print('MM',dict(dm.most_common(3)),dict(bm.most_common(3)))"
# ③ 修正済記録を掃除 (verify が通る記録を log+dump から除去) + 該当カード機能テスト
.venv/bin/python scripts/rust_shadow_check.py --prune
.venv/bin/pytest tests/test_rust_parity.py -q
```
不変条件: **default 2037/0/0 維持 / broad MISMATCH=0 / 対象 MISMATCH 消滅 / 新 MISMATCH ゼロ**。
どれか崩れたら修正を **revert** (correctness 絶対、 silent MISMATCH より bail が正しい)。

### 5. commit / escalate

- 検証を通ったら **1 fix = 1 commit** (`fix(rust): <card> の <root cause> 解消 (MISMATCH=0)`、 診断内容を本文に)。
  一時 print/scratchpad は削除済を確認。 `rust_engine/CLAUDE.md` の落とし穴 checklist に非自明パターンを追記。
- 診断が難航し当セッションで直せないものは **queue に残す** (`rust_mismatch_scan.py` を再実行してキュー更新)。
  = 黙って放置せず、 常に最新の MISMATCH 一覧を repo に出す。

## 自律運用 (cron) — check + 修正はクラウドに置く

構成 (= optcg-effect-bugfix と同型、 3 層):

1. **記録 (detection)** — repo 内に貯まる (`db/rust_divergence_log.jsonl` + `db/rust_divergence/*.json`、 commit
   済で全環境から見える)。 populate は `ONEPIECE_RUST_SHADOW=1` の実ゲームが行う → **クラウド self-play を
   この env で回せばクラウドが記録を貯める**。 加えて広域 scan が先回り検出。
2. **check (CI、 毎 push)** — `tests/test_rust_parity.py` が **MISMATCH=0 を assert** (回帰検出、 クラウド CI で自動)。
   広域強化は `test_rust_parity_no_mismatch_broad` の seed を広げる (35s/実行)。 シャドウ記録の空 assert は
   `scripts/rust_shadow_check.py --assert` (exit 1)。
3. **修正 (cloud cron `optcg-rust-parity-fix`)** — 恒久運用は **claude.ai 側のクラウド cron** に登録する
   (session cron=CronCreate は揮発するので不可)。 optcg-effect-bugfix を登録したのと同じ場所に、 このスキルを
   起動する prompt を置く:
   > 「/onepiece-rust-parity-fix を実行。 (a) `rust_shadow_check.py` のシャドウ記録 と (b) `rust_mismatch_scan.py`
   >  の広域スキャン で MISMATCH を検出し、 上から 1 件ずつ診断 (再現 dump を blob-diff)→ Rust を Python に
   >  bit 一致 or 明示 bail→検証 (`--verify` で対象消滅 + broad MISMATCH=0 + 回帰なし)→`--prune`→commit。
   >  潰せないものは queue/記録に残す (escalate)。 ゲートが崩れる変更は revert。」
   スケジュール例: 毎日 1 回 (`7 4 * * *` 等、 :00 を避ける)。 CLI からは登録できない (クラウド側 UI で設定)。

## ツール早見

| 用途 | コマンド |
|---|---|
| MISMATCH 広域検出 → キュー | `python scripts/rust_mismatch_scan.py --seeds 1-30` |
| CI 検出 (exit 1) | `python scripts/rust_mismatch_scan.py --assert` |
| 差分 summary + bail 内訳 | `python scripts/rust_parity_check.py` |
| ゲート pytest | `pytest tests/test_rust_parity.py` |
| blob-diff pinpoint | `eng.apply_action_blob(dump, action)` + `diff_canonical(canonical_state(c), blob)` |

関連: [[project_rust_engine]] (両運用の全体像・fix 実績) / `rust_engine/CLAUDE.md` (同期落とし穴 checklist)。
