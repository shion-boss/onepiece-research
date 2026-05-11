"use client";

import { useState } from "react";
import { generateDeckArticle } from "@/lib/api";

type Status = "idle" | "loading" | "done" | "error";

export function ArticleGenerator({ slug }: { slug: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [article, setArticle] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const onGenerate = async () => {
    setStatus("loading");
    setError(null);
    setArticle("");
    try {
      const res = await generateDeckArticle(slug);
      setArticle(res.article);
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
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">デッキ概要記事を生成する</h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            デッキ分析・マッチアップデータを元にデッキ紹介記事を生成します
          </p>
        </div>
        <button
          type="button"
          onClick={onGenerate}
          disabled={status === "loading"}
          className="shrink-0 rounded bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {status === "loading" ? "生成中…" : "記事を生成"}
        </button>
      </div>

      {status === "error" && error && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-200">
          <div className="font-medium">エラー</div>
          <div className="mt-1 font-mono text-xs">{error}</div>
        </div>
      )}

      {status === "loading" && (
        <div className="rounded border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          記事を生成しています…
        </div>
      )}

      {status === "done" && article && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              生成完了 — このままコピーして note に貼り付けられます
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
            rows={30}
            className="w-full resize-y rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
          />
        </div>
      )}
    </section>
  );
}
