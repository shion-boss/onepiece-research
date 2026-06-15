import { CardImage } from "@/components/CardImage";
import type { DeckComboOut } from "@/lib/types";

// 種別ごとのバッジ色 (palette: zinc + blue/red/amber/green)。
const KIND_BADGE: Record<string, string> = {
  enabler:
    "border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300",
  payoff:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  amplifier:
    "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300",
  chain:
    "border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300",
  accelerant:
    "border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950 dark:text-violet-300",
};

function ComboList({ items }: { items: DeckComboOut[] }) {
  return (
    <ul className="space-y-2">
      {items.map((c, i) => (
        <li
          key={i}
          className="flex items-start gap-3 rounded-md border border-zinc-100 p-2 dark:border-zinc-800/60"
        >
          <div className="flex shrink-0 items-center gap-1">
            {c.cards.map((card, j) => (
              <div key={card.card_id + j} className="flex items-center gap-1">
                {j > 0 && (
                  <span className="text-zinc-400" aria-hidden>
                    +
                  </span>
                )}
                <div className="w-12 sm:w-14">
                  <CardImage
                    cardId={card.card_id}
                    alt={card.name}
                    className="w-full rounded"
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded border px-1.5 py-0.5 text-xs font-medium ${
                  KIND_BADGE[c.kind] ?? KIND_BADGE.enabler
                }`}
              >
                {c.label}
              </span>
              <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                {c.cards.map((x) => x.name).join(" + ")}
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">
              {c.description}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function DeckCombosPanel({ combos }: { combos: DeckComboOut[] }) {
  if (!combos || combos.length === 0) return null;
  const real = combos.filter((c) => c.kind !== "accelerant");
  const accel = combos.filter((c) => c.kind === "accelerant");
  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <h2 className="mb-1 text-lg font-semibold">デッキ内コンボ</h2>
      {real.length > 0 ? (
        <>
          <p className="mb-3 text-sm text-zinc-500 dark:text-zinc-400">
            このデッキで噛み合うカードの組み合わせ（実行型）。対戦中、これらが手札や場に揃ったら狙える。
          </p>
          <ComboList items={real} />
        </>
      ) : (
        <p className="mb-3 text-sm text-zinc-500 dark:text-zinc-400">
          実行型の 2 枚コンボは検出されませんでした。
        </p>
      )}
      {accel.length > 0 && (
        <div className="mt-4 border-t border-zinc-200 pt-3 dark:border-zinc-800">
          <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            サーチ・加速
          </h3>
          <ComboList items={accel} />
        </div>
      )}
    </section>
  );
}
