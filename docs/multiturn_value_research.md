# 多ターンを畳み込む効率的 value の形 — 研究シンセシス

> 2026-07-25。 ohtsuki の問い「複数ターンを折り込んで勝率を返すスカラーの**新しい形**(input/output を効率化)」への
> ネット調査 + 自エンジン実データ分析。 自律研究 → 実装 → arena 検証の設計文書。

## 0. 前提の整理(重要)
- **現 value は既に多ターンを畳んでいる**。 EIV1 value.pkl は corpus の **終局勝敗 y** で学習 = 1 局面 → 「そのゲームの最終結果」を 1 forward で予測。 これは全未来ターンを **学習target経由で畳んでいる**(探索を回さない)。
- 配備 beam が明示 sim するのは「自ターン + 相手 1 ターン(post-opp)」だけ。 value はその post-opp 盤面(=自次ターン開始)で終局勝率を返す。
- したがって「多ターンを畳む」は未実装ではなく、**畳みの精度**が課題。 効率化の余地は「探索(推論)→ 学習target/入力特徴」への移動。

## 1. 設計空間(ネット調査)
| 形 | 何を変える | 推論コスト | このエンジンでの適性 |
|---|---|---|---|
| **終局target スカラー** (AlphaZero value) | 出力=終局勝率 | O(1) | **既に採用**(現 value) |
| **averaged n-step / λ-return target** ([2402.03903]) | target=複数ホライズンの平均で分散↓ | O(1) | ○ 実装可(下記実験)。 ただし大データで分散は既に低い可能性 |
| **WDL 分布ヘッド** (Leela [wdl-head]) | 出力=勝/分/負の分布 | O(1) | **✗ 却下**: 自エンジンは turn~12 決着・時間切れ引分 0% → 分クラス無意味 |
| **多ホライズン出力ベクトル** [+2T,+4T,終局] | 出力=勝率の軌跡(1pass) | O(1) | △ 探索側が軌跡を消費する改修が要る |
| **MuZero value-equivalent latent dynamics** ([2102.12924]) | 入力=state→latent、 dynamics で latent を cheap に K-unroll、 各 latent の value を読む | O(K) latent(実engine simより桁違いに安い) | ◎ **効率的多ターン畳み込みの理想形**。 ただし NN(representation+dynamics+value head)の大工事 |
| **card-aware 入力 embedding** | 入力=個別カード効果理解 | O(1) | ◎ 別軸(belief/盲目 value 天井を破る) |

## 2. 自エンジン実データ
- corpus: 二値 y(勝/負)、 引き分けラベル無し。 game_id + turn_number でゲーム軌跡を復元可。
- ゲーム長: 中央値 **turn 12**、 max 18、 **turn≥38(時間切れ引分)= 0%**。 → 決着が速い = 引分ほぼ無し。
- 局面数 ~12/game、 534 game/40MB。 → 任意局面から +K ターン後の状態を **同一ゲーム内で lookup 可能**(追加 sim ゼロ)。

## 3. 既存資産との関係
- `build_block_residual_value.py` + `gen_block_value_targets.py` = 既に **λ·mc + (1-λ)·v_next の塊帰結target**(self-play生成)+ 残差アンカー + centering。 memory: block_residual 配備超え +2.2pt。
- 私の「averaged 多ホライズン target」= これの一般化(2点 blend → 複数ホライズン平均)。 corpus 軌跡から bootstrap すれば self-play 不要で作れる。

## 4. 実装する実験(buildable now・testable)
**averaged 多ホライズン target value**(`scripts/eiv1_multihorizon_value.py`):
- corpus をゲーム単位に group。 各局面 s_t について、 同一ゲームの s_{t+2}, s_{t+4} を lookup し **現 value で bootstrap**。
- target(s_t) = mean([ y(終局MC), v_cur(s_{t+2}), v_cur(s_{t+4}) ])  ← averaged n-step(分散↓)
- 回帰器 value_multihorizon.pkl を学習(drop-in スカラー)。 gbm_score は predict 経路で自動対応。
- **de-risk**: held-out y に対する AUC/較正(=sanity のみ。 ⚠ AUC は強さの指標でない=今季3連続実証)。
- **判定**: arena A/B(ε=0 vs 固定EBV2)。 これのみが強さの物差し(`eiv1_gate_candidate` / `matchup_value_deploy_ab`)。

## 5. 正直な予測と本命
- **予測**: averaged 多ホライズンは **deploy-null の可能性が高い**。 理由=(a) 現 value は既に終局を畳む (b) 500k局面で分散は既に低い (c) memory「1-ply value に手を加える路線は deploy-null 頻発 / value路線は出し切り」。 = クリーンに**確認**する価値はある(null なら「値の形いじりでは動かない」を確定)。
- **本命(効率的多ターンの真フロンティア)**:
  1. **MuZero-lite latent dynamics**: 実 engine を回さず latent を cheap に K-unroll → 多ターン先読みを 1 モデルに畳む。 = ohtsuki の狙い「input/output を効率化して多ターン」に最も直接的。 NN 大工事だが本命。
  2. **card-aware value**: 盲目 value の天井(belief-marginal)を破る直交軸。
- 結論: 出力/target の形いじり(WDL/averaged)は自エンジンでは小さい。 効率的に多ターンを畳む **新しい形の本体は latent-dynamics(MuZero型)**。 まず averaged 実験で「値いじり路線が閉じている」を arena で確定させ、 latent-dynamics prototype へ進むのが筋。

## 6. Session-2 所見 — value-FORM ルートは閉、レバーは「決定層」(2026-07-25)

前節の averaged 多ホライズン実験を arena で検証 + **稼働中 EIV1 パイプラインの arena.jsonl / exit_loop.log を精読**した結果、
value スカラーの「形」(target/input/output)いじりが強さを動かさないことが、私の1実験でなく**複数の独立実験で収束**した。

**A. value の target/形は arena で全て parity (私の実験 + パイプライン自身の実験):**
| arm | ref | win | 出典 |
|---|---|---|---|
| value_multihorizon | binary_control (同25k, target設計のみA/B) | **0.475** | 本セッション実験 |
| value_multihorizon | agnostic(EBV2固定) | 0.518 | 〃 |
| value_rollout | value_outcome (rollout target vs 終局 target) | **0.496** | パイプライン iter167 |
| value.pkl (v20, 94dim card-aware) | agnostic | **0.47〜0.52 で振動** | iter137〜191 |

→ **outcome / rollout / multihorizon / binary、 どれも ~0.5**。 = 「多ターンをどう畳んで target にするか / 出力の形」は
強さに対して**閉じている**([[project_multi_eval_functions]]「単一state系は全て閉じた」の再確認、 このセッションで独立3実験追加)。

**B. 特徴を card-aware に richen しても arena は動かない (AUC↑ ≠ 強さ):**
feature は既に v15→**v20 (94dim)** まで card-aware に成長済 (駒種ラベル + 機能×timing + matchup interaction + belief 残カウンター +
除去射程)。 AUC は v18 0.8286→v20 0.8323 と上がるが、 **value.pkl は agnostic(21dim 盲目)と arena parity**。
= richer feature は **ranking(AUC)を上げるが decision(argmax)を変えない** ([[feedback_auc_is_not_decision_quality]])。

**C. ExIt policy 蒸留は top1↑ でも配備を超えない (top1 ≠ 強さ):**
ExIt flywheel の held-out top1 一致率は 0.57→**0.71** と上昇 (探索の最善手を policy が 71% 再現) だが、
`exit_policy_w=0.6` の arena は **A_wr=47%**(配備に僅敗)。 = 模倣精度 ↑ は強さ ↑ を意味しない。 探索を導く value が
card-blind なので、 探索自体が強くならず、 蒸留先の policy も plateau。

**統合診断**: value/policy を richen する全ルート (target-form / feature-enrich / policy-distill) が **AUC・top1 は上げるが arena は
上げない** = 共通の天井。 理由=**決定に効くのは「候補手の間で値が変わる board-interactive な差」だけ**で、 グローバルな ranking 精度は
ほとんどの局面で argmax を変えない ([[project_card_identity_in_decisions]])。 歴代の勝ちレバー (v6 matchup interaction /
block_residual 塊帰結 / force-attack / counter-event 生存 fix) は全て**決定層 board-interactive**だった。

**correctness 確認 (CORE DIRECTIVE)**: lethal の card-knowledge 補正 (`_recovery_defense_bonus`) は完全 —
`recovers_at_zero` LEADER は Enel(OP05-098)のみで hook 済、 ko_immune(73)/negates(22)は全てキャラで lethal 公式
(実効ライフ+カウンター)に嵌らない (無理に入れると no-op か誤り)。 = メモの「ko_immune lethal hook」案は**式に不適合**を精読で確定
(gap なし、 [[project_pros02_puzzle_benchmark]] の「盛り不足は実は妥当」と同型の検出規律)。

**結論の更新 (§5 を上書き)**: 「効率的に多ターンを畳む value の新しい形」= **target/input/output の形いじりでは達成されない (閉)**。
既に達成済の効率形は **block_residual (self-play 塊帰結 target → O(1) 配備スカラー、 +2.2pt)** = offline に多ターンを畳み deploy は O(1)。
残る真フロンティアは 2 つに絞られ、 **両者とも配備 AI を触るので arena gate + ohtsuki の steer とセットが筋**:
  1. **決定層の card-aware 脅威テーブル** (corpus から「相手盤面のどの効果が終局勝率を最も動かしたか」をデータ化 → opp_threat に
     board-interactive 配線)。 = read-only 分析で作れる (regression リスクなし)、 [[project_card_identity_in_decisions]] の「rollout で脅威度表をデータ化」。
  2. **value を小 NN 化 (embedding + MLP)** = カード identity の微差 (eiv1_features.py が明記する成長ピース、 corpus 2.6GB で data 前提は満たす)。
     ⚠ ただし A/B の天井 (AUC↑≠強さ) と [[project_plan_d_results]] のスケール失敗を踏まえ、 embedding が **argmax を変える**ことを
     de-risk してから (= 決定層で効くことを先に確認)。

## Sources
- [Averaging n-step Returns Reduces Variance (2402.03903)](https://arxiv.org/html/2402.03903v4)
- [Leela WDL head](https://lczero.org/blog/2020/04/wdl-head/)
- [Visualizing MuZero Models (2102.12924)](https://ar5iv.labs.arxiv.org/html/2102.12924) / [What model does MuZero learn (2306.00840)](https://arxiv.org/pdf/2306.00840)
- [Efficient Multi-Horizon Learning (OpenReview 7Se_75p9dVA)](https://openreview.net/forum?id=7Se_75p9dVA)
