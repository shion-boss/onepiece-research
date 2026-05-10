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
  cost_le?: number;
  cost_ge?: number;
  name_contains?: string;
  limit?: number;
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

export type DeckSummary = {
  slug: string;
  name: string;
  leader: string;
  leader_name: string;
  leader_color: string[];
  main_count: number;
  unique: number;
};

export type DeckDetail = DeckSpec & {
  slug?: string;
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
