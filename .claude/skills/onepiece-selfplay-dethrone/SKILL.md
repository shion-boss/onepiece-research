---
name: onepiece-selfplay-dethrone
description: >-
  ONE PIECE カードゲーム engine の **対戦用 AI を self-play(自己対戦)で強化する** 運用 runbook。
  「現 1 位デッキを倒す value を beam-in-loop self-play で学習 → deploy → 順位を vs-1位だけ差し替えで
  再計算 → 新 1 位へ再標的」 を繰り返す共進化キャンペーン。 ohtsuki が「対戦用 AI を self-play で強化して」
  「打倒 1 位を回して」「self-play で強くして」「1 位を倒す AI を訓練して」「自己改善キャンペーン回して」
  「AI をもっと強くして」「matrix の 1 位を引きずり下ろして」 等と言ったら、 個別スクリプト名が出てなくても
  必ずこのスキルを使う。 手チューニング(eval 重み/prune)で AI を強くしようとせず、 まずこのスキルの
  self-play ループを検討する(手チューニングは exhausted、 [[project_engine_search_levers_exhausted]])。
---

# 打倒 1 位 self-play 対戦 AI 強化キャンペーン

> **狙い**: AI の強さを「**正しい判断を手でエンコード**」(eval 重み調整・prune) で上げようとせず、
> **対戦から自分で学習させる**。 探索 + 複利 + 共進化で、 投じた規模に比例して強くなるエンジン。
> 一次情報・実証は [[project_selfplay_self_improvement_engine]](2026-06-24 構築)。

## 使いどき / 大前提

ohtsuki が「対戦 AI を強くしたい」 系を言ったら起動。 **最初に確認すべき大前提**:
- **手チューニングは効かない**。 打倒カルガラで value源差替/blend/prune/sim強化/eval項調整を全 A/B → 全 null。
  「いつ・どう攻めるか」 のような文脈判断は線形 eval/手調整では表現できず、 GBM は自分の凡庸 self-play で
  学習する循環。 → **学習(self-play)が唯一登る道**。
- なので「eval をこう直せば?」 と言われても、 まずこのループで「学習で抜けるか」 を測るのが筋。

## 全体ループ(共進化)

```
1. 現 #1 を測る ──→ 2. counter を選ぶ ──→ 3. self-play 訓練(beam-in-loop)
                                                    │
   6. 新 #1 へ再標的 ←── 5. 順位 recompute ←── 4. deploy(勝てば)
   (繰り返す = 共進化)     (vs-#1 だけ差替)      (db/value_gbm_<slug>.pkl)
```
1 位が回転する = **標的が動き続ける(共進化)+ 相手が多様(循環回避)** → 天井が上がり続ける。

## 前提インフラ(全て実装済)

| 役割 | 場所 |
|---|---|
| 現 matrix(順位の真) | `db/matchup_matrix.json`(row-avg が順位) |
| 1 位 gauntlet 測定 | `scripts/gauntlet.py`(全デッキ vs #1) |
| **self-play 訓練(本体)** | `scripts/selfplay_beam_loop.py`(beam-in-loop、 deployable、 `--deck/--opp/--beam-width/--max-depth`) |
| 学習 value の deploy 検証 | `scripts/test_learned_value_deploy.py`(配備 beam に差して vs #1) |
| **順位 高速 recompute** | `scripts/recompute_rank_vs_top.py`(vs-#1 セルだけ差替、 全 matrix 再計算 不要) |
| 学習成果物 | `db/_selfplay/beamloop_<deck>_iter<N>.pkl`(gitignore) |
| 補助 self-play 検証 | `selfplay_climb.py`(mirror)/`selfplay_vs_target.py`(1-ply、 安価な機構確認用) |

## 手順

### 1. 現 #1 を特定
`db/matchup_matrix.json` の各 deck の row 平均勝率を見て最上位を取る(`recompute_rank_vs_top.py` を
引数なしで実行すると現順位 top5 を出す)。 既定の標的はカルガラ(`tcgportal_calgara`)。

### 2. 訓練する counter を選ぶ ─ ⭐効き所の見極めが最重要
**gain ≈ (value の伸びしろ) × (投じた規模)**。 だから選び方が成否を決める:
- ⭐**最優先 = board_eval デッキ(`db/value_gbm_<slug>.pkl` が無い deck)**。 value が手作りで弱く伸びしろ大
  → 小規模でも大 gain(エネル 1467 で board_eval 12% → 学習 36%、 **+24pt 実証**)。
- ⚠**調整済 per-deck GBM 持ちデッキは小規模では超えられない**(dofla 1342 round1 = SLOPE flat)。
  既存 GBM は大量対局で学習済 → 抜くには規模(games/iters↑、 Phase 9 分散)が要る。
- matrix 16 デッキは全部 GBM 持ち。 ⇒ **実 matrix を動かす大 gain は、 board_eval の counter を入れるか、
  規模を投じて GBM 持ちを底上げ**。 まず board_eval counter から。

### 3. self-play 訓練(beam-in-loop)
```bash
# 背景推奨(compute 重)。 deploy 忠実なら beam を配備値 16/10 に(遅い)、 探索は moderate 8/6:
nohup .venv/bin/python scripts/selfplay_beam_loop.py \
  --deck <counter_slug> --opp <top_slug> \
  --iters 8 --games 60 --eval 60 --epsilon 0.25 --eps-end 0.05 \
  --beam-width 8 --max-depth 6 --workers 12 \
  > db/_selfplay/run_<counter>.log 2>&1 &
```
ログの **SLOPE** を見る。 **iter0 = baseline(board_eval or 既存 GBM)**。 iter1+ がそれを **明確に超えて
登れば成功**。 横ばい/下降なら counter 選定 (step2) か規模を見直す。
- ⚠**必ず beam-in-loop を使う**。 1-ply 学習 value は配備 beam に **transfer しない**(deployable test:
  28% → 22-25% に悪化)。 AlphaZero 原則「value は **探索が生成する分布** で学習せよ」。 安い 1-ply
  (`selfplay_vs_target.py`)は機構確認用で、 deploy 候補にはしない。
- ノイズ大(単一試合ラベル)なら `--games` を増やす。 将来は rollout ラベルで variance↓
  ([[project_rollout_gbm_value]])。

### 4. deploy(配備、 勝った時だけ)
学習 value が baseline を **配備忠実な eval で** 超えたら配備:
```bash
# まず配備 beam に差して検証(回帰を配備しない gate):
.venv/bin/python scripts/test_learned_value_deploy.py --arms default,iter<best> --n 80
# 超えていれば配備(ExploitBeam が deck_slug から自動 load する正規の場所へ):
cp db/_selfplay/beamloop_<counter>_iter<best>.pkl db/value_gbm_<counter>.pkl
```
⚠ moderate beam で訓練した value は配備フル beam で最適とは限らない。 **deploy 前に
`test_learned_value_deploy.py`(配備構成)で baseline 超えを確認**。 理想は `--beam-width 16
--max-depth 10` で再訓練。 **回帰 value は配備しない**([[feedback_evaluation_axis]])。

### 5. 順位を vs-#1 だけ差し替えて recompute
全 matrix 再計算(240 cell, 数時間)は不要。 改善した counter の vs-#1 勝率だけ差し替え:
```bash
# 単発: 学習後の (counter vs #1) 勝率を測って override
.venv/bin/python scripts/recompute_rank_vs_top.py --override <counter>=<winrate_0to1>
# 一括: gauntlet を回したなら結果ファイルから
.venv/bin/python scripts/recompute_rank_vs_top.py --gauntlet db/gauntlet_<top>.json
```
#1 の row-avg が下がって陥落したか表示される。 ⚠**#1 は頑健**(全相手の平均)。 1 本改善では落ちない
(実演: 5 デッキ 58% でも calgara 74→67.7% で #1 維持。 12 デッキ ~50% で初めて陥落 → 新 #1 ハンコック)。
→ **複数 counter × 複数 round** が要る = campaign 本質。

### 6. 新 #1 へ再標的 → 繰り返す
#1 が交代したら新 #1 を step1 の標的にして 2-6 を回す。 これが共進化キャンペーン。

## 鉄則(why 付き)

- **手で eval を直す前に、 学習で抜けるか測れ**。 文脈判断は手調整で表現できない(線形 eval の形の限界)。
- **必ず beam-in-loop**(探索の分布で学習)。 1-ply value は配備 beam で効かない。
- **効き所を選べ**(board_eval=大 gain / 調整済 GBM=規模要)。 ここを外すと round 1 dofla のように flat。
- **回帰を配備しない**。 deploy は配備忠実 eval で baseline 超えを確認した時だけ。
- **#1 陥落は広範な改善の産物**。 1 本で諦めない、 複数 round 回す。
- **TCG は循環(じゃんけん)risk**。 1 位回転で相手を多様化するのが循環回避になっている。 単一固定相手 self-play
  だけだと plateau/循環。
- **compute 重い → 背景実行 + checkpoint**。 大規模化は Phase 9 分散([[project_roadmap]])。

## 関連
- [[project_selfplay_self_improvement_engine]] — 本スキルの一次情報・全実証(必ず参照)
- [[project_engine_search_levers_exhausted]] — 手チューニングが exhausted な理由
- [[project_rollout_gbm_value]] — ラベル variance↓ の次手 / [[project_superhuman_ai_distillation]] — 教師の天井
- [[feedback_evaluation_axis]] — raw 勝率 ≠ engine 良し悪し、 回帰を配備しない / [[project_roadmap]] Phase 8-9
- 測定の整合: [[analyze-ai-matchup-log]](AI vs AI ログ)/ [[onepiece-tcg-strategy]](プレイング妥当性)
