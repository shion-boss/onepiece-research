"use client";

import { useState } from "react";
import { runMatrixSampleReplay, runMatrixSampleBatch } from "@/lib/api";
import type { ReplayResponse, MatrixBatchResult } from "@/lib/types";
import { SpectateBoard } from "@/components/SpectateBoard";
import { SpectateVsPanel, useDeckSelect, type SpectateDeck } from "@/components/SpectateVsPanel";

// AI vs AI 10連戦(勝率): 10 戦 (前半 P0 先攻 / 後半 P1 先攻) して勝率を出し、 各試合を観戦。
export function SpectateBatch({
  decks,
  initialDeckA,
  initialDeckB,
}: {
  decks: SpectateDeck[];
  initialDeckA?: string;
  initialDeckB?: string;
}) {
  const sel = useDeckSelect(decks, initialDeckA, initialDeckB);
  const [running, setRunning] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [batch, setBatch] = useState<MatrixBatchResult | null>(null);
  const busy = running || batchRunning;

  async function handleBatch() {
    setError(null);
    setReplay(null);
    setBatch(null);
    if (!sel.deckA || !sel.deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    // 毎回ランダムな基準 seed で 10 戦 (seed 欄は無いので内部で決める)。
    const base = Math.floor(Math.random() * 1_000_000);
    setBatchRunning(true);
    try {
      setBatch(await runMatrixSampleBatch(sel.deckA, sel.deckB, base, 10));
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchRunning(false);
    }
  }

  async function spectate(game: MatrixBatchResult["games"][number]) {
    setError(null);
    setRunning(true);
    try {
      // swap 試合は deck 順を入替えて再現 (= その試合の先攻/盤面を正確に)。
      const r = game.swap
        ? await runMatrixSampleReplay(sel.deckB, sel.deckA, game.seed)
        : await runMatrixSampleReplay(sel.deckA, sel.deckB, game.seed);
      setReplay(r);
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
        title="AI vs AI 10連戦（勝率）"
        subtitle="2 デッキで 10 戦（前半 P0 先攻 / 後半 P1 先攻）して勝率を出し、各試合を観戦できます。"
        decks={decks}
        catA={sel.catA}
        catB={sel.catB}
        deckA={sel.deckA}
        deckB={sel.deckB}
        onCatA={sel.changeCatA}
        onCatB={sel.changeCatB}
        onDeckA={sel.setDeckA}
        onDeckB={sel.setDeckB}
        disabled={busy}
        footer={
          <div className="flex flex-col gap-3">
            <button
              type="button"
              onClick={handleBatch}
              disabled={busy || !sel.deckA || !sel.deckB}
              className="rounded-[var(--radius)] px-8 py-4 text-lg font-semibold text-white transition hover:brightness-110 active:scale-[0.99] disabled:opacity-40"
              style={{ background: "var(--brand)" }}
            >
              {batchRunning ? "実行中..." : "▶ 10連戦を実行"}
            </button>
            {batchRunning && (
              <span className="text-sm text-[color:var(--text-muted)]">
                10 連戦を計算中... AI 同士が 10 試合対戦しています（30〜60 秒）
              </span>
            )}
            {error && <span className="text-sm text-[color:var(--danger)]">{error}</span>}
          </div>
        }
      />
      {batch && <BatchResults batch={batch} loading={running} onSpectate={spectate} />}
    </div>
  );
}

function BatchResults({
  batch,
  loading,
  onSpectate,
}: {
  batch: MatrixBatchResult;
  loading: boolean;
  onSpectate: (game: MatrixBatchResult["games"][number]) => void;
}) {
  const total = batch.n_games || 1;
  const p0pct = Math.round((batch.p0_wins / total) * 100);
  const p1pct = Math.round((batch.p1_wins / total) * 100);
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 pb-8">
      <div className="rounded-[var(--radius)] border p-4" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold" style={{ color: "var(--accent)" }}>
            P0 {batch.deck_a_name}　{batch.p0_wins}勝
          </span>
          <span className="font-semibold" style={{ color: "var(--danger)" }}>
            {batch.p1_wins}勝　{batch.deck_b_name} P1
          </span>
        </div>
        <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
          <div style={{ width: `${p0pct}%`, background: "var(--accent)" }} />
          <div style={{ width: `${p1pct}%`, background: "var(--danger)" }} />
        </div>
        <div className="mt-1 text-center text-xs text-[color:var(--text-muted)]">
          全 {total} 戦 · P0 {p0pct}% / P1 {p1pct}% · 引分 {batch.draws} ・ 先攻は 5 戦ずつ入替
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">各試合（クリックで観戦）</div>
        {batch.games.map((g) => (
          <div
            key={g.game_index}
            className="flex items-center gap-2 rounded-[var(--radius)] border px-2.5 py-1.5 text-sm"
            style={{ borderColor: "var(--border-1)", background: "var(--surface-2)" }}
          >
            <span className="w-10 text-[color:var(--text-muted)]">#{g.game_index + 1}</span>
            <span className="w-16 text-xs text-[color:var(--text-muted)]">先攻 {g.first_player === 0 ? "P0" : "P1"}</span>
            <span
              className="flex-1 font-medium"
              style={{ color: g.winner === 0 ? "var(--accent)" : g.winner === 1 ? "var(--danger)" : "var(--text-muted)" }}
            >
              {g.winner === 0 ? "P0 勝利" : g.winner === 1 ? "P1 勝利" : "引分"}
            </span>
            <span className="text-xs text-[color:var(--text-muted)]">{g.turns}ターン</span>
            <button
              type="button"
              onClick={() => onSpectate(g)}
              disabled={loading}
              className="rounded-[var(--radius)] bg-[color:var(--brand)] px-2.5 py-1 text-xs font-medium text-white hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
            >
              観戦
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
