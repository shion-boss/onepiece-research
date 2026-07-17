"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BoardGrid, buildCellsFromBoard, type BoardLeader } from "./TerritoryBoard";
import { CellPanel } from "./CellHistoryPanel";
import { useResizable } from "@/lib/useResizable";
import { ResizeHandle } from "./ResizeHandle";
import {
  fetchTerritorySnapshots,
  fetchTerritorySnapshot,
  type TerritorySnapshotSummary,
  type TerritorySnapshot,
} from "@/lib/api";

// 戦いの歴史 = 月次スナップショット (完了月の最終陣地 + 集計) の実データ表示。
// 過去 (機能導入前) の月は履歴が無いので空スタート → 月が完了するたびに積み上がる
// (backend: territory.maybe_freeze_snapshots の lazy freeze)。ランダム seed は使わない。
function monthLabel(key: string): string {
  const [y, m] = key.split("-");
  return `${y} / ${m}`;
}

export function BattleHistory({ leaders }: { leaders: BoardLeader[] }) {
  const [snapshots, setSnapshots] = useState<TerritorySnapshotSummary[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<TerritorySnapshot | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [hoverEnabled, setHoverEnabled] = useState(false); // 既定=ホバー切替なし

  const leaderById = useMemo(() => {
    const m = new Map<string, BoardLeader>();
    for (const l of leaders) m.set(l.id, l);
    return m;
  }, [leaders]);

  // 月次スナップショット一覧を取得 (初回のみ、 実データ・完了月のみ)。
  useEffect(() => {
    let alive = true;
    fetchTerritorySnapshots()
      .then((s) => {
        if (!alive) return;
        setSnapshots(s);
        if (s.length) setSel(s[0].month_key); // 最新の完了月を初期選択
      })
      .catch(() => alive && setSnapshots([]));
    return () => {
      alive = false;
    };
  }, []);

  // 選択月の凍結盤を取得。 月切替で選択/ホバーをクリア。
  useEffect(() => {
    if (!sel) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetail(null);
    setSelected(null);
    setHovered(null);
    fetchTerritorySnapshot(sel)
      .then((d) => alive && setDetail(d))
      .catch(() => alive && setDetail(null));
    return () => {
      alive = false;
    };
  }, [sel]);

  const cells = useMemo(
    () => (detail ? buildCellsFromBoard(detail.board, leaderById) : []),
    [detail, leaderById],
  );

  const onClick = useCallback((i: number) => setSelected((p) => (p === i ? null : i)), []);
  const onEnter = useCallback((i: number) => setHovered(i), []);
  const NOOP = useCallback(() => {}, []);
  const activeIdx = selected != null ? selected : hoverEnabled ? hovered : null;
  const active = activeIdx != null && cells.length > 0 ? cells[activeIdx] : null;

  // 列幅ドラッグリサイズ (左=月メニュー / 右=履歴パネル)。
  const left = useResizable(160, 140, 300);
  const right = useResizable(288, 240, 560, true);

  // 読み込み中
  if (snapshots === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[color:var(--text-muted)]">
        読み込み中...
      </div>
    );
  }

  // 空状態: まだ完了した月が無い (= 今後の対戦で積み上がる)。 偽データは出さない。
  if (snapshots.length === 0) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center p-6">
        <div
          className="max-w-md rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-6 text-center"
          style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}
        >
          <h1 className="text-lg font-semibold tracking-tight text-[color:var(--text-strong)]">
            まだ記録がありません
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-[color:var(--text-muted)]">
            対戦が積み重なると、月ごとの記録がここに残ります。
            まずは陣取りの月末凍結（その月末の勢力図＝どのリーダーがどれだけ占領したか）から。
            今後、陣取り以外のコンテンツの記録も加わります。
          </p>
        </div>
      </div>
    );
  }

  const selInfo = snapshots.find((s) => s.month_key === sel) ?? snapshots[0];

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      {/* 左: 月メニュー (実スナップショット、 新しい月順) */}
      <aside className="log-scroll shrink-0 overflow-y-auto py-2" style={{ width: left.width }}>
        <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--text-muted)]">
          戦いの歴史
        </div>
        {snapshots.map((s) => {
          const on = s.month_key === sel;
          return (
            <button
              key={s.month_key}
              type="button"
              onClick={() => setSel(s.month_key)}
              className="flex w-full items-center justify-between gap-1.5 border-l-2 px-3 py-2 text-left text-[13px] transition-colors"
              style={{
                borderLeftColor: on ? "var(--brand)" : "transparent",
                background: on ? "var(--list-hover)" : "transparent",
                color: on ? "var(--text-strong)" : "var(--text-default)",
              }}
            >
              <span>{monthLabel(s.month_key)}</span>
              <span className="text-[10px] text-[color:var(--text-muted)]">{s.n_battles}戦</span>
            </button>
          );
        })}
      </aside>

      <ResizeHandle onMouseDown={left.onMouseDown} />

      {/* 中央: 選択月の最終陣地 */}
      <main className="log-scroll min-w-0 flex-1 overflow-y-auto border-l" style={{ borderColor: "var(--border-1)" }}>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
          <header
            className="rounded-[var(--radius)] border border-l-2 bg-[color:var(--surface-1)] p-5"
            style={{ borderColor: "var(--border-1)", borderLeftColor: "var(--brand)" }}
          >
            <h1 className="text-xl font-semibold tracking-tight text-[color:var(--text-strong)]">
              {monthLabel(selInfo.month_key)} の最終陣地
            </h1>
            <p className="mt-1.5 text-sm text-[color:var(--text-muted)]">
              その月末に凍結した陣取りの状態。占領 {selInfo.occupied} / 空き {1024 - selInfo.occupied}。
              対戦 {selInfo.n_battles} 戦（人間 {selInfo.human_wins} 勝 / AI {selInfo.ai_wins} 勝）。
              マスをクリックで戦いの履歴を表示（再クリックで解除）
            </p>
          </header>
          <div
            className="rounded-[var(--radius)] border p-2"
            style={{ borderColor: "var(--border-1)", background: "var(--surface-1)" }}
          >
            {detail ? (
              <BoardGrid cells={cells} selected={selected} onEnter={onEnter} onClick={onClick} onLeave={NOOP} />
            ) : (
              <div className="flex h-40 items-center justify-center text-sm text-[color:var(--text-muted)]">
                盤を読み込み中...
              </div>
            )}
          </div>
        </div>
      </main>

      {/* 右: 選択マスの詳細 (固定ヘッダー + トグル、 実データ battles) */}
      <ResizeHandle onMouseDown={right.onMouseDown} />
      <div className="log-scroll shrink-0 overflow-y-auto border-l" style={{ width: right.width, borderColor: "var(--border-1)" }}>
        <CellPanel
          cell={active}
          idx={activeIdx}
          leaders={leaders}
          hoverEnabled={hoverEnabled}
          onToggleHover={() => setHoverEnabled((v) => !v)}
          realBattles
        />
      </div>
    </div>
  );
}
