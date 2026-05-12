"use client";

import type { CounterCandidate } from "@/lib/types";
import { CardImage } from "@/components/CardImage";

export function CounterCandidateCard({
  candidate,
  selected,
  onSelect,
}: {
  candidate: CounterCandidate;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full gap-3 rounded-lg border-2 p-3 text-left transition ${
        selected
          ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30"
          : "border-zinc-200 hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
      }`}
    >
      <div className="h-20 w-14 shrink-0 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
        <CardImage
          cardId={candidate.leader}
          alt={candidate.leader_name}
          className="h-full w-full object-cover"
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <span className="text-xs text-zinc-500">#{candidate.rank}</span>
            <span className="font-medium">{candidate.leader_name}</span>
            <span className="text-xs text-zinc-500">{candidate.leader}</span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
              {candidate.archetype}
            </span>
            <span
              className={`rounded px-2 py-0.5 text-xs font-bold ${scoreClass(candidate.estimated_score)}`}
            >
              {candidate.estimated_score}
            </span>
          </div>
        </div>
        {candidate.rationale.length > 0 && (
          <div className="mt-1 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">
            {candidate.rationale.slice(0, 2).join("; ")}
          </div>
        )}
        <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-zinc-500">
          {Object.entries(candidate.role_distribution).map(([role, n]) => (
            <span
              key={role}
              className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800"
            >
              {role}×{n}
            </span>
          ))}
        </div>
      </div>
    </button>
  );
}

function scoreClass(score: number): string {
  if (score >= 70) return "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300";
  if (score >= 50) return "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}
