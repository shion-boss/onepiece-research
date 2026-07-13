"use client";

import { useState } from "react";
import { runMatrixSampleReplay } from "@/lib/api";
import type { ReplayResponse } from "@/lib/types";
import { SpectateBoard } from "@/components/SpectateBoard";
import { CardImage } from "@/components/CardImage";

/**
 * AI vs AI 観戦パネル。 デッキ A / B / seed を選ぶと選択中のリーダーがプレビュー表示され、
 * 「観戦開始」で API が 1 試合シミュレート → SpectateBoard で自動再生 (autoPlay)。
 */

type DeckOption = { slug: string; name: string; kind?: string; leader?: string };

const INPUT =
  "w-full min-w-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-1.5 text-sm text-[color:var(--text-strong)]";

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

  const optA = decks.find((d) => d.slug === deckA);
  const optB = decks.find((d) => d.slug === deckB);

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
      {/* セレクタ + ボタン (上部固定) */}
      <div
        className="shrink-0 rounded-[var(--radius)] border p-3"
        style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}
      >
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_140px_auto] sm:items-end">
          <label className="flex min-w-0 flex-col gap-1 text-xs">
            <span className="text-[color:var(--text-muted)]">P0 デッキ</span>
            <select
              value={deckA}
              onChange={(e) => setDeckA(e.target.value)}
              className={INPUT}
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
            <span className="text-[color:var(--text-muted)]">P1 デッキ</span>
            <select
              value={deckB}
              onChange={(e) => setDeckB(e.target.value)}
              className={INPUT}
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
            <span className="text-[color:var(--text-muted)]">seed</span>
            <div className="flex gap-1">
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
                className={INPUT}
                disabled={running}
              />
              <button
                type="button"
                onClick={handleRandomSeed}
                className="shrink-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 text-xs text-[color:var(--text-default)] hover:bg-[color:var(--surface-3)]"
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
            className="shrink-0 rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-1.5 text-sm font-semibold text-white hover:bg-[color:var(--brand-strong)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "計算中..." : "観戦開始"}
          </button>
        </div>

        {error ? (
          <div className="mt-2 rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-2 text-sm text-[color:var(--danger)]">
            {error}
          </div>
        ) : null}

        {replay ? (
          <div
            className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius)] px-3 py-1.5 text-xs"
            style={{ background: "var(--surface-2)" }}
          >
            <span
              className="font-semibold"
              style={{
                color:
                  replay.winner === 0
                    ? "var(--accent)"
                    : replay.winner === 1
                      ? "var(--danger)"
                      : "var(--text-muted)",
              }}
            >
              {replay.winner === 0
                ? `P0 (${replay.deck_a_name}) 勝利`
                : replay.winner === 1
                  ? `P1 (${replay.deck_b_name}) 勝利`
                  : "引き分け / timeout"}
            </span>
            <span className="text-[color:var(--text-muted)]">·</span>
            <span className="text-[color:var(--text-default)]">
              {replay.turns} ターン / {replay.snapshots.length} snap
            </span>
            {elapsed !== null ? (
              <span className="ml-auto text-[color:var(--text-muted)]">
                計算 {elapsed.toFixed(1)}s (seed={seed})
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* 下部: replay があれば盤面、 無ければリーダープレビュー (選択で切替) */}
      {replay ? (
        <SpectateBoard
          snapshots={replay.snapshots}
          deckBottomName={replay.deck_a_name}
          deckTopName={replay.deck_b_name}
          winner={replay.winner}
          replayKey={`spectate:${replay.job_id}:${replay.game_index}`}
          onClose={() => setReplay(null)}
          autoPlay
        />
      ) : (
        <div
          className="flex flex-1 flex-col items-center justify-center gap-5 rounded-[var(--radius)] p-6"
          style={{ background: "var(--surface-1)" }}
        >
          <div className="flex items-center justify-center gap-6">
            <LeaderCard tag="P0" leader={optA?.leader} name={optA?.name} accent="var(--accent)" />
            <span className="text-2xl font-black italic text-[color:var(--text-muted)]">VS</span>
            <LeaderCard tag="P1" leader={optB?.leader} name={optB?.name} accent="var(--danger)" />
          </div>
          {running ? (
            <div className="flex items-center gap-2 text-sm text-[color:var(--text-muted)]">
              <span
                className="inline-block h-2 w-2 animate-pulse rounded-full"
                style={{ background: "var(--brand)" }}
              />
              シミュレート中... AI 同士が対戦しています（通常 3〜5 秒）
            </div>
          ) : (
            <p className="text-sm text-[color:var(--text-muted)]">
              「観戦開始」で、この 2 デッキの AI 対戦を頭から自動再生します。
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function LeaderCard({
  tag,
  leader,
  name,
  accent,
}: {
  tag: string;
  leader?: string;
  name?: string;
  accent: string;
}) {
  return (
    <div className="flex w-36 flex-col items-center gap-1.5">
      <span
        className="rounded px-2 py-0.5 text-[10px] font-bold text-white"
        style={{ background: accent }}
      >
        {tag}
      </span>
      {leader ? (
        <CardImage
          cardId={leader}
          alt={name ?? leader}
          className="h-40 w-auto rounded-[var(--radius)] border border-[color:var(--border-1)] object-cover"
        />
      ) : (
        <div
          className="flex h-40 w-[103px] items-center justify-center rounded-[var(--radius)] border border-dashed text-xs text-[color:var(--text-muted)]"
          style={{ borderColor: "var(--border-2)" }}
        >
          未選択
        </div>
      )}
      <span className="max-w-full truncate text-xs text-[color:var(--text-default)]">
        {name ?? "—"}
      </span>
    </div>
  );
}
