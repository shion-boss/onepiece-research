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
| 学習 value の deploy 検証 | `scripts/test_learned_value_deploy.py`(配備 beam に差して vs #1、 `--deck/--opp/--beam-width`、 両 seat) |
| ⭐**1 ラウンド実行(gate→deploy→永続化→recompute)** | `scripts/deploy_counter.py`(両 seat 実測 → baseline 超えたら deploy + **matrix 書き戻し** + 履歴。 = 本当に回す本体、 `--counter/--iter/--top/--n`) |
| 順位 recompute(+ `--save` で永続化) | `scripts/recompute_rank_vs_top.py`(vs-#1 セル差替。 引数なし=現順位、 `--save`=matrix 書き戻し) |
| campaign 履歴(audit) | `db/dethrone_campaign.json`(deploy 毎に round 追記。 rotated 判定の記録) |
| 学習成果物 | `db/_selfplay/beamloop_<deck>_iter<N>.pkl`(gitignore) |
| 補助 self-play 検証 | `selfplay_climb.py`(mirror)/`selfplay_vs_target.py`(1-ply、 安価な機構確認用) |

## 手順

### 1. 現 #1 を特定 ─ ⭐**毎ラウンド必ず再確認**(標的は動く)
`db/matchup_matrix.json` の各 deck の row 平均勝率を見て最上位を取る(`recompute_rank_vs_top.py` を
引数なしで実行すると現順位 top5 を出す)。 ⚠**既定値(カルガラ)を仮定するな**。 deploy する度に
`deploy_counter.py` が matrix を書き戻す(手順4.5)ので、 matrix が唯一の真実。 **毎回ここで実測**せよ
(= ohtsuki「どのデッキが一位かを都度確認しないとだめ」、 2026-06-24)。 まだ何も deploy してなければ
カルガラ(`tcgportal_calgara`)が #1。

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

### 4〜6. deploy + 永続化 + recompute ─ ⭐**1 コマンドで回す(推奨)**
`deploy_counter.py` が「両 seat 実測 gate → baseline 超えたら deploy → **matrix 書き戻し** →
recompute → #1 交代判定 → 履歴追記」 を一括でやる(= 手順4・4.5・5・6)。 **これが本体**:
```bash
.venv/bin/python scripts/deploy_counter.py --counter <counter> --iter iter<best> \
    --n 40 --beam-width 16 --max-depth 10   # --top 省略=matrix 現#1。 --dry-run で測るだけ
```
- ⚠ **配備忠実 eval (16/10 + value_defense は deck config 通り) で baseline(現 deployed value)超えを確認**。
  超えなければ deploy しない(= 回帰を配備しない、 [[feedback_evaluation_axis]])。 moderate beam(8/6)で
  訓練した value が 16/10 で効く保証はない(= 1-ply の transfer 失敗例あり)。 ここで初めて deployable 確定。
- ⭐**書き戻しは seat 別**(`cell(counter,top)` と `cell(top,counter)` を独立実測して書く)。 symmetric
  override(`recompute --override` の `w`/`1-w`)は seat 非対称を潰し、 calgara row-avg を**逆向き**に
  動かしうる(2026-06-24 確認: enel=32% override で calgara 74.0→74.2% と上昇)。 deploy_counter は正しい向き。
- **手順4.5 = 永続化が肝**(ohtsuki 2026-06-24)。 これが無いと deploy しても matrix が古いまま →
  手順1 が旧 #1 を返し、 session を跨いで**回らない**。 `matchup_matrix.json` が唯一の真実、 deploy で更新。

⚠**#1 は頑健**(全相手の平均)。 1 本改善では落ちない(実演: 5 デッキ 58% でも calgara 74→67.7% で #1
維持。 12 デッキ ~50% で初めて陥落 → 新 #1 ハンコック)。 → **複数 counter × 複数 round** が要る = campaign 本質。

**手動でやる場合**(deploy_counter を使わない時)= `test_learned_value_deploy.py` で gate → `cp pkl
db/value_gbm_<counter>.pkl` → `recompute_rank_vs_top.py --override <counter>=<wr> --save`(`--save` で永続化)。

### 6. 新 #1 へ再標的 → 繰り返す
#1 が交代したら新 #1 を step1 の標的にして 2-6 を回す。 これが共進化キャンペーン。

## 鉄則(why 付き)

- **手で eval を直す前に、 学習で抜けるか測れ**。 文脈判断は手調整で表現できない(線形 eval の形の限界)。
- **必ず beam-in-loop**(探索の分布で学習)。 1-ply value は配備 beam で効かない。
- **効き所を選べ**(board_eval=大 gain / 調整済 GBM=規模要)。 ここを外すと round 1 dofla のように flat。
- **回帰を配備しない**。 deploy は配備忠実 eval で baseline 超えを確認した時だけ。
- **#1 陥落は広範な改善の産物**。 1 本で諦めない、 複数 round 回す。
- **#1 は毎ラウンド matrix で都度確認**(標的は動く、 既定値を仮定しない)。 deploy は **matrix に永続化**
  (`deploy_counter.py` が seat 別に書き戻す)。 でないと session を跨いで回らない(2026-06-24 ohtsuki 指摘)。
- **TCG は循環(じゃんけん)risk**。 1 位回転で相手を多様化するのが循環回避になっている。 単一固定相手 self-play
  だけだと plateau/循環。
- **compute 重い → 背景実行 + checkpoint**。 大規模化は Phase 9 分散([[project_roadmap]])。

## 関連
- [[project_selfplay_self_improvement_engine]] — 本スキルの一次情報・全実証(必ず参照)
- [[project_engine_search_levers_exhausted]] — 手チューニングが exhausted な理由
- [[project_rollout_gbm_value]] — ラベル variance↓ の次手 / [[project_superhuman_ai_distillation]] — 教師の天井
- [[feedback_evaluation_axis]] — raw 勝率 ≠ engine 良し悪し、 回帰を配備しない / [[project_roadmap]] Phase 8-9
- 測定の整合: [[analyze-ai-matchup-log]](AI vs AI ログ)/ [[onepiece-tcg-strategy]](プレイング妥当性)
