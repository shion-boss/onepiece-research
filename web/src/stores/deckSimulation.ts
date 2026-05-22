"use client";

import { create } from "zustand";

/**
 * デッキ詳細ページ内の「シミュレーション → 改善提案 refresh」 トリガー用 store。
 * DeckResearchWorkflow の探索ボタンが increment、 DeckImprovementSection が subscribe。
 */
type State = {
  improvementsRefreshKey: number;
  triggerImprovementsRefresh: () => void;
};

export const useDeckSimulationStore = create<State>((set) => ({
  improvementsRefreshKey: 0,
  triggerImprovementsRefresh: () =>
    set((s) => ({ improvementsRefreshKey: s.improvementsRefreshKey + 1 })),
}));
