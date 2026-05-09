import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchCard, fetchDeck, fetchDecks } from "@/lib/api";
import type { Card, DeckDetail, DeckSummary } from "@/lib/types";
import { CardImage } from "@/components/CardImage";
import { ColorChip } from "@/components/ColorChip";
import { MatchHistorySection } from "@/components/MatchHistorySection";
import { MatchRunner } from "@/components/MatchRunner";

export default async function DeckDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  let detail: DeckDetail | null = null;
  let decks: DeckSummary[] = [];
  let error: string | null = null;
  try {
    [detail, decks] = await Promise.all([fetchDeck(slug), fetchDecks()]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-6">
        <Link
          href="/decks"
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← /decks
        </Link>
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      </main>
    );
  }

  if (!detail) notFound();

  const summary = decks.find((d) => d.slug === slug);
  const opponents = decks.filter((d) => d.slug !== slug);

  // メイン50枚のカード詳細を一括取得
  const uniqueIds = Array.from(new Set(detail.main.map((e) => e.card_id)));
  const cardDetails = await Promise.all(
    uniqueIds.map((id) =>
      fetchCard(id).catch(() => null as Card | null),
    ),
  );
  const cardById = new Map<string, Card>();
  for (const c of cardDetails) {
    if (c) cardById.set(c.card_id, c);
  }

  // コスト順にソート
  const sortedEntries = [...detail.main].sort((a, b) => {
    const ca = cardById.get(a.card_id)?.cost ?? 0;
    const cb = cardById.get(b.card_id)?.cost ?? 0;
    if (ca !== cb) return ca - cb;
    return a.card_id.localeCompare(b.card_id);
  });

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-6">
      <header className="space-y-1">
        <Link
          href="/decks"
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← /decks
        </Link>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {detail.name ?? slug}
          </h1>
          {summary && (
            <div className="flex gap-1">
              {summary.leader_color.map((c) => (
                <ColorChip key={c} color={c} />
              ))}
            </div>
          )}
        </div>
        {summary && (
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            リーダー: {summary.leader_name} ({summary.leader})
          </div>
        )}
      </header>

      <div className="flex flex-wrap gap-2">
        <Link
          href={`/decks/${encodeURIComponent(slug)}/analyze`}
          className="inline-block rounded border border-zinc-300 px-3 py-1 text-sm transition hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          📊 分析を見る
        </Link>
        <Link
          href={`/decks/new?from=${encodeURIComponent(slug)}`}
          className="inline-block rounded border border-zinc-300 px-3 py-1 text-sm transition hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          📝 コピーして編集
        </Link>
      </div>

      <MatchRunner
        selfSlug={slug}
        selfName={detail.name ?? slug}
        opponents={opponents}
      />

      <section className="space-y-2">
        <h2 className="text-lg font-medium">直近の対戦履歴</h2>
        <MatchHistorySection deckSlug={slug} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">
          メインデッキ ({detail.main.reduce((s, e) => s + e.count, 0)} 枚 / unique {uniqueIds.length})
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {sortedEntries.map((entry) => {
            const card = cardById.get(entry.card_id);
            return (
              <li
                key={entry.card_id}
                className="flex items-center gap-3 rounded border border-zinc-200 p-2 dark:border-zinc-800"
              >
                <CardImage
                  cardId={entry.card_id}
                  alt={card?.name ?? entry.card_id}
                  className="h-14 w-10 rounded object-cover"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {card?.name ?? entry.card_id}
                  </div>
                  <div className="text-xs text-zinc-500 dark:text-zinc-400">
                    {entry.card_id}
                    {card && ` · cost ${card.cost} · P${card.power}`}
                  </div>
                </div>
                <div className="font-mono text-sm">×{entry.count}</div>
              </li>
            );
          })}
        </ul>
      </section>
    </main>
  );
}
