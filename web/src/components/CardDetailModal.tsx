"use client";

import type { Card } from "@/lib/types";
import { CardImage } from "./CardImage";
import { ColorChip } from "./ColorChip";

export function CardDetailModal({
  card,
  onClose,
}: {
  card: Card | null;
  onClose: () => void;
}) {
  if (!card) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="grid max-h-[90vh] w-full max-w-3xl gap-6 overflow-auto rounded-lg bg-white p-6 dark:bg-zinc-900 sm:grid-cols-[auto_1fr]"
        onClick={(e) => e.stopPropagation()}
      >
        <CardImage
          cardId={card.card_id}
          alt={card.name}
          className="aspect-[5/7] w-48 rounded object-cover"
          loading="eager"
        />
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">{card.name}</h2>
            <button
              type="button"
              onClick={onClose}
              className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
              aria-label="close"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {card.color.map((c) => (
              <ColorChip key={c} color={c} />
            ))}
            <span className="rounded bg-zinc-200 px-2 text-xs dark:bg-zinc-800">
              {card.category}
            </span>
            <span className="rounded bg-zinc-200 px-2 text-xs dark:bg-zinc-800">
              {card.rarity}
            </span>
          </div>
          <dl className="grid grid-cols-3 gap-2 text-sm">
            <Stat label="cost" value={card.cost} />
            <Stat label="power" value={card.power} />
            <Stat label="counter" value={card.counter} />
            <Stat label="life" value={card.life} />
            <Stat label="block" value={card.block_icon} />
            <Stat label="attr" value={card.attribute || "-"} />
          </dl>
          {card.features.length > 0 && (
            <div>
              <div className="text-xs text-zinc-500">特徴</div>
              <div className="text-sm">{card.features.join(" / ")}</div>
            </div>
          )}
          {card.text && (
            <div>
              <div className="text-xs text-zinc-500">テキスト</div>
              <p className="whitespace-pre-wrap text-sm">{card.text}</p>
            </div>
          )}
          {card.trigger && (
            <div>
              <div className="text-xs text-zinc-500">トリガー</div>
              <p className="whitespace-pre-wrap text-sm">{card.trigger}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}
