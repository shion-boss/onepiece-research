"use client";

import { useEffect, useState } from "react";
import { fetchDecks, generateBattleReport } from "@/lib/api";
import type { DeckSummary } from "@/lib/types";

type Status = "idle" | "loading" | "done" | "error";

export function VsArticleGenerator({ slug }: { slug: string }) {
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [opponentSlug, setOpponentSlug] = useState("");
  const [nGames, setNGames] = useState(10);
  const [status, setStatus] = useState<Status>("idle");
  const [article, setArticle] = useState("");
  const [meta, setMeta] = useState<{ wins: number; losses: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetchDecks()
      .then((list) => {
        const others = list.filter((d) => d.slug !== slug);
        setDecks(others);
        if (others.length > 0) setOpponentSlug(others[0].slug);
      })
      .catch(() => {});
  }, [slug]);

  const estSeconds = nGames * 3;

  const onRun = async () => {
    if (!opponentSlug) return;
    setStatus("loading");
    setError(null);
    setArticle("");
    setMeta(null);
    try {
      const res = await generateBattleReport(slug, opponentSlug, nGames);
      setArticle(res.article);
      setMeta({ wins: res.n_wins, losses: res.n_losses, total: res.n_games });
      setStatus("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  };

  const onCopy = async () => {
    await navigator.clipboard.writeText(article);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">vs 相手 攻略記事を生成する</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          相手デッキを固定してシミュレーション。勝ち/負け試合の行動差分から攻略ポイントを抽出します
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            対戦相手（固定）
          </label>
          <select
            value={opponentSlug}
            onChange={(e) => setOpponentSlug(e.target.value)}
            disabled={status === "loading"}
            className="rounded border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 disabled:opacity-50"
          >
            {decks.map((d) => (
              <option key={d.slug} value={d.slug}>
                {d.name} ({d.leader_color.join("・")})
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
            試合数: {nGames}戦（推定{estSeconds}秒）
          </label>
          <input
            type="range"
            min={5}
            max={20}
            step={1}
            value={nGames}
            onChange={(e) => setNGames(Number(e.target.value))}
            disabled={status === "loading"}
            className="w-40 accent-zinc-700 dark:accent-zinc-300 disabled:opacity-50"
          />
          <div className="flex justify-between text-[10px] text-zinc-400">
            <span>5戦</span>
            <span>20戦（精度高）</span>
          </div>
        </div>

        <button
          type="button"
          onClick={onRun}
          disabled={status === "loading" || !opponentSlug}
          className="shrink-0 rounded bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {status === "loading" ? "分析中…" : "攻略記事を生成"}
        </button>
      </div>

      {status === "loading" && (
        <div className="rounded border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          <div className="mb-1 font-medium">
            GreedyAI が {nGames} 戦シミュレーション中…
          </div>
          <div className="text-xs">
            相手デッキを固定して勝ち/負け両方のログを収集し、行動差分を分析します。
            推定{estSeconds}秒かかります。
          </div>
        </div>
      )}

      {status === "error" && error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">エラー</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      )}

      {status === "done" && article && meta && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              完了 — {meta.total}戦 {meta.wins}勝 / {meta.losses}敗
            </span>
            <button
              type="button"
              onClick={onCopy}
              className="rounded border border-zinc-300 px-3 py-1 text-sm transition hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              {copied ? "コピーしました" : "全文コピー"}
            </button>
          </div>
          <textarea
            readOnly
            value={article}
            rows={35}
            className="w-full resize-y rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
          />
        </div>
      )}
    </section>
  );
}
