"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { runMatch } from "@/lib/api";
import type { DeckSummary, MatchSummary } from "@/lib/types";
import { useDeckSimulationStore } from "@/stores/deckSimulation";
import { DeckImprovementSection } from "./DeckImprovementSection";

type Goal = "improve" | "evaluate" | "learn";

const GOALS: { id: Goal; emoji: string; label: string; sub: string }[] = [
  { id: "improve", emoji: "💪", label: "デッキを改善したい", sub: "弱点発見 + 提案 + 適用" },
  { id: "evaluate", emoji: "⚔️", label: "強さを測りたい", sub: "勝率と戦績の検証" },
  { id: "learn", emoji: "🧠", label: "戦い方を学びたい", sub: "MCTS 思考ツリー" },
];

export function DeckResearchWorkflow({
  selfSlug,
  selfName,
  opponents,
}: {
  selfSlug: string;
  selfName: string;
  opponents: DeckSummary[];
}) {
  const [goal, setGoal] = useState<Goal>("improve");

  return (
    <div className="space-y-4">
      <div>
        <h2 className="mb-2 text-lg font-medium">🎯 何をしたい?</h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {GOALS.map((g) => {
            const active = goal === g.id;
            return (
              <button
                key={g.id}
                type="button"
                onClick={() => setGoal(g.id)}
                className={`flex flex-col gap-1 rounded-lg border-2 p-3 text-left transition ${
                  active
                    ? goalActiveClass(g.id)
                    : "border-zinc-200 hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-500"
                }`}
              >
                <div className="text-base font-medium">
                  <span className="mr-1">{g.emoji}</span>
                  {g.label}
                </div>
                <div className="text-xs text-zinc-500">{g.sub}</div>
              </button>
            );
          })}
        </div>
      </div>

      {goal === "improve" && (
        <>
          {/* 🔬 研究ラボへの導線 (= 長時間自動研究) */}
          <div className="flex items-center justify-between rounded-lg border-2 border-purple-300 bg-gradient-to-r from-purple-50 to-blue-50 p-3 dark:border-purple-700 dark:from-purple-950/30 dark:to-blue-950/30">
            <div>
              <div className="text-sm font-semibold">
                🔬 真の対策デッキを研究する (= 進化的探索)
              </div>
              <div className="mt-0.5 text-xs text-zinc-600 dark:text-zinc-400">
                数時間かけて世代交代で自動探索 → 最強対策デッキを発見
              </div>
            </div>
            <Link
              href={`/research/new?target=${encodeURIComponent(selfSlug)}`}
              className="rounded bg-purple-600 px-3 py-2 text-xs font-medium text-white hover:bg-purple-500"
            >
              研究セッション開始 →
            </Link>
          </div>
          <ImproveWorkflow selfSlug={selfSlug} selfName={selfName} opponents={opponents} />
        </>
      )}
      {goal === "evaluate" && (
        <EvaluateWorkflow selfSlug={selfSlug} selfName={selfName} opponents={opponents} />
      )}
      {goal === "learn" && (
        <LearnWorkflow selfSlug={selfSlug} opponents={opponents} />
      )}
    </div>
  );
}

function goalActiveClass(g: Goal): string {
  if (g === "improve")
    return "border-orange-500 bg-orange-50 dark:border-orange-400 dark:bg-orange-950/30";
  if (g === "evaluate")
    return "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-950/30";
  return "border-purple-500 bg-purple-50 dark:border-purple-400 dark:bg-purple-950/30";
}

// ============================================================================ #
// 💪 改善ワークフロー (= 改善探索 → 提案 → MCTS 補強 → 適用)
// ============================================================================ #
function ImproveWorkflow({
  selfSlug,
  selfName,
  opponents,
}: {
  selfSlug: string;
  selfName: string;
  opponents: DeckSummary[];
}) {
  const [opponent, setOpponent] = useState(opponents[0]?.slug ?? "");
  const [seed, setSeed] = useState(42);
  const [exploreSeeds, setExploreSeeds] = useState(10);
  const [exploreNGames, setExploreNGames] = useState(10);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exploreResult, setExploreResult] = useState<{ winrate: number; nGames: number } | null>(null);
  const triggerImprovementsRefresh = useDeckSimulationStore(
    (s) => s.triggerImprovementsRefresh,
  );

  async function handleExplore() {
    if (!opponent) return;
    setRunning(true);
    setError(null);
    setProgress({ done: 0, total: exploreSeeds });
    setExploreResult(null);
    try {
      let done = 0;
      const promises = Array.from({ length: exploreSeeds }, (_, i) => {
        const s = seed + i;
        return runMatch({
          deck_a_id: selfSlug,
          deck_b_id: opponent,
          n_games: exploreNGames,
          seed: s,
        }).then((r) => {
          done += 1;
          setProgress({ done, total: exploreSeeds });
          return r;
        });
      });
      const results = await Promise.all(promises);
      triggerImprovementsRefresh();
      const totalGames = results.reduce((s, r) => s + r.n_games, 0);
      const totalWins = results.reduce((s, r) => s + r.deck_a_wins, 0);
      setExploreResult({ winrate: totalWins / totalGames, nGames: totalGames });
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  return (
    <div className="space-y-3">
      {/* Step 1: 改善探索 */}
      <Step
        n={1}
        title="改善探索 (= データ収集で弱点発見)"
        body={
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <OpponentSelect value={opponent} onChange={setOpponent} opponents={opponents} />
              <SeedInput value={seed} onChange={setSeed} />
              <label className="flex items-center gap-1">
                seeds
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={exploreSeeds}
                  onChange={(e) => setExploreSeeds(Number(e.target.value) || 10)}
                  className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
                />
              </label>
              ×
              <label className="flex items-center gap-1">
                N
                <input
                  type="number"
                  min={2}
                  max={50}
                  value={exploreNGames}
                  onChange={(e) => setExploreNGames(Number(e.target.value) || 10)}
                  className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
                />
              </label>
              <span className="font-bold">= {exploreSeeds * exploreNGames} 試合</span>
            </div>
            <button
              type="button"
              onClick={handleExplore}
              disabled={running || !opponent}
              className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-orange-500 disabled:opacity-50"
            >
              {running
                ? progress
                  ? `🔍 改善探索 中… ${progress.done}/${progress.total}`
                  : "🔍 改善探索 中…"
                : "🔍 改善探索を実行"}
            </button>
            {error && (
              <div className="rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300">
                {error}
              </div>
            )}
            {exploreResult && (
              <div className="rounded bg-green-50 p-2 text-xs text-green-800 dark:bg-green-950/30 dark:text-green-300">
                ✓ 完了: {exploreResult.nGames} 試合 / 勝率{" "}
                {(exploreResult.winrate * 100).toFixed(1)}%
                <span className="ml-2 font-bold">
                  → 下の Step 2 に改善提案が表示されました
                </span>
              </div>
            )}
          </div>
        }
      />

      {/* Step 2: 改善提案 (= ImprovementSection 埋込、 opponent は Step 1 と統一) */}
      <Step
        n={2}
        title="改善提案を確認・適用 (= MCTS 補強で精度 up)"
        body={<DeckImprovementSection slug={selfSlug} opponentSlug={opponent} />}
      />

      {/* Step 3: 実践検証 */}
      <Step
        n={3}
        title="検証 (= 提案適用後に勝率を再測定)"
        body={
          <div className="text-xs text-zinc-500">
            提案を適用したら「⚔️ 強さを測りたい」 ゴールに切り替えて、 改善前後の勝率を比較。
          </div>
        }
      />
    </div>
  );
}

// ============================================================================ #
// ⚔️ 検証ワークフロー (= 実践 N=50)
// ============================================================================ #
function EvaluateWorkflow({
  selfSlug,
  selfName,
  opponents,
}: {
  selfSlug: string;
  selfName: string;
  opponents: DeckSummary[];
}) {
  const [opponent, setOpponent] = useState(opponents[0]?.slug ?? "");
  const [seed, setSeed] = useState(42);
  const [n, setN] = useState(50);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchSummary | null>(null);

  async function handleEvaluate() {
    if (!opponent) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await runMatch({
        deck_a_id: selfSlug,
        deck_b_id: opponent,
        n_games: n,
        seed,
      });
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-3">
      <Step
        n={1}
        title="勝率測定 (= GreedyAI で N=50 試合)"
        body={
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <OpponentSelect value={opponent} onChange={setOpponent} opponents={opponents} />
              <SeedInput value={seed} onChange={setSeed} />
              <label className="flex items-center gap-1">
                試合数
                <input
                  type="number"
                  min={10}
                  max={500}
                  step={10}
                  value={n}
                  onChange={(e) => setN(Number(e.target.value) || 50)}
                  className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
                />
              </label>
            </div>
            <button
              type="button"
              onClick={handleEvaluate}
              disabled={running || !opponent}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {running ? "実戦中…" : `⚔️ 実践を実行 (${n} 試合)`}
            </button>
            {error && (
              <div className="rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300">
                {error}
              </div>
            )}
          </div>
        }
      />
      {result && (
        <Step
          n={2}
          title="結果"
          body={<MatchResult selfName={selfName} result={result} selfSlug={selfSlug} />}
        />
      )}
    </div>
  );
}

// ============================================================================ #
// 🧠 学習ワークフロー (= MCTS ツリー可視化ページへ遷移)
// ============================================================================ #
function LearnWorkflow({
  selfSlug,
  opponents,
}: {
  selfSlug: string;
  opponents: DeckSummary[];
}) {
  const router = useRouter();
  const [opponent, setOpponent] = useState(opponents[0]?.slug ?? "");
  const [seed, setSeed] = useState(42);
  const [nSim, setNSim] = useState(30);

  function handleStart() {
    if (!opponent) return;
    router.push(
      `/decks/${encodeURIComponent(selfSlug)}/mcts?opp=${encodeURIComponent(opponent)}&seed=${seed}&n_sim=${nSim}`,
    );
  }

  return (
    <Step
      n={1}
      title="戦い方の探索 (= MCTS の思考ツリーを別ページで可視化)"
      body={
        <div className="space-y-2">
          <div className="text-xs text-zinc-500">
            MCTSAI が 1 試合通して各ターンで深く考える内容を、 思考ツリー +
            「Greedy なら何を選ぶか」 比較で見られる。 1 試合 30〜120 秒。
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <OpponentSelect value={opponent} onChange={setOpponent} opponents={opponents} />
            <SeedInput value={seed} onChange={setSeed} />
            <label className="flex items-center gap-1">
              n_simulations
              <input
                type="number"
                min={1}
                max={200}
                value={nSim}
                onChange={(e) => setNSim(Number(e.target.value) || 30)}
                className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={handleStart}
            disabled={!opponent}
            className="rounded bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
          >
            🧠 戦い方の探索を開始 → MCTS ページへ
          </button>
        </div>
      }
    />
  );
}

// ============================================================================ #
// 共通部品
// ============================================================================ #
function Step({
  n,
  title,
  body,
}: {
  n: number;
  title: string;
  body: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs font-bold dark:bg-zinc-800">
          Step {n}
        </span>
        <h3 className="text-sm font-medium">{title}</h3>
      </div>
      <div>{body}</div>
    </div>
  );
}

function OpponentSelect({
  value,
  onChange,
  opponents,
}: {
  value: string;
  onChange: (s: string) => void;
  opponents: DeckSummary[];
}) {
  return (
    <label className="flex items-center gap-1">
      相手
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-zinc-300 bg-transparent px-2 py-0.5 dark:border-zinc-700"
      >
        {opponents.map((o) => (
          <option key={o.slug} value={o.slug}>
            {o.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function SeedInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <label className="flex items-center gap-1">
      seed
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 dark:border-zinc-700"
      />
    </label>
  );
}

function MatchResult({
  selfName,
  result,
  selfSlug,
}: {
  selfName: string;
  result: MatchSummary;
  selfSlug: string;
}) {
  const winrate = result.deck_a_winrate;
  const winrateClass =
    winrate >= 0.55
      ? "text-emerald-600 dark:text-emerald-400"
      : winrate <= 0.45
        ? "text-red-600 dark:text-red-400"
        : "text-zinc-700 dark:text-zinc-300";
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="text-sm text-zinc-500">{selfName} の勝率</span>
        <span className={`font-mono text-3xl font-semibold ${winrateClass}`}>
          {(winrate * 100).toFixed(1)}%
        </span>
        <span className="text-sm text-zinc-500">
          ({result.deck_a_wins}-{result.deck_b_wins}
          {result.draws > 0 && `, ${result.draws} draws`})
        </span>
      </div>
      <div className="text-xs text-zinc-500">
        平均 {result.avg_turns.toFixed(1)} ターン / 勝者残ライフ{" "}
        {result.avg_life_left_winner.toFixed(2)}
      </div>
      <Link
        href={`/decks/${encodeURIComponent(selfSlug)}/match/${encodeURIComponent(result.job_id)}`}
        className="inline-block text-xs text-blue-600 hover:underline dark:text-blue-400"
      >
        📜 試合ログを見る ({result.job_id}) →
      </Link>
    </div>
  );
}
