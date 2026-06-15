import type { LiveCombo } from "@/lib/api";

// DeckCombosPanel と同じ種別色 (palette: blue/amber/green/red)。
const KIND_BADGE: Record<string, string> = {
  enabler:
    "border-blue-400/60 bg-blue-950/50 text-blue-300",
  payoff:
    "border-amber-400/60 bg-amber-950/50 text-amber-300",
  amplifier:
    "border-green-400/60 bg-green-950/50 text-green-300",
  chain:
    "border-red-400/60 bg-red-950/50 text-red-300",
};

/**
 * 対戦中、 自分の手札/場に「今ピースが揃っているデッキ内コンボ」 を提示するヒント。
 * ohtsuki「デッキのコンボを対戦時に活用」 の live 版 (= 人間支援、 AI value でない)。
 */
export function LiveCombosHint({ combos }: { combos?: LiveCombo[] }) {
  if (!combos || combos.length === 0) return null;
  return (
    <div className="mt-2 rounded border border-amber-400/50 bg-amber-950/30 p-2">
      <div className="mb-1 text-xs font-semibold text-amber-300">
        今狙えるコンボ ({combos.length})
      </div>
      <ul className="space-y-1.5">
        {combos.map((c, i) => (
          <li key={i} className="text-xs leading-snug">
            <div className="flex flex-wrap items-center gap-1">
              <span
                className={`rounded border px-1 py-0.5 font-medium ${
                  KIND_BADGE[c.kind] ?? KIND_BADGE.enabler
                }`}
              >
                {c.label}
              </span>
              <span className="font-medium text-zinc-100">
                {c.cards.map((x) => x.name).join(" + ")}
              </span>
            </div>
            <div className="mt-0.5 text-zinc-400">{c.description}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
