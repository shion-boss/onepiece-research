"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveDeckToServer } from "@/lib/api";
import type { CounterCandidate, Regulation } from "@/lib/types";
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
  const [regulation, setRegulation] = useState<Regulation>("standard");

  const totalCount = candidate.main.reduce((sum, e) => sum + e.count, 0);
  const proposedSlug = `explore_${targetSlug}_${String(candidate.rank).padStart(2, "0")}_${candidate.leader}`;

  // 422 レスポンスから「block①のみ」 エラーを検出
  const errorIsBlockOnly =
    error != null &&
    /スタンダード使用不可.*block/.test(error) &&
    regulation === "standard";

  async function handleSave(forceRegulation?: Regulation) {
    const reg = forceRegulation ?? regulation;
    setSaving(true);
    setError(null);
    try {
      const ts = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      const slug = `${proposedSlug}_${reg === "extra" ? "ex_" : ""}${ts}`;
      const res = await saveDeckToServer({
        name: `対策${candidate.rank}_${candidate.leader_name}_vs_${targetSlug}${reg === "extra" ? "_EX" : ""}`,
        leader: candidate.leader,
        main: candidate.main,
        slug,
        regulation: reg,
        overwrite: true,
      });
      setSavedSlug(res.slug);
      if (forceRegulation) setRegulation(forceRegulation);
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
          <div className="text-lg font-semibold">
            #{candidate.rank} {candidate.leader_name}
            <span className="ml-2 text-sm font-normal text-zinc-500">
              ({candidate.leader}) — {candidate.archetype} / score{" "}
              {candidate.estimated_score}
            </span>
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            メイン {totalCount} 枚 / unique {candidate.main.length}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!savedSlug && (
            <fieldset className="flex items-center gap-2 rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-700">
              <legend className="sr-only">保存規制</legend>
              <label className="flex cursor-pointer items-center gap-1">
                <input
                  type="radio"
                  name="regulation"
                  value="standard"
                  checked={regulation === "standard"}
                  onChange={() => setRegulation("standard")}
                  className="h-3 w-3"
                />
                <span>STD</span>
              </label>
              <label className="flex cursor-pointer items-center gap-1">
                <input
                  type="radio"
                  name="regulation"
                  value="extra"
                  checked={regulation === "extra"}
                  onChange={() => setRegulation("extra")}
                  className="h-3 w-3"
                />
                <span>EX</span>
              </label>
            </fieldset>
          )}
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
              onClick={() => handleSave()}
              disabled={saving}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {saving ? "保存中…" : "デッキとして保存"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          <div>保存失敗: {error}</div>
          {errorIsBlockOnly && (
            <button
              type="button"
              onClick={() => handleSave("extra")}
              disabled={saving}
              className="mt-2 rounded bg-purple-600 px-3 py-1 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-50"
            >
              → EX デッキとして保存し直す
            </button>
          )}
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
        {candidate.main.map((entry) => (
          <div
            key={entry.card_id}
            className="relative overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800"
            title={`${entry.card_id} ×${entry.count}`}
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
          </div>
        ))}
      </div>
    </div>
  );
}
