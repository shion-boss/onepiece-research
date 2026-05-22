"use client";

import { useState } from "react";
import type { MatchupMatrix } from "@/lib/types";
import { MatchupHeatmap } from "@/components/MatchupHeatmap";
import { MatrixSpectate } from "@/components/MatrixSpectate";

type Tab = "matrix" | "spectate";

export function MetaPageClient({
  initialData,
  initialError,
  initialTab,
  initialA,
  initialB,
  initialSeed,
}: {
  initialData: MatchupMatrix | null;
  initialError: string | null;
  initialTab: Tab;
  initialA?: string;
  initialB?: string;
  initialSeed?: number;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);

  const decks = initialData?.decks ?? [];

  return (
    <main
      className={
        tab === "spectate"
          ? "flex h-screen w-full flex-col gap-1.5 px-3 py-1.5"
          : "mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 p-6"
      }
    >
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">メタ分析</h1>
          <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-bold text-blue-700 dark:bg-blue-900 dark:text-blue-300">
            STD
          </span>
        </div>
        <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
          <TabButton active={tab === "matrix"} onClick={() => setTab("matrix")}>
            マトリックス
          </TabButton>
          <TabButton active={tab === "spectate"} onClick={() => setTab("spectate")}>
            ライブ観戦
          </TabButton>
        </div>
        {tab === "matrix" && initialData && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {initialData.decks.length} デッキ × {initialData.decks.length} の勝率行列。各セル{" "}
            {initialData.n_games} 戦 (seed={initialData.seed}) ・最終計算{" "}
            {initialData.computed_at.replace("T", " ").replace("Z", "")} ・更新は{" "}
            <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
              scripts/compute_matchup_matrix.py
            </code>
          </p>
        )}
        {tab === "spectate" && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            デッキ A / B / seed を選んで「▶ 観戦開始」 で 1 試合をシミュレート → 盤面再生
          </p>
        )}
      </header>

      {initialError ? (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">読み込み失敗</div>
          <div className="mt-1 font-mono">{initialError}</div>
        </div>
      ) : tab === "matrix" ? (
        initialData ? <MatchupHeatmap data={initialData} /> : null
      ) : decks.length >= 2 ? (
        <MatrixSpectate
          decks={decks}
          initialDeckA={initialA}
          initialDeckB={initialB}
          initialSeed={initialSeed}
        />
      ) : (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          matrix の デッキ pool が見つかりません。{" "}
          <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">
            scripts/compute_matchup_matrix.py
          </code>{" "}
          を実行してください。
        </div>
      )}
    </main>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px border-b-2 px-3 py-1.5 text-sm transition ${
        active
          ? "border-blue-600 font-medium text-zinc-900 dark:border-blue-400 dark:text-zinc-100"
          : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}
