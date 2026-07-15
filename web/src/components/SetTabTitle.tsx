"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { useWorkspace } from "@/lib/workspace";

// ページから現在パスのタブ名を上書きする。 デッキ詳細で slug でなくデッキ名をタブに出す等。
export function SetTabTitle({ title }: { title: string }) {
  const path = usePathname() || "/";
  const setTabTitle = useWorkspace((s) => s.setTabTitle);
  useEffect(() => {
    if (title) setTabTitle(path, title);
  }, [path, title, setTabTitle]);
  return null;
}
