"use client";

import { useState } from "react";
import type { Card } from "@/lib/types";
import { CardImage } from "./CardImage";
import { CardDetailModal } from "./CardDetailModal";

// デッキ詳細のメインデッキ グリッド。 カードをクリックすると /cards と同じ
// CardDetailModal でカード情報を表示する (UI 共通)。
export function DeckMainGrid({
  entries,
  cards,
}: {
  entries: { card_id: string; count: number }[];
  cards: Card[];
}) {
  const [selected, setSelected] = useState<Card | null>(null);
  const cardById = new Map(cards.map((c) => [c.card_id, c]));
  return (
    <>
      <ul className="grid grid-cols-5 gap-2 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10">
        {entries.map((entry) => {
          const card = cardById.get(entry.card_id);
          return (
            <li key={entry.card_id} className="flex flex-col gap-0.5">
              <button
                type="button"
                onClick={() => card && setSelected(card)}
                disabled={!card}
                title={card ? `${card.name} の情報を表示` : undefined}
                className="relative block w-full rounded transition hover:ring-2 hover:ring-[color:var(--brand)] hover:brightness-110 disabled:cursor-default disabled:hover:ring-0"
              >
                <CardImage
                  cardId={entry.card_id}
                  alt={card?.name ?? entry.card_id}
                  className="aspect-[5/7] w-full rounded object-cover"
                />
                <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[10px] font-semibold leading-5 text-white">
                  ×{entry.count}
                </span>
              </button>
              <div className="truncate text-center text-[10px] leading-tight text-[color:var(--text-muted)]">
                {card?.name ?? entry.card_id}
              </div>
            </li>
          );
        })}
      </ul>
      <CardDetailModal card={selected} onClose={() => setSelected(null)} />
    </>
  );
}
