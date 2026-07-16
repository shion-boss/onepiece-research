import Link from "next/link";
import { notFound } from "next/navigation";
import {
  fetchCard,
  fetchDeck,
  fetchDecks,
  fetchDeckAnalysis,
  fetchDeckStrategy,
} from "@/lib/api";
import { serverAuthHeaders } from "@/lib/auth-server";
import type { Card, DeckAnalysis, DeckDetail, DeckStrategy, DeckSummary } from "@/lib/types";
import { LeaderCard } from "@/components/LeaderCard";
import { ColorChip } from "@/components/ColorChip";
import { DeckStrategyPanel } from "@/components/DeckStrategyPanel";
import { DeckCombosPanel } from "@/components/DeckCombosPanel";
import { DeckAnalyzeCharts } from "@/components/DeckAnalyzeCharts";
import { MatchHistorySection } from "@/components/MatchHistorySection";
import { DeckMainGrid } from "@/components/DeckMainGrid";
import { DeckActions } from "@/components/DeckActions";
import { SetTabTitle } from "@/components/SetTabTitle";

export default async function DeckDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug: rawSlug } = await params;
  const slug = decodeURIComponent(rawSlug);

  const ah = await serverAuthHeaders();
  let detail: DeckDetail | null = null;
  let decks: DeckSummary[] = [];
  let error: string | null = null;
  try {
    [detail, decks] = await Promise.all([fetchDeck(slug, ah), fetchDecks(ah)]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
        <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-4 text-sm text-[color:var(--danger)]">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      </main>
    );
  }

  if (!detail) notFound();

  const summary = decks.find((d) => d.slug === slug);

  // 分析 (このページの主役) を取得。 失敗は致命的でない。
  let analysis: DeckAnalysis | null = null;
  let strategy: DeckStrategy | null = null;
  try {
    [analysis, strategy] = await Promise.all([
      fetchDeckAnalysis(slug, ah).catch(() => null),
      fetchDeckStrategy(slug, ah).catch(() => null),
    ]);
  } catch {
    /* noop */
  }

  const uniqueIds = Array.from(new Set(detail.main.map((e) => e.card_id)));
  const [cardDetails, leaderCard] = await Promise.all([
    Promise.all(uniqueIds.map((id) => fetchCard(id).catch(() => null as Card | null))),
    fetchCard(detail.leader).catch(() => null as Card | null),
  ]);
  const cardById = new Map<string, Card>();
  for (const c of cardDetails) {
    if (c) cardById.set(c.card_id, c);
  }

  const sortedEntries = [...detail.main].sort((a, b) => {
    const ca = cardById.get(a.card_id)?.cost ?? 0;
    const cb = cardById.get(b.card_id)?.cost ?? 0;
    if (ca !== cb) return ca - cb;
    return a.card_id.localeCompare(b.card_id);
  });

  const totalCards = detail.main.reduce((s, e) => s + e.count, 0);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
      {/* タブ名を slug でなくデッキ名にする (= 文字化け回避)。 */}
      <SetTabTitle title={detail.name ?? slug} />
      {/* ヘッダー: リーダー画像 + デッキ情報 */}
      <header className="flex gap-5">
        <div className="shrink-0">
          <LeaderCard
            cardId={detail.leader}
            card={leaderCard}
            alt={summary?.leader_name ?? detail.leader}
            className="h-32 w-[91px] rounded-[var(--radius)] object-cover"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              {detail.name ?? slug}
            </h1>
            {summary && (
              <div className="flex flex-wrap gap-1">
                {summary.leader_color.map((c) => (
                  <ColorChip key={c} color={c} />
                ))}
              </div>
            )}
          </div>
          {summary && (
            <div className="mt-1 text-sm text-[color:var(--text-default)]">
              リーダー: {summary.leader_name}{" "}
              <span className="font-mono text-xs">({summary.leader})</span>
            </div>
          )}
          <div className="mt-0.5 text-sm text-[color:var(--text-muted)]">
            {totalCards} 枚 / unique {uniqueIds.length}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              href={`/play?deck=${encodeURIComponent(slug)}`}
              className="inline-block rounded-[var(--radius)] bg-[color:var(--brand)] px-4 py-1.5 text-sm font-medium text-white transition hover:bg-[color:var(--brand-strong)]"
            >
              このデッキで対戦
            </Link>
            <Link
              href={`/decks/new?from=${encodeURIComponent(slug)}`}
              className="inline-block rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm text-[color:var(--text-default)] transition hover:border-[color:var(--brand)] hover:bg-[var(--list-hover)]"
            >
              コピーして編集
            </Link>
            {/* 名前変更 / 削除 は自作デッキのみ (メタは backend 保護)。 */}
            {summary?.kind === "user" && (
              <DeckActions slug={slug} name={detail.name ?? slug} />
            )}
          </div>
        </div>
      </header>

      {/* 分析 (= このページの主役): 戦略・コンボ・チャート */}
      {analysis ? (
        <div className="space-y-4">
          {strategy && <DeckStrategyPanel strategy={strategy} />}
          <DeckCombosPanel combos={analysis.combos} />
          <DeckAnalyzeCharts data={analysis} />
        </div>
      ) : (
        <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4 text-sm text-[color:var(--text-muted)]">
          分析を読み込めませんでした。
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-medium text-[color:var(--text-strong)]">直近の対戦履歴</h2>
        <MatchHistorySection deckSlug={slug} />
      </section>

      {/* メインデッキ カードグリッド */}
      <section>
        <h2 className="mb-3 text-lg font-medium text-[color:var(--text-strong)]">
          メインデッキ ({totalCards} 枚 / unique {uniqueIds.length})
        </h2>
        <DeckMainGrid
          entries={sortedEntries.map((e) => ({ card_id: e.card_id, count: e.count }))}
          cards={cardDetails.filter((c): c is Card => c !== null)}
        />
      </section>
    </main>
  );
}
