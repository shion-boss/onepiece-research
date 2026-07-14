"use client";

import { Treemap, ResponsiveContainer } from "recharts";

// 陣取り treemap: 面積 = 対戦数、 塗り = 人間勝率 (人間色 vs AI色)、 画像 = リーダーの柄。
export type TerritoryItem = {
  id: string; // 表示画像の card_id (= 最後に戦った人の柄。 seed では base id)
  name: string;
  matches: number; // 対戦数 (= 面積)
  win: number; // 人間勝率 0..1
  neutral: boolean; // 低データ (未開拓) = グレー
};

const HUMAN = "#4ec9b0"; // accent
const AI = "#f14c4c"; // danger
const NEUTRAL = "#6a6a72";

// recharts Treemap の custom node。 node props に元データ (name/win/id/neutral/matches) が spread される。
function Node(props: {
  x: number; y: number; width: number; height: number; index: number;
  name?: string; win?: number; id?: string; neutral?: boolean;
}) {
  const { x, y, width, height, index } = props;
  if (!(width > 0) || !(height > 0)) return null;
  const win = props.win ?? 0.5;
  const neutral = props.neutral ?? false;
  const lead = win >= 0.5;
  const territory = neutral ? NEUTRAL : lead ? HUMAN : AI;
  const clipId = `tm-clip-${index}`;
  const showLabel = width > 52 && height > 36;
  const showImg = width > 16 && height > 16 && props.id;
  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <rect x={x} y={y} width={width} height={height} rx={3} />
        </clipPath>
      </defs>
      {showImg && (
        <image
          href={`/cards/${props.id}.png`}
          x={x}
          y={y - height * 0.12}
          width={width}
          height={height * 1.24}
          preserveAspectRatio="xMidYMid slice"
          clipPath={`url(#${clipId})`}
          opacity={0.92}
        />
      )}
      {/* territory tint (勝ってる側の色でマスを染める、 差が大きいほど濃い) */}
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={territory}
        opacity={neutral ? 0.5 : 0.25 + Math.abs(win - 0.5) * 0.6}
        clipPath={`url(#${clipId})`}
      />
      {/* 勝率バー (下端: 人間色の割合 = 人間勝率) */}
      {!neutral && height > 10 && (
        <>
          <rect x={x} y={y + height - 4} width={width} height={4} fill={AI} clipPath={`url(#${clipId})`} />
          <rect x={x} y={y + height - 4} width={width * win} height={4} fill={HUMAN} clipPath={`url(#${clipId})`} />
        </>
      )}
      <rect x={x} y={y} width={width} height={height} rx={3} fill="none" stroke="#1f1f1f" strokeWidth={1} />
      {showLabel && (
        <text x={x + 5} y={y + 15} fill="#fff" fontSize={11} fontWeight={700} style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 2 }}>
          {(props.name ?? "").length > 9 ? (props.name ?? "").slice(0, 9) + "…" : props.name}
        </text>
      )}
      {showLabel && !neutral && (
        <text x={x + 5} y={y + 28} fill="#fff" fontSize={10} fontWeight={600} style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 2 }}>
          {Math.round(win * 100)}%
        </text>
      )}
    </g>
  );
}

export function TerritoryTreemap({ items, height = 560 }: { items: TerritoryItem[]; height?: number }) {
  // matches>0 のみ (treemap は size>0 必須)。 大きい順は recharts が squarify。
  const data = items.filter((it) => it.matches > 0);
  if (data.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-[color:var(--text-muted)]">
        まだ対戦データがありません
      </div>
    );
  }
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Treemap
          data={data}
          dataKey="matches"
          nameKey="name"
          isAnimationActive={false}
          stroke="#1f1f1f"
          content={<Node x={0} y={0} width={0} height={0} index={0} />}
        />
      </ResponsiveContainer>
    </div>
  );
}
