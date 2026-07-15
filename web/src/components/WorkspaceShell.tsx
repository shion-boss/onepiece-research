"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useState,
  type DragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useWorkspace, type ActivityView } from "@/lib/workspace";
import { AuthControls } from "./AuthControls";
import { StatusBar } from "./StatusBar";
import { CardsSidebar } from "./CardsSidebar";
import { CurrentTabSync } from "./CurrentTabSync";
import { fetchDecks, moveDeckToFolder, renameFolder, deleteFolder, renameDeck } from "@/lib/api";

// ---- icons (VSCode codicon 風の細線 SVG) ----
const svg = (p: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="22" height="22">
    {p}
  </svg>
);
const IconDeck = svg(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M9 20V9" /></>);
const IconCards = svg(<><rect x="3" y="5" width="14" height="16" rx="1.5" /><path d="M7 3h13v15" /></>);
const IconPlay = svg(<path d="M6 4l14 8-14 8z" />);
const chevron = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
    <path d="M9 6l6 6-6 6" />
  </svg>
);

const IconFaq = svg(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.6 9.2a2.4 2.4 0 1 1 3.3 2.2c-.7.4-1.1.9-1.1 1.8" />
    <path d="M12 16.6h.01" strokeLinecap="round" />
  </>,
);
// ゲーム ハブ (陣取り含む複数ゲームを束ねる)。 ゲームパッド アイコン。
const IconGrow = svg(
  <>
    <path d="M17.3 5H6.7a4 4 0 0 0-4 3.6C2.6 9.4 2 14.5 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.4-1.4a2 2 0 0 1 1.4-.6h4.4a2 2 0 0 1 1.4.6L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.5-.6-6.6-.7-7.4A4 4 0 0 0 17.3 5Z" />
    <path d="M6.5 11h3M8 9.5v3" strokeLinecap="round" />
    <path d="M15 12h.01M18 10h.01" strokeLinecap="round" />
  </>,
);
// 戦いの歴史 (巻物/時計)
const IconHistory = svg(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" strokeLinecap="round" />
  </>,
);

// 主要ツール (上部) と Q&A / 履歴 (下部) を分ける = VSCode のアクティビティバー流。
const ACTIVITY_MAIN: { view: ActivityView; label: string; icon: ReactNode }[] = [
  { view: "grow", label: "ゲーム", icon: IconGrow },
  { view: "explorer", label: "デッキ", icon: IconDeck },
  { view: "play", label: "対戦", icon: IconPlay },
  { view: "cards", label: "カード", icon: IconCards },
];
const FAQ_ACT: { view: ActivityView; label: string; icon: ReactNode } = {
  view: "faq",
  label: "ルール Q&A",
  icon: IconFaq,
};
const HISTORY_ACT: { view: ActivityView; label: string; icon: ReactNode } = {
  view: "history",
  label: "戦いの歴史",
  icon: IconHistory,
};

type DeckRow = { slug: string; name: string; kind?: string; leader_color?: string[]; folder?: string; private?: boolean };

const COLOR_HEX: Record<string, string> = {
  赤: "#f14c4c", 緑: "#4ec9b0", 青: "#3794ff", 紫: "#c586c0", 黒: "#6a6a72", 黄: "#cca700",
};

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const router = useRouter();
  const {
    tabs,
    activeTabId,
    closeTab,
    closeAllTabs,
    reorderTab,
    activeView,
    setView,
    sidebarOpen,
    toggleSidebar,
    sidebarWidth,
    setSidebarWidth,
  } = useWorkspace();
  const [matchActive, setMatchActive] = useState(false);
  // タブ D&D 並び替え用: ドラッグ中 / ドロップ先ハイライトの id。
  const [dragTabId, setDragTabId] = useState<string | null>(null);
  const [overTabId, setOverTabId] = useState<string | null>(null);

  useEffect(() => {
    function onChange(e: Event) {
      setMatchActive((e as CustomEvent<boolean>).detail === true);
    }
    window.addEventListener("match-state-change", onChange as EventListener);
    return () =>
      window.removeEventListener("match-state-change", onChange as EventListener);
  }, []);
  useEffect(() => {
    if (!path.startsWith("/play")) setMatchActive(false);
  }, [path]);

  // 対戦中 (full-screen board) はシェルの chrome を隠す。
  if (path.startsWith("/play") && matchActive) return <>{children}</>;

  const onCloseTab = (id: string) => {
    const idx = tabs.findIndex((t) => t.id === id);
    closeTab(id);
    if (id === activeTabId) {
      const rest = tabs.filter((t) => t.id !== id);
      const next = rest[idx] ?? rest[idx - 1] ?? rest[rest.length - 1];
      router.push(next ? next.id : "/");
    }
  };

  const onActivity = (v: ActivityView) => {
    if (v === activeView && sidebarOpen) toggleSidebar();
    else setView(v);
  };

  const renderAct = (a: { view: ActivityView; label: string; icon: ReactNode }) => {
    const on = a.view === activeView && sidebarOpen;
    return (
      <button
        key={a.view}
        type="button"
        title={a.label}
        onClick={() => onActivity(a.view)}
        className={
          "flex h-11 w-full items-center justify-center border-l-2 transition-colors " +
          (on ? "text-white" : "text-[color:var(--text-muted)] hover:text-white")
        }
        style={{ borderLeftColor: on ? "#fff" : "transparent" }}
      >
        {a.icon}
      </button>
    );
  };

  // サイドバー幅のドラッグリサイズ (VSCode 風)。 activity bar (48px) の右から測る。
  const startResize = (e: ReactMouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sidebarWidth;
    const onMove = (ev: MouseEvent) => {
      setSidebarWidth(Math.min(560, Math.max(160, startW + (ev.clientX - startX))));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden">
      {/* URL → タブ同期 (useSearchParams を隔離するため Suspense に包む) */}
      <Suspense fallback={null}>
        <CurrentTabSync />
      </Suspense>
      <div className="flex min-h-0 flex-1">
        {/* activity bar */}
        <div
          className="flex w-12 shrink-0 flex-col items-center border-r pt-2"
          style={{ background: "var(--activity-bar)", borderColor: "var(--border-1)" }}
        >
          {ACTIVITY_MAIN.map(renderAct)}
          {renderAct(FAQ_ACT)}
          {renderAct(HISTORY_ACT)}
          {/* アカウント: アクティビティバー最下部 (VSCode 風) */}
          <div className="mt-auto mb-2 flex w-full justify-center pt-2">
            <AuthControls />
          </div>
        </div>

        {/* sidebar panel */}
        {sidebarOpen && (
          <>
          <aside
            className="flex shrink-0 flex-col border-r"
            style={{ background: "var(--sidebar-bg)", borderColor: "var(--border-1)", width: sidebarWidth }}
          >
            <div className="flex items-center gap-2 border-b px-3 py-3" style={{ borderColor: "var(--border-1)" }}>
              <span
                className="flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white"
                style={{ background: "var(--brand)" }}
                aria-hidden
              >
                OP
              </span>
              <span className="text-[13px] font-semibold text-[color:var(--text-strong)]">OPTCG</span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto log-scroll">
              <SidebarPanel view={activeView} path={path} />
            </div>
          </aside>
          {/* リサイザー: ドラッグでサイドバー幅を変更 */}
          <div
            onMouseDown={startResize}
            title="ドラッグで幅を変更"
            className="w-1 shrink-0 cursor-col-resize hover:bg-[color:var(--brand)]"
          />
          </>
        )}

        {/* editor: tabs + content */}
        <main className="flex min-w-0 flex-1 flex-col" style={{ background: "var(--editor-bg)" }}>
          {tabs.length > 0 && (
          <div
            className="flex shrink-0 items-stretch border-b"
            style={{ borderColor: "var(--border-1)", background: "var(--sidebar-bg)" }}
          >
          {/* 横スクロールバーをタブの上に出す: 外側を上下反転→バーが上へ / 内側を再反転→中身は正立 */}
          <div
            className="tabs-scroll h-10 min-w-0 flex-1 overflow-x-scroll overflow-y-hidden"
            style={{ transform: "scaleY(-1)" }}
          >
          <div className="flex h-full w-max items-stretch" style={{ transform: "scaleY(-1)" }}>
            {tabs.map((t) => {
              const on = t.id === activeTabId;
              const isOver = overTabId === t.id && dragTabId != null && dragTabId !== t.id;
              return (
                <div
                  key={t.id}
                  draggable
                  onDragStart={(e) => {
                    setDragTabId(t.id);
                    e.dataTransfer.effectAllowed = "move";
                    e.dataTransfer.setData("text/plain", t.id);
                  }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    if (overTabId !== t.id) setOverTabId(t.id);
                  }}
                  onDragEnd={() => {
                    setDragTabId(null);
                    setOverTabId(null);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    const src = dragTabId ?? e.dataTransfer.getData("text/plain");
                    if (src && src !== t.id) reorderTab(src, t.id);
                    setDragTabId(null);
                    setOverTabId(null);
                  }}
                  title={t.title}
                  className="group relative flex max-w-[200px] shrink-0 cursor-grab items-center gap-2 border-r pl-3 pr-2 text-[12px] active:cursor-grabbing"
                  style={{
                    borderColor: "var(--border-1)",
                    background: on ? "var(--editor-bg)" : "transparent",
                    color: on ? "var(--text-strong)" : "var(--text-muted)",
                    boxShadow: on ? "inset 0 1px 0 var(--brand)" : undefined,
                    opacity: dragTabId === t.id ? 0.4 : 1,
                  }}
                >
                  {isOver && (
                    <span
                      className="pointer-events-none absolute inset-y-0 left-0 w-0.5"
                      style={{ background: "var(--brand)" }}
                    />
                  )}
                  <Link href={t.id} draggable={false} className="min-w-0 truncate py-2">
                    {t.title}
                  </Link>
                  <button
                    type="button"
                    aria-label="タブを閉じる"
                    onClick={() => onCloseTab(t.id)}
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[color:var(--text-muted)] opacity-0 hover:bg-[var(--surface-3)] hover:text-white group-hover:opacity-100"
                  >
                    <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" strokeWidth="2" fill="none">
                      <path d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
          </div>
          {/* 右端: すべてのタブを一括で閉じる (スクロールに追従せず常に右端に固定) */}
          <button
            type="button"
            onClick={() => {
              closeAllTabs();
              router.push("/");
            }}
            title="すべてのタブを閉じる"
            aria-label="すべてのタブを閉じる"
            className="flex h-10 w-9 shrink-0 items-center justify-center border-l text-[color:var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-white"
            style={{ borderColor: "var(--border-1)" }}
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7">
              <rect x="4" y="7" width="10" height="10" rx="1.5" />
              <path d="M14 8V6.5A1.5 1.5 0 0 1 15.5 5H19a1.5 1.5 0 0 1 1.5 1.5V15A1.5 1.5 0 0 1 19 16.5h-1" />
              <path d="M6.5 9.5l5 5M11.5 9.5l-5 5" strokeLinecap="round" />
            </svg>
          </button>
          </div>
          )}
          <div className="min-h-0 flex-1 overflow-auto log-scroll">{children}</div>
        </main>
      </div>
      <StatusBar />
    </div>
  );
}

// ---- sidebar panel: activeView 毎に内容を切替 ----
function SidebarPanel({ view, path }: { view: ActivityView; path: string }) {
  if (view === "grow") {
    return (
      <div className="py-2">
        <PanelHeader>ゲーム</PanelHeader>
        <PanelLink href="/territory" active={path === "/territory"}>推しリーダー陣取りボード</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          推しリーダーで遊ぶゲーム。ほかのゲームも順次追加予定。
        </p>
      </div>
    );
  }
  if (view === "history") {
    return (
      <div className="py-2">
        <PanelHeader>戦いの歴史</PanelHeader>
        <PanelLink href="/history" active={path === "/history"}>月ごとの戦績を見る</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          毎月末に陣取りの状態を記録。人類 vs AI の歩みを振り返る。
        </p>
      </div>
    );
  }
  if (view === "cards") {
    return <CardsSidebar />;
  }
  if (view === "play") {
    return (
      <div className="py-2">
        <PanelHeader>対戦</PanelHeader>
        <PanelLink href="/play" active={path === "/play"}>人間 vs AI</PanelLink>
        <PanelLink href="/watch" active={path === "/watch"}>AI vs AI（観戦）</PanelLink>
        <PanelLink href="/winrate" active={path === "/winrate"}>AI vs AI（勝率）</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          人間 vs AI = 自分のデッキでプレイ / 観戦 = 2 デッキで 1 試合 / 勝率 = 連戦して勝率。
        </p>
      </div>
    );
  }
  if (view === "faq") {
    return (
      <div className="py-2">
        <PanelHeader>ルール Q&amp;A</PanelHeader>
        <PanelLink href="/faq" active={path === "/faq"}>Q&amp;A を開く</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          公式ルール・カードの裁定を検索できます。
        </p>
      </div>
    );
  }
  return <ExplorerPanel path={path} />;
}

const IconFolder = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
    <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </svg>
);

function ExplorerPanel({ path }: { path: string }) {
  const [decks, setDecks] = useState<DeckRow[] | null>(null);
  const [extraFolders, setExtraFolders] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const { collapsedFolders, toggleFolder } = useWorkspace();

  const reload = useCallback(() => {
    fetchDecks()
      .then((d) => setDecks(d as DeckRow[]))
      .catch(() => setDecks([]));
  }, []);
  useEffect(() => {
    reload();
  }, [reload]);

  const mine = decks?.filter((d) => d.kind === "user") ?? [];
  const meta = decks?.filter((d) => d.kind === "meta") ?? [];
  const rootDecks = mine.filter((d) => !(d.folder && d.folder.length));
  const folderNames = Array.from(
    new Set([...mine.map((d) => d.folder || "").filter(Boolean), ...extraFolders]),
  ).sort((a, b) => a.localeCompare(b, "ja"));

  const move = async (slug: string, folder: string) => {
    try {
      await moveDeckToFolder(slug, folder);
    } catch (e) {
      console.error(e);
      window.alert(
        "このデッキは移動できませんでした。自分で作成したデッキ（マイデッキ）のみフォルダに入れられます。",
      );
    }
    reload();
  };
  const newFolder = () => {
    const name = window.prompt("新しいフォルダ名");
    if (name && name.trim()) setExtraFolders((p) => Array.from(new Set([...p, name.trim()])));
  };
  const renameF = async (f: string) => {
    const name = window.prompt("フォルダ名を変更", f);
    if (name && name.trim() && name.trim() !== f) {
      try {
        await renameFolder(f, name.trim());
      } catch {
        /* noop */
      }
      setExtraFolders((p) => p.map((x) => (x === f ? name.trim() : x)));
      reload();
    }
  };
  const deleteF = async (f: string) => {
    if (window.confirm(`フォルダ「${f}」を解体します。中のデッキはルートに戻ります。`)) {
      try {
        await deleteFolder(f);
      } catch {
        /* noop */
      }
      setExtraFolders((p) => p.filter((x) => x !== f));
      reload();
    }
  };
  const dropProps = (folder: string) => ({
    onDragOver: (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move"; // これが無いとブラウザがドロップを拒否する
      setDragOver(folder);
    },
    onDragLeave: () => setDragOver((d) => (d === folder ? null : d)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const slug = e.dataTransfer.getData("text/deck");
      setDragOver(null);
      if (slug) move(slug, folder);
    },
  });

  const mineOpen = !collapsedFolders.includes("__mine__");
  const metaOpen = !collapsedFolders.includes("__meta__");

  return (
    <div className="py-2">
      <div className="flex items-center justify-between pr-2">
        <PanelHeader>エクスプローラー</PanelHeader>
        <button
          type="button"
          title="新しいフォルダ"
          onClick={newFolder}
          className="text-[color:var(--text-muted)] hover:text-white"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <path d="M12 11v4M10 13h4" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* マイデッキ = ルートフォルダ (ここにドロップでルートへ) */}
      <div className={dragOver === "" ? "bg-[var(--brand-soft)]" : ""} {...dropProps("")}>
        <FolderHeader label="マイデッキ" open={mineOpen} depth={0} onToggle={() => toggleFolder("__mine__")} />
        {mineOpen && (
          <div className="border-l" style={{ marginLeft: "10px", borderColor: "var(--border-1)" }}>
            {decks === null && <Muted>読み込み中…</Muted>}
            {decks !== null && mine.length === 0 && <Muted>まだデッキがありません</Muted>}
            {folderNames.map((f) => {
              const items = mine.filter((d) => (d.folder || "") === f);
              const open = !collapsedFolders.includes(f);
              return (
                <div key={f} className={dragOver === f ? "bg-[var(--brand-soft)]" : ""} {...dropProps(f)}>
                  <FolderHeader
                    label={f}
                    count={items.length}
                    open={open}
                    depth={1}
                    onToggle={() => toggleFolder(f)}
                    onRename={() => renameF(f)}
                    onDelete={() => deleteF(f)}
                  />
                  {open && (
                    <div className="border-l" style={{ marginLeft: "10px", borderColor: "var(--border-2)" }}>
                      {items.map((d) => (
                        <MyDeckRow key={d.slug} deck={d} active={path === `/decks/${d.slug}`} onChanged={reload} />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {rootDecks.map((d) => (
              <MyDeckRow key={d.slug} deck={d} active={path === `/decks/${d.slug}`} onChanged={reload} />
            ))}
            <Link
              href="/decks/new"
              className="flex items-center gap-2 py-1.5 pl-3 pr-3 text-[13px] text-[color:var(--brand-strong)] hover:bg-[var(--list-hover)]"
            >
              ＋ 新規デッキ
            </Link>
          </div>
        )}
      </div>

      {/* 環境デッキ = ルートフォルダ (相手候補、 ドロップ対象外) */}
      <div className="mt-1">
        <FolderHeader label="環境デッキ（相手候補）" open={metaOpen} depth={0} onToggle={() => toggleFolder("__meta__")} />
        {metaOpen && (
          <div className="border-l" style={{ marginLeft: "10px", borderColor: "var(--border-1)" }}>
            {meta.map((d) => (
              <DeckRowLink key={d.slug} deck={d} active={path === `/decks/${d.slug}`} meta />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MyDeckRow({
  deck,
  active,
  onChanged,
}: {
  deck: DeckRow;
  active: boolean;
  onChanged?: () => void;
}) {
  const router = useRouter();
  const color = deck.leader_color?.[0];
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/deck", deck.slug);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={() => router.push(`/decks/${deck.slug}`)}
      role="button"
      title={deck.name}
      className="group flex cursor-pointer items-center gap-2 py-1.5 pl-3 pr-2 text-[13px] hover:bg-[var(--list-hover)]"
      style={
        active
          ? { background: "var(--brand-soft)", color: "#fff", boxShadow: "inset 2px 0 0 var(--brand)" }
          : { color: "var(--text-default)" }
      }
    >
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-sm"
        style={{ background: (color && COLOR_HEX[color]) || "#4a4a52" }}
      />
      <span className="flex-1 truncate">{deck.name}</span>
      {deck.private && (
        <svg
          width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" className="shrink-0 text-[color:var(--text-muted)]"
          aria-label="非公開"
        >
          <title>非公開（陣取りで使用不可）</title>
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      )}
      <button
        type="button"
        title="名前を変更"
        onClick={async (e) => {
          e.stopPropagation();
          const name = window.prompt("デッキ名を変更", deck.name);
          if (name && name.trim() && name.trim() !== deck.name) {
            try {
              await renameDeck(deck.slug, name.trim());
            } catch {
              window.alert("名前を変更できませんでした。自分で作成したデッキのみ変更できます。");
            }
            onChanged?.();
          }
        }}
        className="hidden shrink-0 text-[10px] text-[color:var(--text-muted)] hover:text-white group-hover:block"
      >
        名変
      </button>
    </div>
  );
}

function FolderHeader({
  label,
  count,
  open,
  depth,
  onToggle,
  onRename,
  onDelete,
}: {
  label: string;
  count?: number;
  open: boolean;
  depth: number;
  onToggle: () => void;
  onRename?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      className="group flex items-center gap-1 py-1 pr-2 text-[12px] font-medium text-[color:var(--text-default)] hover:bg-[var(--list-hover)]"
      style={{ paddingLeft: 6 + depth * 4 }}
    >
      <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-1 text-left">
        <span
          className="shrink-0"
          style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .1s" }}
        >
          {chevron}
        </span>
        {IconFolder}
        <span className="flex-1 truncate">{label}</span>
        {count !== undefined && (
          <span className="text-[10px] text-[color:var(--text-muted)]">{count}</span>
        )}
      </button>
      {onRename && (
        <button
          type="button"
          title="名前変更"
          onClick={onRename}
          className="hidden text-[10px] text-[color:var(--text-muted)] hover:text-white group-hover:block"
        >
          名変
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          title="解体"
          onClick={onDelete}
          className="hidden text-[10px] text-[color:var(--text-muted)] hover:text-[color:var(--danger)] group-hover:block"
        >
          解体
        </button>
      )}
    </div>
  );
}

function DeckRowLink({ deck, active, meta }: { deck: DeckRow; active: boolean; meta?: boolean }) {
  const color = deck.leader_color?.[0];
  return (
    <Link
      href={`/decks/${deck.slug}`}
      className="flex items-center gap-2 py-1.5 pl-3 pr-3 text-[13px] hover:bg-[var(--list-hover)]"
      style={
        active
          ? { background: "var(--brand-soft)", color: "#fff", boxShadow: "inset 2px 0 0 var(--brand)" }
          : { color: "var(--text-default)" }
      }
    >
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-sm"
        style={{ background: (color && COLOR_HEX[color]) || "#4a4a52" }}
      />
      <span className="flex-1 truncate">{deck.name}</span>
      {meta && <span className="text-[10px] text-[color:var(--text-muted)]">meta</span>}
    </Link>
  );
}

function PanelHeader({ children }: { children: ReactNode }) {
  return (
    <div className="px-4 pb-2 pt-1 text-[11px] font-semibold uppercase tracking-wider text-[color:var(--text-muted)]">
      {children}
    </div>
  );
}
function PanelLink({ href, active, children }: { href: string; active?: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="block px-4 py-1.5 text-[13px] hover:bg-[var(--list-hover)] hover:text-white"
      style={active ? { color: "#fff", boxShadow: "inset 2px 0 0 var(--brand)" } : { color: "var(--text-default)" }}
    >
      {children}
    </Link>
  );
}
function Muted({ children }: { children: ReactNode }) {
  return <div className="px-4 py-1.5 text-[12px] text-[color:var(--text-muted)]">{children}</div>;
}
