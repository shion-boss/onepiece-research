# 人間並みにカードを使いこなす対戦AI — 実装プラン (handoff)

> 2026-06-08 確定 (ohtsuki)。 セッションクリア → 再開用の handoff。
> 再開時はまず本書 + memory `project_superhuman_ai_distillation` + `project_combo_aware_ai` を読む。

## 0. 目標と前提

**目標**: 「研究に使える妥当なAI」ではなく **人間並みにカードを使いこなす対戦AI**。
**前提合意**: 天井は不明・人間並みの保証なし・数ヶ月規模の研究課題。それでも下記が唯一筋の通った賭け。

## 1. 根本診断 (なぜ今のAIは弱いか)

今のAIが持つのは3つだけ:
1. ルールエンジン — 効果が「何をするか(WHAT)」を正確に実行 (overlay、 4518枚 100%)。
2. board評価 (GBM/線形) — 結果盤面を点数化。
3. 探索 (ExploitBeam: beam + post-opp + GBM)。

**欠けているのは「各カードの効果を、いつ・どう使うのが有効か(HOW/WHEN)」の理解**。だから探索で偶然良い手に当たるのを待つだけ。良いplayには次の3軸の理解が要る:
- **効果セマンティクス**: duration / cost / trigger を読んで価値を測る。
- **時間幅 (horizon)**: クロスターン (DONは自ターンにしか付かないが効果は相手ターン) / 攻撃フェーズ全体 (duration:turn は残り攻撃数で価値が変わる)。
- **相手モデル**: 相手は可視情報 (盤面のDON等) で行動を変える → ブラフ/牽制。隠れ情報 (手札) で「使えるかも」と恐れさせる。

**症状例 (実測)**: 青黄ナミ(A tier)が AI で calgara に ~30%。リーダーのドローエンジン未稼働 / 防御+2000 を防御に活かせない / calgaraリーダーを序盤に殴って相手の life→hand を太らせる。= 全部「使い方を知らない」。

## 2. 鉄則 (この会話で確立。次セッションで踏むな)

1. **deterministic bias / 手コーディング patch は dead-end**。4518枚にスケールせず、AIが理解したことにならない (whack-a-mole)。value を直接歪めると自滅 (deck_play_knowledge bias を per-side A/B したら、効くどころか使ったデッキが弱体化と実証)。
2. **消費は policy prior (探索誘導) + value 特徴 (GBM)。value を歪める bias にしない。**
3. **A/B は env-global (両者ON) でなく per-side で測れ**。さもないと「相手の自滅」を「自分の改善」と誤認する (今回、calgara で +38pt と誤報告した — 実は calgara が自分のDKで弱体化していただけ)。
4. **検証は手の質 + 勝率の両方**。raw 勝率 ≠ デッキ/AIの良し悪し ([[feedback_evaluation_axis]])。matrix #1 (calgara) は「最強」でなく「AIが一番無難に回せる単純デッキ」。
5. **pure self-play はスケール不足** (Plan D で4-5桁不足確定)。→ **LLM bootstrap が必須**。
6. **deep offense / shallow defense の非対称**: 配備は ExploitBeam だが `choose_defense` は override 無しで **GreedyAI を継承** (ExploitBeam→DeepPlanningAI→GreedyAI、 ai.py:1433)。防御の妙が出ないのはここ。

## 3. アーキテクチャ: LLM-knowledge-bootstrap AlphaZero-lite

pure self-play で mastery に届くスケールは無い。だが **LLM (カードを理解) + 100%エンジン** がある。
→ **LLM の card 理解を「教師の事前知識」として注入し、self-play で較正する。** AlphaZero 構造 (policy + value + search + self-play) に LLM 知識を prior として入れ、データ要求を桁で下げる。

```
LLM が各カードの usage 理解を導出 (ナミ分析の全カード版)
   ├─(a) policy prior  → 探索を「良い手」へ誘導 (plan_search の既存 _W_POLICY 口)
   └─(b) value 特徴    → 防御/エンジン/コンボ準備度を GBM へ
        │ self-play で較正 (LLMの誤りを経験が修正、 bootstrap で少データ)
        │ 両側 effect-aware opponent model (ブラフ/牽制が成立)
        ▼ distill して高速プレイ → deploy → 再収集 → iteration
```
※ 旧 handoff (2026-06-03) の「beam教師→pure_lookup蒸留」も policy iteration の一部として両立。違いは **prior の源を LLM 知識にする** こと。

## 4. 既存資産 (ゼロからでない)

- `engine/` 100%エンジン (シミュレータ完成、 RuleReferee)。
- `engine/gbm_value.py` GBM value + rich features (= 効いた唯一のレバー、 [[project_70pct_vs_greedy]])。
- `engine/plan_search.py` の **`_W_POLICY` (policy-prior 差込口、 現状未使用、 env `ONEPIECE_PLAN_POLICY_W`)** ← LLM policy prior をここへ。 同様に Plan A/Imit/G/H の bias 注入パターンあり。
- `engine/deck_play_knowledge.py` + `scripts/build_deck_knowledge.py` (branch `feat/combo-awareness`) = コンボ/各カード usage を DSL から導出。**知識抽出の素材として再利用可。 ただし deterministic bias 消費 (Plan K hook) は捨てる** (効かないと実証済、 既定OFF)。
- self-play corpus pipeline / `scripts/measure_combo_execution.py` (実行率測定)。
- `db/tier_truth.json` = 実メタ tier の正解 → matrix との乖離が「AIの不均一さ=改善ロードマップ」。
- goldfish (一人回し) 案 = 相手ノイズ抜きで「攻めの発展」を学ぶ (防御/ブラフは相手要なので別)。

## 5. 段階プラン (各段は検証ゲート通過で次へ)

### Phase 0 — 最小・最重要リスク試験 (次セッションの着手点)
**問い**: 「LLM理解を正しく消費 (policy prior + value特徴) すれば、手が測定可能に良くなるか?」
- deck = `cardrush_1439` (青黄ナミ)、 benchmark = `tcgportal_calgara` (#1) + field。
- **ナミ usage 知識 (済分析、 §6)** を policy prior + 3-4 value特徴に落とす。
- ExploitBeam に配線 (value歪曲でなく prior/特徴)。
- **rigorous per-side A/B**: 手の質 (ドローエンジン稼働率 / DON温存率 / 防御+2000活用率) + ナミ対field勝率。
- 前回 calgara 失敗の3要因を正す: 誤消費(value歪曲)→policy prior / 得意な calgara→下手なナミ / env-global→per-side。
- **通過判定**: 手の質が明確改善 かつ 勝率が悪化しない。

### Phase 1 — 16デッキへ展開 + 較正
- LLM 知識抽出を16デッキの全カードへ。self-play で prior/value を較正。
- **通過判定**: matrix が `tier_truth` に近づく (= ohtsuki 収束理論の実証。 calgara #1 が崩れ実 tier へ)。

### Phase 2 — 相手モデル + 防御深化
- 両側 effect-aware opponent model (ブラフ/牽制)。`estimate_opp_attack_buff_to_leader` を「可視DONで条件付け・隠れ手札は最悪仮定」に。
- 防御を GreedyAI の浅い heuristic から **learned value 駆動の deep 評価** へ (choose_defense を効果セマンティクス+horizon対応に、 ただし手コーディングでなく learned)。

### Phase 3 — 全カード + 蒸留 + iteration
- 知識を属性パラメタ化して全4518枚へ汎化。distill で高速化。policy iteration で反復強化。

## 6. ナミ usage 知識 (Phase 0 用、 済分析)

リーダー OP11-041 ナミ (青/黄, life4, P5000):
1. **【自ターン】【ターン1回】ライフが離れた時 (手札≤7) → 1ドロー**: 自分のライフを能動的に離す札と連携して回る **ドローエンジン**。AIは未稼働 (ライフを離す動きをしない)。
2. **【DON‼×1】【相手アタック時】【ターン1回】手札1枚捨て → リーダー+2000 (duration:turn)**: **防御**。(a)DON温存=自ターンに攻撃でなくリーダーへDONを残す仕込み (b)duration:turn なので**残り攻撃数が多いほど価値高、 ラッシュの早い段階で発動** (c)可視DON+隠れ手札で**ブラフ牽制** (使えなくても相手の判断を鈍らせる)。
3. **対 calgara**: 序盤に calgara リーダーを殴ると life→hand を太らせる (相手のエンジンに塩) → 疑問手。

policy prior 候補: 「相手ターンに備えDONをリーダーに温存」「ライフを離す札を撃つ (draw誘発)」「除去/ブロッカーを構える」を探索優先。
value 特徴候補: `leader_engine_armed` (overlay の if/cost から導出、 全リーダー汎用) / `don_reserved_on_leader` / `opp_life_to_hand` / `turn_pump_payoff = 残り攻撃数 × pump`。

## 7. repo 状態 (handoff 2026-06-08)

- **main**: PR#24 merged (観戦UI 共有盤面/全画面/ホバー/盤面データ/攻撃・カウンター・ドン付与・防御アニメ + 実践AI全経路統一 SmartOpponentAI) + ステージ「0」表示修正 + 攻撃矢印を解決演出に重ねる。最新 ~`e1d478c`。
- **branch `feat/combo-awareness`** (未merge): deck_play_knowledge (combos/usage 生成器 + 実行時 module + plan_search Plan K hook 全OFF) + 知見「deterministic bias は効かない」。= 素材として参照、 bias 消費は捨てる。
- 配備AI: 全経路 SmartOpponentAI (全16 ExploitBeam、 deploy_results)。matrix = `SmartOpponentAI_deployed`。
- 観戦/人間vsAI/matrix/deck対戦ランナー = 全て SmartOpponentAI で統一済。

## 8. 着手順 (次セッション)

1. 本書 + memory (`project_superhuman_ai_distillation`, `project_combo_aware_ai`, `feedback_evaluation_axis`, `project_70pct_vs_greedy`) を読み状況復元。
2. **Phase 0**: §6 のナミ知識を policy prior 形式 (どの状況でどの行動を探索優先) に落とす → `plan_search` の `_W_POLICY` 類似口に配線 → value特徴を `gbm_value.py` に追加。
3. per-side A/B (手の質 + 勝率) で通過判定。通れば Phase 1 へ。
4. ⚠ 鉄則 (§2) を厳守。特に「value歪曲bias禁止 / per-side測定 / 手の質も見る」。
