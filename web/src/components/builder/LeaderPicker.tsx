"use client";

import { useEffect, useState } from "react";
import type { Card } from "@/lib/types";
import { fetchCards } from "@/lib/api";
import { CardImage } from "@/components/CardImage";
import { ColorChip } from "@/components/ColorChip";

export function LeaderPicker({
  current,
  onPick,
}: {
  current: Card | null;
  onPick: (leader: Card) => void;
}) {
  const [leaders, setLeaders] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetchCards({ category: "LEADER", limit: 200 })
      .then(setLeaders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
        リーダー読み込み失敗: {error}
      </div>
    );
  }
  if (!leaders) return <div className="text-sm text-zinc-500">読み込み中…</div>;

  const filtered = filter
    ? leaders.filter(
        (l) =>
          l.name.includes(filter) || l.card_id.toUpperCase().includes(filter.toUpperCase()),
      )
    : leaders;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="リーダー名 / ID で絞り込み"
          className="w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
        />
      </div>

      {current && (
        <div className="flex items-center gap-3 rounded border border-zinc-300 p-2 dark:border-zinc-700">
          <CardImage
            cardId={current.card_id}
            alt={current.name}
            className="h-16 w-12 rounded object-cover"
          />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">{current.name}</div>
            <div className="text-xs text-zinc-500 dark:text-zinc-400">
              {current.card_id} · life {current.life}
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
            {current.color.map((c) => (
              <ColorChip key={c} color={c} />
            ))}
          </div>
        </div>
      )}

      <div className="grid max-h-72 grid-cols-3 gap-2 overflow-auto sm:grid-cols-4 md:grid-cols-5">
        {filtered.map((l) => (
          <button
            key={l.card_id}
            type="button"
            onClick={() => onPick(l)}
            className={`flex flex-col gap-1 rounded border p-1 text-left transition hover:border-zinc-400 dark:hover:border-zinc-500 ${
              current?.card_id === l.card_id
                ? "border-zinc-900 dark:border-zinc-100"
                : "border-zinc-200 dark:border-zinc-800"
            }`}
          >
            <CardImage
              cardId={l.card_id}
              alt={l.name}
              className="aspect-[5/7] w-full rounded object-cover"
            />
            <div className="truncate text-xs">{l.name}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
