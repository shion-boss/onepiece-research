"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { LeaderPicker } from "@/components/builder/LeaderPicker";
import { CardSearchPane } from "@/components/builder/CardSearchPane";
import { CardImage } from "@/components/CardImage";
import {
  fetchDecks,
  generateDeck,
  saveDeckToServer,
  type GenerateDeckResponse,
  type GeneratedDeckOut,
} from "@/lib/api";
import type { Card, DeckSummary } from "@/lib/types";

type Mode = "combo" | "target" | "meta";

const MODE_LABEL: Record<Mode, string> = {
  combo: "コンボ重視",
  target: "特定デッキに勝つ",
  meta: "環境に対応",
};

export default function GenerateDeckPage() {
  const [leader, setLeader] = useState<Card | null>(null);
  const [mustInclude, setMustInclude] = useState<Card[]>([]);
  const [mode, setMode] = useState<Mode>("combo");
  const [targetSlug, setTargetSlug] = useState("");
  const [hillClimb, setHillClimb] = useState(false);
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [result, setResult] = useState<GenerateDeckResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Record<number, string>>({});

  useEffect(() => {
    fetchDecks().then(setDecks).catch(() => {});
  }, []);

  const addCard = (c: Card) =>
    setMustInclude((prev) =>
      prev.some((x) => x.card_id === c.card_id) || prev.length >= 5
        ? prev
        : [...prev, c],
    );
  const removeCard = (cid: string) =>
    setMustInclude((prev) => prev.filter((x) => x.card_id !== cid));

  const canGenerate =
    !!leader && !loading && (mode !== "target" || !!targetSlug);

  const onGenerate = async () => {
    if (!leader) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setSaved({});
    try {
      const r = await generateDeck({
        leader: leader.card_id,
        must_include: mustInclude.map((c) => c.card_id),
        mode,
        target_slug: mode === "target" ? targetSlug : null,
        n_candidates: mode === "combo" ? 12 : 6,
        n_sim_eval: 4,
        n_games: 12,
        meta_sample: 4,
        hill_climb_iters: hillClimb ? 10 : 0,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const onSave = async (cand: GeneratedDeckOut, i: number) => {
    if (!leader) return;
    try {
      const res = await saveDeckToServer({
        name: `生成 ${leader.name} #${i + 1}`,
        leader: leader.card_id,
        main: cand.main,
      });
      setSaved((prev) => ({ ...prev, [i]: res.slug }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
      <header className="space-y-1">
        <Link
          href="/decks"
          className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
        >
          ← デッキ一覧
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">デッキ自動生成</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          リーダーと使いたいカード（最大5枚）を指定すると、コンボの相棒を引き込み、
          コンボ強度と対戦勝率でランクした候補を作ります。
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-4">
          <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="mb-2 text-sm font-semibold">1. リーダー</h2>
            <LeaderPicker current={leader} onPick={setLeader} />
          </section>

          {leader && (
            <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
              <h2 className="mb-2 text-sm font-semibold">
                2. 使いたいカード（{mustInclude.length}/5）
              </h2>
              <CardSearchPane
                leaderColors={leader.color}
                onAdd={addCard}
                countOf={(cid) =>
                  mustInclude.some((x) => x.card_id === cid) ? 1 : 0
                }
              />
            </section>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="mb-2 text-sm font-semibold">使いたいカード</h2>
            {mustInclude.length === 0 ? (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                未指定（コンボ相棒は自動で集めます）
              </p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {mustInclude.map((c) => (
                  <li key={c.card_id} className="w-14">
                    <button
                      type="button"
                      onClick={() => removeCard(c.card_id)}
                      title={`${c.name} を外す`}
                      className="block w-full"
                    >
                      <CardImage
                        cardId={c.card_id}
                        alt={c.name}
                        className="w-full rounded ring-1 ring-emerald-400/60"
                      />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h2 className="mb-2 text-sm font-semibold">3. 方針</h2>
            <div className="flex flex-col gap-1.5">
              {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
                <label key={m} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="mode"
                    checked={mode === m}
                    onChange={() => setMode(m)}
                  />
                  {MODE_LABEL[m]}
                </label>
              ))}
            </div>
            {mode === "target" && (
              <select
                value={targetSlug}
                onChange={(e) => setTargetSlug(e.target.value)}
                className="mt-3 w-full rounded border border-zinc-300 bg-white p-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="">勝ちたい相手デッキを選択…</option>
                {decks.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.name}
                  </option>
                ))}
              </select>
            )}
            {mode !== "combo" && (
              <label className="mt-3 flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
                <input
                  type="checkbox"
                  checked={hillClimb}
                  onChange={(e) => setHillClimb(e.target.checked)}
                />
                局所探索で磨く（遅くなります）
              </label>
            )}
            <button
              type="button"
              onClick={onGenerate}
              disabled={!canGenerate}
              className="mt-3 w-full rounded bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "生成中…（対戦シミュレーション）" : "デッキを生成"}
            </button>
            {mode !== "combo" && (
              <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                {mode === "target" ? "相手" : "環境"}との対戦で勝率を測るため数十秒かかります。
              </p>
            )}
          </section>
        </aside>
      </div>

      {error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <span className="font-mono">{error}</span>
        </div>
      )}

      {result && (
        <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="mb-1 text-lg font-semibold">生成結果</h2>
          <p className="mb-3 text-sm text-zinc-500 dark:text-zinc-400">
            {result.leader_name} ・ {MODE_LABEL[result.mode as Mode] ?? result.mode}
            {result.opponents.length > 0 &&
              ` ・ 対戦相手: ${result.opponents.join(", ")}`}
          </p>
          <ul className="space-y-2">
            {result.candidates.map((c, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-3 rounded-md border border-zinc-100 p-3 dark:border-zinc-800/60"
              >
                <span className="rounded bg-zinc-100 px-2 py-1 text-xs font-semibold dark:bg-zinc-800">
                  #{i + 1}
                </span>
                {c.win_rate != null && (
                  <span className="text-sm">
                    勝率{" "}
                    <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                      {Math.round(c.win_rate * 100)}%
                    </span>
                  </span>
                )}
                <span className="text-sm text-zinc-600 dark:text-zinc-300">
                  コンボ強度{" "}
                  <span className="font-medium">{c.combo_strength.toFixed(0)}</span>
                </span>
                <span className="text-xs text-zinc-400">score {c.score.toFixed(1)}</span>
                {c.extras.length > 0 && (
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    引込: {c.extras.map((e) => e.name).slice(0, 4).join("・")}
                  </span>
                )}
                <span className="ml-auto flex items-center gap-2">
                  {saved[i] ? (
                    <Link
                      href={`/decks/${encodeURIComponent(saved[i])}`}
                      className="rounded border border-emerald-400 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950"
                    >
                      保存済 → 開く
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onSave(c, i)}
                      className="rounded bg-zinc-800 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-700 dark:bg-zinc-200 dark:text-zinc-900 dark:hover:bg-white"
                    >
                      保存
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {result.warnings.length > 0 && (
            <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">
              {result.warnings.join(" / ")}
            </p>
          )}
        </section>
      )}
    </main>
  );
}
