"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveDeckToServer } from "@/lib/api";
import type { CounterCandidate } from "@/lib/types";
import { CardImage } from "@/components/CardImage";

export function CounterCandidateDetail({
  candidate,
  targetSlug,
}: {
  candidate: CounterCandidate;
  targetSlug: string;
}) {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [savedSlug, setSavedSlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const totalCount = candidate.main.reduce((sum, e) => sum + e.count, 0);
  const proposedSlug = `explore_${targetSlug}_${String(candidate.rank).padStart(2, "0")}_${candidate.leader}`;
  const regulation = candidate.regulation_required; // auto-pick

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const ts = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      const slug = `${proposedSlug}_${regulation === "extra" ? "ex_" : ""}${ts}`;
      const res = await saveDeckToServer({
        name: `対策${candidate.rank}_${candidate.leader_name}_vs_${targetSlug}${regulation === "extra" ? "_EX" : ""}`,
        leader: candidate.leader,
        main: candidate.main,
        slug,
        regulation,
        overwrite: true,
      });
      setSavedSlug(res.slug);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold">
            <span>
              #{candidate.rank} {candidate.leader_name}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                regulation === "extra"
                  ? "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300"
                  : "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
              }`}
              title={
                regulation === "extra"
                  ? `EX 必須 (block① カード ${candidate.extra_only_cards.length} 種含)`
                  : "Standard 使用可"
              }
            >
              {regulation === "extra" ? "EX" : "STD"}
            </span>
          </div>
          <div className="mt-0.5 text-sm text-zinc-500">
            ({candidate.leader}) — {candidate.archetype} / score {candidate.estimated_score}
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            メイン {totalCount} 枚 / unique {candidate.main.length}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {savedSlug ? (
            <button
              type="button"
              onClick={() => router.push(`/decks/${encodeURIComponent(savedSlug)}`)}
              className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-500"
            >
              ✓ 保存済 → デッキを見る
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className={`rounded px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 ${
                regulation === "extra"
                  ? "bg-purple-600 hover:bg-purple-500"
                  : "bg-blue-600 hover:bg-blue-500"
              }`}
            >
              {saving ? "保存中…" : `${regulation === "extra" ? "EX" : "STD"} デッキとして保存`}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          保存失敗: {error}
        </div>
      )}

      {regulation === "extra" && candidate.extra_only_cards.length > 0 && (
        <div className="mb-3 rounded bg-purple-50 p-2 text-xs text-purple-800 dark:bg-purple-950/30 dark:text-purple-300">
          <span className="font-medium">EX 必須カード ({candidate.extra_only_cards.length} 種): </span>
          <span>{candidate.extra_only_cards.join(", ")}</span>
        </div>
      )}

      {candidate.rationale.length > 0 && (
        <div className="mb-3 rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-900">
          <div className="font-medium text-zinc-600 dark:text-zinc-400">採用理由</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-zinc-600 dark:text-zinc-400">
            {candidate.rationale.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10">
        {candidate.main.map((entry) => {
          const isExtraOnly = candidate.extra_only_cards.includes(entry.card_id);
          return (
            <div
              key={entry.card_id}
              className={`relative overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800 ${
                isExtraOnly ? "ring-2 ring-purple-500" : ""
              }`}
              title={`${entry.card_id} ×${entry.count}${isExtraOnly ? " (EX 必須)" : ""}`}
            >
              <div className="aspect-[5/7]">
                <CardImage
                  cardId={entry.card_id}
                  alt={entry.card_id}
                  className="h-full w-full object-cover"
                />
              </div>
              <div className="absolute right-1 top-1 rounded bg-black/70 px-1 text-xs font-bold text-white">
                ×{entry.count}
              </div>
              {isExtraOnly && (
                <div className="absolute left-1 top-1 rounded bg-purple-600 px-1 text-[10px] font-bold text-white">
                  EX
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
