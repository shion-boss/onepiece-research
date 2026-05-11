import type { Card } from "@/lib/types";
import { CardImage } from "./CardImage";
import { ColorChip } from "./ColorChip";

const BLOCK_ICONS = ["", "①", "②", "③", "④", "⑤"] as const;

function BlockBadge({ blockIcon }: { blockIcon: number }) {
  const label = BLOCK_ICONS[blockIcon] ?? String(blockIcon);
  const isStandardIllegal = blockIcon < 2;
  return (
    <span
      className={`rounded px-1 py-0.5 font-mono text-xs font-bold ${
        isStandardIllegal
          ? "bg-red-100 text-red-600 dark:bg-red-900/50 dark:text-red-400"
          : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
      }`}
      title={isStandardIllegal ? "スタンダード使用不可 (block①)" : `block${label}`}
    >
      {label}
    </span>
  );
}

export function CardTile({
  card,
  onClick,
}: {
  card: Card;
  onClick?: (card: Card) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick?.(card)}
      className="group flex flex-col gap-2 rounded-lg border border-zinc-200 p-2 text-left transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
    >
      <div className="relative">
        <CardImage
          cardId={card.card_id}
          alt={card.name}
          className="aspect-[5/7] w-full rounded object-cover"
        />
        <div className="absolute right-1 top-1">
          <BlockBadge blockIcon={card.block_icon} />
        </div>
      </div>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium leading-tight">{card.name}</div>
        <div className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">
          {card.category === "LEADER" ? "—" : card.cost}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {card.color.map((c) => (
          <ColorChip key={c} color={c} />
        ))}
        {card.category !== "LEADER" && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            P{card.power}
          </span>
        )}
      </div>
    </button>
  );
}
