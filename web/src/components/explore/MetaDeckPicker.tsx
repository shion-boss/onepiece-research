"use client";

import { useEffect, useState } from "react";
import { fetchDecks } from "@/lib/api";
import type { DeckSummary } from "@/lib/types";
import { ColorChip } from "@/components/ColorChip";
import { CardImage } from "@/components/CardImage";

export function MetaDeckPicker({
  selected,
  onSelect,
}: {
  selected: DeckSummary | null;
  onSelect: (deck: DeckSummary) => void;
}) {
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchDecks();
        if (!cancelled) setDecks(list);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <div className="text-sm text-zinc-500">読み込み中…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-500">エラー: {error}</div>;
  }
  if (decks.length === 0) {
    return <div className="text-sm text-zinc-500">メタデッキが登録されていません</div>;
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {decks.map((deck) => {
        const isSelected = selected?.slug === deck.slug;
        return (
          <button
            key={deck.slug}
            type="button"
            onClick={() => onSelect(deck)}
            className={`group flex flex-col gap-2 rounded-lg border-2 p-3 text-left transition ${
              isSelected
                ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30"
                : "border-zinc-200 hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
            }`}
          >
            <div className="aspect-[5/7] overflow-hidden rounded bg-zinc-100 dark:bg-zinc-900">
              <CardImage
                cardId={deck.leader}
                alt={deck.leader_name}
                className="h-full w-full object-cover"
              />
            </div>
            <div className="flex items-start justify-between gap-1">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{deck.name}</div>
                <div className="truncate text-xs text-zinc-500 dark:text-zinc-400">
                  {deck.leader_name}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-0.5">
                {deck.leader_color.map((c) => (
                  <ColorChip key={c} color={c} />
                ))}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
