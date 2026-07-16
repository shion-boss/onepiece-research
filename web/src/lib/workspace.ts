// VSCode 風ワークスペース状態: 開いているタブ + アクティビティビュー + サイドバー開閉。
// ルーティングは Next の route ベースのまま、 「開いたページ = タブ」 をクライアント状態で管理する。
import { create } from "zustand";

export type Tab = { id: string; title: string };
export type ActivityView = "grow" | "explorer" | "cards" | "play" | "faq" | "history";

interface WorkspaceState {
  tabs: Tab[];
  activeTabId: string; // 現在アクティブなタブ ID (= pathname、 /cards は絞り込みクエリ込み)
  activeView: ActivityView;
  sidebarOpen: boolean;
  sidebarWidth: number;
  collapsedFolders: string[];
  openTab: (t: Tab) => void;
  closeTab: (id: string) => void;
  closeAllTabs: () => void;
  reorderTab: (dragId: string, dropId: string) => void;
  setActiveTabId: (id: string) => void;
  setView: (v: ActivityView) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (b: boolean) => void;
  setSidebarWidth: (w: number) => void;
  toggleFolder: (f: string) => void;
  // マイデッキ一覧の再取得を促すノンス (= デッキ保存直後に左メニューを即更新するため)。
  decksNonce: number;
  refreshDecks: () => void;
  // タブ名の上書き (tabId → 表示名)。 デッキ詳細タブに slug でなくデッキ名を出す等。
  tabTitleOverrides: Record<string, string>;
  setTabTitle: (id: string, title: string) => void;
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  tabs: [],
  activeTabId: "/",
  activeView: "explorer",
  sidebarOpen: true,
  sidebarWidth: 224,
  collapsedFolders: [],
  decksNonce: 0,
  refreshDecks: () => set((s) => ({ decksNonce: s.decksNonce + 1 })),
  tabTitleOverrides: {},
  setTabTitle: (id, title) =>
    set((s) => ({
      tabTitleOverrides: { ...s.tabTitleOverrides, [id]: title },
      tabs: s.tabs.map((t) => (t.id === id ? { ...t, title } : t)),
    })),
  openTab: (t) =>
    set((s) =>
      // 既存タブのタイトルは上書きしない (= ページ側 setTabTitle が付けたデッキ名等を
      // CurrentTabSync の再 openTab で slug に戻してしまう race を防ぐ)。 タイトル変更は
      // setTabTitle が唯一の手段。 override が優先されるので新規作成時も正しい名前で開く。
      s.tabs.some((x) => x.id === t.id) ? {} : { tabs: [...s.tabs, t] },
    ),
  closeTab: (id) => set((s) => ({ tabs: s.tabs.filter((x) => x.id !== id) })),
  closeAllTabs: () => set({ tabs: [] }),
  // ドラッグ&ドロップ並び替え: dragId を dropId の位置へ移動。
  reorderTab: (dragId, dropId) =>
    set((s) => {
      if (dragId === dropId) return {};
      const from = s.tabs.findIndex((t) => t.id === dragId);
      const to = s.tabs.findIndex((t) => t.id === dropId);
      if (from < 0 || to < 0) return {};
      const next = s.tabs.slice();
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return { tabs: next };
    }),
  setActiveTabId: (id) => set({ activeTabId: id }),
  setView: (v) => set({ activeView: v, sidebarOpen: true }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (b) => set({ sidebarOpen: b }),
  setSidebarWidth: (w) => set({ sidebarWidth: w }),
  toggleFolder: (f) =>
    set((s) => ({
      collapsedFolders: s.collapsedFolders.includes(f)
        ? s.collapsedFolders.filter((x) => x !== f)
        : [...s.collapsedFolders, f],
    })),
}));

// パス → タブ表示名。 未知は末尾セグメント。
export function tabTitleFor(path: string): string {
  const map: Record<string, string> = {
    "/": "ようこそ",
    "/territory": "陣取り",
    "/history": "戦いの歴史",
    "/play": "人間 vs AI",
    "/watch": "AI vs AI 観戦",
    "/winrate": "AI vs AI 勝率",
    "/decks": "マイデッキ",
    "/decks/new": "新規デッキ",
    "/decks/generate": "デッキ生成",
    "/cards": "カード",
    "/faq": "Q&A",
    "/faq/sources": "Q&A 参照先",
    "/combos": "コンボ探索",
    "/meta": "メタ分析",
    "/research": "研究",
  };
  if (map[path]) return map[path];
  const seg = path.split("/").filter(Boolean);
  const dec = (s: string) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  };
  if (seg[0] === "decks" && seg[1]) {
    // slug は override (デッキ名) が優先。 fallback は URL デコードして文字化けを避ける。
    if (seg[2] === "analyze") return `${dec(seg[1])} · 分析`;
    return dec(seg[1]);
  }
  return dec(seg[seg.length - 1] ?? path);
}
