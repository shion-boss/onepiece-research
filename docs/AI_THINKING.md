# 対戦 AI の思考プロセス (人間レビュー用)

> このドキュメントは OPTCG 上級プレイヤーが「AI の判断が正しいか」を検証できるよう、
> 実装の決定ロジックを日本語でまとめたもの。 実コードは `engine/ai.py` / `engine/plan_search.py` /
> `engine/eval.py` / `engine/hand_estimator.py`。
>
> **検証してほしい観点**
> 1. 行動優先順位は妥当か (= キャラ出すべき場面で攻撃してないか、 逆に温存すべき盤面で焚いてないか)
> 2. 評価軸 (= board_eval 15 指標) の **重み比率** は実戦の重要度と乖離してないか
> 3. 「リーサル判定」 「カウンター切る基準」 が公式ルール / 上級者の判断と合っているか
> 4. 「ライフトリガー雷迎を見越して攻撃を抑える」 等の メタ判断 が機能してるか
> 5. アーキタイプ別 (アグロ/ミッド/コントロール/ランプ) のパラメータ調整は妥当か

---

## 0. AI の全体構造

2 段重ね:
1. **GreedyAI** (基底クラス) — 1 手ごとに「次に打つべき最良の行動」 を局所判断する。 ルールベース。
2. **PlanningAI** (default、 GreedyAI を継承) — MAIN フェーズ開始時に **ターン全体の行動列を beam 探索**、
   終端の盤面評価が最も高いプランの 1 手目を返す。 次手は再計画 (= receding horizon)。

防御 (= 相手から殴られた時の counter / blocker 決定) は両者とも GreedyAI のロジックを使う。

```
choose_action (= 「次の 1 手は？」)
   ├── PlanningAI: beam search で plan 探索 → plan[0] を返す
   │       └── plan 探索の中で対戦相手の choose_defense を呼んで counter 反映
   └── GreedyAI: 下記の優先順位リストで 1 手選ぶ
```

---

## 1. GreedyAI の行動優先順位 (= 各 1 手の判断フロー)

`choose_action(state)` は以下の順序で「打つべき行動」 を探す。 上位で見つかれば即 return。

### Step 0: 起動メイン (= リーダー / キャラの 【起動メイン】 効果)

- **コスト 0 の起動メイン**: 即発動 (= ロスなし)
- **ドン消費型** (例: 緑紫ルフィ「ドン-2 +untap_don 2」):
  - **ドン相殺型** (= 支払い ≤ untap_don / add_don の合計): 「ドン再投資先」 と
    「power_pump 価値」 をチェック。 再投資先 (= untap で初めて出せるカード) があれば発動、
    なければスキップ (= 浪費判定)
  - **純粋ドン消費型**: 効果発動前後で `compute_score` を比較、 delta > 0 なら発動
- **untap 系で `don_rested = 0`** (= 起こせるドンがない) なら **後回し**:
  キャラ play / 攻撃で don_rested を貯めてから再評価 (Step 3)
- 学習ゲート: `activate_main_don_compensated_strict` / `activate_main_min_payoff_global`

**OPTCG 文脈**:
- 紫エネル の起動メイン (= ドン+1+4 + 付与) はコスト 0 系として常に発動
- 緑系の「ドン-2 → 起こす + 何か」 系は「起こした後に出せるカードがあるか」 で判断
- ドン浪費系 (= 単に焚くだけで再投資先なし) は **発動しない** が正解として実装

### Step 0.5: イベント

- **撃てるイベントは安い順で消化** (= リソース消費を抑える)
- 注意: イベントの効果価値は judge せず、 「打てるなら打つ」。 これは荒い判断で改善余地あり。

### Step 0.7: ステージ

- 自場にステージ無し かつ 手札のステージ最安を play
- 差替判断はしない (= 既存ステージがあれば追加 play しない)

### Step 1: キャラ play (= 「コスト効率最大化」 + アーキタイプ補正)

候補カードに以下の優先順位:

1. **`keep_field_synergy_only` フィルタ** (= 起動メイン「場が特徴 X のみ」 条件保護):
   - 場が既に全部シナジー特徴のキャラなら、 シナジー外 play は条件を壊すので除外
   - 場が空なら 1 体目は必ずシナジー特徴で建てる
   - 紫エネル の「自分のキャラが《空島》だけならドン加速」 等を破壊させない
2. **`early_finisher_hold` フィルタ** (= 高コストフィニッシャー温存):
   - 自ライフ ≥ `finisher_hold_life` (デフォルト 3) なら finisher を **手札に温存**
   - 中盤に finisher を切ってしまうと終盤の押し込み力が落ちる
3. **`synergy_feature_priority`** (= 特徴シナジー):
   - 該当特徴を持つカードがあれば、 そこから選ぶ
4. **ソート順** (= 同じ特徴フィルタ後の選び方):
   - tier (= 相手 archetype に対する role 有効性 70+ なら 1、 そうでなければ 0)
   - effectiveness 値 (= card_role の compute_effectiveness)
   - cost 降順 (= 大型カード優先 = コスト効率最大化)
   - intent_score (= card_intents.json の状況適合度、 同 cost の tiebreak)

**OPTCG 文脈**:
- 「6 コストドン全部で 6 コスト 1 枚 vs 5+1 で 2 枚」 の選択肢で大型優先 = コスト効率重視
- 「相手がアグロなのに自分も blocker を切ってしまう」 を防ぐため role priority を反映

**懸念点**:
- カウンター期待値 / 場の連動 (= 既出キャラの効果と連動するか) は **見ていない**
- 「キャラ play vs 起動メイン」 の比較は限定的 (= 起動メイン Step 0 で正のみ採用)

### Step 2-pre: リーサル判定 (= 「このターンで勝てるか?」)

`_compute_lethal_action` で以下を厳密に計算 (キャラ KO より優先):

1. 各リーダー攻撃候補について「DON を何枚付与すれば届くか」 計算
   - `dons_needed = ceil((opp_leader_power - attacker_power) / 1000)`
   - 既存付与 + 必要付与 > 4 なら除外 (= ドン上限)
2. DON 予算 (= `me.don_active`) で支払える攻撃を選ぶ (= 必要 DON 安い順)
3. 上位 `hits_needed` (= max(1, opp.life)) 攻撃の合計 excess を計算
4. 相手の **期待カウンター総量** を `hand_estimator` で推定 (= deck + hand プールの平均カウンター × 手札枚数)
5. 1.2x 余裕マージン込みで `total_excess >= 1.2 × est_max_defense` ならリーサル成立
6. リーサル成立時の動き:
   - DON 付与が必要な attacker があれば、 まず 1 枚付与
   - 全部届くなら 最大 excess 攻撃から (= 確実に通す)

**OPTCG 文脈**:
- 「相手のカウンター見て、 1.2 倍読みで突っ込む」 は強気の判定。 1.0 で打ち負ける読みは含めない
- ダブルアタックは無視 (= simplification)
- バニッシュは無視 (= life→hand を計算してない)

**懸念点**:
- カウンター推定は **平均値** ベース。 「2000 を切ってくるか 1000 か」 のバラ付きは反映してない
- 相手の blocker は計算に入ってない (= 防御で blocker を切られると 1 ヒット潰される)

### Step 2a: キャラ KO 狙い (= 相手キャラを倒す)

- 自 attacker.power ≥ target.power を満たす組合せから候補
- ただし **near-lethal (相手ライフ ≤ 1)** で リーダー攻撃 viable があれば、 **リーダー優先** (= 詰めに行く)
- ソート優先順位 (max を選ぶ):
  1. target の role が `finisher` / `removal` / `negation` なら +1 boost
  2. target.cost (高コスト優先)
  3. target.power (タイブレーク)

**OPTCG 文脈**:
- 「相手の鍵カードを優先的に潰す」 (= finisher / removal 系をマーク)
- 高コストキャラを潰すと相手のテンポロスが大きいので cost 優先

### Step 2b: ドン付与で leader 攻撃を成立 (= 1 ドンで届くものを優先)

- `gap = opp.leader.power - attacker.power` が `0 ≤ gap ≤ 1000` なら 1 ドンで届く
- 小さい gap 優先 (= 1 ドンで成立)、 同 gap なら attached_dons 少ない方
- 該当 attacker に AttachDon を返す (= 次の手で攻撃)

### Step 2c: リーダー攻撃判定 (= 「届くものから攻撃」)

- 実効攻撃力 `attack_threshold = opp.leader.power + attack_gap_tolerance`
  - tolerance はアーキタイプ別: アグロ -2000 / ミッド (= 学習) / コントロール 0 / ランプ 0
  - tolerance < 0 = power 不足でも攻撃 (= counter を強制消費させる)
- 高コスト attacker (cost ≥ 5) に対しては **ライフトリガー雷迎のリスク** を見積:
  - `estimate_opp_life_trigger_attacker_ko_risk` で「攻撃が雷迎で KO される期待損失」
  - リスク > 1500 × 1.5 なら攻撃を控える (= リーダー +1500 を取りに行く意味より高コスト失う方が損)
- リーサル成立 (Step 2-pre と同じ判定) → 最大 excess から攻撃
- 非リーサル → **弱い attacker から攻撃** (= 相手の counter 抗力を消費させる)

**OPTCG 文脈**:
- 「6 コストキャラで攻撃 → 雷迎ライフトリガーで KO される」 を避ける = 上級判断
- 「弱→強」 攻撃順は教科書通り (= 相手の counter を引き出してから本命を通す)

**懸念点**:
- 「ダブルアタック」 持ちは打点 2 で扱われない (= 単発攻撃扱い)
- 速攻でリーダーじゃなくキャラに殴る判断はしてない

### Step 3: 後回し起動メイン再評価

- Step 0 で「don_rested 不足で後回し」 にした untap 系を、 play / 攻撃で増えた don_rested 込みで再判定

### Step 4: EndPhase

---

## 2. PlanningAI (= ターン全体プラン beam search)

### 動作

1. MAIN フェーズ開始時に `search_turn_plan(state, ai_opp, beam_width=4, max_depth=6)`
2. 「現状態 + EndPhase 到達 / max_depth まで」 を探索
3. 各候補手で:
   - 状態を fast_clone (= GameState の軽量 deepcopy)
   - 行動を apply。 攻撃なら `ai_opp.choose_defense` を呼んで counter / blocker を差し込み
   - 終端で `compute_score` 計算
4. 各深さで上位 `beam_width=4` のみ残す (= 指数爆発抑制)
5. 終端 score 最良のプランを返す → 1 手目を採用 (= 次手は再計画)

### 何を解いている?

GreedyAI の「event → キャラ → attack」 と固まった順序を捨て、 **行動列のコンボ** を見られる:
- 「ハンド剥がし → 通すアタック」
- 「event 効果でドン回収 → 大型キャラ play → 攻撃」
- 「キャラ play → 起動メイン (= 場のキャラ条件発動) → 攻撃」

### 設定値 (`engine/ai.py` PlanningAI):
- `beam_width = 4`: 各深さで残す候補数。 大きいほど幅広く探すが指数的に遅くなる
- `max_depth = 6`: プラン長上限。 ターン中の総 action 数 (= 起動メイン+ play 数 + 攻撃数)
- 速度: Greedy 比 ~5x slow (= 2-5s/game vs 1s/game)

### 終端の盤面評価 (`compute_score`) で何を見ているか

= 次の節「board_eval 15 指標」 へ

**懸念点**:
- **「コンボ 1 手目で中間 eval が下がる手」** を許容する設計 (= 終端のみ見るので「布石」 はスコア下がっても OK)
- ただしこれが bad_move_rate 6.07% (Greedy 4.08%) の悪化原因。 「真の悪手か布石か」 を区別できてない
- **「相手の counter を全部使わせる」** 系の長期コンボ (= 3-4 手目で利得) は depth=6 で見えるはずだが、
  branching factor が大きい (~13) ので網羅できないケースあり
- **「赤緑クリーク」 のような ramp 系**: ドン加速の長期価値が terminal eval に出ない (= -2pt 残存)

---

## 3. 盤面評価 (board_eval) — 15 指標

`compute_score(state, me_idx)` は me 視点で 各指標の (self - opp) × weight を合計する。
weight は `db/ai_params.json` で調整可能 (= 学習対象)。

| # | 指標 | 重み | 意味 |
|---|---|---|---|
| 1 | life | **1500** | ライフ枚数差 |
| 2 | field_count | **1200** | 場のキャラ数差 |
| 3 | field_power | 1 | 場のパワー総和差 (= 細かい補正) |
| 4 | hand | 250 | 手札枚数差 |
| 5 | don | 200 | DON 総数差 |
| 6 | blocker | 800 | ブロッカー数差 |
| 7 | attached_don | 400 | 場のキャラに付与されたドン総数 |
| 8 | active_chara | 600 | アクティブキャラ数 (= 攻撃可能) |
| 9 | lethal | **5000** | リーサル成立度 (0.0〜1.0、 sigmoid) |
| 10 | opp_next_lethal | **-4000** | 相手の次ターン lethal 推定 (= 自分が殺されるリスク) |
| 11 | deck_finisher | 150 | 残デッキ内 finisher 数 (= 後続の打点) |
| 12 | life_trigger | 200 | 自ライフ内トリガー価値 (= 受けてもいいか判断) |
| 13 | chara_quality | 400 | 場のキャラ role 別合計価値 (= finisher 多 vs vanilla 多) |
| 14 | hand_quality | 150 | 手札の role 別合計価値 |
| 15 | opp_hand_threat | -300 | opp.hand 隠匿脅威推定 (= プール平均役割価値 × 手札枚数) |

ゲーム終了は別重み `W_GAME_OVER = 1,000,000` で決定的に扱う。

### lethal 指標の計算

```
attackers = [me.leader, ...me.characters (active かつ未召喚酔い)]
total_excess = Σ max(0, atk.power - opp.leader.power)
opp_defense = len(opp.life) × 5000 + 期待カウンター総量
ratio = total_excess / opp_defense
lethal = sigmoid(2 × (ratio - 1))
```

= 自分の打点 ≥ 相手の防御力 + 余裕 で 1.0 に近づく。

### opp_next_lethal (= 自分が殺されるリスク)

opp の次ターン (= rest/sickness 解除前提) の総打点 vs 自分のライフ + カウンターを同公式で計算。
攻撃禁止 (`cannot_attack_static`) のキャラは除外。

### 手札の質 (chara_quality / hand_quality)

card_role db で各カードに primary_role を付与:
- finisher: 3.0
- removal / negation: 2.5
- blocker / disruption: 2.0
- recovery / ramp / draw / search: 1.5
- synergy: 1.0
- vanilla / 不明: 0.5

役割 × 枚数 = 場 / 手札の「中身の良さ」。 これがないと「7-cost vanilla = 7-cost finisher」 になっちゃう。

### opp_hand_threat (= 隠匿モデルの脅威推定)

opp.hand は本来見えない情報。 代わりに **未公開プール (opp.deck + opp.hand)** の役割別平均価値を計算し、
手札枚数倍で「相手が finisher を何枚隠し持ってるか」 を期待値推定。

= ハンド剥がし系の価値判断に効く。

**OPTCG 文脈**:
- 「相手のライフが 1 なのにライフ詰めずに場を整える」 は eval 上でも life=1 維持に高い価値が出るが、
  lethal 指標が同時に高くなるので「詰める方が大きい」 と判定される
- 「相手が次ターンリーサルなら自分も急ぐ」 は opp_next_lethal が大きく不利に出るので反映されてる

**懸念点**:
- field_power の重み 1 は ほぼ無視に等しい (= 1000 power 差 = 1000 = blocker 1 枚以下)。
  これは意図的 (= field_count + chara_quality で間接的に評価) だが直感に反するかも
- lethal の sigmoid は「リーサル直前」 を強く重視するが「2 ターン先」 の lethal は弱い
- attached_don 400 はやや過大かも (= 4 ドン付与 = 1600 pt = キャラ 1 体超え)
- deck_finisher 150 は控えめ (= finisher 残 4 枚 = 600 pt = blocker 1 体未満)

---

## 4. 防御判断 (`choose_defense`)

相手が攻撃してきた時、 「ブロッカー切るか」 「counter 何枚切るか」 を決める。

### ステップ 1: ブロッカー候補評価 (リーダー攻撃時のみ)

- `attacker.has_no_block_now` (= 【ブロック不可】) なら無視
- `attacker_prevents_blocker_until_turn_end` (= 一部効果でブロッカー禁止) なら無視
- 各 active blocker について:
  - `survives = blocker.power >= attacker.power` (公式 7-1-4: atk ≥ def で攻撃側勝ち、
    つまり blocker 視点では blocker.power **>** atk なら生存)

  **⚠ 実装注**: コード上は `blocker.power >= attacker.power` (= 同値で生存)、
  正しくは `blocker.power > attacker.power` のはず。 公式ルール 7-1-4 では 同値なら攻撃側勝ち。
- 生存ブロッカー優先で 1 体選ぶ。 生存しないブロッカーは life ≤ 1 でのみ「特攻ブロック」 (= 1 ライフ防衛)

### ステップ 2: attacker のリアクティブ自己強化を予測

- `estimate_attacker_self_buff(state, attacker, overlay)`:
  「相手アタック時 self/leader +N」 系の効果を実効攻撃力に加味
- これを忘れると「6000 攻撃に 1000 counter で 6000 vs 6000 = 攻撃成功」 で counter が無駄になる
- 公式 7-1-5-1 のバトル中処理を予測

### ステップ 3: counter 必要量計算

- `gap = effective_attacker_power - target_power`
- gap < 0 (= 既に守れる) → counter 不要
- それ以外 → `_optimal_counter_combo(hand, gap)` で **最小コンボ** を探索 (brute force、 2^11 まで)

### ステップ 4: 切るかどうかの判断

リーダー攻撃時、 アーキタイプ別の閾値テーブル `defense_thresholds[life_left]`:

```
ライフ 1: (99999, 99) = 致命的、 ありったけ切る
ライフ 2: ミッド (8000, 3) / コントロール (10000, 4) / アグロ (5000, 2)
ライフ 3: ミッド (6000, 2) / コントロール (8000, 3) / アグロ (3000, 1)
ライフ 4+: ミッド (2000, 1) / コントロール (5000, 2) / アグロ (0, 0)
```

= `(切れるカウンター合計上限, 切れる枚数上限)`。 両方クリアしないと切らない (= 受ける)。

シグナル微調整:
- `avoid_life_loss`: 閾値 × 1.5 + 枚数 +1 (= もっと切る)
- `tank_lifeup_ok`: 閾値 × 0.7 (= 受けて手札補充)
- attacker が finisher role なら 閾値 × 1.3 + 枚数 +1 (= 決め手は通すな)

キャラ攻撃 (= キャラ KO 阻止) は別ロジック:
- target.cost ≥ 4 かつ counter 1 枚 ≤ 2000 で切れるなら切る (= 高価値キャラだけ守る)

**OPTCG 文脈**:
- 「ライフ 4 で 1000 カウンターを 1 枚切る」 は **コントロール** だけがやる (= テンポ重視)
- 「ライフ 2 で 8000 カウンター 3 枚」 は **コントロール** はアリ、 **アグロ** はライフ 2 でも受ける
- counter 切る基準が「合計値」 と「枚数」 の両方で縛られるのは現実プレイヤーに近い

**懸念点**:
- ブロッカー判定の `>=` バグ (= 同値で生存扱い) は **公式ルール違反**。 修正必要かも
- 「相手の効果でブロッカーが生存しても KO される」 (= バニッシュ等) は反映してない
- 「2 枚 1000 counter vs 1 枚 2000 counter」 で同じ価値だが、 brute force は「合計値同点なら個数小」 を選ぶ
- counter 値が違う複数候補で「次ターンも counter ほしいから 2k を温存」 は実装してない

---

## 5. マリガン (初手キープ判断)

`engine/game.py:mulligan_decide` で `deck_analysis.mulligan_keep_card_ids` を参照:

- 初期 5 枚に keep 対象 (= analysis.json で指定された重要カード) が **1 枚以上含まれているか**
- 含まれていれば **キープ**、 なければ **マリガン**
- フォールバック (analysis なし): 「コスト 3 以下 1 枚 + サーチ/ドロー 1 枚 + 高コスト ≤ 2 枚」 の総合判定

**OPTCG 文脈**:
- 紫エネル なら OP15-076 (雷獣) / OP15-078 (万雷) などのドローパーツ + サトリ等の 1 コ
- 緑ミホーク なら OP14-020 リーダーの効果起点になる超新星カード
- 各デッキの analysis.json で keep ID を指定すれば反映される

**懸念点**:
- 「複数 keep ID から 何枚以上必要か」 は単純に 1 枚以上で OK にしてる
- 「高コスト 4 枚で手札枯渇」 のような「明らかな悪手」 を機械的に判定してない

---

## 6. ヒドゥンインフォメーション処理 (= 相手の手札推定)

`engine/hand_estimator.py` で「相手の手札は見えない」 という前提のモデル化:

- **公開情報**: opp.hand の枚数、 opp.deck + opp.hand のカード集合 (= プール)、 trash, play, life の公開済カード
- **隠匿情報**: プールのうち どの N 枚が hand に分配されたか

### 主要 API

| 関数 | 何を返すか |
|---|---|
| `expected_counter_per_card(state, opp_idx)` | プール平均カウンター値 |
| `expected_counter_total(state, opp_idx)` | 上記 × opp.hand_count |
| `probability_of_blocker_in_hand` | ハイパージオメトリック分布で「≥1 ブロッカー」 確率 |
| `sample_opponent_hand` | MCTS rollout 用、 無作為サンプル |

### 使われ方

- リーサル判定で「相手の使えるカウンター」 として総量を予測
- 防御判断 (= 自分側) では 自手札は完全可視なので使わない
- opp_hand_threat 指標 (= AI が「相手手札の危険度」 を間接推定)

**OPTCG 文脈**:
- 「相手が 5 枚なら 2000 カウンター 1 枚は持ってる前提」 は 期待値ベース
- 「相手のトラッシュにカウンター 5 枚行ってるから、 残りは薄い」 が自動反映される
- ただし「先攻 1 ターン目で 5 枚のうちカウンターない」 みたいなバラ付きは反映してない

**懸念点**:
- カウンター推定が **均一プール** 前提 (= デッキ内分布のみ考慮、 mulligan で偏る要素は無視)
- 「相手は《空島》軸だから、 大型 finisher を握ってる可能性高い」 のような role 別の偏り推定は弱い

---

## 7. アーキタイプ別パラメータ (= デッキの性格を AI に反映)

`decks/<slug>.analysis.json` の `archetype` フィールドで切替。 default は ミッドレンジ。

| archetype | defense_thresholds | attack_gap_tolerance | 備考 |
|---|---|---|---|
| **アグロ** | life 4: (0, 0) = 一切切らない / life 2: (5000, 2) | **-2000** (= power 不足でも攻撃) | ライフ詰め優先、 counter 控えめ |
| **ミッド** | life 4: (2000, 1) / life 2: (8000, 3) | 学習値 (default 0) | バランス、 default 挙動 |
| **コントロール** | life 4: (5000, 2) / life 2: (10000, 4) | **0** (= 等パワーで GO) | 受け重視、 攻撃機会を逃さない |
| **ランプ** | life 4: (3000, 1) / life 2: (8000, 3) | 0 | ドン加速優先、 prioritize_ramp = True |

### 構造化シグナル (ai_hint_signals) で 追加微調整

analysis.json の `ai_hint_signals` 配列で個別フラグを立てられる:

- `synergy_feature_priority: "空島"` → 該当特徴を優先 play
- `early_finisher_hold: ["OP15-118", ...]` → ライフ ≥ 3 で温存
- `counter_aggression: "high|mid|low"`
- `avoid_life_loss: true` → 防御閾値 × 1.5
- `tank_lifeup_ok: true` → 受け重視 × 0.7
- `blocker_scarce: true` → blocker を粗末に使わない
- `keep_field_synergy_only: "空島"` → 場をシナジー特徴で揃える
- `preferred_search_target_ids: [...]` → サーチ系効果の優先取得

**OPTCG 文脈**:
- 紫エネル は **アグロ寄りミッド** だが auto-classifier はミッドと判定
  → ai_hints で挙動修正してアグロらしく動かしてる
- 緑ミホーク (= 超新星デッキ) は中速のミッドだが
  「カウンター 2000+ 多」 ので tank_lifeup_ok で受けて手札増やす設定
- 黒イム / 青黄ハンコック = コントロール → ライフ受けまくる + 終盤フィニッシュ

---

## 8. MatchupProfile (= 対戦相手別の動作 override)

`db/matchup_strategies.json` で `(my_archetype, opp_archetype)` ペアごとに上書き可能:
- defense_thresholds
- attack_gap_tolerance
- finisher_hold_life (= finisher 温存ライフ閾値)
- role_priority (= 相手アーキタイプに対する各 role の有効性 0..100)

初回の `choose_action` で lazy-load。 同一試合中は再評価しない。

**OPTCG 文脈**:
- 「アグロ vs コントロール」 ではアグロは攻撃を緩めず、 コントロールは受け重視 = 王道の調整
- 「ミッド vs ミッド」 では細かい counter 押し合いになる = default 挙動

**懸念点**:
- profile JSON の中身が手書き / 経験的。 実戦データから自動学習されてはいない
- 16 デッキ × 16 デッキ全マッチアップで個別調整は されてない

---

## 9. 既知の限界 / 検証してほしいポイント

### 9.1 ルール解釈の懸念

- **ブロッカー生存判定の `>=` バグ**: blocker.power == attacker.power で「生存扱い」。
  公式 7-1-4 では同値で攻撃側勝ちなので、 本来は blocker は KO される
- **ダブルアタック** が打点 2 で計算されてない (= lethal 推定が甘くなる)
- **バニッシュ** がライフ→手札の差を反映してない
- **同時発火トリガー順序** は engine 側で公式準拠だが、 AI 側で「先発火させたい」 選択肢を見てない

### 9.2 評価関数の懸念

- **field_power の重み 1** は事実上無視。 これで「7000 power vs 5000 power」 が区別されない
  (= 他指標で吸収する設計だが正しいか?)
- **attached_don 400** は過大気味? 「4 ドン付与 = 1600 pt」 がキャラ 1 体超え
- **lethal sigmoid の急峻性**: ratio = 1.0 付近で大きく動く、 = 「微妙にリーサル成立」 で
  W_LETHAL の 5000 が一気に乗る。 0.99 と 1.01 の差が大きすぎる懸念
- **opp_hand_threat の推定**: 「相手手札の役割密度」 は実戦より粗い (= 役割未付与カードが default 0.5)

### 9.3 思考プロセスの懸念

- **「コンボ初手で eval 下がる」 を許容するため bad_move_rate 高め** (Greedy 4% → Planning 6%)。
  「布石」 と「真の悪手」 を区別できてない
- **「相手の counter 切らせ」 戦略** は depth=6 の plan で見えるはずだが、 branching ~13 で
  全部探索できない (beam=4 で枝刈り)。 重要な手を pruning しちゃう可能性
- **イベントの効果は judge せず「打てるなら打つ」**: 例えば「リーダー +2000 のイベント」 と
  「相手キャラ KO のイベント」 を同じ「コスト順」 で処理 = 改善余地
- **マリガン判定が「キープ ID 1 枚以上」 で単純**: 「サーチ + フィニッシャー両方ある」 みたいな
  複合条件は見てない
- **ランプデッキの長期価値が見えない**: 「ドン加速 → 5 ターン目に 10 コス出す」 のような
  長期プランは depth=6 で届かない

### 9.4 役割タグ (card_role.json) の品質

- 全 4,518 カードに primary_role を付与済だが、 自動分類由来のものは精度が落ちる
- 「同じ finisher でも実用度が違う」 (= 7 コス bandai 産 finisher と 10 コス効果なし) を
  同 3.0 として扱ってる
- 検証してほしい: 自分が使うデッキで「役割タグが間違ってる」 カードがないか

---

## 10. 検証方法 (= AI の判断を実際に観察する)

### 10.1 verbose 対戦ログ

```bash
.venv/bin/python examples/demo_with_effects.py
```

各ターンの AI 思考プロセス (= eval_before / eval_after / 選択アクション) が `state.action_evals` に
記録されるので、 game replay で「なぜこの手を選んだか」 を逆引きできる。

### 10.2 bad_moves レポート

```bash
.venv/bin/python scripts/report_bad_moves.py \
  --deck-a cardrush_1424 --deck-b cardrush_1437 \
  --n-games 20 --threshold -3000
```

eval delta が -3000 未満の「明らかに盤面悪化させた手」 を抽出。
OPTCG 上級者から見て「これは悪手」 と判定されるはずの手を確認できる。

### 10.3 plan_search の中身確認

PlanningAI が「どんな行動列を beam search 中に評価したか」 は現在ログに出てない。
詳細解析が必要なら `engine/plan_search.py` に debug log 追加可。

### 10.4 ターン中の意思決定を確認

```python
# 1 試合のアクション履歴を見る
.venv/bin/python -c "
from engine.deck import CardRepository, DeckList
from engine.harness import run_matchup
repo = CardRepository.from_json('db/cards.json')
d1 = DeckList.from_json('decks/cardrush_1424.json', repo)
d2 = DeckList.from_json('decks/cardrush_1437.json', repo)
rep = run_matchup(d1, d2, n_games=1, seed=42, keep_logs=True)
for entry in rep.games[0].action_evals:
    print(f't{entry[\"turn\"]} p{entry[\"player_idx\"]}: {entry[\"action\"]:<22} delta={entry[\"delta\"]:+d}')
"
```

各アクションごとに「打つ前後でどれだけ盤面が変化したか」 が見える。

---

## 11. レビュー記入欄

レビュアー (= OPTCG 上級者) に確認してほしい質問:

- [ ] 行動優先順位 (= Step 0〜4) は実戦の打ち手と一致するか? 違うなら どの局面で?
- [ ] 「弱→強」 アタック順は妥当か? アグロデッキでも同じ?
- [ ] 防御閾値 (= life 別の counter 切る量) は アーキタイプごとに妥当か?
- [ ] リーサル判定の 1.2x マージン は安全すぎ / 危険すぎ どっち?
- [ ] 雷迎リスク見積で「ライフ獲得 1500 < リスク 2250 で攻撃放棄」 は妥当?
- [ ] role 別重み (finisher 3.0 / removal 2.5 / blocker 2.0 ...) の差は実戦感覚に近い?
- [ ] ブロッカー `>=` バグ (= 同値で生存扱い) は実害ある? 修正必要?
- [ ] PlanningAI の「コンボ 1 手目で eval 下がる」 許容で見落とす局面はあるか?
