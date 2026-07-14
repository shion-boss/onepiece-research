"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useState,
  type DragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useWorkspace, tabTitleFor, type ActivityView } from "@/lib/workspace";
import { AuthControls } from "./AuthControls";
import { StatusBar } from "./StatusBar";
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

// 主要ツール (上部) と Q&A (下部) を分ける = VSCode のアクティビティバー流。
const ACTIVITY_MAIN: { view: ActivityView; label: string; icon: ReactNode }[] = [
  { view: "explorer", label: "デッキ", icon: IconDeck },
  { view: "cards", label: "カード", icon: IconCards },
  { view: "play", label: "対戦", icon: IconPlay },
];
const FAQ_ACT: { view: ActivityView; label: string; icon: ReactNode } = {
  view: "faq",
  label: "ルール Q&A",
  icon: IconFaq,
};

type DeckRow = { slug: string; name: string; kind?: string; leader_color?: string[]; folder?: string };

const COLOR_HEX: Record<string, string> = {
  赤: "#f14c4c", 緑: "#4ec9b0", 青: "#3794ff", 紫: "#c586c0", 黒: "#6a6a72", 黄: "#cca700",
};

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const router = useRouter();
  const {
    tabs,
    openTab,
    closeTab,
    activeView,
    setView,
    sidebarOpen,
    toggleSidebar,
    sidebarWidth,
    setSidebarWidth,
  } = useWorkspace();
  const [matchActive, setMatchActive] = useState(false);

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

  // 現在のルートをタブとして開く (= 遷移した先が自動でタブになる)。
  useEffect(() => {
    openTab({ id: path, title: tabTitleFor(path) });
  }, [path, openTab]);

  // 対戦中 (full-screen board) はシェルの chrome を隠す。
  if (path.startsWith("/play") && matchActive) return <>{children}</>;

  const onCloseTab = (id: string) => {
    const idx = tabs.findIndex((t) => t.id === id);
    closeTab(id);
    if (id === path) {
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
        className="flex h-11 w-full items-center justify-center border-l-2 transition-colors"
        style={{ color: on ? "#fff" : "var(--text-muted)", borderLeftColor: on ? "#fff" : "transparent" }}
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
      <div className="flex min-h-0 flex-1">
        {/* activity bar */}
        <div
          className="flex w-12 shrink-0 flex-col items-center border-r pt-2"
          style={{ background: "var(--activity-bar)", borderColor: "var(--border-1)" }}
        >
          {ACTIVITY_MAIN.map(renderAct)}
          {renderAct(FAQ_ACT)}
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
            <div className="border-t px-3 py-2.5" style={{ borderColor: "var(--border-1)" }}>
              <AuthControls />
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
          <div
            className="flex h-9 shrink-0 items-stretch overflow-x-auto border-b"
            style={{ background: "var(--sidebar-bg)", borderColor: "var(--border-1)" }}
          >
            {tabs.map((t) => {
              const on = t.id === path;
              return (
                <div
                  key={t.id}
                  className="group flex shrink-0 items-center gap-2 border-r pl-3 pr-2 text-[12px]"
                  style={{
                    borderColor: "var(--border-1)",
                    background: on ? "var(--editor-bg)" : "transparent",
                    color: on ? "var(--text-strong)" : "var(--text-muted)",
                    boxShadow: on ? "inset 0 1px 0 var(--brand)" : undefined,
                  }}
                >
                  <Link href={t.id} className="py-2">
                    {t.title}
                  </Link>
                  <button
                    type="button"
                    aria-label="タブを閉じる"
                    onClick={() => onCloseTab(t.id)}
                    className="flex h-4 w-4 items-center justify-center rounded text-[color:var(--text-muted)] opacity-0 hover:bg-[var(--surface-3)] hover:text-white group-hover:opacity-100"
                  >
                    <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" strokeWidth="2" fill="none">
                      <path d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
          <div className="min-h-0 flex-1 overflow-auto log-scroll">{children}</div>
        </main>
      </div>
      <StatusBar />
    </div>
  );
}

// ---- sidebar panel: activeView 毎に内容を切替 ----
function SidebarPanel({ view, path }: { view: ActivityView; path: string }) {
  if (view === "cards") {
    return (
      <div className="py-2">
        <PanelHeader>カード</PanelHeader>
        <PanelLink href="/cards" active={path === "/cards"}>すべてのカードを開く</PanelLink>
        <div className="px-4 pb-1 pt-3 text-[10px] uppercase tracking-wider text-[color:var(--text-muted)]">色で絞る</div>
        {Object.keys(COLOR_HEX).map((c) => (
          <Link
            key={c}
            href={`/cards?color=${encodeURIComponent(c)}`}
            className="flex items-center gap-2 px-4 py-1.5 text-[13px] text-[color:var(--text-default)] hover:bg-[var(--list-hover)] hover:text-white"
          >
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLOR_HEX[c] }} />
            {c}
          </Link>
        ))}
      </div>
    );
  }
  if (view === "play") {
    return (
      <div className="py-2">
        <PanelHeader>対戦</PanelHeader>
        <PanelLink href="/play" active={path === "/play"}>人間 vs AI</PanelLink>
        <PanelLink href="/watch" active={path === "/watch"}>AI vs AI（観戦）</PanelLink>
        <PanelLink href="/winrate" active={path === "/winrate"}>AI vs AI（10連戦）</PanelLink>
        <p className="px-4 pt-2 text-[11px] leading-relaxed text-[color:var(--text-muted)]">
          人間 vs AI = 自分のデッキでプレイ / 観戦 = 2 デッキで 1 試合 / 10連戦 = 10 戦して勝率。
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
        <FolderHeader label="マイデッキ（非公開）" open={mineOpen} depth={0} onToggle={() => toggleFolder("__mine__")} />
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
