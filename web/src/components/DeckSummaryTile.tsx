import Link from "next/link";
import type { DeckSummary } from "@/lib/types";
import { ColorChip } from "./ColorChip";

export function DeckSummaryTile({ deck }: { deck: DeckSummary }) {
  return (
    <Link
      href={`/decks/${encodeURIComponent(deck.slug)}`}
      className="block rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4 transition hover:-translate-y-0.5 hover:border-[color:var(--brand)] hover:bg-[var(--list-hover)]"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg font-medium text-[color:var(--text-strong)]">{deck.name}</span>
            {deck.regulation && (
              <span
                className="rounded-[var(--radius-sm)] px-1.5 py-0.5 text-xs font-bold"
                style={
                  deck.regulation === "standard"
                    ? { background: "var(--brand-soft)", color: "var(--brand-strong)" }
                    : { background: "var(--surface-3)", color: "var(--text-default)" }
                }
              >
                {deck.regulation === "standard" ? "STD" : "EX"}
              </span>
            )}
          </div>
          <div className="text-xs text-[color:var(--text-muted)]">
            {deck.leader_name} ({deck.leader})
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {deck.leader_color.map((c) => (
            <ColorChip key={c} color={c} />
          ))}
        </div>
      </div>
      <div className="mt-2 text-xs text-[color:var(--text-muted)]">
        {deck.main_count} 枚 / unique {deck.unique}
      </div>
    </Link>
  );
}
