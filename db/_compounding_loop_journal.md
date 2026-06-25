# 複利改善ループ journal (Claude主導 自律 cycle 履歴)

> クラウド scheduled agent が毎回 **読んで→追記**する。 同じ idea を二度試さない。
> 1 brick = 1 永続改善。 gate 通過した時だけ commit。 詳細 method = memory `project_compounding_improvement_loop`。

## 鉄則
- **検出器に report_bad_moves を使わない**(board_eval delta が field_power/攻撃過小評価で飽和)。 使うのは ①deployed game 精読(`scripts/_dump_deployed_game.py`)②ルール audit(`audit_overlay_vs_faq`/`smoke_test_card_effects`/`audit_engine_strictness`)③eval/heuristic の構造解析。
- **診断で false-positive を棄却**: 公式テキスト(`db/cards.json` text + `db/faq/cardqa_*.json` + rules skill)で「本当にバグか engine-correct か」を確認。 mature codebase なので大半は correct。
- **gate = 広い × 高N × audit**: `scripts/ab_control_vs_aggro.py` 等で N=40 複数ペア before/after、 どのデッキも noise 超で regress しない事 + `pytest -q` green + audit clean。 **勝率単独で bank しない**(rule 忠実性も確認)。
- **cold-start マッチ(control vs 速攻)は対象外** = アーキ級(Phase 9)。
- **main に push しない**。 `auto/compounding-loop` ブランチに積む。

## cycle 履歴

### #1 — 2026-06-25 — BANKED ✅ field_power soft-cap 既定ON (commit 8ddfd44)
- 検出: croc vs bonney の board_eval が ±200k 爆発(field_power = pumped power, DON+1000 二重計上)。
- 診断: 実バグ(構造的)。 control を「空盤面=大敗」と誤評価。
- 修正: `engine/eval.py:_field_power_contribution` で cap*tanh(±6k)、 既定ON(`ONEPIECE_NO_FP_CAP=1` で opt-out)。
- gate: control +17.5pt / aggro −1.7pt(noise)= net正・no-harm。 pytest green。 matrix-safe(GBM 経路 不変)。
- 次の候補: GBM feature 側の field_power も cap(要再学習)/ defense heuristic の精読。

### #2 — 2026-06-25 — REJECTED (no brick, 正常) deployed 精読 false-positive 2件
- croc vs bonney deployed 精読 → 「activate-main の discard cost」「leader 名前衝突で character 攻撃に見えた」 → 両方 engine-correct(OP14-120 on_ko 任意discard / leader=Crocodile への leader attack)。 検証が false-positive を棄却 = 安全装置 OK。
