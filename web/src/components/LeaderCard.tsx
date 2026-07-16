"use client";

import { useState } from "react";
import type { Card } from "@/lib/types";
import { CardImage } from "./CardImage";
import { CardDetailModal } from "./CardDetailModal";

// デッキ詳細ヘッダーのリーダー画像。 メインデッキのカードと同様、 クリックで
// CardDetailModal を開いてカード情報を確認できる (UI 共通)。
export function LeaderCard({
  cardId,
  card,
  alt,
  className,
}: {
  cardId: string;
  card: Card | null;
  alt: string;
  className?: string;
}) {
  const [selected, setSelected] = useState<Card | null>(null);
  return (
    <>
      <button
        type="button"
        onClick={() => card && setSelected(card)}
        disabled={!card}
        title={card ? `${card.name} の情報を表示` : undefined}
        className="block rounded-[var(--radius)] transition hover:ring-2 hover:ring-[color:var(--brand)] hover:brightness-110 disabled:cursor-default disabled:hover:ring-0"
      >
        <CardImage cardId={cardId} alt={alt} className={className} />
      </button>
      <CardDetailModal card={selected} onClose={() => setSelected(null)} />
    </>
  );
}
