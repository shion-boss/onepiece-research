"use client";

import { useState } from "react";
import { motion } from "framer-motion";
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
  const [firstPlayer, setFirstPlayer] = useState<"p0" | "p1" | "random">("p0");
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
    // 先攻: p0=deck_a 先攻 / p1=deck_b 先攻 / random は毎回どちらか。
    const fp = firstPlayer === "p1" ? 1 : firstPlayer === "p0" ? 0 : Math.round(Math.random());
    setRunning(true);
    try {
      setReplay(await runMatrixSampleReplay(sel.deckA, sel.deckB, seed, fp));
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
            <div className="flex flex-col gap-3 rounded-[var(--radius)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-4">
              <h2 className="text-sm font-semibold text-[color:var(--text-strong)]">対戦オプション</h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-[color:var(--text-muted)]">先攻 / 後攻</span>
                  <select
                    value={firstPlayer}
                    onChange={(e) => setFirstPlayer(e.target.value as "p0" | "p1" | "random")}
                    disabled={running}
                    className="rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-2 text-sm text-[color:var(--text-strong)]"
                  >
                    <option value="p0">P0 が先攻</option>
                    <option value="p1">P1 が先攻</option>
                    <option value="random">ランダム</option>
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-[color:var(--text-muted)]">seed（同じ値で再現可能）</span>
                  <div className="flex gap-1">
                    <input
                      type="number"
                      value={seed}
                      onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
                      disabled={running}
                      className="flex-1 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-2 text-sm font-mono text-[color:var(--text-strong)]"
                    />
                    <button
                      type="button"
                      onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}
                      disabled={running}
                      className="shrink-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-3 text-xs text-[color:var(--text-default)] hover:bg-[color:var(--surface-3)]"
                      title="ランダム seed"
                    >
                      ⟳
                    </button>
                  </div>
                </label>
              </div>
            </div>
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
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between text-xs text-[color:var(--text-muted)]">
                  <span>2 体の AI が全ターンを計算しています…</span>
                  <span>約 10 秒</span>
                </div>
                {/* 実 % は取れない (= 1 回の同期計算) ので、 経過時間ベースで減速しながら
                    伸びるゲージ。 計算時間はデッキ依存 (軽い~1s / value-defense系~9s) なので
                    遅い方 (~10s) に合わせて 92% まで伸ばし、 完了で盤面 replay に切り替わる
                    (= 早く終われば途中で切替、 遅くても 92% で待てる)。 */}
                <div className="h-2 w-full overflow-hidden rounded-full bg-[color:var(--surface-2)]">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: "var(--brand)" }}
                    initial={{ width: "4%" }}
                    animate={{ width: "92%" }}
                    transition={{ duration: 10, ease: "easeOut" }}
                  />
                </div>
              </div>
            )}
            {error && <span className="text-sm text-[color:var(--danger)]">{error}</span>}
          </div>
        }
      />
    </div>
  );
}
