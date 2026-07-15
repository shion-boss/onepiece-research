// VSCode 風の下部ステータスバー (青)。 WorkspaceShell の最下段に flex 子として置く
// (対戦中の full-screen ではシェルごと非表示になるのでここでは path 判定不要)。
export function StatusBar() {
  return (
    <footer
      className="flex h-6 shrink-0 items-center gap-4 px-3 text-[11px] text-white"
      style={{ background: "var(--status-bar)" }}
    >
      <span className="font-medium">OPTCG</span>
      <span className="opacity-90">環境: OP16</span>
      <span className="ml-auto opacity-90">AI: ExploitBeam</span>
      <span className="opacity-90">公式準拠 100%</span>
    </footer>
  );
}
