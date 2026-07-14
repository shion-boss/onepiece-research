import type { Card } from "@/lib/types";
import { type BanInfo, formatBanPartners } from "@/lib/banlist";
import { CardImage } from "./CardImage";
import { ColorChip } from "./ColorChip";

const BLOCK_ICONS = ["", "①", "②", "③", "④", "⑤"] as const;

function BanBadge({ ban }: { ban: BanInfo }) {
  if (ban.kind === "forbidden") {
    return (
      <span
        className="rounded-[var(--radius-sm)] bg-[color:var(--danger)] px-1.5 py-0.5 text-xs font-bold text-white"
        title="禁止カード (= デッキに採用不可)"
      >
        禁止
      </span>
    );
  }
  if (ban.kind === "restricted") {
    return (
      <span
        className="rounded-[var(--radius-sm)] bg-[color:var(--warning)] px-1.5 py-0.5 text-xs font-bold text-[color:var(--background)]"
        title="制限カード (= 採用枚数に制限)"
      >
        制限
      </span>
    );
  }
  // pair: 単体では合法だが 相方と同時採用不可
  const partners = formatBanPartners(ban.partners);
  return (
    <span
      className="rounded-[var(--radius-sm)] bg-[color:var(--warning)]/15 px-1.5 py-0.5 text-xs font-bold text-[color:var(--warning)] ring-1 ring-[color:var(--warning)]/40"
      title={`ペア制限: ${partners} と同時採用不可`}
    >
      ペア
    </span>
  );
}

function BlockBadge({ blockIcon }: { blockIcon: number }) {
  const label = BLOCK_ICONS[blockIcon] ?? String(blockIcon);
  const isStandardIllegal = blockIcon < 2;
  return (
    <span
      className={`rounded-[var(--radius-sm)] px-1 py-0.5 font-mono text-xs font-bold ${
        isStandardIllegal
          ? "bg-[color:var(--danger)]/15 text-[color:var(--danger)]"
          : "bg-[color:var(--surface-2)] text-[color:var(--text-muted)]"
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
  ban,
}: {
  card: Card;
  onClick?: (card: Card) => void;
  ban?: BanInfo;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick?.(card)}
      className="group flex flex-col gap-2 rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-2 text-left transition hover:-translate-y-0.5 hover:border-[color:var(--brand)] hover:bg-[var(--list-hover)]"
    >
      <div className="relative">
        <CardImage
          cardId={card.card_id}
          alt={card.name}
          className="aspect-[5/7] w-full rounded object-cover"
        />
        {ban && (
          <div className="absolute left-1 top-1">
            <BanBadge ban={ban} />
          </div>
        )}
      </div>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium leading-tight text-[color:var(--text-strong)]">{card.name}</div>
        <div className="shrink-0 text-xs text-[color:var(--text-muted)]">
          {card.category === "LEADER" ? "—" : card.cost}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {card.color.map((c) => (
          <ColorChip key={c} color={c} />
        ))}
        {card.category !== "LEADER" && (
          <span className="text-xs text-[color:var(--text-muted)]">
            P{card.power}
          </span>
        )}
        <span className="ml-auto">
          <BlockBadge blockIcon={card.block_icon} />
        </span>
      </div>
    </button>
  );
}
