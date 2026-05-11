"use client";

import { create } from "zustand";
import type { Card, Regulation } from "@/lib/types";

export type BuilderEntry = {
  card: Card;
  count: number;
};

const STORAGE_KEY = "deckBuilder.draft";
const MAX_PER_BASE_ID = 4;
const TARGET_TOTAL = 50;

function baseId(cardId: string): string {
  return cardId.split("_", 1)[0];
}

type State = {
  leader: Card | null;
  entries: BuilderEntry[];
  name: string;
  regulation: Regulation;
  setName: (n: string) => void;
  setLeader: (leader: Card | null) => void;
  setRegulation: (r: Regulation) => void;
  addCard: (card: Card) => string | null; // 失敗時はエラー文字列
  decrement: (cardId: string) => void;
  increment: (cardId: string) => string | null;
  removeCard: (cardId: string) => void;
  reset: () => void;
  loadFromLocalStorage: () => boolean;
  saveToLocalStorage: () => void;
  countByBaseId: (cardId: string) => number;
  totalMain: () => number;
};

export const useDeckBuilderStore = create<State>((set, get) => ({
  leader: null,
  entries: [],
  name: "新しいデッキ",
  regulation: "standard",

  setName: (n) => set({ name: n }),
  setRegulation: (r) => set({ regulation: r }),

  setLeader: (leader) => {
    if (leader === null) {
      set({ leader: null, entries: [] });
      return;
    }
    // 色が変わった場合、合致しないカードを除く
    const leaderColors = new Set(leader.color);
    set((s) => ({
      leader,
      entries: s.entries.filter((e) =>
        e.card.color.some((c) => leaderColors.has(c)),
      ),
    }));
  },

  addCard: (card) => {
    const { leader, entries } = get();
    if (!leader) return "リーダーを先に選んでください";
    if (card.category === "LEADER") return "リーダーはメインに入れられません";
    const leaderColors = new Set(leader.color);
    if (!card.color.some((c) => leaderColors.has(c))) {
      return `リーダーの色 ${[...leaderColors].join("/")} に合いません`;
    }

    const bid = baseId(card.card_id);
    const used = entries
      .filter((e) => baseId(e.card.card_id) === bid)
      .reduce((s, e) => s + e.count, 0);
    if (used >= MAX_PER_BASE_ID) {
      return `${card.name} は既に 4 枚`;
    }
    const total = entries.reduce((s, e) => s + e.count, 0);
    if (total >= TARGET_TOTAL) {
      return "メイン 50 枚に達しています";
    }

    set((s) => {
      const existing = s.entries.find((e) => e.card.card_id === card.card_id);
      if (existing) {
        return {
          entries: s.entries.map((e) =>
            e.card.card_id === card.card_id ? { ...e, count: e.count + 1 } : e,
          ),
        };
      }
      return { entries: [...s.entries, { card, count: 1 }] };
    });
    return null;
  },

  increment: (cardId) => {
    const e = get().entries.find((x) => x.card.card_id === cardId);
    if (!e) return "見つかりません";
    return get().addCard(e.card);
  },

  decrement: (cardId) =>
    set((s) => ({
      entries: s.entries
        .map((e) =>
          e.card.card_id === cardId ? { ...e, count: e.count - 1 } : e,
        )
        .filter((e) => e.count > 0),
    })),

  removeCard: (cardId) =>
    set((s) => ({
      entries: s.entries.filter((e) => e.card.card_id !== cardId),
    })),

  reset: () => set({ leader: null, entries: [], name: "新しいデッキ", regulation: "standard" }),

  countByBaseId: (cardId) => {
    const bid = baseId(cardId);
    return get()
      .entries.filter((e) => baseId(e.card.card_id) === bid)
      .reduce((s, e) => s + e.count, 0);
  },

  totalMain: () => get().entries.reduce((s, e) => s + e.count, 0),

  saveToLocalStorage: () => {
    if (typeof window === "undefined") return;
    const { leader, entries, name, regulation } = get();
    const payload = {
      name,
      regulation,
      leader: leader?.card_id ?? null,
      entries: entries.map((e) => ({ card_id: e.card.card_id, count: e.count })),
      saved_at: new Date().toISOString(),
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  },

  loadFromLocalStorage: () => {
    if (typeof window === "undefined") return false;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    try {
      const payload = JSON.parse(raw) as {
        name?: string;
        regulation?: Regulation;
        leader: string | null;
        entries: { card_id: string; count: number }[];
      };
      if (payload.name) set({ name: payload.name });
      if (payload.regulation) set({ regulation: payload.regulation });
      return true;
    } catch {
      return false;
    }
  },
}));

export const _builderInternal = { STORAGE_KEY, MAX_PER_BASE_ID, TARGET_TOTAL, baseId };
