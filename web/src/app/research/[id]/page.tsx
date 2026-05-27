"use client";

import Link from "next/link";
import { Suspense, use, useEffect, useState } from "react";
import {
  fetchResearchSession,
  pauseResearchSession,
  resumeResearchSession,
  saveDeckToServer,
  stopResearchSession,
} from "@/lib/api";
import type { ResearchSessionDetail } from "@/lib/types";
import { CardImage } from "@/components/CardImage";

export default function ResearchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">読み込み中…</div>}>
      <ResearchDetailContent params={params} />
    </Suspense>
  );
}

function ResearchDetailContent({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = use(params);
  const sessionId = decodeURIComponent(rawId);
  const [data, setData] = useState<ResearchSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [savedAs, setSavedAs] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      fetchResearchSession(sessionId)
        .then((d) => {
          if (!cancelled) {
            setData(d);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };
    tick();
    const interval = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId]);

  async function handlePause() {
    setActionBusy(true);
    try {
      await pauseResearchSession(sessionId);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(false);
    }
  }
  async function handleResume() {
    setActionBusy(true);
    try {
      await resumeResearchSession(sessionId);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(false);
    }
  }
  async function handleStop() {
    if (!confirm("セッションを停止しますか? (= 不可逆)")) return;
    setActionBusy(true);
    try {
      await stopResearchSession(sessionId);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(false);
    }
  }
  async function handleSaveBest() {
    if (!data?.best_deck) return;
    setActionBusy(true);
    try {
      const ts = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      const slug = `research_${data.target_slug}_${sessionId.slice(0, 6)}_${ts}`;
      const res = await saveDeckToServer({
        name: `研究結果_${data.target_slug}_${(data.best_winrate ?? 0) * 100 | 0}%`,
        leader: data.best_deck.leader,
        main: data.best_deck.main,
        slug,
        regulation: "standard",
        overwrite: true,
      });
      setSavedAs(res.slug);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionBusy(false);
    }
  }

  if (error && !data) {
    return (
      <main className="mx-auto w-full max-w-6xl px-6 py-8">
        <div className="rounded bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          エラー: {error}
        </div>
      </main>
    );
  }
  if (!data) {
    return <main className="p-6 text-sm text-zinc-500">読み込み中…</main>;
  }

  const maxBest = data.generation_history.reduce(
    (m, h) => Math.max(m, h.best_winrate ?? 0),
    0,
  );
  const maxGen = data.config.max_generations as number ?? 50;
  const targetWR = data.config.target_winrate as number ?? 0.7;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-6 py-8">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">研究セッション {sessionId.slice(0, 8)}…</h1>
          <div className="mt-1 text-sm text-zinc-500">
            対象: <span className="font-mono">{data.target_slug}</span> / 目標勝率{" "}
            {(targetWR * 100).toFixed(0)}% / 最大 {maxGen} 世代
          </div>
        </div>
        <Link
          href="/research"
          className="text-sm text-blue-600 hover:underline"
        >
          ← セッション一覧
        </Link>
      </header>

      {/* 状態 + 制御ボタン */}
      <section className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <StatusBadge status={data.status} />
        {data.completion_reason && (
          <span className="text-xs text-zinc-500">{data.completion_reason}</span>
        )}
        <div className="font-mono text-sm">
          世代 {data.current_generation}/{maxGen}
        </div>
        <div className="ml-auto flex gap-2">
          {data.status === "running" && (
            <>
              <button
                type="button"
                onClick={handlePause}
                disabled={actionBusy}
                className="rounded bg-yellow-600 px-3 py-1 text-xs font-medium text-white hover:bg-yellow-500 disabled:opacity-50"
              >
                一時停止
              </button>
              <button
                type="button"
                onClick={handleStop}
                disabled={actionBusy}
                className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
              >
                停止
              </button>
            </>
          )}
          {data.status === "paused" && (
            <button
              type="button"
              onClick={handleResume}
              disabled={actionBusy}
              className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              再開
            </button>
          )}
        </div>
      </section>

      {/* 進捗グラフ (= 簡易 ASCII chart) */}
      <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <h2 className="mb-2 text-sm font-medium">世代別 ベスト勝率</h2>
        {data.generation_history.length === 0 ? (
          <div className="text-xs text-zinc-500">まだ世代完了なし…</div>
        ) : (
          <div className="space-y-1">
            {data.generation_history.map((h) => (
              <div key={h.generation} className="flex items-center gap-2 text-xs">
                <span className="w-12 font-mono text-zinc-500">Gen {h.generation}</span>
                <div className="h-3 flex-1 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
                  <div
                    className="h-full bg-blue-500"
                    style={{ width: `${(h.best_winrate ?? 0) * 100}%` }}
                  />
                </div>
                <span className="w-16 text-right font-mono">
                  {((h.best_winrate ?? 0) * 100).toFixed(1)}%
                </span>
                <span className="w-12 text-right text-zinc-500">
                  {h.n_candidates} 候補
                </span>
              </div>
            ))}
            <div className="mt-2 text-[10px] text-zinc-500">
              目標: {(targetWR * 100).toFixed(0)}% / 現在ベスト: {((data.best_winrate ?? 0) * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </section>

      {/* ベストデッキ */}
      {data.best_deck && (
        <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium">
              現在のベストデッキ (勝率 {((data.best_winrate ?? 0) * 100).toFixed(1)}%)
            </h2>
            {savedAs ? (
              <Link
                href={`/decks/${encodeURIComponent(savedAs)}`}
                className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
              >
                保存済 — デッキを見る
              </Link>
            ) : (
              <button
                type="button"
                onClick={handleSaveBest}
                disabled={actionBusy}
                className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
              >
                ベストデッキを保存
              </button>
            )}
          </div>
          <div className="mb-2 flex items-center gap-2 text-xs">
            <div className="h-12 w-9 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
              <CardImage
                cardId={data.best_deck.leader}
                alt={data.best_deck.leader}
                className="h-full w-full object-cover"
              />
            </div>
            <span className="font-mono">{data.best_deck.leader}</span>
            <span className="text-zinc-500">{data.best_deck.leader_name ?? ""}</span>
          </div>
          <div className="grid grid-cols-6 gap-1 sm:grid-cols-8 md:grid-cols-10 lg:grid-cols-12">
            {data.best_deck.main.map((entry) => (
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
                <div className="absolute right-0.5 top-0.5 rounded bg-black/70 px-1 text-[9px] font-bold text-white">
                  ×{entry.count}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "running"
      ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
      : status === "paused"
        ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300"
        : status === "completed"
          ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
          : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  const label =
    status === "running" ? "実行中"
      : status === "paused" ? "一時停止"
        : status === "completed" ? "完了"
          : "停止";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}
