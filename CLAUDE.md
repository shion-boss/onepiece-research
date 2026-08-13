# プロジェクト: ワンピースカードゲーム デッキ研究ツール

> このファイルは Claude Code が自動的に読み込み、プロジェクトの文脈として利用する。
> プロジェクトの方針・構造・規約をここに集約する。詳細は各サブディレクトリの `CLAUDE.md` を参照。

## このツールが目指すもの

**「公式準拠 100% の OPTCG エンジン上で、 デッキ研究と AI 対戦を集合知で進める研究プラットフォーム」**

3 つの達成目標:

1. **デッキ研究ツールとしての完成度**: 推しキャラ軸デッキを組み、 メタトップに勝てるかを定量評価
2. **AI 強化の段階的進展**: ヒューリスティック → 確率モデル → self-play 学習 → 超人 AI へ
3. **コミュニティ参加型研究**: ボランティア self-play 計算で **公開 TCG 分散研究** を実現

利用シーン:
- 推しキャラを軸にしたデッキを組み、メタデッキ群と AI 対戦させて勝率を見る
- デッキの色配分・コストカーブ・特徴シナジーを可視化する
- 環境上位デッキの傾向を分析する
- 学習基盤 (= Phase 8 以降) で上級者層に届く AI を構築する研究プラットフォーム
- 分散コンピューティング (= Phase 9 以降) でコミュニティ参加型に拡大

**詳細ロードマップは [docs/ROADMAP.md](./docs/ROADMAP.md) を参照**。
Phase 1-7 完了 (= 全カード実装済 + 配備AI = SmartOpponentAI→ExploitBeam)、 [[project_ai_strengthening_plan]] が現役プロジェクト。

> ⚠ **「公式準拠 100%」 は 2026-08-13 時点で 達成していない (= 目標であって現状ではない)**。
> 公式 Q&A 全 1,205 件の conformance ([[project_faq_conformance_routine]]) で **検査済 955 件
> (n/a 82 除く 873) のうち 138 件 = 約 15.8% が違反 (fixed)**、 conform 735 件。
> 壊れていたのは主に **カード個別の効果解釈** (コスト gate 欠落 = タダ撃ち / 対象範囲を片側限定 /
> 印刷値と現在値の取り違え / **「〜まで」「〜てもよい」 の任意性を落として強制化**) で、
> 中核ルール (ターン進行・DON・ライフ・KO・攻防解決) は概ね正しい。
> 中核の例外はバトル中断 (2026-08-04 是正)、 **発動コスト由来トリガーの解決順** (2026-08-09 是正、
> 公式 8-4-1-3〜5 / cardqa_op_14)、 **「元々のパワー」 は効果で書き換わる** (2026-08-10 是正、
> 公式 4-9-2-1 / EB01-061)、 **ライフの表向き/裏向きは 1 枚ごと** (2026-08-11 是正、
> cardqa_st_13 / ST13-003 + cardqa_eb_01 / EB01-052)、 **デッキ0枚は 「ドローできない時」 ではなく
> 「0枚になった時点」 で敗北** (2026-08-13 是正、 公式 9-2-1-2 + 1-2-2 + 9-1-2 / cardqa_st_03。
> ルール置換 deck_out_wins/defer が静的リセット漏れで永続していたのも同時に是正)、
> **リーダーのデッキ構築制限が未実装** (2026-08-13 是正、 OP12-001 / OP13-079 / P-117) の 6 件。
> **escalated (= 要深掘りで保留) は 0 件**。
> **未処理 250 件 = 全体の 20.7% は未検査**。
> 「100%」 と書けるのは台帳が全件 conform/fixed になった時だけ。
>
> ⭐ **「〜まで」 「〜てもよい」 は 0 を選べる** (総合ルール **1-3-5-1**: 上限だけが定められ下限指定が
> 無ければ 0 を選べる)。 overlay がこの任意性を落として強制にしている型が繰り返し見つかっている
> (2026-08-13: 手札 N 枚まで捨てる 3 枚 / デッキ上 N 枚をトラッシュに置いてもよい 9 枚)。
> 新しい overlay を書く時は **文末の 「まで」 「てもよい」 「できる」 を必ず spec に落とす**。

## アーキテクチャ

**Next.js (TypeScript) フロントエンド + Python (FastAPI) バックエンド** の構成。

```
onepiece_research/
├── scraper/        # 公式サイトから全弾スクレイプ (Python)
├── engine/         # ルールエンジン + AI + 対戦ハーネス (Python)
├── api/            # FastAPI で engine をラップする HTTP API (Python)
├── db/             # cards.json / cards.sqlite / card_effects.json (4,518 全登録, 効果あり 3,745)
│                   #   + rules/ (公式PDF) / faq/ (公式Q&A) / banlist/ (禁止リスト)
│                   #   + matchup_matrix.json (事前計算 N×N 勝率)
├── decks/          # メタ(環境)デッキ JSON、 16 デッキ pool。 メタ判定は `db/meta_decks.json` 登録制
│                   #   (接頭辞でなく)。 ユーザー作成デッキは kind:"user" タグ (P2 で DB 分離予定、 docs/multiuser_plan.md)
│   ├── *.analysis.json # 各デッキの静的分析 (戦略 / マリガン / キーカード / AI ヒント)
│   └── _archive/   # 旧 meta_*.json + 非代表 cardrush_raw/ の退避先
├── images/         # 全カード画像 (必要時 scripts/cache_all_images.py で取得)
├── scripts/        # 補助スクリプト (scrape / cache / matrix / overlay / audit / weight tuning)
├── web/            # Next.js フロントエンド (TypeScript, App Router)
│   └── public/cards/   # 全 4,518 枚キャッシュ済 (878MB)
├── examples/       # スモークテスト・デモスクリプト (demo_matchup.py / demo_smoke.py / demo_with_effects.py)
├── tests/          # pytest テスト (6,026 collected)
└── .venv/          # Python 仮想環境 (gitignore 推奨)
```

> **注意**: WSL のホスト経由でマウントされていると `*.py` が `*.PY` (大文字) として
> 表示されることがある。`*.py` 限定の glob/pytest 設定では拾えないので注意。

### なぜこの分割か

| 関心事 | 担当 | 理由 |
|---|---|---|
| カードDB / スクレイプ | Python | requests + BS4 が枯れていてシンプル |
| ルールエンジン / 効果DSL | Python | データクラスとパターンマッチが楽。既存資産あり |
| AI / 対戦シミュレーション | Python | NumPy/将来のRLライブラリとの親和性 |
| デッキビルダーUI | Next.js | リッチなインタラクション・画像表示 |
| ダッシュボード / グラフ | Next.js | recharts/chart.js が豊富 |
| 対戦結果ビューア | Next.js | リアルタイム表示・URL共有しやすい |

## 開発フェーズと現状

- [x] **Phase 1 完了**: カードDB(全54弾4,518枚、`cards.json` / `cards.sqlite`)
- [x] **Phase 2 完了**: ルールエンジン(コアデータ構造、ターン進行、攻防、効果DSL)
  - 主要トリガー (R44-R64 拡張済): 登場/アタック/起動メイン/KO時/ターン終了時/ブロック時/相手アタック時/トリガー/カウンター/メインイベント
    + **on_self_chara_leave_by_self_effect / on_self_rested / on_self_hand_discarded /
      on_self_chara_played / on_opp_chara_played / on_self_event_played /
      on_opp_life_taken / on_self_life_to_hand/to_trash / on_self_don_returned_to_deck /
      on_opp_blocker_use / on_self_chara_ko / on_opp_chara_ko / opp_attack_on_leader /
      opp_attack_on_chara**
  - DSL プリミティブ **324 種** (engine/effects.py 内 elif k == "..." パターンで列挙。
    226 種の時点で [[project_card_implementation_audit]] が 226/226 実装確認済、 以降は公式 Q&A
    conformance で必要になった分を追加している)
- [x] **Phase 2.5 完了**: カード効果オーバーレイ **全 4,518 カード登録 (100%)** (`db/card_effects.json`)。
  - 効果あり: 3,745 件 (82.9%) — character 78.6% / event 100% / leader 100% / stage 79.1%
  - 効果なし (バニラ/ブロッカーのみ/パラレル空): 773 件 (空配列でマーク済)
  - **`_unimplemented` マーカー: 0 件達成 🎯 (R56 で完全消去、 残:なし)**
  - audit sev≥5 = 0、 sev=3-4 = 0 (R59) — `db/audit_acknowledged.json` で intrinsic 除外
  - engine 厳密化 audit 10/10 pass (`scripts/audit_engine_strictness.py`)
  - cardqa vs overlay 整合性 0 漏れ (X5、 `scripts/verify_overlay_vs_cardqa.py`)
  - 全 4,518 カード 公式テキストとの **突合作業は完了** (2026-05-22、 [[project_card_implementation_audit]] + [[project_dsl_jp_audit_complete]])
    ⚠ **「整合 100%」 ではない**。 当時の監査は **すべて自己参照** だった:
      overlay vs cardqa マーカー / overlay vs FAQ 要約 / engine 厳密化 audit /
      **Python↔Rust 差分 (= 同じ overlay を読む 2 実装)** / **backfill テスト (= 現 overlay から生成)**。
      どれも 「overlay 自身が公式テキストを読み違えている」 型を **構造的に検出できない**。
      実際 backfill テストは バグを正解として固定しており、 2026-08-05 に 13 本が
      「タダ撃ちできること」 を assert していたと判明した。
    → **外部オラクルは公式 Q&A だけ**。 進捗は `db/faq_qa_status.json` を真とする
      ([[project_faq_conformance_routine]])。
  - DSL 条件 (eval_condition): leader_feature/color, self/opp life/hand/don 各種, opp_turn/self_turn,
    self_rested, self_trash_count_ge, self_don_ge, victim_truly_original_power_ge,
    victim_feature_in, played_chara_truly_original_cost_ge, played_self_chara_has_no_effect,
    actor_source_feature_contains, self_chara_filtered_count_ge, don_diff_le 等 30+
  - DSL プリミティブ主要カテゴリ:
    - **draw/discard**: draw / draw_per_self_hand_discarded / trash_self_hand_random / trash_opp_hand_random
    - **KO/離脱**: ko / ko_multi / ko_all_others / return_to_hand(_multi) / return_to_deck_bottom(_multi) /
      chara_to_self_life / chara_to_opp_life
    - **power**: power_pump (amount_per source × multiplier) / power_pump_per_target_attached_don /
      set_base_power / set_base_power_timed / set_base_power_copy
    - **cost**: set_base_cost / set_base_cost_timed / reduce_play_cost / reduce_play_cost_filtered_static
    - **don**: attach_don / attach_rested_don / attach_active_don / add_don / add_rested_don /
      untap_don / rest_opp_don / keep_opp_rested_don_next_refresh / rest_self_don_for_battle_buff_per_don
    - **rest**: rest / untap_chara / rest_self_cards(_filtered) / set_cannot_rest / stay_rested_next_refresh
    - **search/play**: search / play_from_hand(_or_trash/_named/_named_set/_named_with_dynamic_cost) /
      play_from_trash / play_event_from_hand / summon_from_deck / reveal_top_then / reveal_top_play
    - **life**: life_to_hand / life_top_or_bottom_to_hand / put_top_to_life / hand_to_self_life /
      scry_life / scry_all_life_one_to_deck / scry_all_life_reorder / mill_self_life_until_n /
      peek_self_life_top / mill_opp_life_to_hand/to_trash
    - **キーワード付与**: give_keyword (target/keyword/keywords-choice/duration: turn|next_opp_turn_end) /
      give_rush / give_attack_active_chara
    - **置換効果**: replace_ko / replace_leave / replace_rest (cost 配列 + do)
    - **KO 耐性**: prevent_ko / set_ko_immune / set_ko_immune_timed / set_ko_immune_battle_only /
      set_immune_attribute_in_battle (negate option)
    - **静的効果**: set_attack_taunt / set_cannot_attack_static / set_opp_protect_static /
      cannot_attack_target_except / cannot_attack_target_cost_le
    - **コスト/遅延**: optional_cost_then / schedule_at_opp_main_phase_start / schedule_at_self_turn_end /
      block_self_draw_turn / block_chara_play_turn / prevent_self_life_to_hand_turn /
      set_attack_cost_discard_hand / optional_discard_hand_for_battle_buff
    - **その他**: redirect_attack / negate_effect / disable_effect / extra_turn / swap_opp_power /
      draw_per_hand_to_deck_bottom / return_self_to_deck_bottom_if_condition / trash_to_deck /
      opp_trash_to_deck_bottom / static_swords_attack_chara / 他
- [x] **Phase 3 完了**: AI 階層 + 対戦ハーネス
  - AI クラス: `RandomAI` / `GreedyAI` / `LookaheadAI` / `MCTSAI` / `PlanningAI` / `GoalDirectedAI` / `ExploitBeamAI` / `SmartOpponentAI`
    - ⭐ **配備 (= ユーザーが実際に戦う相手) の既定 = `SmartOpponentAI`** → deck別に `ExploitBeam`/greedy 自動切替。 **全16プールデッキは ExploitBeam (= 最強)**。 API 全経路 (practice/match/人間vsAI/matrix/観戦) が `api/main.py:_build_default_ai_factory` / `_practice_run_kwargs` 経由でこれを使う ([[feedback_unified_deployed_ai]]、 577637a)。 **環境外/未知デッキ (deploy_results に無い slug) は greedy に degrade** (= 任意デッキを最強化するには Stage 0 = ゲート緩和 + per-deck GBM が必要)
    - **`GoalDirectedAI` (= Plan H、 archetype別 bonus + 3-tier fallback)** は engine/harness の **ライブラリ既定** (`engine/harness._default_ai_factory`)。 用途 = scripts/tests・degrade fallback・`ONEPIECE_HUMAN_AI=light`。 ⚠ **配備の対戦相手ではない** (= 実体は上記 SmartOpponentAI)
    - **`ExploitBeamAI` (= 2026-06-04、 vs GreedyAI 最強、 [[project_70pct_vs_greedy]])**: beam(16/10) +
      post-opp 再ランク (`ONEPIECE_POSTOPP_EVAL`、 完了プランを「自ターン終了→相手greedyのターンsim→その後」で
      eval) + 学習 GBM value (`engine/gbm_value.py`、 post-opp盤面=自次ターン開始=GBM学習分布で正確)。
      **vs GreedyAI on cardrush_1342 = 72.7% (N=300)**。 GBM は `db/value_gbm_<slug>.pkl` を deck別に
      `scripts/train_value_gbm.py` で学習 (無ければ board_eval に degrade)。 教訓: 学習valueは正しい分布で使え /
      探索のmyopiaは deterministic opp の sim で補正。 `scripts/bench_ais_vs_greedy.py` で測定
      - **⚠ matchup-条件付き / per-deck value (v5/v6/専用/residual) は撤回済 = 幻と判明 (2026-07-22, c23c939)**:
        かつて「v6(相手 leader tag + board×matchup interaction、 38dim)を 11/16 deck 配備で +10〜29pt /
        実メタ rankΔ=1.0」と評価したが、 **これは board_eval を基準にした時だけ強く見えた幻**。 正しい基準
        (= agnostic value)で測ると **v6 vs agnostic = 1342 で -3.4pt / pros02専用 held-out +0.4 / エネル特化
        -1.2 = 効かない/負ける**。 唯一の実成長は gate緩和(aggro を board_eval→agnostic に、 配置修正)。
        → **38 個の per-deck pkl を `db/_value_archive_perdeck/` に退避、 配備を uniform agnostic (21dim) に
        全体統一**。 `_resolve_gbm_path` は per-deck pkl 無し → agnostic fallback(全メタ+pros02+user deck が
        uniform agnostic + beam で戦う)。 **教訓: value の A/B 基準は必ず agnostic(board_eval は弱すぎて
        card-aware を過大評価する)**。 2026-07-27 の sig(card 効果シグネチャ)clean isolation も 0.483 = null
        で同結論を再確認 = **card-aware value は閉じた**。 「agnostic 本体の強化 = 天井を上げる唯一の道」。
        `gbm_value.py` は今も v1〜v22 の次元自動判別を持つ(後方互換、 実験用)が **配備は agnostic 1個のみ**。
      - **⭐ offense force-attack 再有効化 (= 2026-07-08、 `_offense_force_attack=True`)**: 一度
        2026-06-13 に無効化した (= beam に委ねる、 配備ミラー A/B 平均 ~66% を根拠) が、 **ohtsuki の実戦
        フィードバックで復活**。 「AIはあんまり攻撃してこない=怖くない、 カウンター不要、 手札枯渇しない」
        「相手の手札が増えるより減らない方が嫌」。 実ログ計測: AI-Bonney が 2/3 game で 0〜1回/5-6T しか
        攻撃せず = 病的に消極的 (rollout scanner も独立に「74% 局面で最良手=顔攻撃」検出)。 **無効化を
        正当化したミラー A/B は passivity を罰せない** (両者消極 = 手札を削れない弊害を測れない、 人間モデル
        (粗)でも punish 不足)。 force-attack コードは元々「完全 block でも相手 counter1枚=手札-1で価値」
        「leader 攻撃はノーコストで相手手札-1期待」= ohtsuki の原理で書かれ、 boost は lethal_pressure 時
        のみに絞る refine 済で crude でない。 `DeepPlanningAI.choose_action` 早期return群 (ai.py 2763-2840)。
        lethal-check (`_use_lethal_check`) は別flagで常時有効。 ⚠ ミラー勝率は下がりうるが受容 (= mirror ≠
        human 品質、 [[feedback_evaluation_axis]])、 **要 matrix 再計算**。 汎用 flag A/B = `scripts/ab_flag.py`。
        深掘り: value が「相手手札を削る圧」を過小評価する構造 = 次の value fix 候補 [[feedback_ai_too_passive_attack_pressure]]
    - **AI 実行モード (2026-06-03〜、 [[feedback_eval_specs_in_pure_lookup]])**: GoalDirectedAI は target spec を 2 モードで使う。
      - **pure_lookup (= 既定)**: `_choose_action_pure_lookup` で spec bonus argmax、 beam を bypass (~50ms/手)。 **GoalDirectedAI 使用時** (= harness ライブラリ default・corpus 収集・online 学習) は これ。 spec が policy そのもの。 spec coverage 不足の局面のみ GreedyAI fallback (= 実測 88% は spec hit)。 ⚠ 配備の practice/matrix/観戦 は SmartOpponentAI なので この経路を通らない
      - **beam plan_search (= opt-out)**: `pure_lookup=False` or env `ONEPIECE_PURE_LOOKUP=0` で PlanningAI の beam(4/6) を使い、 spec を葉 eval に bonus 加算。 `scripts/eval_goal_directed_mirror.py` (beam 強度測定) と plan_search 内部 opp_sim のみ
      - ⚠ **spec の A/B は pure_lookup で測る** (`scripts/eval_pure_lookup_ab.py`)。 beam は spec が board_eval に薄まり差が出ない。 「deployed 絶対強さ」測定時のみ beam
  - **共通基盤**: lethal_planner / hand_estimator (= 隠匿情報モデル) / アーキタイプ別ヒューリスティック (= `decks/<slug>.analysis.json` を読込)
  - **静的解析**: `decks/<slug>.analysis.json` の `mulligan_keep_card_ids` / `ai_hint_signals` を全 AI で参照
  - **RuleReferee**: AI vs AI 対戦中のルール違反監視。 matchup matrix 計算で違反ゼロ
  - **AI 行動品質評価**: `engine/eval.py` 15 指標 board_eval + `state.action_evals` delta 記録 + `scripts/report_bad_moves.py`
  - **公式 floor_rule II. 時間切れ準拠** (2026-05-28 追加): `run_matchup(time_limit_turns=40, time_limit_mode="both_lose")` が default。
    壁時計の 30 分推奨を turn 上限 proxy 化 (= 40 turn ≈ 20 turn/player)、 cap 到達で **両者敗北 (= draw)**。
    `extra_turns` mode で 公式決勝/トーナメントの 追加3/2ターン + ①life ②deck ③random tiebreak 可能。
    一次情報: `db/rules/floor_rule_20240913.pdf` + rules skill `13. ルール処理 > 時間切れ`
- [x] **Phase 4 完了**: メタデッキ DB **16 デッキ** (`decks/cardrush_*.json` 15 件 + テストデッキ 1)。
  cardrush.media の大会上位入賞 (優勝/準優勝) を `scripts/scrape_cardrush_decks.py` で取得 →
  アーキタイプ毎に最新優勝を `select_cardrush_representatives.py` で代表選出 →
  禁止ペア違反は除外。月次更新フロー確立。
- [x] **Phase 5 完了**: デッキビルダー
  - `engine/deckbuilder.py`: コアカード固定型自動構築
  - `POST /api/decks` → 任意レシピを `decks/<slug>.json` に保存 (validate 通過必須)
  - `POST /api/decks/validate` → リアルタイム検証
  - `POST /api/decks/build` → コアカード指定で自動構築
  - UI: `/decks/new` (リーダー選択 + カード追加 + 下書き保存 + サーバ保存)
- [x] **Phase 6 完了**: Next.js UI
  - `/cards` ブラウザ(URLクエリ駆動フィルタ + グリッド + 詳細モーダル)
  - `/decks` 一覧 / `/decks/[slug]` 詳細 + 対戦ランナー(`MatchRunner`)
  - `/decks/new` デッキビルダー UI (Phase 5)
  - `/decks/[slug]/analyze` 分析ダッシュボード (recharts: 色配分 Pie / コストカーブ Bar /
    カウンター分布 / 特徴Top / activate_main 一覧)
  - `/meta` matchup matrix ビューア
  - `/faq` 公式FAQ + cardqa 検索
- [x] **画像配信**: 全 4,518 枚を `web/public/cards/` にキャッシュ済 (878MB)。
  `<CardImage>` で 404 → 公式 URL フォールバック。
- [x] **Phase 4.5 完了 (R70+R71)**: **PlanningAI** (ターン全体プラン beam search)
  - `engine/plan_search.py`: beam search + fast_clone (= CardDef/InPlay の __deepcopy__ 共有で 3.3x 高速化)
  - `engine/ai.py:PlanningAI` (= GreedyAI を継承、 beam=4 / depth=6)
  - PlanningAI は `GoalDirectedAI` の親クラスとして 現役 (= beam plan_search の実体)。 ただし **GoalDirectedAI の既定は pure_lookup** (= beam bypass、 2026-06-03〜)。 beam は `pure_lookup=False` / env opt-out 時のみ (= eval ツール / 内部 opp_sim)。 上記「AI 実行モード」参照
- [x] **メタデッキ Phase 4 拡張 (= tcg-portal 化、 2026-05-14)**: 16 デッキ pool。
  - cardrush 10 件 (= 個別優勝レシピ、 3 ヶ月集計から代表選出)
    + tcg-portal 6 件 (= cardrush 不在の leader を集計合成で補完)
  - 全 16 リーダーは tcg-portal `/meta-analysis` 上位 (= 2026-02-14〜05-13 の 1,040 大会データ)
  - `decks/_archive/cardrush_raw/` に過去 3 ヶ月 88 件の優勝レシピを保管 (= deck classifier 学習用)

### 進行中 / 計画中フェーズ (= Phase 7+, 詳細は [docs/ROADMAP.md](./docs/ROADMAP.md))

- [x] **Phase 7 完了 (2026-05-14)**: AI ヒューリスティック層強化 + bluff + lethal_planner
  - 累計 108 新規 tests / 全 pass、 期待効果 +15〜+30pt vs 旧 PlanningAI
- [x] **Plan H = GoalDirectedAI 完了 (2026-05-25)**: target spec DSL + archetype 別 bonus + 3-tier fallback
  - 詳細: [[project_plan_h_hybrid_result]] + [[project_bonus_learning_pipeline]]
  - engine/harness の **ライブラリ既定** AI (= scripts/tests/degrade/light)。 ⚠ **配備 (ユーザー対戦) の既定ではない** (= 2026-06-04 以降 配備は SmartOpponentAI→ExploitBeam、 [[feedback_unified_deployed_ai]])。 16 deck mirror eval で平均 +1.9pt (= [[project_phase1_5_baseline]])
- [~] **AI 強化統合 plan 進行中**: [[project_ai_strengthening_plan]]
  - Phase 1 完了 (= effect 不発 prune + fast_clone fix + EndPhase prune)
  - Phase 2 着手前 (= opp model mirror)
- **Dead-end 路線** (= 撤退、 教訓のみ memory 保持):
  - Plan D (= AlphaZero value NN): [[project_plan_d_results]] スケール不足確定
  - Plan F (= 重み NN): [[feedback_weight_nn_limit]] argmax 不変で eval 反映されず
  - Plan E / MegaPlanningAI / AdaptiveComboAI: 着手前で凍結
- [ ] **Phase 9 計画中**: 分散コンピューティング / ボランティア参加 (= 詳細 ROADMAP.md)
- [ ] **Phase 10+ 長期**: 任意 deck 汎用 AI / デッキ構築 AI / ナッシュ均衡解析

### 現在のメタ Tier

最新 16 deck mirror eval は [[project_phase1_5_baseline]] を参照 (= 2026-05-27、 +1.9pt avg)。
詳細 analysis: `scripts/analyze_matrix.py` + `db/matrix_analysis_report.json`。

**評価軸の注意**: raw 勝率 ≠ engine の良し悪し。 ゴールは「全デッキが強くなる」 ことではなく、 「正しくゲームが行われ、 AI が意味ある効果の使い方・戦い方をしている」 こと。 評価すべきは AI の各手が (1) 盤面を有利に傾けたか (2) 布石か (3) 効果を意味あるタイミング/対象で発動しているか。 詳細: [[feedback_evaluation_axis]]。

> **⚠ 配備 AI = uniform agnostic value (21dim) + ExploitBeam (2026-07-22 c23c939 以降)**。 かつて
> 「matchup-aware v6 を 11/16 deck 配備で proactive≫reactive artifact を解消、 実メタ rankΔ=1.0」と
> 記していたが、 **これは board_eval 基準の幻で撤回済**(v6 vs agnostic = -3.4pt、 上の value 節参照)。
> 現配備は per-deck value を持たず uniform agnostic。 **matrix は uniform agnostic で要再計算(stale)**。
>
> **探索路線も beam 以下と実測確定 (2026-07-27, [[project_search_route_pivot]])**: 「1-ply value + 単ターン
> beam が control-vs-aggro を作れない、 根治は multi-turn 探索の大工事」と当時考えたが、 実測で **multi-turn
> rollout(turns=2 + value誘導)= 47.5% = null**(error 複利が深さの signal を殺す)、 **value-leaf MCTS +
> 現 value = 6.7〜20% = beam に決定的劣位**(policy net 無し + per-action MCTS は whole-turn 連携を組めない
> 構造欠陥)。 = **探索深さは強さの lever でない。 配備 beam が本 game/hardware で near-ceiling**。 天井を
> 上げる残る道は ① agnostic value 本体の self-play 強化(plateau 気味)② AlphaZero policy+value at scale
> (このPC infeasible → 分散 compute = Phase 9 前提)。 [[project_search_route_pivot]] に全体像。

## Next.js 側の方針

- **Next.js 16** + App Router(2026-05 時点 CNA で生成)
- **TypeScript** 必須
- スタイル: **Tailwind CSS v4** (PostCSS設定は CNA 既定)
- 状態管理: Zustand(Reduxは重すぎる)
- データ取得: **Server Components + fetch**、必要なら SWR
- 画像: 自前キャッシュ `/cards/<id>.png` を優先、未キャッシュは公式 CDN へフォールバック
  (`<CardImage>` コンポーネントが onError で切り替え)
- グラフ: recharts(SVG・SSR可。analyze ページで導入済)
- shadcn/ui は **未導入**(必要になったら `npx shadcn@latest init`。
  CLI 名は `shadcn-ui` ではなく `shadcn` (rename 済))
- **UI に絵文字を使わない**: ボタン/ラベル/ヘッダー/バッジ/状態表示 等、ユーザーが目にする全 UI 要素 で 絵文字 禁止。アイコンが必要なら SVG (lucide-react 等) を 使う。詳細は `web/AGENTS.md` 参照
- 全 page の outer shell は `<PageShell>` (= max-w-6xl 固定)、 header は `<PageHeader>` で統一。横幅をナビ毎に変えない (= 視覚的安定 優先)

### コンポーネント命名規約

- `<CardTile>`: 一覧用の小さいカード表示(画像 + 名前 + コスト + パワー)
- `<CardDetailModal>`: クリック時の詳細表示
- `<CardImage>`: ローカル画像 + 公式 URL フォールバック付き `<img>` ラッパ
- `<ColorChip color="赤" />`: 色記号 + 背景色のチップ
- `<CardFilterBar>`: `/cards` のクエリ駆動フィルタ
- `<DeckSummaryTile>`: `/decks` 一覧用
- `<MatchRunner>`: `/decks/[slug]` の対戦ランナー
- `<CostCurveChart>`: コストカーブ(未実装、analyze ページで)

## Python 側の方針

- Python 3.10+
- 型ヒント必須(将来 mypy)
- 副作用は `engine/game.py` の `apply_action` に局所化
- 効果は `engine/effects.py` の DSL で記述、`db/card_effects.json` に追記して拡張
- API は `api/main.py`(FastAPI)。Pydantic モデルもこのファイルに同居 (専用 `schemas.py` は未分離)
- カード参照は常に `CardRepository` を経由
- 新しいプリミティブ追加時は `tests/test_effects.py` にテストを足す (`pytest tests/`)

### コードスタイル

- 関数名: snake_case、クラス: PascalCase
- 例外メッセージは英語(マルチバイトの編集ミスを減らすため)
- 日本語コメント可、ただしカード名以外の長文は避ける

### 重要な注意

- `cards.json` を「正」とする。SQLite は派生物
- 効果オーバーレイ(`db/card_effects.json`)は **公式テキスト忠実主義**:
  - 自動近似 (= 「fallback」 「自動抽出」 「簡略」 「省略」 「近似」) **禁止**
  - 解釈不可な効果は `[]` (空) もしくは `{"_unimplemented": "..."}` でマーク
  - 条件節 (ライフ X 以下、 リーダー特徴 Y 等) は省略しない
  - 既存の simplified entry を発見したら必ず公式テキストから再構築
  - `scripts/audit_overlay_vs_faq.py` で違反検出 (severity)
  - DSL に対応する primitive がない場合は新規追加 (`engine/effects.py:execute_effect`)
  - **公式の語の書き分けを潰さない** (2026-08-04 に 165 効果エントリを是正、 詳細は
    `docs/official_rulings.md`):
    - 素の 「コストN以下」 = **効果修正後の現在コスト** / 「元々のコストN以下」 = **印刷コスト**
      (spec は `truly_original_cost_{le,ge,eq}_N`)
    - 素の 「パワーN以下」 = **現在パワー** (ドン付与/バフ込み) / 「元々のパワーN以下」 =
      **印刷パワー** (spec は `truly_original_power_{le,ge,eq}`)。 置換条件は
      `target_{cost,power}_{le,ge}` = 現在値 / `target_truly_original_*` = 印刷値
    - ⚠ ルール **4-9 が定義するのは 「元々の」 の意味だけ**。 素の表記を印刷値にする根拠ではない
      (overlay の `_doc` に 「4-9 に従い印刷値」 と書かれていたカードが実際は誤りだった)
    - ⚠ 盤面 (InPlay) の filter は `_matches_filter_ip` / `matches_filter_ip` を使う。
      `_matches_filter(x.card, ...)` は CardDef のみ = 印刷値固定で、 経路によって裁定が変わる
    - 「相手の」 が **無い** 「キャラ1枚まで」 = **両陣営** (自キャラ・発動元自身も選べる)。
      spec は `one_character_either_*` / `one_inplay_either_filtered`
    - 【トリガー】の文面は `text` でなく **`trigger` フィールド** (820 枚)。 監査を書く時は
      効果エントリの `when` で読むフィールドを切り替える
- ルール厳密性 < シミュレーションが回ること
- カード固有効果はメタデッキの主要カードから優先実装
- **`harness.run_matchup` には `effects_overlay` を必ず渡す**(過去に渡し忘れて全試合で
  効果未発火だったバグあり。デフォルト引数で `db/card_effects.json` を自動ロード済み)
- **DON+1000 は所有者のターン中のみ有効** (公式 6-5-5)。`InPlay.is_owners_turn` フラグを
  `_recompute_static` (= ownership 反映) が更新する。テストで `InPlay.of()` 直接生成時は
  デフォルト True で動くが、ターン跨ぎを伴うシナリオでは必ず `_recompute_static(state)` を
  呼ぶか、`setup_game` 経由で初期化する
- **ライフの表向き/裏向きは `Player.life_face_up: list[bool]`** (= `life` と同じ index、
  2026-08-11 に 「表向き枚数」 の count モデルから移行)。 `face_up_life_count` は **導出プロパティ**
  (書き込み不可)。 ライフを触る時は **必ず両方を同じ行で対にして** 操作する。
  - 並べ替え/抜き取りは `_life_set_pairs` (Python) / `take_life_pairs`+`set_life_pairs` (Rust) を通す。
    `pl.life = [...]` の単独代入は `Player.__setattr__` がフラグを全裏向きに張り直すので、
    **表向きの札を並べ替えると表向きが消える**。 表向きを保つ時は `life` 代入の **後に**
    `life_face_up` を代入する
  - `_recompute_static` に長さ検査の AssertionError がある (退避は `ONEPIECE_LIFE_FLAG_LAX=1`)。
    ⚠ **長さ一致は同期の証明にならない** — 位置ずれは掃引でしか出ない
    ([[feedback_length_check_is_not_sync_proof]])
- **公式ルールの一次情報は `db/rules/*.pdf` + `db/faq/*.json` + `db/banlist/master.json`** に集約済み。
  skill は `.claude/skills/onepiece-tcg-rules/SKILL.md`。ルール裁定や engine の不一致を直す時はまず skill を参照、
  個別カード Q&A は `db/faq/cardqa_*.json` を grep する

## API 設計

実装済み (`api/main.py`):

| エンドポイント | メソッド | 用途 |
|---|---|---|
| `/api/health` | GET | 死活確認(カード件数返却) |
| `/api/cards` | GET | カード一覧 (color/category/feature/cost_le/cost_ge/name_contains/limit) |
| `/api/cards/{card_id}` | GET | カード単体 |
| `/api/decks` | GET | `decks/*.json` の一覧 (`DeckSummary[]`) |
| `/api/decks` | POST | レシピ保存 → `decks/<slug>.json` (validate 必須、409/422 返す) |
| `/api/decks/validate` | POST | レシピ検証のみ (UI リアルタイム用) |
| `/api/decks/build` | POST | コアカード固定型 自動構築 |
| `/api/decks/generate` | POST | デッキ自動生成 (使いたいカード≤5 固定 + コンボ相棒引込 + combo_strength/target/meta 勝率でランク、 `engine/deck_generator.py`) |
| `/api/decks/{slug}` | GET | デッキ単体 (raw JSON) |
| `/api/decks/{slug}/analyze` | GET | デッキ分析(色配分・コストカーブ・効果密度 + **デッキ内コンボ/サーチ加速** `combos[]`) |
| `/api/combos/{card_id}` | GET | コンボ探索 (任意カード→相性カードを型別ランク、 `engine/combo_finder.py`、 `?per_group=&regulation=`) |
| `/api/decks/{slug}` | PUT | デッキ上書き保存 (validate 必須) |
| `/api/decks/{slug}` | DELETE | デッキ削除 (メタ(環境)デッキは保護 = `db/meta_decks.json` 登録制) |
| `/api/match` | POST | 対戦実行 `{deck_a/deck_b or deck_a_id/deck_b_id, n_games, seed}` |
| `/api/match/{job_id}` | GET | 過去対戦のサマリ |
| `/api/match/{job_id}/games` | GET | ゲーム一覧 (短) |
| `/api/match/{job_id}/games/{i}` | GET | 個別ゲームログ (verbose) |
| `/api/match/history` | GET | 過去対戦の履歴 |
| `/api/meta/matrix` | GET | 事前計算 N×N 勝率マトリックス |
| `/api/faq/search` | GET | 公式FAQ + cardqa 横断検索 |
| `/api/faq/by-card/{card_id}` | GET | 特定カードのQA |
| `/api/faq/sources` | GET | FAQ ソース一覧 |

レスポンス型は `api/main.py` の Pydantic モデルと `web/src/lib/types.ts` の両方で定義。
**不整合が起きたら `api/main.py` 側を真とする**。

## ツール / スクリプト群

主要スクリプト (`scripts/`) は以下のカテゴリ:

| カテゴリ | スクリプト |
|---|---|
| データ更新 | scrape_official_faq.py / scrape_official_banlist.py / scrape_cardrush_decks.py / refresh_all.py |
| overlay 拡張・監査 | suggest_overlay_from_cards.py / merge_overlay_suggestions.py / audit_overlay_vs_faq.py / verify_overlay_vs_cardqa.py / smoke_test_card_effects.py |
| engine 厳密化 | audit_engine_strictness.py (10 項目、 R63 で追加) |
| **公式 Q&A conformance** | faq_qa_manifest.py (全 1,205 件の処理台帳) / audit_sonogo_order.py (「その後」順) / audit_target_scope.py (「相手の」修飾 vs 片側限定 spec) |
| 対戦・分析 | compute_matchup_matrix.py / report_bad_moves.py (R63、 AI 行動品質) / tune_eval_weights.py |
| 画像 | cache_deck_images.py / cache_all_images.py |

主要データ (`db/`):

- `cards.json` / `cards.sqlite`: カード DB (正は cards.json)
- `card_effects.json`: 効果オーバーレイ (4,518 全カード、 _unimplemented = 0)
- `audit_acknowledged.json`: audit script で intrinsic 除外する issue リスト (R59 追加)
- `matchup_matrix.json`: N×N 勝率行列 (16×16 = 256 セル、 mirror 除く 240 セル計算)
  - **方針: 表示用 matrix は 配備 AI (= uniform ExploitBeam + agnostic value + per-deck config) で 計算する** (= /meta で 公開する データを 実際の対戦相手 AI に 揃える)。 ⚠ **現配備 = uniform agnostic value (21dim) + beam** (2026-07-22 c23c939 で per-deck v6 を撤回・退避、 上の value 節参照)。 **matrix は uniform agnostic で要再計算 (現行の `ExploitBeam_v6` 産は stale = v6 は退避済で実際には agnostic に fallback している)**。 再計算: `compute_matchup_matrix.py --ai-mode exploitbeam --incremental --workers 12 --n-games 20` (= 先攻/後攻は cell内で交互、 A vs B と B vs A 両方計算)。 旧 ExploitBeam_v6 / ExploitBeam_vd / SmartOpponentAI_deployed / GoalDirectedAI 産は全て stale。
    - ⚠ **value-defense (= per-deck config で ON の deck) は matrix を ~5x 遅くする** (= 全試合に防御 sim が乗る、 240cell N=20 で **~5.4h**)。 必ず `--incremental` + 新 `--ai-version` で起動し、 5 cell checkpoint + version 照合で **crash 時に同一コマンド再実行で自動 resume** (= 計算済 cell を reuse、 timeout 失敗対策)。
    - ⚠ **配備AIの手が変わる変更後は要再計算** (例: 2026-06-13 offense force-attack 除去 / 2026-06-22 meta value-defense config 配備で再計算実施)。 deck の per-deck config (`db/deck_ai_config_*.json`) を変えたら その deck が絡む cell が stale
- `faq_qa_status.json`: **公式 Q&A 全 1,205 件 (ユニーク) の処理台帳**。 status =
  pending/conform/fixed/n/a/escalated。 公式 Q&A は engine が Python でも Rust でもない
  **唯一の外部オラクル** で、 **両エンジンが同じ間違いをしている領域はここでしか見つからない**
  (差分検証は原理的に沈黙する)。 cron `optcg-faq-conformance` (毎時) が未処理を減らす。
  裁定の根拠は `docs/official_rulings.md` に一次情報つきで恒久記録する
  (⚠ `db/_pending_review.md` は自動再生成されるので手書きしない)
- `overlay_audit.{md,json}`: audit 結果 (sev≥5 = 0、 sev=3-4 = 0)
- `overlay_when_missing.json`: cardqa sweep 結果 (X5、 missing 0)
- `rules/*.pdf`: 公式ルール一次情報
- `faq/*.json`: 公式 FAQ + cardqa (2,500+ 件)
- `banlist/master.json`: 禁止/制限カード
- `opponent_deck_priors.json`: **相手デッキ belief モデル** (= B軸 相手理解、 leader → P(card|50枚) prior + 実大会レシピ bootstrap pool、 175 deck/20 leader)。 相手 leader (公開情報) から中身を推定し、 (1) value の threat feature (2) determinization サンプラー (3) 分析 UI の土台。 runtime = `engine/opponent_deck_model.py` (belief_for_leader / sample_main / top_cards、 seen で事後更新)。 builder = `scripts/build_opponent_deck_priors.py` (corpus = decks/*.json + decks/_archive/cardrush_raw/*.json)。 **determinize への配線は実装済** (2026-07-27、 `hand_estimator._belief_determinize` = seen 整合の実レシピから opp hand/deck を materialize、 `determinize_state(use_belief=)` / env `ONEPIECE_BELIEF_DETERMINIZE`、 OFF-by-default)。 self-play(deck 既知)は強さ中立、 真価は deployment(deck 未知で相手の型を読む)。 v6 feature 接続は moot(v6 撤回済)。 [[project_opponent_deck_belief_model]] / [[project_search_route_pivot]]
- `leader_effect_profiles.json`: **リーダー効果の型 + 使い方 prior** (= A軸 自分理解、 opponent_deck_priors の対称、 318 leader)。 overlay の DSL から効果を分類 — timing(active=起動で時を選ぶ / attack / reactive / automatic / passive)× role(draw_engine/ramp/removal/aggression/enabler/develop/life_defense) → usage_pattern(engine_use_often / hold_for_threat / enabler_this_turn 等)。 「リーダー効果を いつ/どう 使うと強いか」 の粗い prior (精密な timing は多ターン探索 + Claude 教師が埋める、 play ログ無い為)。 runtime = `engine/leader_effect_profile.py` (primary_usage / when_decision / usage_hint / active_effects)。 builder = `scripts/build_leader_effect_profiles.py`。 ⚠ **まだ配備 AI には未配線** ([[project_opponent_deck_belief_model]] の A軸)
  - **統合 consumer = `engine/matchup_context.py`** (= A軸+B軸 prior を state に対して評価する層)。 `describe_matchup_context(state,me_idx)` が {own(自 leader 使い方), opponent(相手 belief 脅威、 見えた札で事後 sharpening)} を返し、 `format_context_text` で Claude 教師 / ログ 可読テキスト化。 探索の相手モデル・Claude 教師 context・分析 UI の共通入力。 ⚠ **1-ply value に静的 feature を足す路線は deploy-null 頻発** (v3/v5/v8 未配備、 効いたのは board-interactive v6 のみ) → prior の payoff は **多ターン探索/Claude 教師とセットで** 出る (単体 value feature 化では薄い)

## 開発コマンド

### 初回セットアップ

```bash
# Python (要 python3.12-venv)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Next.js (web/ 直下)
cd web && npm install
```

### 日常開発

```bash
# === 公式データ更新 (月次推奨) ===
.venv/bin/python scraper/scraper.py --all          # カードDB更新 (--with-images で全画像)
.venv/bin/python scripts/check_official_updates.py # PDF/FAQ/cardqa/banlist 全方位チェック
.venv/bin/python scripts/check_rules_update.py     # PDF だけのチェック (個別)
.venv/bin/python scripts/scrape_official_faq.py    # FAQ + cardqa 全件再取得
.venv/bin/python scripts/scrape_official_banlist.py # 禁止/制限カード再取得
.venv/bin/python scripts/refresh_all.py            # 上記 + メタデッキ + matrix を一括

# === メタデッキ更新 (cardrush.media 産) ===
.venv/bin/python scripts/scrape_cardrush_decks.py  # 大会優勝デッキを `decks/cardrush_*.json` で取得
.venv/bin/python scripts/scrape_cardrush_decks.py --scores 優勝 準優勝 --since 2026-01-01
.venv/bin/python scripts/select_cardrush_representatives.py # アーキタイプ毎に1つ代表選出

# === overlay 拡張・監査 ===
.venv/bin/python scripts/suggest_overlay_from_cards.py # cards.json から overlay 候補を自動抽出
                                                       # → db/card_effects.suggestions.json (手動マージ)
.venv/bin/python scripts/merge_overlay_suggestions.py  # suggestions の選択マージ
.venv/bin/python scripts/audit_overlay_vs_faq.py       # overlay vs FAQ 突合監査
                                                       # → db/overlay_audit.md (上位80件) + .json (全件)
                                                       # acknowledged.json で intrinsic 除外、 現状 sev≥3 = 0
.venv/bin/python scripts/verify_overlay_vs_cardqa.py   # cardqa 効果マーカー vs overlay when 整合性
                                                       # → db/overlay_when_missing.json (現状 missing 0)
.venv/bin/python scripts/audit_engine_strictness.py    # engine 厳密化 audit (10 項目、 現状 10/10 pass)
.venv/bin/python scripts/smoke_test_card_effects.py    # 全カード効果スモークテスト
                                                       # 各 effect を最小ステートで発火 → 変化検出

# === 画像 ===
.venv/bin/python scripts/cache_deck_images.py      # decks/ で使う画像をローカルキャッシュ
.venv/bin/python scripts/cache_all_images.py       # 全カード画像 (約 1〜2GB / 30〜60min)

# === 対戦 / matrix ===
.venv/bin/pytest                                   # 全テスト実行 (tests/ 以下)
.venv/bin/python examples/demo_matchup.py          # 50戦マッチアップ デモ
.venv/bin/python examples/demo_smoke.py            # 単一試合のスモークテスト
.venv/bin/python examples/demo_with_effects.py     # 効果オーバーレイ込みの対戦デモ
.venv/bin/python scripts/compute_matchup_matrix.py --n-games 20 --seed 42  # 勝率行列再計算
                                                                            # 16 デッキ × 256 セル × 20 戦 = 5120 試合 (約 60 分)
.venv/bin/python scripts/report_bad_moves.py --deck-a <a> --deck-b <b> --n-games 20 --threshold -3000
                                                                            # AI 行動品質分析 (R63、 board_eval delta が大きく負の手を抽出)

# === サーバ ===
.venv/bin/uvicorn api.main:app --reload --port 8000   # API起動
cd web && npm run dev                                  # Next.js dev (http://localhost:3000)
cd web && npm run build && npm start
cd web && npx tsc --noEmit                             # 型チェック
```

> 注: WSL のホスト経由マウントだと `*.py` が `*.PY` (大文字) として見えることがある。
> glob (`*.py`) で拾えない場合は明示パスで指定するか、`pyproject.toml` 経由で
> pytest に検出させる (現状こちらを使用)。

## Claude Code を使う時のヒント

- 機能追加は1機能=1ブランチ、PR を Claude Code に頼んで作らせると速い
- 「Phase 5: デッキビルダー実装」など phase 単位で依頼
- API のレスポンス型は `api/main.py` (Pydantic) と `web/src/lib/types.ts` の両方で定義
  → 不整合が起きたら `api/main.py` 側を真とする
- 変更前に `git status` の確認を Claude Code に依頼するクセをつける
- 効果を追加したら `pytest tests/` + デモ対戦で勝率の変動を確認

## 既知の落とし穴(過去にハマった)

- 公式サイトはGET `?series=550115` で各弾取得可能。HTMLレンダリング型なので JS 不要
- 画像URLは `https://www.onepiece-cardgame.com/images/cardlist/card/<card_id>.png` パターン。
  パラレル(`_p1`, `_p2`)も同パターンで取得可能
- マウントFS(WindowsのCowork経由など)では SQLite 直書きが失敗する場合あり。
  Python から書く場合は `/tmp` に作って bytes コピーするとよい
- `harness.run_matchup` に `effects_overlay` を渡し忘れていたバグあり (修正済み)。
  追加時は必ず `setup_game(..., effects_overlay=...)` までつないであるか確認
- `create-next-app` は内部で `git init` する。リポジトリルートが既に git 管理なら
  `web/.git` を削除してネスト解消する
- WSL の 8.3 短名: `*.PY` の大文字化、glob で拾えない場合がある。`pyproject.toml` の
  `[tool.pytest.ini_options]` で testpaths を指定して回避

### cardrush.media (メタデッキの参考ソース)

- Next.js SSR ページなので `<script id="__NEXT_DATA__">` を正規表現抽出 → `json.loads`
  すれば全データ (recipes 含む) が取れる。BS4 / playwright 不要
- card_number フィールドが既存 `cards.json` の `card_id` と完全一致 (OP14-020 / ST24-002 / EB01-015 / PRB02-006 / P-114 すべて検証済)
- 一覧ページ pageProps.lastPage でページ数取得 / 30件/page
- 同じアーキタイプで複数優勝レシピがある場合は `select_cardrush_representatives.py` で
  最新優勝を1つだけ採用 (それ以外は `decks/_archive/cardrush_raw/` へ)
- 取得したレシピが現禁止リスト違反 (例: OP07-115 + EB04-058 ペア) を含む場合、
  `DeckList.validate()` で検出される。該当レシピは `_archive/` へ追放、
  代替が無いアーキタイプは matrix から除外する
