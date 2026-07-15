export type CardCategory = "LEADER" | "CHARACTER" | "EVENT" | "STAGE";

export type Card = {
  card_id: string;
  name: string;
  category: CardCategory;
  color: string[];
  cost: number;
  life: number;
  power: number;
  counter: number;
  attribute: string;
  block_icon: number;
  features: string[];
  text: string;
  trigger: string;
  rarity: string;
  image_url?: string | null;
};

export type CardFilters = {
  color?: string;
  category?: CardCategory;
  feature?: string;
  set?: string;
  cost_le?: number;
  cost_ge?: number;
  name_contains?: string;
  block_icon_ge?: number;
  limit?: number;
};

// --- 弾 (= card_id 接頭辞) 一覧 (= /api/sets) ---
export type SetInfo = {
  code: string;
  count: number;
};

// --- コンボ探索 (= /api/combos/{card_id}) ---
export type ComboCard = {
  card_id: string;
  name: string;
  category: string;
  color: string[];
  cost: number;
  power: number;
  features: string[];
  text: string;
  score: number;
  reason: string;
};

export type ComboGroup = {
  key: string;
  label: string;
  description: string;
  cards: ComboCard[];
};

export type ComboChainStep = {
  card_id: string;
  name: string;
  role: string;
  category: string;
  color: string[];
  cost: number;
  text: string;
};

export type ComboChain = {
  n_cards: number;
  score: number;
  label: string;
  description: string;
  steps: ComboChainStep[];
};

export type ComboResult = {
  anchor: ComboCard;
  hooks: string[];
  groups: ComboGroup[];
  chains: ComboChain[];
};

export type DeckEntry = {
  card_id: string;
  count: number;
};

export type DeckSpec = {
  leader: string;
  main: DeckEntry[];
  name?: string;
};

export type Regulation = "standard" | "extra";

export type DeckSummary = {
  slug: string;
  name: string;
  leader: string;
  leader_name: string;
  leader_color: string[];
  main_count: number;
  unique: number;
  regulation?: Regulation;
  kind?: "meta" | "user"; // 環境デッキ(正準) か ユーザー作成か
  folder?: string; // ユーザーデッキの所属フォルダ ("" = ルート)
};

export type DeckDetail = DeckSpec & {
  slug?: string;
  regulation?: Regulation;
};

export type MatchRequest = {
  deck_a?: DeckSpec;
  deck_b?: DeckSpec;
  deck_a_id?: string;
  deck_b_id?: string;
  n_games?: number;
  seed?: number;
};

export type CountByLabel = {
  label: string;
  count: number;
};

export type CardRef = {
  card_id: string;
  name: string;
};

// db/banlist/master.json (GET /api/banlist)
export type Banlist = {
  standard_min_block: number;
  fetched_at?: string;
  source_url?: string;
  forbidden: CardRef[];
  restricted: CardRef[];
  forbidden_pairs: { a: CardRef; b: CardRef }[];
};

export type DeckAnalysis = {
  slug: string;
  name: string;
  leader: string;
  leader_name: string;
  main_count: number;
  color_dist: CountByLabel[];
  cost_curve: CountByLabel[];
  feature_top: CountByLabel[];
  counter_dist: CountByLabel[];
  avg_power: number;
  avg_cost: number;
  avg_counter: number;
  activate_main_cards: CardRef[];
  combos: DeckComboOut[];
};

export type DeckComboOut = {
  cards: CardRef[]; // 2-4 枚 (= 2枚コンボ or 多枚チェーン)
  kind: string; // enabler / payoff / amplifier / chain
  label: string;
  description: string;
  score: number;
};

export type MatchSummary = {
  job_id: string;
  deck_a_name: string;
  deck_b_name: string;
  deck_a_winrate: number;
  deck_a_wins: number;
  deck_b_wins: number;
  draws: number;
  n_games: number;
  avg_turns: number;
  median_turns: number;
  avg_life_left_winner: number;
  deck_a_first_wins: number;
  deck_a_second_wins: number;
};

export type FaqHit = {
  source: string;
  category: string;
  q: string;
  a: string;
};

export type FaqSource = {
  source: string;
  category: string;
  count: number;
};

export type MatchHistoryEntry = {
  timestamp: string;
  job_id: string;
  deck_a_name: string;
  deck_b_name: string;
  deck_a_id: string | null;
  deck_b_id: string | null;
  n_games: number;
  seed: number;
  deck_a_winrate: number;
  deck_a_wins: number;
  deck_b_wins: number;
  draws: number;
  avg_turns: number;
};

export type CoreBuildRequest = {
  leader: string;
  core_cards?: string[];
  core_counts?: Record<string, number>;
  name?: string;
  seed?: number;
};

export type CoreBuildResponse = {
  name: string;
  leader: string;
  leader_name: string;
  main: DeckEntry[];
  warnings: string[];
  effect_density: number;
  counter_total: number;
};

export type MatchupCell = {
  deck_b: string;
  winrate: number | null;
  wins: number;
  losses: number;
  draws: number;
  avg_turns: number;
  // self-play 打倒1位 campaign が deploy 時に書き戻した cell (= deploy_counter.py)。
  // 全 matrix 再計算でなく vs-#1 セルだけ更新した出自マーカー。
  selfplay_deployed?: boolean;
};

export type MatchupRow = {
  deck_a: string;
  deck_a_name: string;
  row: MatchupCell[];
};

export type MatchupMatrix = {
  computed_at: string;
  n_games: number;
  seed: number;
  decks: { slug: string; name: string }[];
  matrix: MatchupRow[];
  // schema 2.0+ で 追加 (= compute_matchup_matrix.py の AI version 識別子)
  ai_version?: string;
  schema_version?: string;
};

export type GameLog = {
  index: number;
  winner: number; // 0 (deck_a) / 1 (deck_b) / -1 (draw)
  first_player: number;
  turns: number;
  actions: number;
  p0_life_left: number;
  p1_life_left: number;
  p0_field: number;
  p1_field: number;
  log: string[];
};

export type CharSnapshot = {
  instance_id: number;
  card_id: string;
  name: string;
  rested: boolean;
  attached_dons: number;
  summoning_sickness: boolean;
  power: number;
  base_power: number;
  keywords: string[];
};

export type PlayerSnapshot = {
  name: string;
  leader: CharSnapshot;
  characters: CharSnapshot[];
  stages: CharSnapshot[];
  hand: string[];
  hand_count: number;
  known_hand_card_ids?: string[]; // 公開済 (サーチ等) の手札 card_id。 相手のものも見てよい情報
  life_count: number;
  trash: string[];
  trash_count: number;
  deck_count: number;
  don_active: number;
  don_rested: number;
  don_total: number;
  don_remaining_in_deck: number;
};

export type AttackEvent = {
  type: string;
  attacker_iid: number;
  target_iid: number;
  target_kind: string;
  atk_power: number;
  defender_power: number;
};

export type StateSnapshot = {
  turn: number;
  turn_player_idx: number;
  phase: string;
  log: string;
  game_over: boolean;
  winner: number | null;
  event: AttackEvent | null;
  players: PlayerSnapshot[];
  // turn_player_idx 視点の board_eval (= compute_score 14 指標)。
  // engine/core.py:_build_snapshot が R62+ で埋め込む。 古い snapshot には欠ける。
  board_eval?: number;
  // 手前 (= P0) 視点固定の盤面データ内訳 (= compute_breakdown、 AI が手を判断する全指標)。
  // {metric: {self(手前), opp(相手), diff, contribution}}。 record_snapshots=True の replay/sample のみ。
  board_eval_detail?: Record<
    string,
    { self: number; opp: number; diff: number; contribution: number }
  >;
};

export type ReplayResponse = {
  job_id: string;
  game_index: number;
  deck_a_name: string;
  deck_b_name: string;
  first_player: number;
  winner: number;
  turns: number;
  snapshots: StateSnapshot[];
};

// AI vs AI 連戦 (勝率 + 各試合 seed)。 観戦は seed で replay を再現。
export type MatrixBatchResult = {
  deck_a_name: string;
  deck_b_name: string;
  n_games: number;
  p0_wins: number;
  p1_wins: number;
  draws: number;
  games: {
    game_index: number;
    seed: number;
    winner: number; // P0(deck_a) 基準: 0=P0勝, 1=P1勝, -1=引分
    turns: number;
    first_player: number; // 0=P0先攻, 1=P1先攻
    swap: boolean; // true なら deck 順を入替えて実行 (= P1 先攻)。 観戦再現に使う
  }[];
};

// 1 試合だけ実行した結果 (10連戦を 1 試合ずつ逐次表示する用)。
export type MatrixGameResult = {
  deck_a_name: string;
  deck_b_name: string;
  seed: number;
  swap: boolean;
  first_player: number;
  winner: number; // P0(deck_a) 基準: 0=P0勝, 1=P1勝, -1=引分
  turns: number;
};

// 逐次表示用の 1 試合行 (MatrixBatchResult.games[number] と同形)。
export type MatrixBatchGame = MatrixBatchResult["games"][number];

// === 試合後分析 ===
export type EvalPoint = {
  snap_idx: number;
  turn: number;
  phase: string;
  score: number;
  normalized: number;
  log: string;
};

export type TurningPoint = {
  snap_idx: number;
  turn: number;
  delta: number;
  side: "self_gain" | "self_loss";
  log: string;
  score_before: number;
  score_after: number;
};

export type GameSummary = {
  avg_score: number;
  max_lead: number;
  max_deficit: number;
  final_score: number;
  comeback: boolean;
};

export type GameAnalysisResponse = {
  job_id: string;
  game_index: number;
  me_idx: number;
  me_name: string;
  opp_name: string;
  winner: number | null;
  eval_series: EvalPoint[];
  turning_points: TurningPoint[];
  summary: GameSummary | null;
};

// === デッキ静的分析 (engine/deck_analyzer.py) ===
export type DeckCostBucket = { cost: number; count: number };

export type DeckKeyCard = {
  card_id: string;
  name: string;
  count: number;
  cost: number;
  role: string;
  reason: string;
};

export type DeckIdealMove = {
  turn: number;
  description: string;
  candidate_cards: string[];
};

export type DeckStrategy = {
  deck_name: string;
  leader_id: string;
  leader_name: string;
  leader_color: string[];
  leader_features: string[];
  leader_text: string;

  total_cards: number;
  n_character: number;
  n_event: number;
  n_stage: number;
  avg_cost: number;
  cost_curve: DeckCostBucket[];
  counter_total: number;
  counter_2k_count: number;
  counter_1k_count: number;
  blocker_count: number;
  color_distribution: Record<string, number>;
  top_features: [string, number][];

  archetype: string;
  speed: string;
  defense: string;
  consistency: string;
  strategy_summary: string;

  mulligan_keep_card_ids: string[];
  mulligan_keep_criteria: string[];
  mulligan_throw_criteria: string[];

  ideal_moves: DeckIdealMove[];

  weaknesses: string[];
  strengths: string[];
  key_cards: DeckKeyCard[];
  ai_hints: string[];
};

// === Phase B.5: 対策デッキ探索 ===
export type CounterCandidate = {
  rank: number;
  leader: string;
  leader_name: string;
  archetype: string;
  estimated_score: number;
  rationale: string[];
  role_distribution: Record<string, number>;
  main: DeckEntry[];
  regulation_required: Regulation;   // "standard" or "extra"
  extra_only_cards: string[];        // block① のみのカード ID
};

export type ExploreCounterRequest = {
  target_slug: string;
  leader_filter?: string[];
  must_include?: string[];
  n_candidates?: number;
};

export type ExploreCounterResponse = {
  target_slug: string;
  target_name: string;
  n_generated: number;
  candidates: CounterCandidate[];
};

// === デッキ改善提案 ===
export type CardChange = {
  card_id: string;
  delta: number;
  name: string;
};

export type ImprovementProposal = {
  proposal_id: string;
  proposal_type: "swap" | "count_decrease" | "count_increase";
  changes: CardChange[];
  reason: string;
  impact_estimate: number;
};

export type CardStat = {
  card_id: string;
  name: string;
  n_in_deck: number;
  n_appearances: number;
  n_total_plays: number;
  winrate_when_played: number;
};

export type DeckImprovementsResponse = {
  slug: string;
  n_matches: number;
  deck_winrate_baseline: number;
  card_stats: CardStat[];
  proposals: ImprovementProposal[];
};

export type ApplyImprovementResponse = {
  slug: string;
  main: DeckEntry[];
  warnings: string[];
};

// === Phase R: 研究セッション ===
export type ResearchSessionConfig = {
  target_slug: string;
  leader_filter?: string[] | null;
  must_include?: string[] | null;
  target_winrate?: number;
  max_generations?: number;
  n_games_per_eval?: number;
  initial_population?: number;
  mutations_per_top?: number;
  top_k?: number;
  seed?: number;
};

export type ResearchSessionStartResponse = {
  session_id: string;
  status: string;
};

export type ResearchSessionSummary = {
  id: string;
  target_slug: string;
  status: "running" | "paused" | "completed" | "stopped";
  created_at: string;
  updated_at: string;
  current_generation: number;
  best_winrate: number | null;
  completion_reason: string | null;
};

export type ResearchGenerationHistory = {
  generation: number;
  n_candidates: number;
  best_winrate: number | null;
  avg_winrate: number | null;
};

export type ResearchSessionDetail = {
  id: string;
  target_slug: string;
  config: Record<string, unknown>;
  status: "running" | "paused" | "completed" | "stopped";
  created_at: string;
  updated_at: string;
  current_generation: number;
  best_winrate: number | null;
  best_deck: { leader: string; main: DeckEntry[]; name?: string; leader_name?: string } | null;
  completion_reason: string | null;
  generation_history: ResearchGenerationHistory[];
};

export type ResearchCandidate = {
  id: number;
  generation: number;
  candidate_idx: number;
  deck: { leader: string; main: DeckEntry[]; name?: string; leader_name?: string };
  parent_id: number | null;
  mutation_type: string | null;
  winrate: number | null;
  n_games: number | null;
  evaluated_at: string | null;
};

export type ResearchBestDeckResponse = {
  session_id: string;
  candidate_id: number;
  generation: number;
  winrate: number;
  n_games: number;
  mutation_type: string;
  deck: { leader: string; main: DeckEntry[]; name?: string; leader_name?: string };
};

// MCTS rerank (Explorer 候補の MCTS 評価、 U3)
export type RerankResult = {
  leader: string;
  name: string;
  original_index: number;
  mcts_wins: number;
  mcts_total: number;
  mcts_winrate: number;
};

export type RerankResponse = {
  target_slug: string;
  target_name: string;
  n_candidates: number;
  n_games_per_candidate: number;
  results: RerankResult[];
  elapsed_seconds: number;
};

// MCTS-based 改善提案 (= U2)
export type McctsCardStat = {
  card_id: string;
  name: string;
  n_in_deck: number;
  mcts_plays: number;
  greedy_plays: number;
  mcts_preference: number;       // -1..+1
};

export type McctsImprovementsRequest = {
  opponent_slug: string;
  seed?: number;
  n_simulations?: number;
};

export type McctsImprovementsResponse = {
  slug: string;
  opponent_slug: string;
  n_mcts_turns: number;
  card_stats: McctsCardStat[];
  proposals: ImprovementProposal[];
};
