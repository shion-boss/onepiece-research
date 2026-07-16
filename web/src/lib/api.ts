import type {
  ApplyImprovementResponse,
  Banlist,
  Card,
  CardChange,
  CardFilters,
  ComboResult,
  CardRef,
  CoreBuildRequest,
  CoreBuildResponse,
  DeckAnalysis,
  DeckDetail,
  DeckEntry,
  DeckImprovementsResponse,
  DeckSummary,
  ExploreCounterRequest,
  ExploreCounterResponse,
  FaqHit,
  FaqSource,
  GameLog,
  McctsImprovementsRequest,
  McctsImprovementsResponse,
  RerankResponse,
  MatchHistoryEntry,
  MatchRequest,
  MatchSummary,
  MatchupMatrix,
  DeckStrategy,
  GameAnalysisResponse,
  ReplayResponse,
  MatrixBatchResult,
  MatrixGameResult,
  ResearchBestDeckResponse,
  ResearchCandidate,
  ResearchSessionConfig,
  ResearchSessionDetail,
  ResearchSessionStartResponse,
  ResearchSessionSummary,
  SetInfo,
} from "./types";

import { authHeaders } from "./auth";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function fetchCards(filters: CardFilters = {}): Promise<Card[]> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v != null && v !== "") params.set(k, String(v));
  }
  // カード DB は不変・公開データ → force-cache で再取得しない。
  const res = await fetch(`${API}/api/cards?${params}`, { cache: "force-cache" });
  if (!res.ok) throw new Error(`fetchCards failed: ${res.status}`);
  return res.json();
}

export async function fetchSets(): Promise<SetInfo[]> {
  const res = await fetch(`${API}/api/sets`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchSets failed: ${res.status}`);
  return res.json();
}

export async function fetchBanlist(): Promise<Banlist> {
  const res = await fetch(`${API}/api/banlist`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchBanlist failed: ${res.status}`);
  return res.json();
}

export async function fetchCard(cardId: string): Promise<Card> {
  // カード単体は不変 → force-cache (デッキ詳細で 1 枚ずつ引く分を毎回再取得しない)。
  const res = await fetch(`${API}/api/cards/${encodeURIComponent(cardId)}`, {
    cache: "force-cache",
  });
  if (!res.ok) throw new Error(`fetchCard failed: ${res.status}`);
  return res.json();
}

export async function fetchCombos(
  cardId: string,
  perGroup = 8,
  regulation: "all" | "standard" = "all",
): Promise<ComboResult> {
  const res = await fetch(
    `${API}/api/combos/${encodeURIComponent(cardId)}?per_group=${perGroup}&regulation=${regulation}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchCombos failed: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<{ ok: boolean; cards: number }> {
  const res = await fetch(`${API}/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchHealth failed: ${res.status}`);
  return res.json();
}

// --- 陣取り (territory) 占領状態 (公開 read。 ポーリングで常時最新) --- //
export type TerritoryCell = {
  cell_id: number;
  leader_id: string | null;   // base card_id (137 単位、 集計キー)
  variant_id: string | null;  // 表示用 full card_id (パラレル suffix 込み)
  user: string | null;        // 占領者
  deck_slug: string | null;   // 占領者の使用デッキ (防衛 AI が操縦)
  version: number;
  updated_at?: string;        // 最終占領日時 (= ブロックの最新 variant 選択用)
};

export type TerritoryBoard = {
  board_version: number;
  n_cells: number;
  cells: TerritoryCell[]; // 占領済みマスのみ (空きは省略)
};

export async function fetchTerritoryBoard(): Promise<TerritoryBoard> {
  const res = await fetch(`${API}/api/territory`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchTerritoryBoard failed: ${res.status}`);
  return res.json();
}

export async function fetchTerritoryCell(cellId: number): Promise<TerritoryCell> {
  const res = await fetch(`${API}/api/territory/${cellId}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchTerritoryCell failed: ${res.status}`);
  return res.json();
}

// --- 戦いの歴史: 月次スナップショット (完了月の最終陣地 + 集計。 実データ、 空スタート) --- //
export type TerritorySnapshotSummary = {
  month_key: string;   // "YYYY-MM"
  occupied: number;    // その月末の占領マス数
  n_battles: number;   // その月の対戦数 (non_stakes 除く)
  human_wins: number;  // 挑戦者(人間)の勝ち数
  ai_wins: number;     // 防衛(AI)の勝ち数
  frozen_at: string;   // 凍結日時
};

export type TerritorySnapshot = TerritorySnapshotSummary & {
  board: TerritoryBoard; // その月末に凍結した盤 (buildCellsFromBoard で描画)
};

export async function fetchTerritorySnapshots(): Promise<TerritorySnapshotSummary[]> {
  const res = await fetch(`${API}/api/territory/snapshots`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchTerritorySnapshots failed: ${res.status}`);
  const data = await res.json();
  return (data.snapshots ?? []) as TerritorySnapshotSummary[];
}

export async function fetchTerritorySnapshot(monthKey: string): Promise<TerritorySnapshot> {
  const res = await fetch(`${API}/api/territory/snapshots/${encodeURIComponent(monthKey)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchTerritorySnapshot failed: ${res.status}`);
  return res.json();
}

// サーバコンポーネントは authHeaders() が効かない (document 無し) ので、 cookie から読んだ
// X-Dev-User を extra で渡す。 クライアントからは authHeaders() が自動で付く。
export async function fetchDecks(
  extra: Record<string, string> = {},
): Promise<DeckSummary[]> {
  const res = await fetch(`${API}/api/decks`, {
    cache: "no-store",
    headers: { ...(await authHeaders()), ...extra },
  });
  if (!res.ok) {
    // 診断: API が返した理由 (401 の detail 等) をエラーに含めて画面に出す。
    const body = await res.text().catch(() => "");
    throw new Error(`fetchDecks failed: ${res.status} — ${body}`);
  }
  return res.json();
}

export async function fetchDeck(
  slug: string,
  extra: Record<string, string> = {},
): Promise<DeckDetail> {
  const res = await fetch(`${API}/api/decks/${encodeURIComponent(slug)}`, {
    cache: "no-store",
    headers: { ...(await authHeaders()), ...extra },
  });
  if (!res.ok) throw new Error(`fetchDeck failed: ${res.status}`);
  return res.json();
}

export async function fetchDeckAnalysis(
  slug: string,
  extra: Record<string, string> = {},
): Promise<DeckAnalysis> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/analyze`,
    { cache: "no-store", headers: { ...(await authHeaders()), ...extra } },
  );
  if (!res.ok) throw new Error(`fetchDeckAnalysis failed: ${res.status}`);
  return res.json();
}

// 裏で計算するデッキ分析レポート (= AI vs AI 相性 + 役割内訳 + キーカード)。
export type DeckReportMatchup = {
  slug: string;
  name: string;
  leader: string;
  leader_name: string;
  win_rate: number;
  n: number;
};
export type DeckReportBody = {
  computed_at: string;
  ai_version: string;
  n_games_per_matchup: number;
  recipe_hash?: string;
  roles: { role: string; label: string; count: number }[];
  key_cards: { card_id: string; name: string; role: string; label: string; threat_level: number; count: number }[];
  archetype: string;
  speed_dist: { early: number; mid: number; late: number };
  curve_buckets: { low: number; mid: number; high: number };
  matchups: DeckReportMatchup[];
  n_opponents?: number;
  matchup_summary: { avg: number; best: DeckReportMatchup[]; worst: DeckReportMatchup[] };
  insights?: { kind: string; title: string; detail: string; strength?: number }[];
  profile?: Partial<{
    avg_turns: number;
    first_attack_turn: number;
    attacks_per_game: number;
    attacks_landed: number;
    ko_dealt: number;
    ko_lost: number;
    opp_attacks: number;
    blocker_uses: number;
    counter_uses: number;
  }>;
  top_cards?: { card_id: string; name: string; play_rate: number }[];
  matchup_plans?: { archetype: string; win_rate: number; n: number; detail: string }[];
  win_combos?: { cards: string[]; label: string; win_rate: number; base_win_rate: number; n: number; strength: number }[];
  mulligan?: { name: string; win_rate_with: number; win_rate_without: number; n: number; strength: number }[];
  partial?: boolean;
};
export type DeckReport = {
  status: "none" | "pending" | "running" | "done" | "failed";
  stale: boolean;
  report: DeckReportBody | null;
  kind: "user" | "meta";
};

export async function fetchDeckReport(slug: string, headers?: HeadersInit): Promise<DeckReport> {
  const res = await fetch(`${API}/api/decks/${encodeURIComponent(slug)}/report`, {
    cache: "no-store",
    headers: { ...(await authHeaders()), ...(headers as Record<string, string> | undefined) },
  });
  if (!res.ok) throw new Error(`fetchDeckReport failed: ${res.status}`);
  return res.json();
}

export async function requestDeckAnalysis(slug: string): Promise<{ status: string }> {
  const res = await fetch(`${API}/api/decks/${encodeURIComponent(slug)}/analyze-request`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeaders()) },
  });
  if (!res.ok) throw new Error(`requestDeckAnalysis failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function runMatch(req: MatchRequest): Promise<MatchSummary> {
  const res = await fetch(`${API}/api/match`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`runMatch failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function fetchMatchSummary(jobId: string): Promise<MatchSummary> {
  const res = await fetch(`${API}/api/match/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchMatchSummary failed: ${res.status}`);
  return res.json();
}

export async function fetchMatchGames(jobId: string): Promise<GameLog[]> {
  const res = await fetch(
    `${API}/api/match/${encodeURIComponent(jobId)}/games`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchMatchGames failed: ${res.status}`);
  return res.json();
}

export async function fetchMatchGame(
  jobId: string,
  gameIndex: number,
): Promise<GameLog> {
  const res = await fetch(
    `${API}/api/match/${encodeURIComponent(jobId)}/games/${gameIndex}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchMatchGame failed: ${res.status}`);
  return res.json();
}

export async function fetchMatchReplay(
  jobId: string,
  gameIndex: number,
): Promise<ReplayResponse> {
  const res = await fetch(
    `${API}/api/match/${encodeURIComponent(jobId)}/games/${gameIndex}/replay`,
    {
      method: "POST",
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`fetchMatchReplay failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function fetchDeckStrategy(
  slug: string,
  extra: Record<string, string> = {},
): Promise<DeckStrategy> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/strategy`,
    { cache: "no-store", headers: { ...(await authHeaders()), ...extra } },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`fetchDeckStrategy failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function fetchGameAnalysis(
  jobId: string,
  gameIndex: number,
): Promise<GameAnalysisResponse> {
  const res = await fetch(
    `${API}/api/match/${encodeURIComponent(jobId)}/games/${gameIndex}/analysis`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`fetchGameAnalysis failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export interface CreateDeckRequest {
  name: string;
  leader: string;
  main: { card_id: string; count: number }[];
  slug?: string;
  overwrite?: boolean;
  regulation?: string;
  private?: boolean; // 非公開 (= 陣取りで使用不可)。 生成時にのみ有効・以後不変
  draft?: boolean; // 下書き保存 (= 未完成でも保存、 対戦選択肢に出さない)
}

export interface CreateDeckResponse {
  slug: string;
  path: string;
  warnings: string[];
}

export interface ValidateDeckResponse {
  ok: boolean;
  errors: string[];
}

export async function saveDeckToServer(
  req: CreateDeckRequest,
): Promise<CreateDeckResponse> {
  const res = await fetch(`${API}/api/decks`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`saveDeckToServer failed: ${res.status} ${detail}`);
  }
  return res.json();
}

async function postJson(path: string, body: unknown): Promise<void> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status} ${await res.text().catch(() => "")}`);
}

/** デッキをフォルダへ移動 ("" = ルート)。 */
export function moveDeckToFolder(slug: string, folder: string): Promise<void> {
  return postJson(`/api/decks/${encodeURIComponent(slug)}/folder`, { folder });
}
/** フォルダ名を変更 (中の全デッキを付け替え)。 */
export function renameFolder(oldName: string, newName: string): Promise<void> {
  return postJson(`/api/folders/rename`, { old: oldName, new: newName });
}
/** フォルダを解体 (中のデッキをルートへ)。 */
export function deleteFolder(folder: string): Promise<void> {
  return postJson(`/api/folders/delete`, { folder });
}
/** デッキの表示名を変更 (slug は不変)。 */
export function renameDeck(slug: string, name: string): Promise<void> {
  return postJson(`/api/decks/${encodeURIComponent(slug)}/name`, { name });
}

/** 自作デッキを削除 (メタ環境デッキは 403 で保護)。 */
export async function deleteDeck(slug: string): Promise<void> {
  const res = await fetch(`${API}/api/decks/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    headers: { ...(await authHeaders()) },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`deleteDeck failed: ${res.status} ${detail}`);
  }
}

export async function validateDeckOnServer(
  req: CreateDeckRequest,
): Promise<ValidateDeckResponse> {
  const res = await fetch(`${API}/api/decks/validate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`validateDeckOnServer failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function exploreCounterDecks(
  req: ExploreCounterRequest,
): Promise<ExploreCounterResponse> {
  const res = await fetch(`${API}/api/explore/counter-decks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`exploreCounterDecks failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function fetchDeckImprovements(
  slug: string,
): Promise<DeckImprovementsResponse> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/improvements`,
    { cache: "no-store" },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`fetchDeckImprovements failed: ${res.status} ${detail}`);
  }
  return res.json();
}

// === Phase R: 研究セッション ===
export async function startResearchSession(
  config: ResearchSessionConfig,
): Promise<ResearchSessionStartResponse> {
  const res = await fetch(`${API}/api/research/sessions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(config),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`startResearchSession failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function listResearchSessions(opts?: {
  limit?: number;
  status?: "running" | "paused" | "completed" | "stopped";
}): Promise<ResearchSessionSummary[]> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.status) params.set("status", opts.status);
  const url = `${API}/api/research/sessions${params.toString() ? "?" + params : ""}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`listResearchSessions failed: ${res.status}`);
  return res.json();
}

export async function fetchResearchSession(
  sessionId: string,
): Promise<ResearchSessionDetail> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchResearchSession failed: ${res.status}`);
  return res.json();
}

export async function pauseResearchSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}/pause`,
    { method: "POST", cache: "no-store" },
  );
  if (!res.ok) throw new Error(`pauseResearchSession failed: ${res.status}`);
}

export async function resumeResearchSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}/resume`,
    { method: "POST", cache: "no-store" },
  );
  if (!res.ok) throw new Error(`resumeResearchSession failed: ${res.status}`);
}

export async function stopResearchSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}/stop`,
    { method: "POST", cache: "no-store" },
  );
  if (!res.ok) throw new Error(`stopResearchSession failed: ${res.status}`);
}

export async function fetchResearchBestDeck(
  sessionId: string,
): Promise<ResearchBestDeckResponse> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}/best-deck`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchResearchBestDeck failed: ${res.status}`);
  return res.json();
}

export async function fetchResearchCandidates(
  sessionId: string,
  opts?: { generation?: number; limit?: number },
): Promise<ResearchCandidate[]> {
  const params = new URLSearchParams();
  if (opts?.generation !== undefined) params.set("generation", String(opts.generation));
  if (opts?.limit) params.set("limit", String(opts.limit));
  const url = `${API}/api/research/sessions/${encodeURIComponent(sessionId)}/candidates${params.toString() ? "?" + params : ""}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchResearchCandidates failed: ${res.status}`);
  return res.json();
}

export async function deleteResearchSession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API}/api/research/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE", cache: "no-store" },
  );
  if (!res.ok) throw new Error(`deleteResearchSession failed: ${res.status}`);
}

export async function rerankWithMcts(req: {
  target_slug: string;
  candidates: { leader: string; main: { card_id: string; count: number }[]; name?: string }[];
  seed?: number;
  n_simulations?: number;
  n_games_per_candidate?: number;
}): Promise<RerankResponse> {
  const res = await fetch(`${API}/api/explore/rerank-with-mcts`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`rerankWithMcts failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function runMctsImprovements(
  slug: string,
  req: McctsImprovementsRequest,
): Promise<McctsImprovementsResponse> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/improvements/mcts`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`runMctsImprovements failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function applyDeckImprovement(
  slug: string,
  changes: CardChange[],
): Promise<ApplyImprovementResponse> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/apply-improvement`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ changes }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`applyDeckImprovement failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function buildDeckWithCore(
  req: CoreBuildRequest,
): Promise<CoreBuildResponse> {
  const res = await fetch(`${API}/api/decks/build`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`buildDeckWithCore failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export type GenerateDeckRequest = {
  leader: string;
  must_include?: string[];
  mode?: "combo" | "target" | "meta";
  target_slug?: string | null;
  n_candidates?: number;
  n_sim_eval?: number;
  n_games?: number;
  meta_sample?: number;
  hill_climb_iters?: number;
  seed?: number;
  regulation?: "standard" | "extra";
};

export type GeneratedDeckOut = {
  main: DeckEntry[];
  leader: string;
  combo_strength: number;
  win_rate?: number | null;
  score: number;
  extras: CardRef[];
};

export type GenerateDeckResponse = {
  leader: string;
  leader_name: string;
  mode: string;
  opponents: string[];
  candidates: GeneratedDeckOut[];
  warnings: string[];
};

export async function generateDeck(
  req: GenerateDeckRequest,
): Promise<GenerateDeckResponse> {
  const res = await fetch(`${API}/api/decks/generate`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`generateDeck failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function fetchMetaMatrix(): Promise<MatchupMatrix> {
  const res = await fetch(`${API}/api/meta/matrix`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchMetaMatrix failed: ${res.status}`);
  return res.json();
}

export type MatrixProgress = {
  running: boolean;
  exists: boolean;
  ai_version?: string;
  n_games_per_cell?: number;
  n_decks?: number;
  rows_done?: number;
  rows_total?: number;
  cells_done?: number;
  cells_total?: number;
  last_row_cells_filled?: number;
  last_cell_time?: string | null;
  matrix_mtime?: number | null;
  computed_at?: string;
  tier_preview?: {
    deck_slug: string;
    deck_name: string;
    avg_winrate: number;
    matches_played: number;
  }[];
  decks?: { slug: string; name: string }[];
};

export async function fetchMatrixProgress(): Promise<MatrixProgress> {
  const res = await fetch(`${API}/api/matrix/progress`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchMatrixProgress failed: ${res.status}`);
  return res.json();
}

export type MatrixLogEntry = {
  ts?: string;
  event?: string;
  deck_a?: string;
  deck_b?: string;
  deck_a_name?: string;
  deck_b_name?: string;
  game_index?: number;
  winner?: number | null;
  turns?: number;
  p0_life_left?: number;
  p1_life_left?: number;
  p0_field?: number;
  p1_field?: number;
  cell_winrate?: number;
  cell_wins?: number;
  cell_losses?: number;
  cell_draws?: number;
  [k: string]: unknown;
};

export type MatrixLogTail = {
  exists: boolean;
  entries: MatrixLogEntry[];
  count?: number;
  error?: string;
};

export async function fetchMatrixLogTail(
  lines = 50,
): Promise<MatrixLogTail> {
  const res = await fetch(
    `${API}/api/matrix/log/tail?lines=${lines}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchMatrixLogTail failed: ${res.status}`);
  return res.json();
}

export async function runMatrixSampleReplay(
  deckA: string,
  deckB: string,
  seed = 42,
  firstPlayer = 0,
): Promise<ReplayResponse> {
  const res = await fetch(`${API}/api/matrix/sample/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ deck_a: deckA, deck_b: deckB, seed, first_player: firstPlayer }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`runMatrixSampleReplay failed: ${res.status} ${text}`);
  }
  return res.json();
}

/** 2 デッキで n 連戦して勝率 + 各試合の結果(seed)を返す (観戦は同 seed の replay で再現)。 */
export async function runMatrixSampleBatch(
  deckA: string,
  deckB: string,
  seed: number,
  nGames: number,
): Promise<MatrixBatchResult> {
  const res = await fetch(`${API}/api/matrix/sample/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ deck_a: deckA, deck_b: deckB, seed, n_games: nGames }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`runMatrixSampleBatch failed: ${res.status} ${text}`);
  }
  return res.json();
}

/** 2 デッキで 1 試合だけ実行 (seed/swap は client 指定)。 10連戦を 1 試合ずつ逐次表示する用。 */
export async function runMatrixSampleGame(
  deckA: string,
  deckB: string,
  seed: number,
  swap: boolean,
): Promise<MatrixGameResult> {
  const res = await fetch(`${API}/api/matrix/sample/game`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ deck_a: deckA, deck_b: deckB, seed, swap }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`runMatrixSampleGame failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function fetchFaqSources(): Promise<FaqSource[]> {
  const res = await fetch(`${API}/api/faq/sources`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchFaqSources failed: ${res.status}`);
  return res.json();
}

export type FaqMeta = { count: number; sources: number; generated_at: string | null };

export async function fetchFaqMeta(): Promise<FaqMeta> {
  const res = await fetch(`${API}/api/faq/meta`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchFaqMeta failed: ${res.status}`);
  return res.json();
}

// Q&A スクレイプ対象のリンク一覧 (= Q&A 参照先タブ)。
export type FaqSourceLink = {
  source: string;
  label: string;
  source_url: string | null;
  count: number;
  fetched_at?: string | null;
};

export async function fetchFaqSourceLinks(headers?: HeadersInit): Promise<FaqSourceLink[]> {
  const res = await fetch(`${API}/api/faq/source-links`, { cache: "no-store", headers });
  if (!res.ok) throw new Error(`fetchFaqSourceLinks failed: ${res.status}`);
  return res.json();
}

// ---- Phase A: 人間 vs AI 対戦 セッション API ---- //

export type HumanLegalAction = {
  idx: number;
  kind: string;
  label: string;
  hand_idx?: number;
  iid?: number;
  attacker_iid?: number;
  target_iid?: number;
  source_iid?: number;
  effect_index?: number;
  n?: number;
  sacrifice_iid?: number;  // 場 5 体 差替 え 時 の trash 対 象 (= 公 式 3-7-6-1)
};

export type HumanSessionSpec = {
  seed: number;
  deck_a_slug: string;
  deck_b_slug: string;
  human_first: boolean;
};

export type HumanActionLog = {
  kind:
    | "action"
    | "defense"
    | "choice"
    | "use_opp_attack_effect"
    | "use_counter_event";
  action_idx?: number;
  blocker_iid?: number | null;
  counter_card_idxs?: number[];
  picks?: number[];
  source_iid?: number;
  effect_idx?: number;
  hand_idx?: number;
};

export type LiveCombo = {
  cards: { card_id: string; name: string }[];
  kind: string; // enabler / payoff / amplifier / chain
  label: string;
  description: string;
  score: number;
};

export type HumanMatchState = {
  session_id?: string;
  game_over: boolean;
  winner: number | null;
  turn: number;
  turn_player_idx: number;
  phase: string;
  human_idx: number;
  ai_idx: number;
  pending_kind: "action" | "defense" | "choice" | null;
  pending_payload: Record<string, unknown> | null;
  log: string[];
  snapshot: Record<string, unknown> | null;
  // 前回 payload 以降 に 追加 された 中間 snapshot 群 (= AI 動作 を 順次 再生 する 用)
  frames?: Record<string, unknown>[];
  legal_actions: HumanLegalAction[];
  // 今この盤面で自分の手札/場に揃っているデッキ内コンボ (= 対戦時活用ヒント)
  live_combos?: LiveCombo[];
  snapshots_count: number;
  deck_a_slug: string;
  deck_b_slug: string;
  // serverless 環境 で session が 別 function instance に 振られた 場合 に 再構築 する 用。
  // start で受け取り、 各 apply* で 毎回 送信。 localStorage に 保存して リロード復元 も可。
  session_spec?: HumanSessionSpec;
  actions?: HumanActionLog[];
  // 陣取り挑戦なら start 応答に付く (= 対象マス + 開始時 version + 防衛側情報)。
  challenge?: {
    cell_id: number;
    expected_version: number;
    owned: boolean;
    defender_leader_id: string | null;
    defender_variant_id: string | null;
    defender_user: string | null;
  };
};

type ResumeFields = {
  session_spec?: HumanSessionSpec;
  prior_actions?: HumanActionLog[];
};

export async function startHumanMatch(
  deckASlug: string,
  deckBSlug: string,
  opts: { seed?: number; human_first?: boolean | null; cell_id?: number } = {},
): Promise<HumanMatchState> {
  const res = await fetch(`${API}/api/human_match`, {
    method: "POST",
    // authHeaders: 自分の非公開デッキ (deck_a) を per-user DB から resolve するのに必要。
    // dev = X-Dev-User / 本番 Clerk = Bearer。
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      deck_a_slug: deckASlug,
      deck_b_slug: deckBSlug,
      seed: opts.seed ?? 42,
      human_first: opts.human_first ?? null,
      // 陣取り挑戦なら対象マス。 占領マスは server が防衛デッキを差し替える。
      ...(opts.cell_id != null ? { cell_id: opts.cell_id } : {}),
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`startHumanMatch failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function fetchHumanMatch(sid: string): Promise<HumanMatchState> {
  const res = await fetch(`${API}/api/human_match/${sid}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchHumanMatch failed: ${res.status}`);
  return res.json();
}

export async function applyHumanAction(
  sid: string,
  actionIdx: number,
  resume?: ResumeFields,
): Promise<HumanMatchState> {
  const res = await fetch(`${API}/api/human_match/${sid}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action_idx: actionIdx,
      session_spec: resume?.session_spec,
      prior_actions: resume?.prior_actions,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`applyHumanAction failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function applyHumanDefense(
  sid: string,
  blockerIid: number | null,
  counterCardIdxs: number[],
  resume?: ResumeFields,
): Promise<HumanMatchState> {
  const res = await fetch(`${API}/api/human_match/${sid}/defense`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      blocker_iid: blockerIid,
      counter_card_idxs: counterCardIdxs,
      session_spec: resume?.session_spec,
      prior_actions: resume?.prior_actions,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`applyHumanDefense failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function applyHumanChoice(
  sid: string,
  picks: number[],
  resume?: ResumeFields,
): Promise<HumanMatchState> {
  const res = await fetch(`${API}/api/human_match/${sid}/choice`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      picks,
      session_spec: resume?.session_spec,
      prior_actions: resume?.prior_actions,
    }),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`applyHumanChoice failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function applyHumanUseOppAttackEffect(
  sid: string,
  source_iid: number,
  effect_idx: number,
  resume?: ResumeFields,
): Promise<HumanMatchState> {
  const res = await fetch(
    `${API}/api/human_match/${sid}/use_opp_attack_effect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_iid,
        effect_idx,
        session_spec: resume?.session_spec,
        prior_actions: resume?.prior_actions,
      }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `applyHumanUseOppAttackEffect failed: ${res.status} ${text}`,
    );
  }
  return res.json();
}

export async function applyHumanUseCounterEvent(
  sid: string,
  hand_idx: number,
  resume?: ResumeFields,
): Promise<HumanMatchState> {
  const res = await fetch(
    `${API}/api/human_match/${sid}/use_counter_event`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hand_idx,
        session_spec: resume?.session_spec,
        prior_actions: resume?.prior_actions,
      }),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `applyHumanUseCounterEvent failed: ${res.status} ${text}`,
    );
  }
  return res.json();
}

export async function endHumanMatch(sid: string): Promise<void> {
  await fetch(`${API}/api/human_match/${sid}`, {
    method: "DELETE",
    cache: "no-store",
  });
}

// 陣取り挑戦のコンテキスト (= 勝利時に占領を試みる + 戦い履歴を記録)。 陣取り経由の対戦だけ渡す。
export type ChallengeContext = {
  cell_id: number;
  expected_version: number;
  human_leader_id?: string | null;
  human_variant_id?: string | null;
  defender_leader_id?: string | null;
  defender_variant_id?: string | null;
  defender_user?: string | null;
};

export type TerritoryBattle = {
  id: number;
  cell_id: number;
  ts: string;
  attacker_user: string | null;
  attacker_leader_id: string | null;
  attacker_variant_id: string | null;
  defender_user: string | null;
  defender_leader_id: string | null;
  defender_variant_id: string | null;
  attacker_won: boolean;
  captured: boolean;
  non_stakes: boolean;
  turns: number | null;
};

export async function fetchTerritoryBattles(cellId: number): Promise<TerritoryBattle[]> {
  const res = await fetch(`${API}/api/territory/${cellId}/battles`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchTerritoryBattles failed: ${res.status}`);
  return (await res.json()).battles ?? [];
}

export type SaveResultResponse = {
  url: string;
  cached: boolean;
  destination?: string;
  territory?: {
    cell_id: number | null;
    capture: { captured: boolean; version?: number; board_version?: number } | null;
    non_stakes: boolean;
  };
};

export async function saveHumanMatchResult(
  sid: string,
  resume?: { session_spec?: HumanSessionSpec; prior_actions?: HumanActionLog[] },
  challenge?: ChallengeContext,
): Promise<SaveResultResponse> {
  // 2026-05-31 fix: Vercel serverless で cache miss 時 404 silent fail し て
  // log メモ が 消 え る bug 修 復。 buildResume() で session_spec + prior_actions
  // を 送 信 し て endpoint 側 で reconstruct 可 能 化。
  const res = await fetch(`${API}/api/human_match/${sid}/save_result`, {
    method: "POST",
    cache: "no-store",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...(resume ?? {}), ...(challenge ?? {}) }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`saveHumanMatchResult failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function addHumanMatchLogComment(
  sid: string,
  log_index: number,
  log_text: string | null,
  comment: string,
): Promise<{ entry: unknown; total: number }> {
  const res = await fetch(`${API}/api/human_match/${sid}/log_comment`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ log_index, log_text, comment }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`addHumanMatchLogComment failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function fetchMatchHistory(
  deckId?: string,
  limit = 20,
): Promise<MatchHistoryEntry[]> {
  const params = new URLSearchParams();
  if (deckId) params.set("deck_id", deckId);
  params.set("limit", String(limit));
  const res = await fetch(`${API}/api/match/history?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchMatchHistory failed: ${res.status}`);
  return res.json();
}

export async function searchFaq(
  q: string,
  sourcePrefix?: string,
  limit = 50,
): Promise<FaqHit[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (sourcePrefix) params.set("source_prefix", sourcePrefix);
  params.set("limit", String(limit));
  const res = await fetch(`${API}/api/faq/search?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`searchFaq failed: ${res.status}`);
  return res.json();
}

export interface BattleReportResponse {
  article: string;
  deck_name: string;
  opponent_name: string;
  n_games: number;
  n_wins: number;
  n_losses: number;
}

export async function generateBattleReport(
  slug: string,
  opponentSlug: string,
  nGames: number = 10,
  seed: number = 42,
): Promise<BattleReportResponse> {
  const params = new URLSearchParams({
    opponent_slug: opponentSlug,
    n_games: String(nGames),
    seed: String(seed),
  });
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/battle-report?${params}`,
    { method: "POST", cache: "no-store" },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `battle-report failed: ${res.status}`);
  }
  return res.json();
}

export async function generateDeckArticle(
  slug: string,
): Promise<{ article: string; deck_name: string; model: string }> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/generate-article`,
    { method: "POST", cache: "no-store" },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `generate-article failed: ${res.status}`);
  }
  return res.json();
}

// === spectate コメント (= 観戦時のアノテーション、 サーバ永続) ===

export type SpectateCommentIn = {
  replay_key: string;
  deck_a: string;
  deck_b: string;
  first_player: number;
  winner: number | null;
  turns: number;
  snapshot_idx: number;
  snapshot_log: string;
  snapshot_turn: number | null;
  text: string;
  author?: string | null;
};

export type SpectateCommentOut = SpectateCommentIn & {
  id: string;
  created_at: string;
  author: string | null;
  agreed_by: string[];
};

export async function listSpectateComments(
  replayKey: string,
): Promise<SpectateCommentOut[]> {
  const params = new URLSearchParams({ replay_key: replayKey });
  const res = await fetch(`${API}/api/spectate/comments?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`listSpectateComments failed: ${res.status}`);
  return res.json();
}

export async function addSpectateComment(
  body: SpectateCommentIn,
): Promise<SpectateCommentOut> {
  const res = await fetch(`${API}/api/spectate/comments`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `addSpectateComment failed: ${res.status}`);
  }
  return res.json();
}

export async function deleteSpectateComment(id: string): Promise<void> {
  const res = await fetch(
    `${API}/api/spectate/comments/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`deleteSpectateComment failed: ${res.status}`);
}

export async function agreeSpectateComment(
  id: string,
  author: string,
): Promise<SpectateCommentOut> {
  const res = await fetch(
    `${API}/api/spectate/comments/${encodeURIComponent(id)}/agree`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ author }),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `agreeSpectateComment failed: ${res.status}`);
  }
  return res.json();
}

export async function unagreeSpectateComment(
  id: string,
  author: string,
): Promise<void> {
  const params = new URLSearchParams({ author });
  const res = await fetch(
    `${API}/api/spectate/comments/${encodeURIComponent(id)}/agree?${params}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`unagreeSpectateComment failed: ${res.status}`);
}

// === Audit System (= docs/AUTO_AUDIT_SYSTEM.md、 2026-05-28) ===

export interface AuditCardHealth {
  card_id: string;
  name: string;
  category: string;
  static_issue_count: number;
  runtime_violation_count: number;
  cardqa_count: number;
  has_overlay: boolean;
  health: "ok" | "info" | "warn" | "error";
  static_issues: Array<{ rule_id: string; severity: number; category: string }>;
  runtime_violations: Array<{ rule_id: string; severity: number }>;
}

export interface AuditCoverage {
  generated_at: string;
  summary: {
    total_cards: number;
    cards_with_overlay: number;
    static_issues_total: number;
    runtime_violations_total: number;
    runtime_events_total: number;
    cardqa_total: number;
    primitive_distinct: number;
    by_health: Record<string, number>;
  };
  cards: AuditCardHealth[];
  primitives: Array<{ primitive: string; usage_count: number }>;
}

export async function fetchAuditCoverage(): Promise<AuditCoverage> {
  const res = await fetch(`${API}/api/audit/coverage`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchAuditCoverage failed: ${res.status}`);
  return res.json();
}
