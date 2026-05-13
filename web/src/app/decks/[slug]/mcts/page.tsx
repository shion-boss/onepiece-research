"use client";

import { Suspense, use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { fetchDecks, runMctsGame } from "@/lib/api";
import type { DeckSummary, McctsGameResponse } from "@/lib/types";
import { MctsTreeView } from "@/components/MctsTreeView";

export default function McctsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">読み込み中…</div>}>
      <McctsContent params={params} />
    </Suspense>
  );
}

function McctsContent({ params }: { params: Promise<{ slug: string }> }) {
  const { slug: rawSlug } = use(params);
  const slug = decodeURIComponent(rawSlug);
  const searchParams = useSearchParams();
  const initialOpponent = searchParams.get("opp") ?? "";
  const initialSeed = parseInt(searchParams.get("seed") ?? "42", 10);
  const initialNSim = parseInt(searchParams.get("n_sim") ?? "30", 10);

  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [opponent, setOpponent] = useState(initialOpponent);
  const [seed, setSeed] = useState(initialSeed);
  const [nSim, setNSim] = useState(initialNSim);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [game, setGame] = useState<McctsGameResponse | null>(null);
  const [turnIdx, setTurnIdx] = useState(0);

  useEffect(() => {
    fetchDecks().then((d) => {
      setDecks(d);
      if (!opponent && d.length > 0) {
        const first = d.find((x) => x.slug !== slug) ?? d[0];
        setOpponent(first.slug);
      }
    });
  }, [slug, opponent]);

  const opponents = useMemo(() => decks.filter((d) => d.slug !== slug), [decks, slug]);

  async function handleRun() {
    if (!opponent) return;
    setRunning(true);
    setError(null);
    setGame(null);
    setTurnIdx(0);
    try {
      const r = await runMctsGame(slug, {
        opponent_slug: opponent,
        seed,
        n_simulations: nSim,
        max_tree_depth: 2,
      });
      setGame(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  const currentTurn =
    game && game.mcts_turns.length > 0 ? game.mcts_turns[turnIdx] : null;

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">🧠 戦い方の探索 — MCTS 思考ツリー</h1>
          <div className="mt-1 text-sm text-zinc-500">
            自デッキ {slug} / MCTSAI vs GreedyAI で 1 試合実行、 各 MCTS choose_action の
            ツリーをターン別に表示します
          </div>
        </div>
        <Link
          href={`/decks/${encodeURIComponent(slug)}`}
          className="text-sm text-blue-600 hover:underline"
        >
          ← デッキに戻る
        </Link>
      </header>

      <section className="flex flex-wrap items-end gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <label className="flex flex-col gap-1 text-xs text-zinc-500">
          相手デッキ
          <select
            value={opponent}
            onChange={(e) => setOpponent(e.target.value)}
            className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          >
            {opponents.map((o) => (
              <option key={o.slug} value={o.slug}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-500">
          seed
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value) || 42)}
            className="w-20 rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-500">
          n_simulations (= 1 アクション選択あたり rollout 数)
          <input
            type="number"
            min={1}
            max={200}
            value={nSim}
            onChange={(e) => setNSim(Number(e.target.value) || 30)}
            className="w-20 rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </label>
        <button
          type="button"
          onClick={handleRun}
          disabled={running || !opponent}
          className="rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
        >
          {running ? `実行中… (n_sim=${nSim} で 30〜120 秒)` : "🧠 MCTS で 1 試合実行"}
        </button>
      </section>

      {error && (
        <div className="rounded bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          エラー: {error}
        </div>
      )}

      {game && (
        <>
          <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <div className="text-sm">
              <span className="font-medium">{game.deck_mcts}</span>
              <span className="mx-2 text-zinc-500">vs</span>
              <span>{game.deck_opp}</span>
              <span className="ml-3 text-zinc-500">
                {game.total_turns} ターン / {game.total_actions} アクション / 勝者{" "}
                {game.winner === 0 ? "MCTS 側" : game.winner === 1 ? "相手側" : "引分"}
              </span>
            </div>
            <div className="mt-1 text-xs text-zinc-500">
              MCTS が考えたターン: {game.mcts_turns.length} 件
            </div>
          </section>

          {game.mcts_turns.length > 0 && (
            <>
              {/* 重要ターン抽出 (= Greedy と差分のあるもの top 5) */}
              <DisagreementSummary
                turns={game.mcts_turns}
                onSelectTurn={(idx) => setTurnIdx(idx)}
              />

              <section className="space-y-3">
                <div className="flex items-center gap-3">
                  <label className="flex flex-col gap-1 text-xs text-zinc-500">
                    ターン (= MCTS 考え時)
                    <input
                      type="range"
                      min={0}
                      max={game.mcts_turns.length - 1}
                      value={turnIdx}
                      onChange={(e) => setTurnIdx(Number(e.target.value))}
                      className="w-72"
                    />
                  </label>
                  <div className="text-xs">
                    {turnIdx + 1} / {game.mcts_turns.length}
                  </div>
                  {currentTurn && (
                    <div className="ml-auto text-xs text-zinc-500">
                      Game ターン T{currentTurn.turn} action #{currentTurn.action_index}
                    </div>
                  )}
                </div>

                {currentTurn && (
                  <div className="space-y-2">
                    {/* MCTS 判断 summary (= 人間可読) */}
                    <div
                      className={`rounded-lg border-2 p-3 ${
                        currentTurn.agree_with_greedy
                          ? "border-green-300 bg-green-50 dark:border-green-700 dark:bg-green-950/30"
                          : "border-orange-300 bg-orange-50 dark:border-orange-700 dark:bg-orange-950/30"
                      }`}
                    >
                      <div className="text-xs text-zinc-500">
                        T{currentTurn.turn} の MCTS 判断 (確信度{" "}
                        {(currentTurn.mcts_confidence * 100).toFixed(0)}%)
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-3 text-sm">
                        <div>
                          <span className="text-zinc-500">🧠 MCTS:</span>{" "}
                          <span className="rounded bg-purple-100 px-2 py-0.5 font-mono text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                            {currentTurn.chosen_action_label}
                          </span>
                        </div>
                        <div>
                          <span className="text-zinc-500">⚡ Greedy:</span>{" "}
                          <span className="rounded bg-zinc-100 px-2 py-0.5 font-mono text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                            {currentTurn.greedy_action_label || "(unknown)"}
                          </span>
                        </div>
                      </div>
                      <div
                        className={`mt-1 text-xs font-medium ${
                          currentTurn.agree_with_greedy
                            ? "text-green-700 dark:text-green-300"
                            : "text-orange-700 dark:text-orange-300"
                        }`}
                      >
                        {currentTurn.agree_with_greedy
                          ? "✓ MCTS と Greedy は同じ選択 (= Greedy で十分)"
                          : "⚠️ MCTS と Greedy が異なる (= Greedy が見落としている可能性)"}
                      </div>
                    </div>
                    <MctsTreeView root={currentTurn.root_tree} />
                  </div>
                )}
              </section>
            </>
          )}

          {game.mcts_turns.length === 0 && (
            <div className="rounded bg-zinc-50 p-3 text-sm text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
              MCTS が選択する場面が無かった (= 全 action が 1 択)
            </div>
          )}
        </>
      )}
    </main>
  );
}

function DisagreementSummary({
  turns,
  onSelectTurn,
}: {
  turns: import("@/lib/types").McctsTurn[];
  onSelectTurn: (idx: number) => void;
}) {
  const disagreements = turns
    .map((t, i) => ({ ...t, idx: i }))
    .filter((t) => !t.agree_with_greedy);
  const agreeCount = turns.length - disagreements.length;
  const top = disagreements
    .slice()
    .sort((a, b) => b.mcts_confidence - a.mcts_confidence)
    .slice(0, 5);

  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="mb-2 text-sm font-medium">
        MCTS vs Greedy 比較 サマリ
      </h3>
      <div className="mb-3 text-xs text-zinc-500">
        全 {turns.length} 場面 / 一致{" "}
        <span className="font-bold text-green-600">{agreeCount}</span> / 差分{" "}
        <span className="font-bold text-orange-600">{disagreements.length}</span>{" "}
        ({((disagreements.length / Math.max(1, turns.length)) * 100).toFixed(0)}% で MCTS が異なる選択)
      </div>
      {top.length > 0 ? (
        <>
          <div className="mb-1 text-xs text-zinc-500">
            重要差分 Top {top.length} (= 確信度高い MCTS の選択):
          </div>
          <ul className="space-y-1 text-xs">
            {top.map((t) => (
              <li key={t.idx}>
                <button
                  type="button"
                  onClick={() => onSelectTurn(t.idx)}
                  className="flex w-full items-center gap-2 rounded border border-orange-200 bg-orange-50 px-2 py-1 text-left hover:bg-orange-100 dark:border-orange-900 dark:bg-orange-950/30 dark:hover:bg-orange-950/50"
                >
                  <span className="font-mono text-zinc-500">T{t.turn}</span>
                  <span className="rounded bg-purple-100 px-1.5 py-0.5 font-mono text-[10px] text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                    🧠 {t.chosen_action_label}
                  </span>
                  <span className="text-zinc-400">vs</span>
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                    ⚡ {t.greedy_action_label || "(?)"}
                  </span>
                  <span className="ml-auto font-bold text-orange-700">
                    確信 {(t.mcts_confidence * 100).toFixed(0)}%
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="text-xs text-zinc-500">
          MCTS と Greedy はほぼ全場面で一致 (= Greedy が十分強い)
        </div>
      )}
    </section>
  );
}
