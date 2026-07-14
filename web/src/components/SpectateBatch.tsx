"use client";

import { useRef, useState } from "react";
import { runMatrixSampleReplay, runMatrixSampleGame } from "@/lib/api";
import type { ReplayResponse, MatrixBatchGame } from "@/lib/types";
import { SpectateBoard } from "@/components/SpectateBoard";
import { SpectateVsPanel, useDeckSelect, type SpectateDeck } from "@/components/SpectateVsPanel";

const DEFAULT_N_GAMES = 10;
const MAX_N_GAMES = 100;
const clampN = (v: number) => (Number.isFinite(v) ? Math.max(1, Math.min(MAX_N_GAMES, Math.floor(v))) : DEFAULT_N_GAMES);

// AI vs AI 連戦(勝率): N 戦 (前半 P0 先攻 / 後半 P1 先攻) を 1 試合ずつ実行し、
// 結果が出るたびに逐次表示。 各試合は同 seed の replay で観戦できる。
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
  const [nGames, setNGames] = useState(DEFAULT_N_GAMES);
  const [running, setRunning] = useState(false); // 単発観戦の replay ロード中
  const [batchRunning, setBatchRunning] = useState(false); // 連戦 実行中
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [games, setGames] = useState<MatrixBatchGame[]>([]);
  const [names, setNames] = useState<{ a: string; b: string } | null>(null);
  const [total, setTotal] = useState(DEFAULT_N_GAMES); // 実行中バッチの目標戦数 (途中で入力を変えても固定)
  const runIdRef = useRef(0);
  const busy = running || batchRunning;

  async function handleBatch() {
    setError(null);
    setReplay(null);
    setGames([]);
    setNames(null);
    if (!sel.deckA || !sel.deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    const n = clampN(nGames);
    setNGames(n);
    setTotal(n);
    const runId = ++runIdRef.current; // 途中で再実行されたら古い loop を捨てる
    const base = Math.floor(Math.random() * 1_000_000);
    const half = Math.floor(n / 2);
    setBatchRunning(true);
    try {
      for (let i = 0; i < n; i++) {
        const swap = i >= half; // 前半 da 先攻 / 後半 db 先攻
        const r = await runMatrixSampleGame(sel.deckA, sel.deckB, base + i, swap);
        if (runId !== runIdRef.current) return; // stale
        if (i === 0) setNames({ a: r.deck_a_name, b: r.deck_b_name });
        setGames((prev) => [
          ...prev,
          {
            game_index: i,
            seed: r.seed,
            winner: r.winner,
            turns: r.turns,
            first_player: r.first_player,
            swap: r.swap,
          },
        ]);
      }
    } catch (e) {
      if (runId === runIdRef.current) setError(String(e));
    } finally {
      if (runId === runIdRef.current) setBatchRunning(false);
    }
  }

  async function spectate(game: MatrixBatchGame) {
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
        title="AI vs AI 連戦（勝率）"
        subtitle="選んだ回数だけ対戦して勝率を出します（先攻は半分ずつ入替）。結果は 1 試合ずつ表示され、各試合を観戦できます。"
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
            <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4">
              <h2 className="text-sm font-semibold text-[color:var(--text-strong)]">対戦オプション</h2>
              <label className="flex flex-col gap-1 text-xs sm:max-w-xs">
                <span className="text-[color:var(--text-muted)]">連戦数（1〜{MAX_N_GAMES} · 先攻は半分ずつ入替）</span>
                <input
                  type="number"
                  min={1}
                  max={MAX_N_GAMES}
                  value={nGames}
                  disabled={batchRunning}
                  onChange={(e) => setNGames(clampN(parseInt(e.target.value || "1", 10)))}
                  className="w-28 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-2 text-sm font-mono text-[color:var(--text-strong)]"
                />
              </label>
            </div>
            <button
              type="button"
              onClick={handleBatch}
              disabled={busy || !sel.deckA || !sel.deckB}
              className="rounded-[var(--radius)] px-8 py-4 text-lg font-semibold text-white transition hover:brightness-110 active:scale-[0.99] disabled:opacity-40"
              style={{ background: "var(--brand)" }}
            >
              {batchRunning ? `実行中... ${games.length}/${total}` : `▶ ${clampN(nGames)}戦を実行`}
            </button>
            {error && <span className="text-sm text-[color:var(--danger)]">{error}</span>}
          </div>
        }
      />
      {(games.length > 0 || batchRunning) && (
        <BatchResults
          games={games}
          total={total}
          deckAName={names?.a ?? "P0"}
          deckBName={names?.b ?? "P1"}
          batchRunning={batchRunning}
          replayLoading={running}
          onSpectate={spectate}
        />
      )}
    </div>
  );
}

function BatchResults({
  games,
  total,
  deckAName,
  deckBName,
  batchRunning,
  replayLoading,
  onSpectate,
}: {
  games: MatrixBatchGame[];
  total: number;
  deckAName: string;
  deckBName: string;
  batchRunning: boolean;
  replayLoading: boolean;
  onSpectate: (game: MatrixBatchGame) => void;
}) {
  const done = games.length;
  const p0 = games.filter((g) => g.winner === 0).length;
  const p1 = games.filter((g) => g.winner === 1).length;
  const draws = games.filter((g) => g.winner === -1).length;
  const denom = done || 1;
  const p0pct = Math.round((p0 / denom) * 100);
  const p1pct = Math.round((p1 / denom) * 100);
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 pb-8">
      <div className="rounded-[var(--radius)] border p-4" style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}>
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold" style={{ color: "var(--accent)" }}>
            P0 {deckAName}　{p0}勝
          </span>
          <span className="font-semibold" style={{ color: "var(--danger)" }}>
            {p1}勝　{deckBName} P1
          </span>
        </div>
        <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
          <div style={{ width: `${p0pct}%`, background: "var(--accent)" }} />
          <div style={{ width: `${p1pct}%`, background: "var(--danger)" }} />
        </div>
        <div className="mt-1 text-center text-xs text-[color:var(--text-muted)]">
          {batchRunning
            ? `対戦中... ${done}/${total} 完了 · P0 ${p0}勝 / P1 ${p1}勝 ・ 引分 ${draws}`
            : `全 ${done} 戦 · P0 ${p0pct}% / P1 ${p1pct}% · 引分 ${draws} ・ 先攻は 5 戦ずつ入替`}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">各試合（クリックで観戦）</div>
        {games.map((g) => (
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
              disabled={replayLoading}
              className="rounded-[var(--radius)] bg-[color:var(--brand)] px-2.5 py-1 text-xs font-medium text-white hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
            >
              観戦
            </button>
          </div>
        ))}
        {batchRunning && (
          <div
            className="flex items-center gap-2 rounded-[var(--radius)] border border-dashed px-2.5 py-1.5 text-sm text-[color:var(--text-muted)]"
            style={{ borderColor: "var(--border-2)" }}
          >
            <span className="w-10">#{done + 1}</span>
            <span>対戦中...</span>
          </div>
        )}
      </div>
    </div>
  );
}
