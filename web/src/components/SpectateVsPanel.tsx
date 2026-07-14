"use client";

import { useState, type ReactNode } from "react";
import { CardImage } from "@/components/CardImage";

// AI vs AI の共通デッキ選択 UI (人間vsAI の StartPanel と同じ VS パネル調)。
export type SpectateDeck = { slug: string; name: string; kind?: string; leader?: string };
export type Category = "meta" | "user";

// P0/P1 の カテゴリ + デッキ 選択状態 (観戦 / 10連戦 で共通)。
export function useDeckSelect(decks: SpectateDeck[], initialDeckA?: string, initialDeckB?: string) {
  const inCat = (cat: Category) => decks.filter((d) => (d.kind ?? "meta") === cat);
  const nth = (cat: Category, n: number) => inCat(cat)[n]?.slug ?? inCat(cat)[0]?.slug ?? decks[0]?.slug ?? "";
  const has = (slug: string | undefined) => !!slug && decks.some((d) => d.slug === slug);
  const catOf = (slug: string | undefined): Category => (decks.find((d) => d.slug === slug)?.kind as Category) ?? "meta";

  const initCatA: Category = has(initialDeckA) ? catOf(initialDeckA) : "meta";
  const initCatB: Category = has(initialDeckB) ? catOf(initialDeckB) : "meta";
  const [catA, setCatA] = useState<Category>(initCatA);
  const [catB, setCatB] = useState<Category>(initCatB);
  const [deckA, setDeckA] = useState<string>(has(initialDeckA) ? (initialDeckA as string) : nth(initCatA, 0));
  const [deckB, setDeckB] = useState<string>(has(initialDeckB) ? (initialDeckB as string) : nth(initCatB, 1));

  const changeCatA = (c: Category) => {
    setCatA(c);
    setDeckA(nth(c, 0));
  };
  const changeCatB = (c: Category) => {
    setCatB(c);
    setDeckB(nth(c, 0));
  };
  return { catA, catB, deckA, deckB, setDeckA, setDeckB, changeCatA, changeCatB };
}

export function SpectateVsPanel({
  title,
  subtitle,
  decks,
  catA,
  catB,
  deckA,
  deckB,
  onCatA,
  onCatB,
  onDeckA,
  onDeckB,
  disabled,
  footer,
}: {
  title: string;
  subtitle: string;
  decks: SpectateDeck[];
  catA: Category;
  catB: Category;
  deckA: string;
  deckB: string;
  onCatA: (c: Category) => void;
  onCatB: (c: Category) => void;
  onDeckA: (s: string) => void;
  onDeckB: (s: string) => void;
  disabled: boolean;
  footer?: ReactNode;
}) {
  const optA = decks.find((d) => d.slug === deckA);
  const optB = decks.find((d) => d.slug === deckB);
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <header
        className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-6"
        style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}
      >
        <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">{title}</h1>
        <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">{subtitle}</p>
      </header>

      <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
        <SideCard tag="P0" accent="var(--accent)" decks={decks} category={catA} deck={deckA} leader={optA?.leader} name={optA?.name} onCategory={onCatA} onDeck={onDeckA} disabled={disabled} />
        <div className="flex items-center justify-center px-2">
          <div className="text-4xl font-black tracking-widest text-[color:var(--border-2)]">VS</div>
        </div>
        <SideCard tag="P1" accent="var(--danger)" decks={decks} category={catB} deck={deckB} leader={optB?.leader} name={optB?.name} onCategory={onCatB} onDeck={onDeckB} disabled={disabled} />
      </div>

      {footer}
    </div>
  );
}

function SideCard({
  tag,
  accent,
  decks,
  category,
  deck,
  leader,
  name,
  onCategory,
  onDeck,
  disabled,
}: {
  tag: string;
  accent: string;
  decks: SpectateDeck[];
  category: Category;
  deck: string;
  leader?: string;
  name?: string;
  onCategory: (c: Category) => void;
  onDeck: (s: string) => void;
  disabled: boolean;
}) {
  const filtered = decks.filter((d) => (d.kind ?? "meta") === category);
  const cats: { key: Category; label: string }[] = [
    { key: "meta", label: "環境デッキ" },
    { key: "user", label: "マイデッキ" },
  ];
  return (
    <div
      className="flex flex-col gap-3 rounded-[var(--radius)] border border-t-2 bg-[color:var(--surface-1)] p-4"
      style={{ borderColor: "var(--border-1)", borderTopColor: accent }}
    >
      <div className="flex items-center gap-2">
        <span className="rounded px-2 py-0.5 text-xs font-bold text-white" style={{ background: accent }}>{tag}</span>
        <span className="text-sm text-[color:var(--text-muted)]">AI が操作</span>
      </div>

      <div className="flex justify-center">
        {leader ? (
          <CardImage cardId={leader} alt={name ?? leader} className="h-36 w-auto rounded-[var(--radius)] border border-[color:var(--border-1)] object-cover" />
        ) : (
          <div className="flex h-36 w-[93px] items-center justify-center rounded-[var(--radius)] border border-dashed text-xs text-[color:var(--text-muted)]" style={{ borderColor: "var(--border-2)" }}>
            未選択
          </div>
        )}
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

      <label className="flex flex-col gap-1 text-xs">
        <span className="text-[color:var(--text-muted)]">デッキ選択</span>
        <select
          value={deck}
          onChange={(e) => onDeck(e.target.value)}
          disabled={disabled || filtered.length === 0}
          className="rounded-[var(--radius)] border border-[color:var(--border-2)] bg-[color:var(--surface-2)] p-2 text-sm font-medium text-[color:var(--text-strong)]"
        >
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
      </label>
    </div>
  );
}
