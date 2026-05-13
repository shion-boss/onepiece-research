import type {
  ApplyImprovementResponse,
  Card,
  CardChange,
  CardFilters,
  CoreBuildRequest,
  CoreBuildResponse,
  DeckAnalysis,
  DeckDetail,
  DeckImprovementsResponse,
  DeckSummary,
  ExploreCounterRequest,
  ExploreCounterResponse,
  FaqHit,
  FaqSource,
  GameLog,
  McctsGameRequest,
  McctsGameResponse,
  MatchHistoryEntry,
  MatchRequest,
  MatchSummary,
  MatchupMatrix,
  DeckStrategy,
  GameAnalysisResponse,
  ReplayResponse,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function fetchCards(filters: CardFilters = {}): Promise<Card[]> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v != null && v !== "") params.set(k, String(v));
  }
  const res = await fetch(`${API}/api/cards?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchCards failed: ${res.status}`);
  return res.json();
}

export async function fetchCard(cardId: string): Promise<Card> {
  const res = await fetch(`${API}/api/cards/${encodeURIComponent(cardId)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchCard failed: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<{ ok: boolean; cards: number }> {
  const res = await fetch(`${API}/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchHealth failed: ${res.status}`);
  return res.json();
}

export async function fetchDecks(): Promise<DeckSummary[]> {
  const res = await fetch(`${API}/api/decks`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchDecks failed: ${res.status}`);
  return res.json();
}

export async function fetchDeck(slug: string): Promise<DeckDetail> {
  const res = await fetch(`${API}/api/decks/${encodeURIComponent(slug)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`fetchDeck failed: ${res.status}`);
  return res.json();
}

export async function fetchDeckAnalysis(slug: string): Promise<DeckAnalysis> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/analyze`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(`fetchDeckAnalysis failed: ${res.status}`);
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

export async function fetchDeckStrategy(slug: string): Promise<DeckStrategy> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/strategy`,
    { cache: "no-store" },
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
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`saveDeckToServer failed: ${res.status} ${detail}`);
  }
  return res.json();
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

export async function runMctsGame(
  slug: string,
  req: McctsGameRequest,
): Promise<McctsGameResponse> {
  const res = await fetch(
    `${API}/api/decks/${encodeURIComponent(slug)}/mcts-game`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`runMctsGame failed: ${res.status} ${detail}`);
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

export async function fetchMetaMatrix(): Promise<MatchupMatrix> {
  const res = await fetch(`${API}/api/meta/matrix`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchMetaMatrix failed: ${res.status}`);
  return res.json();
}

export async function fetchFaqSources(): Promise<FaqSource[]> {
  const res = await fetch(`${API}/api/faq/sources`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchFaqSources failed: ${res.status}`);
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
