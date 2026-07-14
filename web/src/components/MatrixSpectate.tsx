"use client";

import { useState } from "react";
import { runMatrixSampleReplay, runMatrixSampleBatch } from "@/lib/api";
import type { ReplayResponse, MatrixBatchResult } from "@/lib/types";
import { SpectateBoard } from "@/components/SpectateBoard";
import { CardImage } from "@/components/CardImage";

/**
 * AI vs AI 観戦パネル。 各サイド (P0/P1) で カテゴリ (環境/マイデッキ) → デッキ を選び、
 * 「観戦開始」= 1 試合をその場で観戦、 「10連戦」= 10 戦して勝率 + 各試合を観戦できる。
 * 各試合は seed で決定的なので、 勝率一覧から任意の試合を replay 再現して観戦する。
 */

type DeckOption = { slug: string; name: string; kind?: string; leader?: string };
type Category = "meta" | "user";

const INPUT =
  "w-full min-w-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-1.5 text-sm text-[color:var(--text-strong)]";

export function MatrixSpectate({
  decks,
  initialDeckA,
  initialDeckB,
  initialSeed,
}: {
  decks: DeckOption[];
  initialDeckA?: string;
  initialDeckB?: string;
  initialSeed?: number;
}) {
  const catOf = (slug: string | undefined): Category =>
    (decks.find((d) => d.slug === slug)?.kind as Category) ?? "meta";
  const inCat = (cat: Category) => decks.filter((d) => (d.kind ?? "meta") === cat);
  const nth = (cat: Category, n: number) =>
    inCat(cat)[n]?.slug ?? inCat(cat)[0]?.slug ?? decks[0]?.slug ?? "";
  const has = (slug: string | undefined) => !!slug && decks.some((d) => d.slug === slug);

  const initCatA: Category = has(initialDeckA) ? catOf(initialDeckA) : "meta";
  const initCatB: Category = has(initialDeckB) ? catOf(initialDeckB) : "meta";

  const [catA, setCatA] = useState<Category>(initCatA);
  const [catB, setCatB] = useState<Category>(initCatB);
  const [deckA, setDeckA] = useState<string>(has(initialDeckA) ? (initialDeckA as string) : nth(initCatA, 0));
  const [deckB, setDeckB] = useState<string>(has(initialDeckB) ? (initialDeckB as string) : nth(initCatB, 1));
  const [seed, setSeed] = useState<number>(initialSeed ?? 42);
  const [running, setRunning] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [batch, setBatch] = useState<MatrixBatchResult | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const optA = decks.find((d) => d.slug === deckA);
  const optB = decks.find((d) => d.slug === deckB);
  const busy = running || batchRunning;

  const changeCatA = (c: Category) => {
    setCatA(c);
    setDeckA(nth(c, 0));
  };
  const changeCatB = (c: Category) => {
    setCatB(c);
    setDeckB(nth(c, 0));
  };

  async function runOne(gseed: number) {
    setError(null);
    setRunning(true);
    const t0 = performance.now();
    try {
      const r = await runMatrixSampleReplay(deckA, deckB, gseed);
      setReplay(r);
      setElapsed((performance.now() - t0) / 1000);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function handleStart() {
    setReplay(null);
    setBatch(null);
    setElapsed(null);
    if (!deckA || !deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    await runOne(seed);
  }

  async function handleBatch() {
    setError(null);
    setReplay(null);
    setBatch(null);
    setElapsed(null);
    if (!deckA || !deckB) {
      setError("両方のデッキを選択してください");
      return;
    }
    // 10連戦は毎回ランダムな基準 seed で (= 新しいサンプル)。 使った seed は欄に表示し再現可能に。
    const base = Math.floor(Math.random() * 1_000_000);
    setSeed(base);
    setBatchRunning(true);
    try {
      const b = await runMatrixSampleBatch(deckA, deckB, base, 10);
      setBatch(b);
    } catch (e) {
      setError(String(e));
    } finally {
      setBatchRunning(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div
        className="shrink-0 rounded-[var(--radius)] border p-3"
        style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SideSelector label="P0" accent="var(--accent)" decks={decks} category={catA} deck={deckA} onCategory={changeCatA} onDeck={setDeckA} disabled={busy} />
          <SideSelector label="P1" accent="var(--danger)" decks={decks} category={catB} deck={deckB} onCategory={changeCatB} onDeck={setDeckB} disabled={busy} />
        </div>

        <div className="mt-3 flex flex-col gap-3">
          {/* 観戦開始 + seed (= この seed で 1 試合を観戦) */}
          <div className="flex flex-wrap items-end gap-2">
            <button
              type="button"
              onClick={handleStart}
              disabled={busy || !deckA || !deckB}
              className="w-44 rounded-[var(--radius)] bg-[color:var(--brand)] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[color:var(--brand-strong)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? "計算中..." : "観戦開始"}
            </button>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[color:var(--text-muted)]">seed（観戦開始で使用）</span>
              <div className="flex gap-1">
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(parseInt(e.target.value || "0", 10))}
                  className="w-28 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-1.5 text-sm text-[color:var(--text-strong)]"
                  disabled={busy}
                />
                <button
                  type="button"
                  onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}
                  className="shrink-0 rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] px-2 text-xs text-[color:var(--text-default)] hover:bg-[color:var(--surface-3)]"
                  disabled={busy}
                  title="ランダム seed"
                >
                  ⟳
                </button>
              </div>
            </label>
          </div>

          {/* 10連戦 (= 毎回ランダム seed で 10 試合。 各試合は seed をずらす) */}
          <button
            type="button"
            onClick={handleBatch}
            disabled={busy || !deckA || !deckB}
            className="w-44 rounded-[var(--radius)] border px-4 py-1.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            style={{ borderColor: "var(--brand)", color: "var(--brand-strong)" }}
          >
            {batchRunning ? "10連戦 計算中..." : "10連戦（勝率）"}
          </button>
        </div>

        {error ? (
          <div className="mt-2 rounded-[var(--radius)] border border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 p-2 text-sm text-[color:var(--danger)]">
            {error}
          </div>
        ) : null}

        {replay ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius)] px-3 py-1.5 text-xs" style={{ background: "var(--surface-2)" }}>
            <span
              className="font-semibold"
              style={{ color: replay.winner === 0 ? "var(--accent)" : replay.winner === 1 ? "var(--danger)" : "var(--text-muted)" }}
            >
              {replay.winner === 0 ? `P0 (${replay.deck_a_name}) 勝利` : replay.winner === 1 ? `P1 (${replay.deck_b_name}) 勝利` : "引き分け / timeout"}
            </span>
            <span className="text-[color:var(--text-muted)]">·</span>
            <span className="text-[color:var(--text-default)]">{replay.turns} ターン / {replay.snapshots.length} snap</span>
            {elapsed !== null ? <span className="ml-auto text-[color:var(--text-muted)]">計算 {elapsed.toFixed(1)}s</span> : null}
          </div>
        ) : null}
      </div>

      {/* 下部 */}
      {replay ? (
        <SpectateBoard
          snapshots={replay.snapshots}
          deckBottomName={replay.deck_a_name}
          deckTopName={replay.deck_b_name}
          winner={replay.winner}
          replayKey={`spectate:${replay.job_id}:${replay.game_index}`}
          onClose={() => setReplay(null)}
          autoPlay
        />
      ) : batch ? (
        <BatchResults batch={batch} loading={running} onSpectate={runOne} />
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-5 rounded-[var(--radius)] p-6" style={{ background: "var(--surface-1)" }}>
          <div className="flex items-center justify-center gap-6">
            <LeaderCard tag="P0" leader={optA?.leader} name={optA?.name} accent="var(--accent)" />
            <span className="text-2xl font-black italic text-[color:var(--text-muted)]">VS</span>
            <LeaderCard tag="P1" leader={optB?.leader} name={optB?.name} accent="var(--danger)" />
          </div>
          {batchRunning ? (
            <div className="flex items-center gap-2 text-sm text-[color:var(--text-muted)]">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--brand)" }} />
              10 連戦を計算中... AI 同士が 10 試合対戦しています（30〜60 秒）
            </div>
          ) : running ? (
            <div className="flex items-center gap-2 text-sm text-[color:var(--text-muted)]">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--brand)" }} />
              シミュレート中... AI 同士が対戦しています（通常 3〜5 秒）
            </div>
          ) : (
            <p className="text-sm text-[color:var(--text-muted)]">
              「観戦開始」= 1 試合を観戦 / 「10連戦（勝率）」= 10 戦して勝率を見て各試合を観戦。
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function BatchResults({
  batch,
  loading,
  onSpectate,
}: {
  batch: MatrixBatchResult;
  loading: boolean;
  onSpectate: (seed: number) => void;
}) {
  const total = batch.n_games || 1;
  const p0pct = Math.round((batch.p0_wins / total) * 100);
  const p1pct = Math.round((batch.p1_wins / total) * 100);
  return (
    <div className="flex flex-1 flex-col gap-3 overflow-auto rounded-[var(--radius)] p-4" style={{ background: "var(--surface-1)" }}>
      {/* 勝率サマリ */}
      <div>
        <div className="flex items-center justify-between text-sm">
          <span className="font-semibold" style={{ color: "var(--accent)" }}>
            P0 {batch.deck_a_name}　{batch.p0_wins}勝
          </span>
          <span className="font-semibold" style={{ color: "var(--danger)" }}>
            {batch.p1_wins}勝　{batch.deck_b_name} P1
          </span>
        </div>
        <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-full" style={{ background: "var(--surface-3)" }}>
          <div style={{ width: `${p0pct}%`, background: "var(--accent)" }} />
          <div style={{ width: `${p1pct}%`, background: "var(--danger)" }} />
        </div>
        <div className="mt-1 text-center text-xs text-[color:var(--text-muted)]">
          全 {total} 戦 · P0 {p0pct}% / P1 {p1pct}% · 引分 {batch.draws}
        </div>
      </div>

      {/* 各試合 (観戦可) */}
      <div className="flex flex-col gap-1">
        <div className="text-[11px] font-medium uppercase tracking-wider text-[color:var(--text-muted)]">各試合（クリックで観戦）</div>
        {batch.games.map((g) => (
          <div
            key={g.game_index}
            className="flex items-center gap-2 rounded-[var(--radius)] border px-2.5 py-1.5 text-sm"
            style={{ borderColor: "var(--border-1)", background: "var(--surface-2)" }}
          >
            <span className="w-12 text-[color:var(--text-muted)]">#{g.game_index + 1}</span>
            <span
              className="flex-1 font-medium"
              style={{ color: g.winner === 0 ? "var(--accent)" : g.winner === 1 ? "var(--danger)" : "var(--text-muted)" }}
            >
              {g.winner === 0 ? "P0 勝利" : g.winner === 1 ? "P1 勝利" : "引分"}
            </span>
            <span className="text-xs text-[color:var(--text-muted)]">{g.turns}ターン</span>
            <button
              type="button"
              onClick={() => onSpectate(g.seed)}
              disabled={loading}
              className="rounded-[var(--radius)] bg-[color:var(--brand)] px-2.5 py-1 text-xs font-medium text-white hover:bg-[color:var(--brand-strong)] disabled:opacity-50"
            >
              観戦
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function SideSelector({
  label,
  accent,
  decks,
  category,
  deck,
  onCategory,
  onDeck,
  disabled,
}: {
  label: string;
  accent: string;
  decks: DeckOption[];
  category: Category;
  deck: string;
  onCategory: (c: Category) => void;
  onDeck: (slug: string) => void;
  disabled: boolean;
}) {
  const filtered = decks.filter((d) => (d.kind ?? "meta") === category);
  const cats: { key: Category; label: string }[] = [
    { key: "meta", label: "環境デッキ" },
    { key: "user", label: "マイデッキ" },
  ];
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold text-white" style={{ background: accent }}>{label}</span>
        <span className="text-xs text-[color:var(--text-muted)]">デッキ</span>
      </div>
      <div className="flex gap-1">
        {cats.map((c) => {
          const active = category === c.key;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => onCategory(c.key)}
              disabled={disabled}
              className="flex-1 rounded-[var(--radius)] border px-2 py-1 text-xs font-medium transition-colors"
              style={active ? { background: "var(--brand)", borderColor: "transparent", color: "#fff" } : { borderColor: "var(--border-2)", color: "var(--text-default)" }}
            >
              {c.label}
            </button>
          );
        })}
      </div>
      <select value={deck} onChange={(e) => onDeck(e.target.value)} className={INPUT} disabled={disabled || filtered.length === 0}>
        {filtered.length === 0 ? (
          <option value="">（このカテゴリにデッキがありません）</option>
        ) : (
          filtered.map((d) => (
            <option key={d.slug} value={d.slug}>
              {d.name}
            </option>
          ))
        )}
      </select>
    </div>
  );
}

function LeaderCard({ tag, leader, name, accent }: { tag: string; leader?: string; name?: string; accent: string }) {
  return (
    <div className="flex w-36 flex-col items-center gap-1.5">
      <span className="rounded px-2 py-0.5 text-[10px] font-bold text-white" style={{ background: accent }}>{tag}</span>
      {leader ? (
        <CardImage cardId={leader} alt={name ?? leader} className="h-40 w-auto rounded-[var(--radius)] border border-[color:var(--border-1)] object-cover" />
      ) : (
        <div className="flex h-40 w-[103px] items-center justify-center rounded-[var(--radius)] border border-dashed text-xs text-[color:var(--text-muted)]" style={{ borderColor: "var(--border-2)" }}>
          未選択
        </div>
      )}
      <span className="max-w-full truncate text-xs text-[color:var(--text-default)]">{name ?? "—"}</span>
    </div>
  );
}
