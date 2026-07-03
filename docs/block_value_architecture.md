# 塊(ターン)単位 value アーキテクチャ — 再設計

> 2026-07-02。 「評価が不適切/単発が間違い/value=探索の産物/本番は浅く/評価単位=ターン塊」
> の議論が収束した設計。 静的 1-ply の単発 MC value を捨て、 **ターン塊(round)の帰結**で
> value を評価・訓練する。 高評価の塊 = コンボ(創発的発見)。

## 1. 動機:なぜ現 value が不適切か

現 value(`value_gbm_<slug>.pkl`)は **各局面に最終勝敗をそのまま貼る単発 Monte Carlo**:
- **noisy**(結果論): 負け試合の良い手にも 0、 まぐれ勝ちの悪手にも 1 → 大量データが要る(= 学習不足を悪化)。
- **plan-blind**: 「良いプランを打てば勝つ」の *プラン依存* が単発局面ラベルで消える。
- **例(核心)**: ①DON付与→攻撃 と ②攻撃→レストキャラにDON付与 は質が全く違う(②は DON 無駄)のに、
  単発 value は attached_don を数えるだけで **区別できず ②を penalize しない**。

実証(2026-07-02): feature追加(v10)/calibration再学習(配備分布)/policyデータ(Claude手打ち)を
片っ端から A/B → **全 null か negative**。 = **静的単発 value 路線は天井**。 根治は target と単位の再設計。

## 2. 核心原則

**評価の単位 = ターン塊(round)。 value の target = 塊の帰結。 高評価の塊 = コンボ。**

- 単発の局面 value でなく、 **プラン(行動列)を、その帰結(数手先)で評価**する。
- value の教師 = 生の最終勝敗でなく、 **塊の帰結(探索でブートストラップした逐次 target)**。
- 探索は **訓練時に** 良い塊を生成して value に焼き込む。 **本番は浅い先読み + その value**(runtime 探索を最小化)。

## 3. 4 ブロックの round 構造

1 round = 自ターン + 相手ターン を、 proactive×reactive × 自×相手 で 4 塊に分ける:

| ブロック | 中身 | 現 engine の対応 |
|---|---|---|
| ① 自ターン・自行動 | 自分のプラン(展開/DON/攻撃/効果) | `search_turn_plan`(beam) |
| ② 自ターン・相手行動 | 相手の受け(カウンター/ブロック) | `choose_defense`(post-opp) |
| ③ 相手ターン・相手行動 | 相手のプラン | `_simulate_opp_turn`(post-opp) |
| ④ 相手ターン・自行動 | 自分の受け(防御/カウンター) | `choose_defense`(post-opp) |

**ExploitBeam の post-opp eval は既に ①②③④ の 1-round 版**(commit 群)。 = ゼロからでない。

## 4. Q(state, plan) と V(round-end)

- プラン評価 = **Q(state, plan) = V( ①②③④ を解決した後の round-end 状態 )**。 塊探索は Q でプランを順位付け。
- Plan①(DON→攻撃)→ round-end が良い盤面 → Q 高。 Plan②(攻撃→DON無駄)→ round-end が弱い盤面 → Q 低。
- **葉の V が round-end 状態を正確に評価**できれば、 塊探索が Plan①>Plan② を正しく選ぶ。
- = 現 ExploitBeam の post-opp と同型。 **足りないのは V の訓練 target(下記)。**

## 5. 【最重要】value の target を「単発 MC」→「塊帰結(探索ブートストラップ)」に

現: `V(局面) ← 最終勝敗(0/1)` = 単発 MC。 **これを捨てる。**

新: `V(局面) ← 塊の帰結値` の 2 系統(併用):
- **(a) 探索値ブートストラップ(AlphaZero 型)**: `V(局面) ← 配備 ExploitBeam がその局面で計算した post-opp 値`
  = 探索が改善した値を V に焼く。 反復で V が探索を吸収。
- **(b) n-step / round TD**: `V(round開始) ← γ·V(次round開始)` = 塊の帰結を逐次伝播。 低分散(サンプル効率↑)。

**訓練は配備 policy(ExploitBeam)の self-play で**(rollout policy ≠ 配備 policy だと効かない、 [[project_rollout_gbm_value]] の教訓)。 反復(value → 探索で強い塊 → V 再訓練)。

## 6. コンボの創発的発見

- **①(自ターン行動列)で最も Q が高い塊 = 諸行動が噛み合う = コンボ。**
- 塊探索が「最も高い行動塊」を探す = **コンボの emergent 発見**(型ベースの `combo_finder` より強い)。
- 用途 2 つ: (a) AI がコンボを打つ、 (b) **product**(コンボ発見 → デッキ研究/攻略記事、 [[project_deck_guide_monetization]])。
- 実装: 塊探索で Q が突出したプランを `db/_analyst/combos_<slug>.jsonl` に記録(行動列 + Q + 頻度)。

## 7. 何が在り、 何が新規か

| 要素 | 状態 |
|---|---|
| 塊探索(①②③④ 1-round) | ✅ ExploitBeam post-opp に在る |
| プラン探索(① beam) | ✅ `search_turn_plan` |
| **V の塊帰結 target 訓練** | ❌ 新規(現 = 単発 MC) ← 本丸 |
| **コンボ抽出** | ❌ 新規 |
| 塊探索の多 round 化 | △ `POSTOPP_TURNS` 有るが opt-in |

## 8. 実装フェーズ

**Phase 1(本丸・最優先): V を塊帰結 target で再訓練**
1. `scripts/gen_block_value_targets.py`: ExploitBeam self-play を打ち、 各局面で
   (state feat v6, post-opp探索値, n-step帰結値, 最終勝敗) を記録。
2. `scripts/train_block_value.py`: 探索値ブートストラップ target で GBM/回帰を訓練 → `value_gbm_<slug>_block.pkl`。
3. A/B(`gbm_path` 強制、 配備ミラー): block-value vs 現配備 value。 効けば配備。
4. 反復(新 value で self-play → 再訓練)。

**Phase 2: コンボ抽出**
- 塊探索で Q 突出プランを記録 → combos_<slug>.jsonl → AI ヒント + product。

**Phase 3: 塊探索の深化**
- 1-round → N-round(`POSTOPP_TURNS` 拡張)。 塊 value が良くなった前提で深く。

## 9. 正直な caveat(天井)

- **compute 律速**: 塊探索(①②③④ × 多 round)+ 反復訓練 = ExploitBeam self-play 大量 = 遅い。 あなたの制約の本丸。
- **葉 V の品質が依然律速**: 良い塊(良いコンボ/control 線)が訓練データに無いと V が学べない(循環)。 塊構造は探索を整理するが、 **良い線を訓練に入れる問題は残る**(= compute か 良い教師)。
- **calibration ≠ ranking**: target を変えても play 改善は A/B で要確認(単発 MC 再訓練は悪化した実績)。
- **段階的に**: Phase 1 の block-value A/B が効くかを最小で確認してから深化(scale 前に prove、 本セッションの規律)。

## まとめ

**評価単位を round 塊にし、 V の target を塊帰結(探索ブートストラップ)にして配備 policy で反復訓練、
高評価の塊をコンボとして抽出。** ExploitBeam の post-opp が土台。 本丸 = Phase 1(V の塊帰結訓練)。
静的単発 value 磨き(全 null)を捨て、 target のつけ方そのものを変える。
