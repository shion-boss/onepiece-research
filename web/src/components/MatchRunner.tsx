"use client";

import Link from "next/link";
import { useState } from "react";
import { runMatch } from "@/lib/api";
import type { DeckSummary, MatchSummary } from "@/lib/types";
import { useDeckSimulationStore } from "@/stores/deckSimulation";

type Mode = "explore" | "evaluate";

const MODE_DEFAULT_N: Record<Mode, number> = {
  explore: 10,    // 探索: 軽量、 改善ヒント向け
  evaluate: 50,   // 実践: 検証、 勝率精度向け
};

export function MatchRunner({
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
  const [exploreN, setExploreN] = useState(MODE_DEFAULT_N.explore);
  const [evaluateN, setEvaluateN] = useState(MODE_DEFAULT_N.evaluate);
  const [busy, setBusy] = useState<Mode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchSummary | null>(null);
  const [resultMode, setResultMode] = useState<Mode | null>(null);
  const triggerImprovementsRefresh = useDeckSimulationStore(
    (s) => s.triggerImprovementsRefresh,
  );

  async function runMode(mode: Mode) {
    if (!opponent) return;
    setBusy(mode);
    setError(null);
    setResult(null);
    try {
      const n = mode === "explore" ? exploreN : evaluateN;
      const r = await runMatch({
        deck_a_id: selfSlug,
        deck_b_id: opponent,
        n_games: n,
        seed,
      });
      setResult(r);
      setResultMode(mode);
      // 探索 mode は 改善提案を refresh
      if (mode === "explore") {
        triggerImprovementsRefresh();
      }
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
      <h2 className="text-lg font-medium">対戦シミュレーション</h2>

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
          seed
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value) || 0)}
            className="w-20 rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {/* 探索 ボタン (= 軽量、 改善ヒント向け) */}
        <div className="rounded border border-orange-200 bg-orange-50/50 p-3 dark:border-orange-900 dark:bg-orange-950/20">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium">🔍 探索</div>
              <div className="text-xs text-zinc-500">
                戦い方の模索 + デッキ改善箇所の発見
              </div>
            </div>
            <label className="flex flex-col text-[10px] text-zinc-500">
              試合数
              <input
                type="number"
                min={2}
                max={50}
                step={2}
                value={exploreN}
                onChange={(e) => setExploreN(Number(e.target.value) || 10)}
                className="w-16 rounded border border-zinc-300 bg-transparent px-1 py-0.5 text-sm dark:border-zinc-700"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={() => runMode("explore")}
            disabled={busy != null || !opponent}
            className="w-full rounded bg-orange-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-orange-500 disabled:opacity-50"
          >
            {busy === "explore"
              ? "探索中…"
              : `🔍 探索を実行 (${exploreN} 試合)`}
          </button>
          <div className="mt-1 text-[10px] text-zinc-500">
            完了後、 下の「改善提案」 セクションが自動更新されます
          </div>
        </div>

        {/* 実践 ボタン (= 本番、 勝率検証向け) */}
        <div className="rounded border border-blue-200 bg-blue-50/50 p-3 dark:border-blue-900 dark:bg-blue-950/20">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium">⚔️ 実践</div>
              <div className="text-xs text-zinc-500">
                勝率測定 + 戦い方の詳細分析
              </div>
            </div>
            <label className="flex flex-col text-[10px] text-zinc-500">
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
          </div>
          <button
            type="button"
            onClick={() => runMode("evaluate")}
            disabled={busy != null || !opponent}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50"
          >
            {busy === "evaluate"
              ? "実戦中…"
              : `⚔️ 実践を実行 (${evaluateN} 試合)`}
          </button>
          <div className="mt-1 text-[10px] text-zinc-500">
            完了後、 詳細勝率 + 試合ログへのリンクが表示されます
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
          <div className="text-xs text-zinc-500">
            {resultMode === "explore" ? "🔍 探索結果 (= 改善提案も更新済)" : "⚔️ 実践結果"}
          </div>
          <MatchResult selfName={selfName} result={result} />
          <div className="text-right text-sm">
            <Link
              href={`/decks/${encodeURIComponent(selfSlug)}/match/${encodeURIComponent(result.job_id)}`}
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              📜 試合ログを見る ({result.job_id}) →
            </Link>
          </div>
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
