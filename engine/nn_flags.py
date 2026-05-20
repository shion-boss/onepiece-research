# -*- coding: utf-8 -*-
"""NN 有効/無効 切替 用 lightweight context manager (= torch 非依存)。

nn_eval.py から 切り出し (= 2026-05-20)。 GoalDirectedAI 系 が ai_experimental 経由 で
torch を import せず に 済む ため、 Vercel function memory 制限 で OOM 回避 する用。

実 NN inference は nn_eval (= torch 依存) で 行う、 nn_flags は flag 操作 だけ。
"""

from contextlib import contextmanager

_NN_FORCE_DISABLED = False


def is_nn_forced_disabled() -> bool:
    """NN が 強制無効化 されてる か (= nn_eval の get_model() で 参照)。"""
    return _NN_FORCE_DISABLED


@contextmanager
def nn_disabled():
    """NN を 一時的に 強制無効化 する context manager。

    AI の choose_action 内 で 囲うと、 その期間内 の compute_score 呼び出し は
    NN を 経由せず 線形 fallback に 流れる。
    """
    global _NN_FORCE_DISABLED
    saved = _NN_FORCE_DISABLED
    _NN_FORCE_DISABLED = True
    try:
        yield
    finally:
        _NN_FORCE_DISABLED = saved
