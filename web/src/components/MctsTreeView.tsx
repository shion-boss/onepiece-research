"use client";

import type { McctsNode } from "@/lib/types";

/**
 * MCTS の思考ツリー (= 1 アクション選択時の root) を recursive 描画。
 * 各 node: action label + visits + avg_value + chosen ハイライト。
 * visits 数で枝の濃さ可視化。
 */
export function MctsTreeView({ root }: { root: McctsNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mb-2 flex items-center gap-3">
        <div>
          <span className="font-medium">root</span>
          <span className="ml-2 text-zinc-500">
            visits {root.visits} / avg {root.avg_value.toFixed(2)}
          </span>
        </div>
        <div className="text-[10px] text-zinc-500">
          (child の visits 順 / 緑=最終選択)
        </div>
      </div>
      <ul className="space-y-1">
        {root.children.map((child, i) => (
          <NodeRow key={i} node={child} depth={1} maxVisits={root.visits} />
        ))}
      </ul>
      {root.children.length === 0 && (
        <div className="text-zinc-500">
          子なし (= MCTS が action 選択を skip、 既存挙動)
        </div>
      )}
    </div>
  );
}

function NodeRow({
  node,
  depth,
  maxVisits,
}: {
  node: McctsNode;
  depth: number;
  maxVisits: number;
}) {
  const visitRatio = maxVisits > 0 ? node.visits / maxVisits : 0;
  // visit 比率で背景色を濃く
  const bgIntensity = Math.round(visitRatio * 200);
  const bgStyle = node.is_chosen
    ? "bg-green-100 dark:bg-green-900/40 ring-2 ring-green-500"
    : `bg-blue-50 dark:bg-blue-950/30`;
  const valueColor =
    node.avg_value >= 0.6
      ? "text-emerald-600 dark:text-emerald-400"
      : node.avg_value <= 0.4
        ? "text-red-600 dark:text-red-400"
        : "text-zinc-600 dark:text-zinc-400";

  return (
    <li>
      <div
        className={`flex items-center gap-2 rounded px-2 py-1 ${bgStyle}`}
        style={{ marginLeft: `${(depth - 1) * 16}px` }}
      >
        {/* visit bar */}
        <div className="h-2 w-12 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
          <div
            className="h-full bg-blue-500"
            style={{ width: `${Math.max(2, visitRatio * 100)}%` }}
            title={`visits ${node.visits}/${maxVisits}`}
          />
        </div>
        <span className="font-mono text-[11px] text-zinc-700 dark:text-zinc-300 min-w-0 truncate">
          {node.action_label}
        </span>
        <span className="ml-auto flex shrink-0 gap-2 text-[11px]">
          <span className="text-zinc-500">v={node.visits}</span>
          <span className={`font-bold ${valueColor}`}>
            {node.avg_value.toFixed(2)}
          </span>
          {node.is_chosen && (
            <span className="rounded bg-green-600 px-1 text-white">★ 選択</span>
          )}
          {node.n_children > 0 && (
            <span className="text-zinc-400">+{node.n_children} 孫</span>
          )}
        </span>
      </div>
      {node.children.length > 0 && (
        <ul className="mt-1 space-y-1">
          {node.children.map((c, i) => (
            <NodeRow
              key={i}
              node={c}
              depth={depth + 1}
              maxVisits={node.visits}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
