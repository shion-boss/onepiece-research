"use client";

import type { BuilderEntry } from "@/stores/deckBuilder";
import { CardImage } from "@/components/CardImage";

export function BuilderSidebar({
  entries,
  onIncrement,
  onDecrement,
  onRemove,
}: {
  entries: BuilderEntry[];
  onIncrement: (cardId: string) => void;
  onDecrement: (cardId: string) => void;
  onRemove: (cardId: string) => void;
}) {
  const total = entries.reduce((s, e) => s + e.count, 0);
  const sorted = [...entries].sort((a, b) => {
    if (a.card.cost !== b.card.cost) return a.card.cost - b.card.cost;
    return a.card.card_id.localeCompare(b.card.card_id);
  });

  if (entries.length === 0) {
    return (
      <div className="rounded-[var(--radius)] border border-[color:var(--border-1)] p-4 text-center text-sm text-[color:var(--text-muted)]">
        右側からカードをクリックして追加
      </div>
    );
  }

  return (
    <ul className="space-y-1">
      {sorted.map((e) => (
        <li
          key={e.card.card_id}
          className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[color:var(--border-1)] px-2 py-1"
        >
          <CardImage
            cardId={e.card.card_id}
            alt={e.card.name}
            className="h-10 w-7 rounded object-cover"
          />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-[color:var(--text-default)]">{e.card.name}</div>
            <div className="text-xs text-[color:var(--text-muted)]">
              cost {e.card.cost} · P{e.card.power}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onDecrement(e.card.card_id)}
              className="h-7 w-7 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] text-sm text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
              aria-label="1枚減らす"
            >
              −
            </button>
            <span className="w-6 text-center font-mono text-sm text-[color:var(--text-default)]">{e.count}</span>
            <button
              type="button"
              onClick={() => onIncrement(e.card.card_id)}
              className="h-7 w-7 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] text-sm text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
              aria-label="1枚増やす"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => onRemove(e.card.card_id)}
              className="h-7 w-7 rounded-[var(--radius-sm)] border border-[color:var(--border-2)] text-sm text-[color:var(--danger)] hover:bg-[color:var(--danger)]/10"
              aria-label="削除"
            >
              ✕
            </button>
          </div>
        </li>
      ))}
      <li className="pt-1 text-right text-xs text-[color:var(--text-muted)]">
        合計 {total} / 50
      </li>
    </ul>
  );
}
