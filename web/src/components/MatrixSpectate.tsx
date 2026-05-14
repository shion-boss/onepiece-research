"use client";

import { useState } from "react";
import { runMatrixSampleReplay } from "@/lib/api";
import type { ReplayResponse } from "@/lib/types";
import { MatchReplay } from "@/components/MatchReplay";

/**
 * matrix 観戦パネル (= /meta/progress 内)
 *
 * デッキ A / B / seed を選んで「▶ 観戦開始」 を押すと、 API が 1 試合
 * シミュレートして 盤面 snapshot 付き replay を返す。 既存の MatchReplay
 * コンポーネントで盤面再生 (= マット表示、 カード、 アタック矢印、 board_eval ライン等)。
 *
 * 走行中の matrix プロセスとは別計算、 CPU を一時共有。
 */

type DeckOption = { slug: string; name: string };

export function MatrixSpectate({
  decks,
  initialDeckA,
  initialDeckB,
  initialSeed,
}: {
  decks: DeckOption[];
  initialDeckA?: string;
  initialDeckB?: string;
  initialSeed?: number;
}) {
  const has = (slug: string | undefined) =>
    !!slug && decks.some((d) => d.slug === slug);
  const [deckA, setDeckA] = useState<string>(
    has(initialDeckA) ? (initialDeckA as string) : decks[0]?.slug ?? "",
  );
  const [deckB, setDeckB] = useState<string>(
    has(initialDeckB)
      ? (initialDeckB as string)
      : decks[1]?.slug ?? decks[0]?.slug ?? "",
  );
  const [seed, setSeed] = useState<number>(initialSeed ?? 42);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  async function handleStart() {
    setError(null);
    setReplay(null);
    setElapsed(null);
    if (!deckA || !deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    setRunning(true);
    const t0 = performance.now();
    try {
      const r = await runMatrixSampleReplay(deckA, deckB, seed);
      setReplay(r);
      setElapsed((performance.now() - t0) / 1000);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  function handleRandomSeed() {
    setSeed(Math.floor(Math.random() * 1_000_000));
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {/* セレクタ + ボタンは shrink-0 (= 上部固定) */}
      <div className="shrink-0 rounded border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_140px_auto] sm:items-end">
          <label className="flex min-w-0 flex-col gap-1 text-xs">
            <span className="text-zinc-500">P0 デッキ</span>
            <select
              value={deckA}
              onChange={(e) => setDeckA(e.target.value)}
              className="w-full rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              disabled={running}
            >
              {decks.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-xs">
            <span className="text-zinc-500">P1 デッキ</span>
            <select
              value={deckB}
              onChange={(e) => setDeckB(e.target.value)}
              className="w-full rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              disabled={running}
            >
              {decks.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-xs">
            <span className="text-zinc-500">seed</span>
            <div className="flex gap-1">
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
                className="w-full min-w-0 rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
                disabled={running}
              />
              <button
                type="button"
                onClick={handleRandomSeed}
                className="shrink-0 rounded border border-zinc-300 bg-white px-2 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:hover:bg-zinc-700"
                disabled={running}
                title="ランダム seed"
              >
                ⟳
              </button>
            </div>
          </label>
          <button
            type="button"
            onClick={handleStart}
            disabled={running || !deckA || !deckB}
            className="shrink-0 rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "計算中..." : "▶ 観戦開始"}
          </button>
        </div>

        {error ? (
          <div className="mt-2 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
            {error}
          </div>
        ) : null}

        {replay ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded bg-zinc-50 px-3 py-1.5 text-xs dark:bg-zinc-950">
            <span
              className={
                replay.winner === 0
                  ? "font-semibold text-emerald-600 dark:text-emerald-400"
                  : replay.winner === 1
                    ? "font-semibold text-red-600 dark:text-red-400"
                    : "font-semibold text-zinc-500"
              }
            >
              {replay.winner === 0
                ? `P0 (${replay.deck_a_name}) 勝利`
                : replay.winner === 1
                  ? `P1 (${replay.deck_b_name}) 勝利`
                  : "引き分け / timeout"}
            </span>
            <span className="text-zinc-500">·</span>
            <span>
              {replay.turns} ターン / {replay.snapshots.length} snap
            </span>
            {elapsed !== null ? (
              <span className="ml-auto text-zinc-500">
                計算 {elapsed.toFixed(1)}s (seed={seed})
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* 計算中スピナー or MatchReplay は flex-1 で残り高さを取る */}
      {running ? (
        <div className="flex flex-1 items-center justify-center rounded bg-zinc-50 p-6 text-sm text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500 align-middle" />{" "}
          <span className="ml-2">シミュレート中... (PlanningAI、 通常 3-10 秒)</span>
        </div>
      ) : replay ? (
        <MatchReplay replay={replay} />
      ) : (
        <div className="flex flex-1 items-center justify-center rounded border border-dashed border-zinc-300 p-6 text-sm text-zinc-500 dark:border-zinc-700">
          デッキ / seed を選んで 「▶ 観戦開始」 を押すと盤面再生が始まります。
        </div>
      )}
    </div>
  );
}
