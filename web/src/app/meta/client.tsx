"use client";

import { useState } from "react";
import type { MatchupMatrix } from "@/lib/types";
import { MatchupHeatmap } from "@/components/MatchupHeatmap";
import { MatrixSpectate } from "@/components/MatrixSpectate";
import { PageHeader } from "@/components/ui/PageHeader";
import { PageShell } from "@/components/ui/PageShell";

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

  const tabs = (
    <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
      <TabButton active={tab === "matrix"} onClick={() => setTab("matrix")}>
        マトリックス
      </TabButton>
      <TabButton active={tab === "spectate"} onClick={() => setTab("spectate")}>
        ライブ観戦
      </TabButton>
    </div>
  );

  // spectate tab は full-screen layout (= 既存)、 matrix tab は PageShell。
  if (tab === "spectate") {
    return (
      <main className="flex h-screen w-full flex-col gap-1.5 px-3 py-1.5">
        <PageHeader
          title="メタ分析"
          description="デッキ A / B / seed を 選んで 「観戦開始」 で 1 試合 シミュレート → 盤面再生"
          actions={tabs}
        />
        {decks.length >= 2 ? (
          <MatrixSpectate
            decks={decks}
            initialDeckA={initialA}
            initialDeckB={initialB}
            initialSeed={initialSeed}
          />
        ) : (
          <NoMatrixBanner />
        )}
      </main>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="メタ分析"
        description={
          initialData
            ? `${initialData.decks.length} デッキ × ${initialData.decks.length} の 勝率行列。 各 cell ${initialData.n_games} 戦 (seed=${initialData.seed})`
            : "デッキ間 N×N 勝率行列"
        }
        actions={tabs}
        meta={
          initialData && (
            <>
              {initialData.ai_version && (
                <span>
                  AI:{" "}
                  <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[11px] dark:bg-zinc-800">
                    {initialData.ai_version}
                  </code>
                </span>
              )}
              <span>
                計算日時: {initialData.computed_at.replace("T", " ").replace("Z", " UTC")}
              </span>
              <span>
                更新:{" "}
                <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[11px] dark:bg-zinc-800">
                  scripts/compute_matchup_matrix.py
                </code>
              </span>
            </>
          )
        }
      />
      {initialError ? (
        <ErrorBanner message={initialError} />
      ) : initialData ? (
        <MatchupHeatmap data={initialData} />
      ) : (
        <NoMatrixBanner />
      )}
    </PageShell>
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

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
      <div className="font-medium">読み込み失敗</div>
      <div className="mt-1 font-mono text-xs">{message}</div>
    </div>
  );
}

function NoMatrixBanner() {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
      matrix の デッキ pool が 見つかりません。{" "}
      <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">
        scripts/compute_matchup_matrix.py
      </code>{" "}
      を 実行してください。
    </div>
  );
}
