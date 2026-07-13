"use client";

import { useEffect, useState } from "react";
import type { Card } from "@/lib/types";
import { fetchCards } from "@/lib/api";
import { CardImage } from "@/components/CardImage";
import { ColorChip } from "@/components/ColorChip";
import { useDeckBuilderStore } from "@/stores/deckBuilder";

export function LeaderPicker({
  current,
  onPick,
}: {
  current: Card | null;
  onPick: (leader: Card) => void;
}) {
  const regulation = useDeckBuilderStore((s) => s.regulation);
  const [leaders, setLeaders] = useState<Card[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetchCards({
      category: "LEADER",
      block_icon_ge: regulation === "standard" ? 2 : undefined,
      limit: 200,
    })
      .then(setLeaders)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [regulation]);

  if (error) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-3 text-sm text-[color:var(--danger)]">
        リーダー読み込み失敗: {error}
      </div>
    );
  }
  if (!leaders) return <div className="text-sm text-[color:var(--text-muted)]">読み込み中…</div>;

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
          className="w-full rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
        />
      </div>

      {current && (
        <div className={`flex items-center gap-3 rounded-[var(--radius)] border p-2 ${
          regulation === "standard" && current.block_icon < 2
            ? "border-[color:var(--danger)]/50 bg-[color:var(--danger)]/10"
            : "border-[color:var(--border-2)]"
        }`}>
          <CardImage
            cardId={current.card_id}
            alt={current.name}
            className="h-16 w-12 rounded-[var(--radius-sm)] object-cover"
          />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-[color:var(--text-strong)]">{current.name}</div>
            <div className="text-xs text-[color:var(--text-muted)]">
              {current.card_id} · life {current.life}
            </div>
            {regulation === "standard" && current.block_icon < 2 && (
              <div className="mt-0.5 text-xs font-medium text-[color:var(--danger)]">
                スタンダード使用不可 (block①)
              </div>
            )}
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
            className={`flex flex-col gap-1 rounded-[var(--radius-sm)] border p-1 text-left transition hover:border-[color:var(--brand)] ${
              current?.card_id === l.card_id
                ? "border-[color:var(--brand)]"
                : "border-[color:var(--border-1)]"
            }`}
          >
            <CardImage
              cardId={l.card_id}
              alt={l.name}
              className="aspect-[5/7] w-full rounded-[var(--radius-sm)] object-cover"
            />
            <div className="truncate text-xs text-[color:var(--text-default)]">{l.name}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
