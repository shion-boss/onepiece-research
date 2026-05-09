# -*- coding: utf-8 -*-
"""pytest 共通設定: プロジェクトルートを sys.path に通す。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
