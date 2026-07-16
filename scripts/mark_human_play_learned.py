"""人間vsAI ログの matchup を「学習済み」にマークする (= Claude が学習に使った後に実行)。

効果 (ohtsuki 2026-07-16 の運用): 対象 matchup の現在の累計件数を消費 (upto=games) +
学習回数 batches+1 → **ゲージの分母が +10** され、 ゲージが未充填状態に戻る。

使い方:
  # 分子が分母以上 (= 学習ライン到達) の matchup を全部マーク
  .venv/bin/python scripts/mark_human_play_learned.py

  # 特定の matchup を1つマーク (key = 'human__vs__ai')
  .venv/bin/python scripts/mark_human_play_learned.py cardrush_1467__vs__eb04_boney

  # 到達してなくても強制的にマーク (--force + key)
  .venv/bin/python scripts/mark_human_play_learned.py --force cardrush_1467__vs__eb04_boney
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import _aggregate_human_play_stats, _mark_human_play_learned  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    stats = _aggregate_human_play_stats()
    marked = []
    for m in stats["by_matchup"]:
        key = f"{m['human_deck']}__vs__{m['ai_deck']}"
        ready = m["new_games"] >= m["threshold"]
        target = (key in args) if args else ready
        if target and (ready or force):
            res = _mark_human_play_learned(key, m["games"])
            nxt = 10 + 10 * res["batches"]
            marked.append(f"  {key}: 消費 {m['new_games']} 件 (旧分母 {m['threshold']}) "
                          f"→ batches={res['batches']} / 次の分母={nxt}")
    if marked:
        print(f"{len(marked)} matchup を学習済みにマーク:")
        print("\n".join(marked))
    else:
        print("マーク対象なし (学習ライン未到達 / 指定 key 無し。 強制は --force <key>)")


if __name__ == "__main__":
    main()
