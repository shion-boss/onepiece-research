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
        className="grid max-h-[92vh] w-full max-w-5xl gap-8 overflow-auto rounded-[var(--radius-lg)] border border-[color:var(--border-2)] bg-[color:var(--surface-1)] p-7 sm:grid-cols-[auto_1fr]"
        onClick={(e) => e.stopPropagation()}
      >
        <CardImage
          cardId={card.card_id}
          alt={card.name}
          className="aspect-[5/7] w-72 rounded object-cover lg:w-80"
          loading="eager"
        />
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-0.5">
              <h2 className="text-2xl font-semibold text-[color:var(--text-strong)]">{card.name}</h2>
              <div
                className="select-all font-mono text-sm text-[color:var(--text-muted)]"
                title="カード番号 (クリックで選択 → 検索に使える)"
              >
                {card.card_id}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 text-[color:var(--text-muted)] hover:text-[color:var(--text-strong)]"
              aria-label="close"
            >
              ✕
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {card.color.map((c) => (
              <ColorChip key={c} color={c} />
            ))}
            <span className="rounded-[var(--radius-sm)] bg-[color:var(--surface-3)] px-2 text-xs text-[color:var(--text-default)]">
              {card.category}
            </span>
            <span className="rounded-[var(--radius-sm)] bg-[color:var(--surface-3)] px-2 text-xs text-[color:var(--text-default)]">
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
              <div className="text-xs text-[color:var(--text-muted)]">特徴</div>
              <div className="text-sm text-[color:var(--text-default)]">{card.features.join(" / ")}</div>
            </div>
          )}
          {card.text && (
            <div>
              <div className="text-xs text-[color:var(--text-muted)]">テキスト</div>
              <p className="whitespace-pre-wrap text-base leading-relaxed text-[color:var(--text-default)]">
                {card.text}
              </p>
            </div>
          )}
          {card.trigger && (
            <div>
              <div className="text-xs text-[color:var(--text-muted)]">トリガー</div>
              <p className="whitespace-pre-wrap text-base leading-relaxed text-[color:var(--text-default)]">
                {card.trigger}
              </p>
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
      <dt className="text-xs text-[color:var(--text-muted)]">{label}</dt>
      <dd className="font-mono text-[color:var(--text-default)]">{value}</dd>
    </div>
  );
}
