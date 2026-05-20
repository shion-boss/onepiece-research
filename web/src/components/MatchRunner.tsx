"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { runMatch } from "@/lib/api";
import type { DeckSummary, MatchSummary } from "@/lib/types";
import { useDeckSimulationStore } from "@/stores/deckSimulation";

export function MatchRunner({
  selfSlug,
  selfName,
  opponents,
}: {
  selfSlug: string;
  selfName: string;
  opponents: DeckSummary[];
}) {
  const router = useRouter();
  const [opponent, setOpponent] = useState(opponents[0]?.slug ?? "");
  const [seed, setSeed] = useState(42);
  const [exploreSeeds, setExploreSeeds] = useState(10);     // 並列 seed 数
  const [exploreNGames, setExploreNGames] = useState(10);   // 1 seed あたりの試合数
  const [evaluateN, setEvaluateN] = useState(50);
  const [mctsNSim, setMctsNSim] = useState(30);
  const [busy, setBusy] = useState<"explore" | "evaluate" | null>(null);
  const [exploreProgress, setExploreProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchSummary | null>(null);
  const triggerImprovementsRefresh = useDeckSimulationStore(
    (s) => s.triggerImprovementsRefresh,
  );

  // 戦い方の探索 (= MCTS) は別ページに遷移
  function handleStrategyExplore() {
    if (!opponent) return;
    const url = `/decks/${encodeURIComponent(selfSlug)}/mcts?opp=${encodeURIComponent(opponent)}&seed=${seed}&n_sim=${mctsNSim}`;
    router.push(url);
  }

  // 改善探索 (= 多 seed 並列)
  async function handleImprovementExplore() {
    if (!opponent) return;
    setBusy("explore");
    setError(null);
    setResult(null);
    setExploreProgress({ done: 0, total: exploreSeeds });
    try {
      let done = 0;
      const promises = Array.from({ length: exploreSeeds }, (_, i) => {
        const s = seed + i; // seed, seed+1, ..., seed+9
        return runMatch({
          deck_a_id: selfSlug,
          deck_b_id: opponent,
          n_games: exploreNGames,
          seed: s,
        }).then((r) => {
          done += 1;
          setExploreProgress({ done, total: exploreSeeds });
          return r;
        });
      });
      const results = await Promise.all(promises);
      // 全完了 → 改善提案 refresh + 集計表示
      triggerImprovementsRefresh();
      // 集計: 全 seed の合計勝率
      const totalGames = results.reduce((s, r) => s + r.n_games, 0);
      const totalWins = results.reduce((s, r) => s + r.deck_a_wins, 0);
      const totalLosses = results.reduce((s, r) => s + r.deck_b_wins, 0);
      const totalDraws = results.reduce((s, r) => s + r.draws, 0);
      // 表示用に集計を MatchSummary 形式で組み立て
      setResult({
        job_id: `multi-seed-${seed}`,
        deck_a_name: selfName,
        deck_b_name: results[0]?.deck_b_name ?? opponent,
        deck_a_winrate: totalWins / totalGames,
        deck_a_wins: totalWins,
        deck_b_wins: totalLosses,
        draws: totalDraws,
        n_games: totalGames,
        avg_turns: results.reduce((s, r) => s + r.avg_turns, 0) / results.length,
        median_turns: results.reduce((s, r) => s + r.median_turns, 0) / results.length,
        avg_life_left_winner: results.reduce((s, r) => s + r.avg_life_left_winner, 0) / results.length,
        deck_a_first_wins: results.reduce((s, r) => s + r.deck_a_first_wins, 0),
        deck_a_second_wins: results.reduce((s, r) => s + r.deck_a_second_wins, 0),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setExploreProgress(null);
    }
  }

  // 実践 (= 単一 seed N=50)
  async function handleEvaluate() {
    if (!opponent) return;
    setBusy("evaluate");
    setError(null);
    setResult(null);
    try {
      const r = await runMatch({
        deck_a_id: selfSlug,
        deck_b_id: opponent,
        n_games: evaluateN,
        seed,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (opponents.length === 0) {
    return (
      <div className="rounded border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        対戦相手が他にいません (このデッキしか登録されていない)。
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">対戦シミュレーション</h2>
        <span className="rounded bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300" title="現 default AI: GoalDirectedAI v1 spec + adaptive=True (= 旧 PlanningAI baseline より mirror eval +6pt 改善 確証)">
          AI: GoalDirectedAI v1
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
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

        <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
          seed (= 起点)
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value) || 0)}
            className="w-20 rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {/* 戦い方の探索 (= MCTS) */}
        <div className="rounded border border-purple-200 bg-purple-50/50 p-3 dark:border-purple-900 dark:bg-purple-950/20">
          <div className="mb-2">
            <div className="text-sm font-medium">🧠 戦い方の探索</div>
            <div className="mt-0.5 text-xs text-zinc-500">
              MCTSAI で 1 試合 + 思考ツリー可視化 (= AI が深く考える)
            </div>
          </div>
          <label className="mb-2 flex items-center gap-2 text-[10px] text-zinc-500">
            n_simulations
            <input
              type="number"
              min={1}
              max={200}
              value={mctsNSim}
              onChange={(e) => setMctsNSim(Number(e.target.value) || 30)}
              className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-sm dark:border-zinc-700"
            />
          </label>
          <button
            type="button"
            onClick={handleStrategyExplore}
            disabled={busy != null || !opponent}
            className="w-full rounded bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
          >
            🧠 ツリー可視化ページを開く
          </button>
          <div className="mt-1 text-[10px] text-zinc-500">
            別ページで実行 (1 試合 30〜120 秒)
          </div>
        </div>

        {/* 改善探索 (= 多 seed) */}
        <div className="rounded border border-orange-200 bg-orange-50/50 p-3 dark:border-orange-900 dark:bg-orange-950/20">
          <div className="mb-2">
            <div className="text-sm font-medium">🔍 改善探索</div>
            <div className="mt-0.5 text-xs text-zinc-500">
              多 seed で広範データ収集 → 改善提案を更新
            </div>
          </div>
          <div className="mb-2 flex items-center gap-2 text-[10px] text-zinc-500">
            <label className="flex items-center gap-1">
              seeds
              <input
                type="number"
                min={1}
                max={20}
                value={exploreSeeds}
                onChange={(e) => setExploreSeeds(Number(e.target.value) || 10)}
                className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-sm dark:border-zinc-700"
              />
            </label>
            <span>×</span>
            <label className="flex items-center gap-1">
              N
              <input
                type="number"
                min={2}
                max={50}
                value={exploreNGames}
                onChange={(e) => setExploreNGames(Number(e.target.value) || 10)}
                className="w-12 rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-sm dark:border-zinc-700"
              />
            </label>
            <span className="font-bold">= {exploreSeeds * exploreNGames} 試合</span>
          </div>
          <button
            type="button"
            onClick={handleImprovementExplore}
            disabled={busy != null || !opponent}
            className="w-full rounded bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-500 disabled:opacity-50"
          >
            {busy === "explore"
              ? exploreProgress
                ? `探索中… ${exploreProgress.done}/${exploreProgress.total}`
                : "探索中…"
              : `🔍 改善探索を実行`}
          </button>
          <div className="mt-1 text-[10px] text-zinc-500">
            完了後、 改善提案セクションが自動更新
          </div>
        </div>

        {/* 実践 */}
        <div className="rounded border border-blue-200 bg-blue-50/50 p-3 dark:border-blue-900 dark:bg-blue-950/20">
          <div className="mb-2">
            <div className="text-sm font-medium">⚔️ 実践</div>
            <div className="mt-0.5 text-xs text-zinc-500">
              N 試合で勝率測定 (= 検証、 勝つための戦い方)
            </div>
          </div>
          <label className="mb-2 flex items-center gap-2 text-[10px] text-zinc-500">
            試合数
            <input
              type="number"
              min={10}
              max={500}
              step={10}
              value={evaluateN}
              onChange={(e) => setEvaluateN(Number(e.target.value) || 50)}
              className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-sm dark:border-zinc-700"
            />
          </label>
          <button
            type="button"
            onClick={handleEvaluate}
            disabled={busy != null || !opponent}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {busy === "evaluate"
              ? "実戦中…"
              : `⚔️ 実践を実行 (${evaluateN} 試合)`}
          </button>
          <div className="mt-1 text-[10px] text-zinc-500">
            勝率 + 試合ログへのリンク
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">エラー</div>
          <div className="mt-1 font-mono">{error}</div>
        </div>
      )}

      {result && (
        <>
          <MatchResult selfName={selfName} result={result} />
          {!result.job_id.startsWith("multi-seed-") && (
            <div className="text-right text-sm">
              <Link
                href={`/decks/${encodeURIComponent(selfSlug)}/match/${encodeURIComponent(result.job_id)}`}
                className="text-blue-600 hover:underline dark:text-blue-400"
              >
                📜 試合ログを見る ({result.job_id}) →
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MatchResult({
  selfName,
  result,
}: {
  selfName: string;
  result: MatchSummary;
}) {
  const winrate = result.deck_a_winrate;
  const winrateClass =
    winrate >= 0.55
      ? "text-emerald-600 dark:text-emerald-400"
      : winrate <= 0.45
        ? "text-red-600 dark:text-red-400"
        : "text-zinc-700 dark:text-zinc-300";

  const halfGames = Math.max(1, Math.floor(result.n_games / 2));
  const firstWinrate = result.deck_a_first_wins / halfGames;
  const secondWinrate = result.deck_a_second_wins / halfGames;

  return (
    <div className="space-y-3 rounded border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex items-baseline gap-2">
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          {selfName} の勝率
        </span>
        <span className={`font-mono text-3xl font-semibold ${winrateClass}`}>
          {(winrate * 100).toFixed(1)}%
        </span>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          ({result.deck_a_wins}-{result.deck_b_wins}
          {result.draws > 0 && `, ${result.draws} draws`})
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <Stat
          label="先攻時"
          value={`${(firstWinrate * 100).toFixed(0)}%`}
          sub={`${result.deck_a_first_wins}/${halfGames}`}
        />
        <Stat
          label="後攻時"
          value={`${(secondWinrate * 100).toFixed(0)}%`}
          sub={`${result.deck_a_second_wins}/${halfGames}`}
        />
        <Stat
          label="平均ターン"
          value={result.avg_turns.toFixed(1)}
          sub={`med ${result.median_turns.toFixed(1)}`}
        />
        <Stat
          label="勝者残ライフ"
          value={result.avg_life_left_winner.toFixed(2)}
        />
        <Stat label="試合数" value={String(result.n_games)} />
      </dl>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
      <dd className="font-mono text-base">
        {value}
        {sub && (
          <span className="ml-1 text-xs text-zinc-500 dark:text-zinc-400">
            {sub}
          </span>
        )}
      </dd>
    </div>
  );
}
