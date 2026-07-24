# value 以外のデータ整理・活用手法 — 統合リサーチレポート (2026-07-24)

5 方向のネット徹底調査 (不完全情報求解 / policy・model-based / 選好・offline / 概念抽出 / TCG特化) を
横断統合。OPTCG プロジェクト固有条件 = **不完全情報・2人ゼロサム・完璧シミュレータ保有・約49万自己
対戦ログ (状態+勝敗、行動未記録)・効果 DSL で構造化済・GBM value 頭打ち・16コアCPU→将来分散** で評価。

---

## 1. 全5報告が一致した「診断」

**value 単一スカラーが天井の理由 (5報告が独立に同意):**
1. **理論**: 不完全情報では単一状態→単一勝率は ill-defined (値は belief に依存し相手 belief に…と再帰)。
   その argmax = 決定的方策 → 原理的に**搾取可能** (読まれる・ブラフ不可)。
2. **目的関数のミススペック**: 1つの回帰関数に「絶対較正 (序盤 vs 終盤)」と「兄弟手の弁別」を同時に
   やらせている。学習容量の大半が較正に使われ、兄弟手の微差 (advantage) は残差ノイズに埋もれる。
3. **実測との整合**: 「特徴を足しても arena 互角」「belief を value feature に足すと deploy-null」は、
   この理論的天井に当たっていた症状。GBM 容量も既に CAP 済 (max_iter=1000、n>30000 で張り付き)。

## 2. 全報告が一致した「やってはいけない」 (強い否定)

- **❌ モデル (dynamics) を学ぶ (MuZero/EfficientZero のモデル部)**: 完璧 engine を持つので純損失。
  MuZero の存在意義 = シミュレータが無い/遅い環境の代替。我々には不要。周辺技術 (Reanalyze/
  Sampled/Gumbel) だけ借りる。
- **❌ 相手手札の明示 belief を value の入力特徴に足す**: **3つの独立ソースが一致** — (a) 我々の実測
  (belief-null)、(b) LOCM の ProphetCoac が勝率を下げた、(c) 理論 (belief は value 入力でなく探索の
  集約構造か学習目的に置くべき)。**最も確度の高い否定的知見**。
- **❌ ReBeL / Deep CFR の直輸入**: カードゲームは belief 整合状態の列挙が非現実的、計算量が桁違い
  (HUNL で 45億サンプル/200万 GPU時間)。CCG での実用例なし。アイデアだけ借りる。
- **❌ 素の PPO/IMPALA 単独**: 探索を捨て完璧 engine を活かせない + 不完全情報ゼロサムで搾取されやすい。

## 3. 全報告が収束した「やるべき」方向 — 較正 (value) と弁別 (policy/rank) の分離

### AI を強くする 3本柱 (報告 1・2・3・5 が収束)

**① Expert Iteration + policy head (最多推奨)**
探索 (beam) の「兄弟手のソフト分布 (訪問数/advantage の softmax)」を policy head に蒸留 → その policy で
探索を絞る → 反復。**value を捨てず、絶対較正は GBM に任せ、兄弟解像度だけ policy head が担う**
(AlphaZero の policy+value 分離)。EIV1 構想の正統実装で、欠けているのは policy head 1個だけ。
- Reanalyze (MuZero 由来): ログの各局面を**今の探索で再ラベル** → **行動未記録でも policy 教師が作れる**。
  = 49万ログをそのまま再利用。今日「行動未記録」を制約と言ったが問題にならない。
- 一次: AlphaGo/AlphaZero policy target, Expert Iteration (1705.08439), MCTS as regularized policy opt (2007.12509)

**② DouZero 型 Deep Monte-Carlo + カード行列行動符号化 (TCG分野の最検証処方箋)**
Q(state, action) を「盤面カード行列 + 行動カード行列」入力の NN で回帰、ターゲットは終局勝敗の MC
リターン。**行動を埋め込むことで巨大行動空間を列挙せず扱う**。DouZero は 27,472 行動・不完全情報・
DouDizhu (OPTCG と条件酷似) を、DQN でも CFR でもなく DMC で制覇 = 「1-ply value を argmax する構造の
限界」を越えた唯一の量産実証。**48コアCPU + GPU数枚で人間級** = CPU 律速でも成立。
- 既存の 226 DSL プリミティブ・特徴タグ・条件節を**行動の特徴ベクトルに直接流用**できる (embedding 入力が人手済)
- 一次: DouZero (2106.06135), DouZero+ (2204.02558), Axie action-rep (2206.12700)

**③ PIMC / ISMCTS 決定化 (不完全情報の実務標準・既存資産で即着手)**
`opponent_deck_priors.json` を belief サンプラーに転用 → 相手デッキを複数決定化 → 各世界で beam/短探索
→ **情報集合で集約 (ISMCTS)**。OPTCG は盤面公開・ブラフ中心性が低く PIMC 適性が良い (leaf correlation
高・disambiguation 高)。決定化ごとに完全並列 = **将来の分散ボランティア計算そのもの**。
- ⚠ strategy fusion (各世界で別最適 → 集約で情報集合非最適): **各世界を最尤仮説に commit して指す**
  (hedge 平均でなく) と緩む。我々の human_hypothesis_commit と整合。
- ⚠ これが「belief を value に足すと null」の同根 (平均化が per-world 逸脱を潰す) → 集約は ISMCTS で正しく
- 一次: ISMCTS (Cowling 2012), PIMC いつ効く (Long 2010), AlphaZe** (Frontiers 2023)

### 「兄弟手ランクを直接学ぶ」補助レバー (報告 3)

**④ ランキング残差ヘッド / GRPO / CPL**
- **ランキング残差** (Coulom-BT / RankQ): 現行 GBM を壊さず、兄弟間の順位制約だけを残差ヘッドで足す。
  block_residual (非回帰配備) の実績パターンにそのまま乗る。hard negative (僅差で劣る兄弟) が解像度を上げる。
- **GRPO** (DeepSeek): critic を廃止し、**同一局面の N 兄弟の群内相対 (勝率−群平均)/群std** で advantage。
  = 我々の「1局面 N rollout」がそのまま群になる。**構造が完全一致**。critic 較正のノイズを原理的に消す。
- **CPL**: 選好 = advantage の順序、と仮定すると教師あり対照損失だけで最適方策を復元。完全 off-policy。
- 一次: RankQ (2605.11151), GRPO (DeepSeek), CPL (2310.13639), Coulom 2007

### データ規模の再解釈 (報告 5 Metamon — 重要な補正)

Metamon (Pokémon) は人間475k → **自己対戦で5Mに水増しした瞬間に人間上位10%** へ跳ねた。
かつ「**自己対戦データは "実在しない多様なデッキ (OOD)" で水増ししないと自分の戦略に過学習して実相手に
弱くなる**」。
- **「量は律速でない」の精密化**: 同種データを CAP 済 GBM に足すのは無益 (実測通り)。しかし
  **量 × 多様性 × 大きい器 (Transformer)** の三点セットは lever。Metamon の跳躍はこの3つが揃った時。
- 我々の「学習相手を厚く (歴代60デッキ)」洞察の理論的裏付け。→ corpus を数百万・OOD デッキへ拡張する
  価値は、**器を NN に替える前提で**ある。

## 4. プロダクト方向 (報告 4) — AI 強化と同じ表現から

- **即効: EBM (glass-box GAM) を GBM の「鏡」に**。同じ特徴・同じ49万件で学習し、特徴別 shape function
  (「相手手札枚数 → 勝率寄与」曲線) で **value の判断を全可視化**。passivity バグ等を曲線で自動診断。
  強さは既存 beam に任せ**並走させるので配備リスク0**。投資対効果が最大。一次: EBM (InterpretML)
- **土台: SPR 型 自己教師あり表現** (自分の潜在表現の数手先予測、負例不要でオフラインログに素直)。
  EIV1 の card-aware 表現の実装レシピ。これができると概念抽出・検索・クラスタが全部乗る。
- **コーチ: 事例検索 (This looks like that / ProtoPNet)**: 「あなたのこの局面 ≈ 過去のこれ、最善はこれ」。
  territory 構想「将棋みたいに手の良し悪しを教える」に直結。
- **記事: 概念抽出 (AlphaZero chess concepts / Schut teachability)**: 非自明 novel なコツを掘り、Claude で
  記事化。deck_guide_monetization の目玉。card2vec でデッキ構築支援。

## 5. この project への統合ロードマップ (既存資産に乗せる順)

```
Tier 0 (即効・低リスク・数日)
  - EBM を GBM の鏡として学習 → value の判断を可視化・自動診断 (プロダクト即効)
  - 現行 beam の兄弟分布を policy ラベル化する scaffold (ExIt の第一歩、GBM 分類器でも可)

Tier 1 (本命の足場・1-2週)
  - ① policy head 追加 + Reanalyze (49万ログを今の探索で再ラベル) → beam prior に配線 → A/B gate
  - ③ PIMC 決定化を beam の相手 sim に (opponent_deck_priors 転用、最尤 commit、ISMCTS 集約)
  - value は block_residual floor として温存 (非回帰配備)

Tier 2 (器の刷新・分散前提)
  - ② DouZero 型 DMC + カード埋め込み (行動を DSL 特徴でベクトル化) → 巨大行動を列挙せず
  - SPR 自己教師あり表現 → card-aware 汎用 value (任意ユーザーデッキ = Phase 10)
  - ⑤ OOD デッキで corpus を数百万へ (Metamon 流、多様性が質)

Tier 3 (分散・プロダクト)
  - PIMC/DMC の大量 rollout を分散ボランティア計算で (Phase 9)
  - 概念抽出 → 攻略記事自動生成 (マネタイズ capstone)
```

## 6. 最も確度の高い3つの結論 (行動指針)

1. **value は捨てず「較正 (value) と弁別 (policy/rank) を分離」する** — 全報告の共通処方箋。最小改修は
   既存 beam+GBM に policy head を1個足すこと (ExIt)。今日の rollout target はこの方向で正しく、ただし
   絶対勝率の回帰でなく**兄弟の相対分布/順位**として学ぶ (GRPO/policy蒸留) のが正解。
2. **belief は value 入力に足さず、探索の集約 (PIMC/ISMCTS) に置く** — 3独立ソースが一致した最確定知見。
3. **モデルは学ばない (engine が完璧)、ReBeL/Deep CFR は直輸入しない (計算が桁違い)** — 除外が明確。

## 主要一次ソース (抜粋)
- ExIt: 1705.08439 / MCTS as reg policy opt: 2007.12509 / Gumbel MuZero (ICLR22)
- DouZero: 2106.06135 / Metamon: 2504.04395 / AlphaZe** (Frontiers 2023)
- ISMCTS: Cowling 2012 / PIMC 適性: Long 2010 (AAAI) / DeepNash R-NaD: 2206.15378
- GRPO (DeepSeek) / CPL: 2310.13639 / RankQ: 2605.11151 / Coulom 2007
- EBM (InterpretML) / SPR: 2007.05929 / AlphaZero chess concepts: 2111.09259 / ProtoPNet (NeurIPS19)
- LOCM ByteRL: 2303.04096 / Beat ByteRL (exploitability): 2404.16689 / MtG card embedding: 2407.05879
- Pluribus (Science 2019) / ReBeL: 2007.13544 (直輸入は非推奨)
