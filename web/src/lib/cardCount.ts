// カード一覧の「現在の絞り込み後 件数」を CardBrowser (client) → ヘッダ (client) で共有する
// 軽量ストア。 ヘッダは server component 内にあるが、 件数バッジだけ client 化して購読する。
import { create } from "zustand";

interface CardCountState {
  count: number | null; // null = まだ CardBrowser が未マウント (fallback を表示)
  setCount: (n: number | null) => void;
}

export const useCardCount = create<CardCountState>((set) => ({
  count: null,
  setCount: (n) => set({ count: n }),
}));
