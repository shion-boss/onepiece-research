import Link from "next/link";
import type { DeckSummary } from "@/lib/types";
import { ColorChip } from "./ColorChip";

export function DeckSummaryTile({ deck }: { deck: DeckSummary }) {
  return (
    <Link
      href={`/decks/${encodeURIComponent(deck.slug)}`}
      className="block rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg font-medium">{deck.name}</span>
            {deck.regulation && (
              <span
                className={`rounded px-1.5 py-0.5 text-xs font-bold ${
                  deck.regulation === "standard"
                    ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                    : "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300"
                }`}
              >
                {deck.regulation === "standard" ? "STD" : "EX"}
              </span>
            )}
          </div>
          <div className="text-xs text-zinc-500 dark:text-zinc-400">
            {deck.leader_name} ({deck.leader})
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {deck.leader_color.map((c) => (
            <ColorChip key={c} color={c} />
          ))}
        </div>
      </div>
      <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
        {deck.main_count} 枚 / unique {deck.unique}
      </div>
    </Link>
  );
}
