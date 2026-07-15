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
    <Suspense fallback={<div className="p-6 text-sm text-[color:var(--text-muted)]">読み込み中…</div>}>
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
  // 非公開 (= 陣取りで使用不可)。 生成時にのみ決定・以後不変なので保存時に一度だけ送る。
  const [isPrivate, setIsPrivate] = useState(false);
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
            className="inline-flex items-center gap-1 text-sm text-[color:var(--text-muted)] hover:underline"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M15 18l-6-6 6-6" />
            </svg>
            マイデッキ
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight text-[color:var(--text-strong)]">
            デッキを作る
            {hydrating && (
              <span className="ml-2 text-xs text-[color:var(--text-muted)]">ロード中…</span>
            )}
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-[var(--radius-sm)] border border-[color:var(--border-2)] text-sm overflow-hidden">
            <button
              type="button"
              onClick={() => setRegulation("standard")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "standard"
                  ? "bg-[color:var(--brand)] text-white"
                  : "bg-transparent text-[color:var(--text-muted)] hover:bg-[var(--list-hover)]"
              }`}
            >
              STD
            </button>
            <button
              type="button"
              onClick={() => setRegulation("extra")}
              className={`px-3 py-1 font-medium transition ${
                regulation === "extra"
                  ? "bg-[color:var(--brand)] text-white"
                  : "bg-transparent text-[color:var(--text-muted)] hover:bg-[var(--list-hover)]"
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
            className="rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 text-sm text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
          />
          <span
            className={`rounded-[var(--radius-sm)] px-2 py-1 font-mono text-sm ${
              valid
                ? "bg-[color:var(--accent)]/15 text-[color:var(--accent)]"
                : "bg-[color:var(--surface-2)] text-[color:var(--text-default)]"
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
            className="inline-flex items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm font-medium text-[color:var(--text-default)] transition hover:bg-[var(--list-hover)] disabled:opacity-50"
            title="ブラウザの localStorage に下書き保存"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
              <path d="M17 21v-8H7v8M7 3v5h7" />
            </svg>
            下書き
          </button>
          <label
            className="flex cursor-pointer items-center gap-1.5 rounded-[var(--radius)] border border-[color:var(--border-2)] px-2.5 py-1.5 text-sm text-[color:var(--text-default)] transition hover:bg-[var(--list-hover)]"
            title="非公開デッキは陣取りの防衛に使われません（相手に露出しない）。作成後は変更できません。"
          >
            <input
              type="checkbox"
              checked={isPrivate}
              onChange={(e) => setIsPrivate(e.target.checked)}
              className="accent-[color:var(--brand)]"
            />
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <rect x="3" y="11" width="18" height="11" rx="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            非公開
          </label>
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
                  private: isPrivate,
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
            className="rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
            title="API 経由で decks/<slug>.json に保存"
          >
            {saving ? "保存中…" : "サーバ保存"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm("リセットしますか?")) reset();
            }}
            className="rounded-[var(--radius)] border border-[color:var(--border-2)] px-3 py-1.5 text-sm text-[color:var(--text-default)] transition hover:bg-[var(--list-hover)]"
          >
            リセット
          </button>
        </div>
      </header>

      {flash && (
        <div className="rounded-[var(--radius)] border border-[color:var(--accent)]/40 bg-[color:var(--accent)]/10 px-3 py-2 text-sm text-[color:var(--accent)]">
          {flash}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        {/* 左: リーダー + デッキ */}
        <aside className="space-y-4">
          <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
            <h2 className="text-sm font-medium text-[color:var(--text-strong)]">リーダー</h2>
            <LeaderPicker current={leader} onPick={setLeader} />
          </section>

          {leader && (
            <>
              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">自動構築 (コアカード固定)</h2>
                <p className="text-xs text-[color:var(--text-muted)]">
                  使いたい card_id を改行/スペース/カンマ区切りで入力 (例: <code>OP15-077 OP15-076</code>)。
                  リーダー色合致 + effect 濃度高めの 50 枚を自動生成。
                </p>
                <textarea
                  value={coreInput}
                  onChange={(e) => setCoreInput(e.target.value)}
                  rows={3}
                  placeholder="OP15-077 OP15-076 OP15-075"
                  className="w-full resize-y rounded-[var(--radius-sm)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 py-1 font-mono text-xs text-[color:var(--text-default)] outline-none placeholder:text-[color:var(--text-muted)] focus:border-[color:var(--brand)]"
                />
                <button
                  type="button"
                  onClick={onAutoBuild}
                  disabled={autoBuilding}
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-[var(--radius)] bg-[color:var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
                >
                  {autoBuilding ? (
                    "構築中…"
                  ) : (
                    <>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <path d="M12 2l1.9 6.4L20 10l-6.1 1.6L12 18l-1.9-6.4L4 10l6.1-1.6z" />
                        <path d="M18.5 13l.9 2.9L22 16.5l-2.6.6L18.5 20l-.9-2.9L15 16.5l2.6-.6z" />
                      </svg>
                      自動構築
                    </>
                  )}
                </button>
              </section>

              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">コストカーブ</h2>
                <CostCurveMini entries={entries} />
              </section>

              <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
                <h2 className="text-sm font-medium text-[color:var(--text-strong)]">デッキ ({total} 枚)</h2>
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
        <section className="space-y-2 rounded-[var(--radius-lg)] border border-[color:var(--border-1)] bg-[color:var(--surface-1)] p-3">
          <h2 className="text-sm font-medium text-[color:var(--text-strong)]">カード検索</h2>
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
