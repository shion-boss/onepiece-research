"use client";

import { useState } from "react";
import { runMatrixSampleReplay } from "@/lib/api";
import type { ReplayResponse } from "@/lib/types";
import { SpectateBoard } from "@/components/SpectateBoard";
import { SpectateVsPanel, useDeckSelect, type SpectateDeck } from "@/components/SpectateVsPanel";

// AI vs AI 観戦 (単発): 2 デッキを選んで 1 試合をその seed で観戦。
export function MatrixSpectate({
  decks,
  initialDeckA,
  initialDeckB,
}: {
  decks: SpectateDeck[];
  initialDeckA?: string;
  initialDeckB?: string;
}) {
  const sel = useDeckSelect(decks, initialDeckA, initialDeckB);
  const [seed, setSeed] = useState(42);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);

  async function handleStart() {
    setError(null);
    setReplay(null);
    if (!sel.deckA || !sel.deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    setRunning(true);
    try {
      setReplay(await runMatrixSampleReplay(sel.deckA, sel.deckB, seed));
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  if (replay) {
    return (
      <SpectateBoard
        snapshots={replay.snapshots}
        deckBottomName={replay.deck_a_name}
        deckTopName={replay.deck_b_name}
        winner={replay.winner}
        replayKey={`spectate:${replay.job_id}:${replay.game_index}`}
        onClose={() => setReplay(null)}
        autoPlay
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto">
      <SpectateVsPanel
        title="AI vs AI 観戦"
        subtitle="2 つのデッキを選ぶと、AI 同士が 1 試合プレイした盤面を観戦できます。"
        decks={decks}
        catA={sel.catA}
        catB={sel.catB}
        deckA={sel.deckA}
        deckB={sel.deckB}
        onCatA={sel.changeCatA}
        onCatB={sel.changeCatB}
        onDeckA={sel.setDeckA}
        onDeckB={sel.setDeckB}
        disabled={running}
        footer={
          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-xs">
              <span className="text-[color:var(--text-muted)]">seed（この試合を再現）</span>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
                disabled={running}
                className="w-28 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-1.5 text-sm text-[color:var(--text-strong)]"
              />
              <button
                type="button"
                onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}
                disabled={running}
                className="shrink-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1.5 text-xs text-[color:var(--text-default)] hover:bg-[color:var(--surface-3)]"
                title="ランダム seed"
              >
                ⟳
              </button>
            </label>
            <button
              type="button"
              onClick={handleStart}
              disabled={running || !sel.deckA || !sel.deckB}
              className="rounded-[var(--radius)] px-8 py-4 text-lg font-semibold text-white transition hover:brightness-110 active:scale-[0.99] disabled:opacity-40"
              style={{ background: "var(--brand)" }}
            >
              {running ? "開始中..." : "▶ 観戦 開始"}
            </button>
            {running && (
              <span className="text-sm text-[color:var(--text-muted)]">シミュレート中...（通常 3〜5 秒）</span>
            )}
            {error && <span className="text-sm text-[color:var(--danger)]">{error}</span>}
          </div>
        }
      />
    </div>
  );
}
