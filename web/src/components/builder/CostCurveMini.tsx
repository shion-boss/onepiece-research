"use client";

import type { BuilderEntry } from "@/stores/deckBuilder";

export function CostCurveMini({ entries }: { entries: BuilderEntry[] }) {
  const counts = new Array(11).fill(0) as number[];
  for (const e of entries) {
    const c = Math.max(0, Math.min(10, e.card.cost));
    counts[c] += e.count;
  }
  const max = Math.max(1, ...counts);

  return (
    <div className="space-y-1">
      <div className="flex h-16 items-end gap-1">
        {counts.map((n, cost) => (
          <div
            key={cost}
            className="flex-1 rounded-t bg-zinc-300 dark:bg-zinc-700"
            style={{ height: `${(n / max) * 100}%` }}
            title={`cost ${cost}: ${n} 枚`}
          />
        ))}
      </div>
      <div className="flex gap-1 text-[10px] text-zinc-500 dark:text-zinc-400">
        {counts.map((_, cost) => (
          <div key={cost} className="flex-1 text-center">
            {cost}
          </div>
        ))}
      </div>
    </div>
  );
}
