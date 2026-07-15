"use client";

import useSWR from "swr";
import {
  fetchTerritoryBoard,
  fetchTerritoryCell,
  fetchTerritoryBattles,
  type TerritoryBoard,
  type TerritoryCell,
  type TerritoryBattle,
} from "./api";

// 盤全体: ゆっくりポーリング (占領は数分オーダー) + タブ復帰時に更新。
// → ページ再読み込み不要で「常に最新」を保つ。
export function useTerritoryBoard(initial?: TerritoryBoard) {
  const { data, error, isLoading, mutate } = useSWR<TerritoryBoard>(
    "territory-board",
    fetchTerritoryBoard,
    {
      refreshInterval: 20_000,
      revalidateOnFocus: true,
      dedupingInterval: 5_000,
      keepPreviousData: true,
      fallbackData: initial,
    },
  );
  return { board: data, error, isLoading, refresh: mutate };
}

// 選択中マスの戦い履歴 (= CellPanel で実データ表示)。 cellId=null なら fetch しない。
export function useTerritoryBattles(cellId: number | null) {
  const { data } = useSWR<TerritoryBattle[]>(
    cellId != null ? ["territory-battles", cellId] : null,
    () => fetchTerritoryBattles(cellId as number),
    { revalidateOnFocus: true, dedupingInterval: 5_000 },
  );
  return data;
}

// 挑戦中のマス: version だけ短間隔ポーリング (= 対戦中に他人が先に奪取した race を検知)。
// cellId=null の間はポーリングしない (SWR key null)。
export function useTerritoryCell(cellId: number | null, { active = true } = {}) {
  const { data, mutate } = useSWR<TerritoryCell>(
    cellId != null && active ? ["territory-cell", cellId] : null,
    () => fetchTerritoryCell(cellId as number),
    {
      refreshInterval: 4_000,
      revalidateOnFocus: true,
      dedupingInterval: 1_500,
    },
  );
  return { cell: data, refresh: mutate };
}
