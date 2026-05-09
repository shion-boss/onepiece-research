"use client";

import { useState } from "react";
import type { Card } from "@/lib/types";
import { CardTile } from "./CardTile";
import { CardDetailModal } from "./CardDetailModal";

export function CardGrid({ cards }: { cards: Card[] }) {
  const [selected, setSelected] = useState<Card | null>(null);

  if (cards.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        該当するカードがありません
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {cards.map((c) => (
          <CardTile key={c.card_id} card={c} onClick={setSelected} />
        ))}
      </div>
      <CardDetailModal card={selected} onClose={() => setSelected(null)} />
    </>
  );
}
