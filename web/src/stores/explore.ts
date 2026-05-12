"use client";

import { create } from "zustand";
import type { Card, CounterCandidate, DeckSummary } from "@/lib/types";

type State = {
  // 入力
  target: DeckSummary | null;
  leaderFilter: Card[];      // リーダー指定 (= 複数選択可)
  mustInclude: Card[];       // 必須カード (= 複数選択可)
  // 出力
  candidates: CounterCandidate[];
  selectedRank: number | null;  // 詳細表示中の rank (1-based)
  // 状態
  loading: boolean;
  error: string | null;

  setTarget: (target: DeckSummary | null) => void;
  addLeaderFilter: (leader: Card) => void;
  removeLeaderFilter: (cardId: string) => void;
  addMustInclude: (card: Card) => void;
  removeMustInclude: (cardId: string) => void;
  resetConstraints: () => void;
  setCandidates: (candidates: CounterCandidate[]) => void;
  setSelectedRank: (rank: number | null) => void;
  setLoading: (b: boolean) => void;
  setError: (msg: string | null) => void;
  reset: () => void;
};

export const useExploreStore = create<State>((set) => ({
  target: null,
  leaderFilter: [],
  mustInclude: [],
  candidates: [],
  selectedRank: null,
  loading: false,
  error: null,

  setTarget: (target) =>
    set({ target, candidates: [], selectedRank: null, error: null }),

  addLeaderFilter: (leader) =>
    set((s) => {
      if (s.leaderFilter.some((l) => l.card_id === leader.card_id)) return s;
      return { leaderFilter: [...s.leaderFilter, leader] };
    }),

  removeLeaderFilter: (cardId) =>
    set((s) => ({
      leaderFilter: s.leaderFilter.filter((l) => l.card_id !== cardId),
    })),

  addMustInclude: (card) =>
    set((s) => {
      if (s.mustInclude.some((c) => c.card_id === card.card_id)) return s;
      return { mustInclude: [...s.mustInclude, card] };
    }),

  removeMustInclude: (cardId) =>
    set((s) => ({
      mustInclude: s.mustInclude.filter((c) => c.card_id !== cardId),
    })),

  resetConstraints: () => set({ leaderFilter: [], mustInclude: [] }),

  setCandidates: (candidates) =>
    set({ candidates, selectedRank: candidates.length > 0 ? 1 : null }),

  setSelectedRank: (rank) => set({ selectedRank: rank }),

  setLoading: (loading) => set({ loading }),

  setError: (error) => set({ error }),

  reset: () =>
    set({
      target: null,
      leaderFilter: [],
      mustInclude: [],
      candidates: [],
      selectedRank: null,
      loading: false,
      error: null,
    }),
}));
