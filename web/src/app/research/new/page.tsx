"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { fetchDecks, startResearchSession } from "@/lib/api";
import type { DeckSummary } from "@/lib/types";
import { QuickResearchPanel } from "@/components/explore/QuickResearchPanel";

type Mode = "quick" | "evolutionary";

export default function NewResearchPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">読み込み中…</div>}>
      <NewResearchPageContent />
    </Suspense>
  );
}

function NewResearchPageContent() {
  const params = useSearchParams();
  const initialTarget = params.get("target") ?? "";
  const initialMode: Mode = params.get("mode") === "evolutionary" ? "evolutionary" : "quick";
  const [mode, setMode] = useState<Mode>(initialMode);

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-6 py-8">
      <header>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">対策デッキ研究</h1>
          <Link href="/research" className="text-sm text-blue-600 hover:underline dark:text-blue-400">
            ← セッション一覧
          </Link>
        </div>
        <p className="mt-1 text-sm text-zinc-500">
          メタデッキに対する 対策デッキ を 探索する。 短時間 (= クイック) と
          長時間 (= 進化的) の 2 モード。
        </p>
      </header>

      <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
        <TabButton active={mode === "quick"} onClick={() => setMode("quick")}>
          🔍 クイック
          <span className="ml-1 text-xs text-zinc-500">(数分)</span>
        </TabButton>
        <TabButton active={mode === "evolutionary"} onClick={() => setMode("evolutionary")}>
          🧬 進化的
          <span className="ml-1 text-xs text-zinc-500">(数時間)</span>
        </TabButton>
      </div>

      {mode === "quick" ? (
        <QuickResearchPanel initialTargetSlug={initialTarget || undefined} />
      ) : (
        <EvolutionaryForm initialTarget={initialTarget} />
      )}
    </main>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px border-b-2 px-3 py-1.5 text-sm transition ${
        active
          ? "border-blue-600 font-medium text-zinc-900 dark:border-blue-400 dark:text-zinc-100"
          : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}

function EvolutionaryForm({ initialTarget }: { initialTarget: string }) {
  const router = useRouter();
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [target, setTarget] = useState(initialTarget);
  const [targetWinrate, setTargetWinrate] = useState(0.7);
  const [maxGenerations, setMaxGenerations] = useState(20);
  const [nGames, setNGames] = useState(50);
  const [initialPop, setInitialPop] = useState(20);
  const [topK, setTopK] = useState(5);
  const [mutationsPerTop, setMutationsPerTop] = useState(3);
  const [seed, setSeed] = useState(42);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDecks().then((d) => {
      setDecks(d);
      if (!target && d.length > 0) setTarget(d[0].slug);
    });
  }, [target]);

  async function handleStart() {
    if (!target) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await startResearchSession({
        target_slug: target,
        target_winrate: targetWinrate,
        max_generations: maxGenerations,
        n_games_per_eval: nGames,
        initial_population: initialPop,
        top_k: topK,
        mutations_per_top: mutationsPerTop,
        seed,
      });
      router.push(`/research/${encodeURIComponent(res.session_id)}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  // 推定時間: max_gen * (init_pop or top_k * mut_per_top) * n_games * ~0.5sec
  const estPerGen = (initialPop > topK * mutationsPerTop ? initialPop : topK * mutationsPerTop);
  const estSeconds = maxGenerations * estPerGen * nGames * 0.5;
  const estMinutes = Math.round(estSeconds / 60);

  return (
    <section className="mx-auto max-w-2xl space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <p className="text-sm text-zinc-500">
        対象デッキ + 制約 + パラメータを設定して研究開始。 backend が世代交代で
        自動探索 → 完了後に最強対策デッキを取得。
      </p>

      <div>
        <label className="block text-sm font-medium">対象デッキ (= 対策対象)</label>
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
        >
          {decks.map((d) => (
            <option key={d.slug} value={d.slug}>
              {d.name} ({d.slug})
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-zinc-500">目標勝率 (0-1)</label>
          <input
            type="number"
            min={0.5}
            max={1}
            step={0.05}
            value={targetWinrate}
            onChange={(e) => setTargetWinrate(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
          <div className="mt-0.5 text-[10px] text-zinc-500">
            到達したら自動停止
          </div>
        </div>
        <div>
          <label className="block text-xs text-zinc-500">最大世代数</label>
          <input
            type="number"
            min={1}
            max={100}
            value={maxGenerations}
            onChange={(e) => setMaxGenerations(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">1 候補あたり試合数</label>
          <input
            type="number"
            min={5}
            max={200}
            step={5}
            value={nGames}
            onChange={(e) => setNGames(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">初期母集団</label>
          <input
            type="number"
            min={5}
            max={50}
            value={initialPop}
            onChange={(e) => setInitialPop(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">top_k (= 残す)</label>
          <input
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">top1 件あたり変異数</label>
          <input
            type="number"
            min={1}
            max={10}
            value={mutationsPerTop}
            onChange={(e) => setMutationsPerTop(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
        <div>
          <label className="block text-xs text-zinc-500">seed</label>
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
            className="mt-1 w-full rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
        </div>
      </div>

      <div className="rounded bg-zinc-50 p-2 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
        <strong>推定時間</strong>: 最大 約 {estMinutes} 分 (= {maxGenerations} 世代 ×{" "}
        {estPerGen} 候補 × {nGames} 試合 × ~0.5秒)。
        <br />
        目標勝率到達で早期完了する可能性あり。 途中停止 / 再開 / ベスト取得 可能。
      </div>

      {error && (
        <div className="rounded bg-red-50 p-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={handleStart}
        disabled={submitting || !target}
        className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
      >
        {submitting ? "起動中…" : "🔬 研究セッションを開始"}
      </button>
    </section>
  );
}
