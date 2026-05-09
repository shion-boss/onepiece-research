"use client";

import { useMemo, useState } from "react";

type Group = {
  header: string;       // "T1 P0" 等
  lines: string[];
};

const TURN_HEADER_RE = /^(T\d+ P[01]):/;

function groupLog(log: string[]): Group[] {
  const out: Group[] = [];
  let cur: Group | null = null;
  for (const line of log) {
    const m = line.match(TURN_HEADER_RE);
    if (m && (!cur || cur.header !== m[1])) {
      cur = { header: m[1], lines: [] };
      out.push(cur);
    }
    if (cur) {
      cur.lines.push(line);
    } else {
      // T0 行など (setup や ゲーム開始ログ)
      cur = { header: "setup", lines: [line] };
      out.push(cur);
    }
  }
  return out;
}

export function MatchLogViewer({ log }: { log: string[] }) {
  const [filter, setFilter] = useState("");
  const groups = useMemo(() => groupLog(log), [log]);

  const filtered = useMemo(() => {
    if (!filter) return groups;
    return groups
      .map((g) => ({
        header: g.header,
        lines: g.lines.filter((l) => l.includes(filter)),
      }))
      .filter((g) => g.lines.length > 0);
  }, [groups, filter]);

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="フィルタ (例: KO / 効果 / TRIGGER / atk)"
        className="w-full rounded border border-zinc-300 bg-transparent px-3 py-1.5 text-sm dark:border-zinc-700"
      />
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        {filtered.length === 0 ? (
          <div className="p-4 text-sm text-zinc-500 dark:text-zinc-400">
            該当行なし
          </div>
        ) : (
          filtered.map((g, i) => (
            <details
              key={i}
              open
              className="border-t border-zinc-200 first:border-t-0 dark:border-zinc-800"
            >
              <summary className="cursor-pointer bg-zinc-50 px-3 py-1.5 text-sm font-medium dark:bg-zinc-900">
                {g.header}{" "}
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  ({g.lines.length})
                </span>
              </summary>
              <pre className="overflow-x-auto whitespace-pre-wrap p-3 font-mono text-xs leading-5 text-zinc-700 dark:text-zinc-300">
                {g.lines.join("\n")}
              </pre>
            </details>
          ))
        )}
      </div>
    </div>
  );
}
