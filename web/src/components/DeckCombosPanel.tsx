import { CardImage } from "@/components/CardImage";
import type { DeckComboOut } from "@/lib/types";

// 種別ごとのバッジ色 (VSCode tokens: brand/accent/warning/danger)。
const KIND_BADGE: Record<string, string> = {
  enabler:
    "border-[color:var(--brand-soft-border)] bg-[color:var(--brand-soft)]/40 text-[color:var(--brand-strong)]",
  payoff:
    "border-[color:var(--warning)]/40 bg-[color:var(--warning)]/10 text-[color:var(--warning)]",
  amplifier:
    "border-[color:var(--accent)]/40 bg-[color:var(--accent)]/10 text-[color:var(--accent)]",
  chain:
    "border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 text-[color:var(--danger)]",
  accelerant:
    "border-[color:var(--border-2)] bg-[color:var(--surface-2)] text-[color:var(--text-default)]",
};

function ComboList({ items }: { items: DeckComboOut[] }) {
  return (
    <ul className="space-y-2">
      {items.map((c, i) => (
        <li
          key={i}
          className="flex items-start gap-3 rounded-[var(--radius)] border border-[color:var(--border-1)] p-2"
        >
          <div className="flex shrink-0 items-center gap-1">
            {c.cards.map((card, j) => (
              <div key={card.card_id + j} className="flex items-center gap-1">
                {j > 0 && (
                  <span className="text-[color:var(--text-muted)]" aria-hidden>
                    +
                  </span>
                )}
                <div className="w-12 sm:w-14">
                  <CardImage
                    cardId={card.card_id}
                    alt={card.name}
                    className="w-full rounded-[var(--radius-sm)]"
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-xs font-medium ${
                  KIND_BADGE[c.kind] ?? KIND_BADGE.enabler
                }`}
              >
                {c.label}
              </span>
              <span className="truncate text-sm font-medium text-[color:var(--text-strong)]">
                {c.cards.map((x) => x.name).join(" + ")}
              </span>
            </div>
            <p className="mt-1 text-sm text-[color:var(--text-default)]">
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
    <section className="rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4">
      <h2 className="mb-1 text-lg font-semibold text-[color:var(--text-strong)]">デッキ内コンボ</h2>
      {real.length > 0 ? (
        <>
          <p className="mb-3 text-sm text-[color:var(--text-muted)]">
            このデッキで噛み合うカードの組み合わせ（実行型）。対戦中、これらが手札や場に揃ったら狙える。
          </p>
          <ComboList items={real} />
        </>
      ) : (
        <p className="mb-3 text-sm text-[color:var(--text-muted)]">
          実行型の 2 枚コンボは検出されませんでした。
        </p>
      )}
      {accel.length > 0 && (
        <div className="mt-4 border-t border-[color:var(--border-1)] pt-3">
          <h3 className="mb-2 text-sm font-semibold text-[color:var(--text-default)]">
            サーチ・加速
          </h3>
          <ComboList items={accel} />
        </div>
      )}
    </section>
  );
}
