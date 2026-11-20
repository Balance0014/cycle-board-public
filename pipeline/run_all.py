"""一键全流程（本地和云端都只跑这一个）：下载 → 第二来源核对 → 计算 → 复核对比 → 出图 → 验收。

用法：python pipeline/run_all.py            正常更新
      python pipeline/run_all.py --offline  不下载，用已有数据（调试用）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib  # noqa: E402

import acceptance  # noqa: E402
import crosscheck  # noqa: E402
import fetch  # noqa: E402
import render  # noqa: E402
import review  # noqa: E402
from topics import TOPICS  # noqa: E402


def main():
    offline = "--offline" in sys.argv
    src = fetch.fetch_all(offline=offline)
    print("数据：", "；".join(f"{v['名称']} 到 {v['末日']}" for v in src.values()))
    cross = crosscheck.run()
    print("第二来源核对：", "；".join(f"{c['项目']}{'通过' if c['通过'] else '不通过'}" for c in cross))
    for t in TOPICS:
        importlib.import_module(t["键"]).build()
    changes = review.diff()
    print("待复核：", len(changes), "处")
    print("出图：", render.run())
    fails = acceptance.run()
    if fails:
        print("验收不通过：\n" + "\n".join(fails))
        return 1
    print("验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
