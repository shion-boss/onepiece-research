"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useDeckBuilderStore } from "@/stores/deckBuilder";
import { LeaderPicker } from "@/components/builder/LeaderPicker";
import { CardSearchPane } from "@/components/builder/CardSearchPane";
import { BuilderSidebar } from "@/components/builder/BuilderSidebar";
import { CostCurveMini } from "@/components/builder/CostCurveMini";
import {
  buildDeckWithCore,
  fetchCard,
  fetchDeck,
  saveDeckToServer,
} from "@/lib/api";

export default function NewDeckPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-zinc-500">読み込み中…</div>}>
      <NewDeckPageContent />
    </Suspense>
  );
}

function NewDeckPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const fromSlug = params.get("from");

  const {
    leader,
    entries,
    name,
    regulation,
    setName,
    setLeader,
    setRegulation,
    addCard,
    increment,
    decrement,
    removeCard,
    reset,
    saveToLocalStorage,
    countByBaseId,
  } = useDeckBuilderStore();

  const [flash, setFlash] = useState<string | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [coreInput, setCoreInput] = useState("");
  const [autoBuilding, setAutoBuilding] = useState(false);
  const [saving, setSaving] = useState(false);
  const hydratedSlugRef = useRef<string | null>(null);

  // ?from=<slug> でデッキ初期化 (1度だけ)
  useEffect(() => {
    if (!fromSlug) return;
    if (hydratedSlugRef.current === fromSlug) return;
    hydratedSlugRef.current = fromSlug;

    let cancelled = false;
    (async () => {
      setHydrating(true);
      try {
        const detail = await fetchDeck(fromSlug);
        const leaderCard = await fetchCard(detail.leader);
        const cardMap = new Map<string, Awaited<ReturnType<typeof fetchCard>>>();
        for (const e of detail.main) {
          if (cardMap.has(e.card_id)) continue;
          try {
            cardMap.set(e.card_id, await fetchCard(e.card_id));
          } catch {
            // 個別失敗はスキップ
          }
        }
        if (cancelled) return;
        // store を初期化
        reset();
        setLeader(leaderCard);
        setName(detail.name ?? `${fromSlug} のコピー`);
        for (const e of detail.main) {
          const card = cardMap.get(e.card_id);
          if (!card) continue;
          for (let i = 0; i < e.count; i++) {
            addCard(card);
          }
        }
        setFlash(`${detail.name ?? fromSlug} をロードしました (${detail.main.reduce((s, x) => s + x.count, 0)} 枚)`);
        setTimeout(() => setFlash(null), 3000);
      } catch (e) {
        setFlash(`ロード失敗: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        if (!cancelled) setHydrating(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromSlug]);

  const total = entries.reduce((s, e) => s + e.count, 0);
  const valid = total === 50 && leader !== null;

  const coreCardIds = new Set(
    coreInput.split(/[\s,、]+/).map((s) => s.trim()).filter(Boolean),
  );

  const onToggleCore = (card: { card_id: string }) => {
    const id = card.card_id;
    setCoreInput((prev) => {
      const ids = prev.split(/[\s,、]+/).map((s) => s.trim()).filter(Boolean);
      if (ids.includes(id)) return ids.filter((x) => x !== id).join(" ");
      return prev.trim() ? `${prev.trim()} ${id}` : id;
    });
  };

  const showFlash = (msg: string, ttlMs = 2000) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), ttlMs);
  };

  const onAutoBuild = async () => {
    if (!leader) {
      showFlash("先にリーダーを選んでください");
      return;
    }
    const cores = coreInput
      .split(/[\s,、]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    setAutoBuilding(true);
    try {
      const result = await buildDeckWithCore({
        leader: leader.card_id,
        core_cards: cores,
        name: name || undefined,
      });
      // 結果を store に流し込む (既存 main をリセット)
      const cardMap = new Map<string, Awaited<ReturnType<typeof fetchCard>>>();
      for (const e of result.main) {
        if (cardMap.has(e.card_id)) continue;
        try {
          cardMap.set(e.card_id, await fetchCard(e.card_id));
        } catch {
          // 失敗はスキップ
        }
      }
      // 全カード削除して再構築
      reset();
      setLeader(leader);
      setName(result.name);
      for (const e of result.main) {
        const card = cardMap.get(e.card_id);
        if (!card) continue;
        for (let i = 0; i < e.count; i++) addCard(card);
      }
      const wstr = result.warnings.length > 0
        ? ` (warnings: ${result.warnings.length})`
        : "";
      showFlash(
        `自動構築完了: ${result.main.reduce((s, e) => s + e.count, 0)} 枚 / effect ${result.effect_density} / counter ${result.counter_total}${wstr}`,
        4000,
      );
    } catch (e) {
      showFlash(`自動構築失敗: ${e instanceof Error ? e.message : String(e)}`, 4000);
    } finally {
      setAutoBuilding(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/decks"
            className="text-sm text-zinc-500 hover:underline dark:text-zinc-400"
          >
            ← /decks
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">
            /decks/new
            {hydrating && (
              <span className="ml-2 text-xs text-zinc-500">ロード中…</span>
            )}
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded border border-zinc-300 text-sm dark:border-zinc-700 overflow-hidden">
            <button
              type="button"
              onClick={() => setRegulation("standard")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "standard"
                  ? "bg-blue-600 text-white"
                  : "bg-transparent text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              STD
            </button>
            <button
              type="button"
              onClick={() => setRegulation("extra")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "extra"
                  ? "bg-purple-600 text-white"
                  : "bg-transparent text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }`}
            >
              EX
            </button>
          </div>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="デッキ名"
            className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          />
          <span
            className={`rounded px-2 py-1 font-mono text-sm ${
              valid
                ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100"
                : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
            }`}
          >
            {total}/50
          </span>
          <button
            type="button"
            onClick={() => {
              saveToLocalStorage();
              showFlash("localStorage に保存しました");
            }}
            disabled={!leader}
            className="rounded border border-zinc-400 px-3 py-1.5 text-sm font-medium transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
            title="ブラウザの localStorage に下書き保存"
          >
            💾 下書き
          </button>
          <button
            type="button"
            onClick={async () => {
              if (!leader || !valid) {
                showFlash(
                  !leader
                    ? "リーダーを選んでください"
                    : `合計 ${total}/50 枚にしてから保存`,
                  3000,
                );
                return;
              }
              setSaving(true);
              try {
                const deckName =
                  name && name.trim()
                    ? name.trim()
                    : `${leader.name} 自作`;
                const res = await saveDeckToServer({
                  name: deckName,
                  leader: leader.card_id,
                  main: entries.map((e) => ({
                    card_id: e.card.card_id,
                    count: e.count,
                  })),
                  regulation,
                });
                showFlash(
                  `サーバ保存しました (slug: ${res.slug}) → デッキ詳細へ移動`,
                  3000,
                );
                setTimeout(() => router.push(`/decks/${res.slug}`), 600);
              } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                showFlash(`サーバ保存失敗: ${msg}`, 5000);
              } finally {
                setSaving(false);
              }
            }}
            disabled={!leader || !valid || saving}
            className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:opacity-50"
            title="API 経由で decks/<slug>.json に保存"
          >
            {saving ? "保存中…" : "☁️ サーバ保存"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm("リセットしますか?")) reset();
            }}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm transition hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            リセット
          </button>
        </div>
      </header>

      {flash && (
        <div className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
          {flash}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        {/* 左: リーダー + デッキ */}
        <aside className="space-y-4">
          <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <h2 className="text-sm font-medium">リーダー</h2>
            <LeaderPicker current={leader} onPick={setLeader} />
          </section>

          {leader && (
            <>
              <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <h2 className="text-sm font-medium">自動構築 (コアカード固定)</h2>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  使いたい card_id を改行/スペース/カンマ区切りで入力 (例: <code>OP15-077 OP15-076</code>)。
                  リーダー色合致 + effect 濃度高めの 50 枚を自動生成。
                </p>
                <textarea
                  value={coreInput}
                  onChange={(e) => setCoreInput(e.target.value)}
                  rows={3}
                  placeholder="OP15-077 OP15-076 OP15-075"
                  className="w-full resize-y rounded border border-zinc-300 bg-transparent px-2 py-1 font-mono text-xs dark:border-zinc-700"
                />
                <button
                  type="button"
                  onClick={onAutoBuild}
                  disabled={autoBuilding}
                  className="w-full rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
                >
                  {autoBuilding ? "構築中…" : "🤖 自動構築"}
                </button>
              </section>

              <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <h2 className="text-sm font-medium">コストカーブ</h2>
                <CostCurveMini entries={entries} />
              </section>

              <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <h2 className="text-sm font-medium">デッキ ({total} 枚)</h2>
                <BuilderSidebar
                  entries={entries}
                  onIncrement={(cid) => {
                    const err = increment(cid);
                    if (err) showFlash(err);
                  }}
                  onDecrement={decrement}
                  onRemove={removeCard}
                />
              </section>
            </>
          )}
        </aside>

        {/* 右: カード検索 */}
        <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <h2 className="text-sm font-medium">カード検索</h2>
          <CardSearchPane
            leaderColors={leader?.color ?? []}
            onAdd={(c) => {
              const err = addCard(c);
              if (err) showFlash(err);
            }}
            countOf={(cid) => countByBaseId(cid)}
            onMarkCore={onToggleCore}
            coreCardIds={coreCardIds}
          />
        </section>
      </div>
    </main>
  );
}
