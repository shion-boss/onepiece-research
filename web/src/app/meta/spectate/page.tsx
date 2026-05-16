"use client";

import { Suspense } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { fetchMatrixProgress, type MatrixProgress } from "@/lib/api";
import { MatrixSpectate } from "@/components/MatrixSpectate";

/**
 * matrix 観戦専用ページ。
 *
 * - matrix progress endpoint からデッキ一覧を取得 (= 一度だけ、 polling 不要)
 * - URL query で `?a=<slug>&b=<slug>&seed=<n>` を受け取り、 初期値に反映
 * - **h-screen レイアウト** + flex で MatchReplay に残り高さを確保 (= /decks/.../replay と同型)
 *
 * Next.js 16 対応 (= 2026-05-16 修正):
 * - `useSearchParams` hook を Suspense 内で使う (= window 参照を削除)
 * - `force-dynamic` で static prerender を回避 (= 旧 build で 404 fallback 化していた issue 対応)
 */

export const dynamic = "force-dynamic";

export default function SpectatePage() {
  return (
    <Suspense fallback={<PageShell loading />}>
      <SpectateInner />
    </Suspense>
  );
}

function SpectateInner() {
  // useSearchParams は Suspense 内で使う (= Next.js 16 推奨パターン)
  const sp = useSearchParams();

  const { data: progress, error } = useSWR<MatrixProgress>(
    "matrix-progress-spectate",
    fetchMatrixProgress,
    { refreshInterval: 0 },
  );

  if (error) {
    return (
      <PageShell>
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">デッキ一覧取得失敗</div>
          <div className="mt-1 font-mono">{String(error)}</div>
        </div>
      </PageShell>
    );
  }

  if (!progress) {
    return <PageShell loading />;
  }

  if (!progress.exists || !progress.decks || progress.decks.length < 2) {
    return (
      <PageShell>
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          matrix の デッキ pool が見つかりません。{" "}
          <code className="rounded bg-amber-100 px-1 dark:bg-amber-900">
            scripts/compute_matchup_matrix.py
          </code>{" "}
          を実行してください。
        </div>
      </PageShell>
    );
  }

  const initialA = sp.get("a") ?? undefined;
  const initialB = sp.get("b") ?? undefined;
  const initialSeedStr = sp.get("seed");
  const initialSeed = initialSeedStr ? parseInt(initialSeedStr, 10) : undefined;

  return (
    <PageShell>
      <MatrixSpectate
        decks={progress.decks}
        initialDeckA={initialA}
        initialDeckB={initialB}
        initialSeed={Number.isFinite(initialSeed) ? initialSeed : undefined}
      />
    </PageShell>
  );
}

function PageShell({
  children,
  loading,
}: {
  children?: React.ReactNode;
  loading?: boolean;
}) {
  return (
    <main className="flex h-screen w-full flex-col gap-1.5 px-3 py-1.5">
      <header className="flex shrink-0 flex-wrap items-center gap-3 text-sm">
        <h1 className="text-base font-semibold tracking-tight">観戦</h1>
        <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-bold text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
          盤面再生
        </span>
        <Link
          href="/meta/progress"
          className="text-sm text-blue-600 hover:underline dark:text-blue-400"
        >
          ← matrix 進捗
        </Link>
        <Link
          href="/meta"
          className="text-sm text-blue-600 hover:underline dark:text-blue-400"
        >
          ← メタ分析
        </Link>
      </header>
      {loading ? (
        <div className="rounded bg-zinc-50 p-3 text-sm text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
          デッキ pool を読込中...
        </div>
      ) : (
        children
      )}
    </main>
  );
}
