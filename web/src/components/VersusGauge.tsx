"use client";

// 人間 vs AI の合計勝敗を 1 本のゲージで表示。 陣取りの上に置く要約バー。
const HUMAN = "#4ec9b0";
const AI = "#f14c4c";

export function VersusGauge({
  humanWins,
  aiWins,
  label,
}: {
  humanWins: number;
  aiWins: number;
  label: string;
}) {
  const total = humanWins + aiWins || 1;
  const hp = Math.round((humanWins / total) * 100);
  const ap = 100 - hp;
  return (
    <div className="rounded-[var(--radius)] border p-4" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
      <div className="mb-1.5 flex items-baseline justify-between text-sm">
        <span className="font-bold" style={{ color: HUMAN }}>
          人間 {humanWins.toLocaleString()} 勝
        </span>
        <span className="text-xs text-[color:var(--text-muted)]">{label}</span>
        <span className="font-bold" style={{ color: AI }}>
          AI {aiWins.toLocaleString()} 勝
        </span>
      </div>
      <div className="relative flex h-7 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
        <div className="flex items-center justify-start pl-2 text-xs font-bold text-white" style={{ width: `${hp}%`, background: HUMAN }}>
          {hp >= 12 ? `${hp}%` : ""}
        </div>
        <div className="flex items-center justify-end pr-2 text-xs font-bold text-white" style={{ width: `${ap}%`, background: AI }}>
          {ap >= 12 ? `${ap}%` : ""}
        </div>
        {/* 50% ライン */}
        <div className="pointer-events-none absolute inset-y-0 left-1/2 w-px bg-white/40" />
      </div>
    </div>
  );
}
