"""云端这一班没跑成时（.github/workflows/daily.yml 最后一步调用）：在上一次发布的状态文件里记一笔「云端失败」，
菜单下一次同步就橙色提示哪一班、卡在哪一环，不用等 2 天变红才知道（11-25 加）。
下一班跑成功会整份重写状态文件，这一笔自动消失；连着失败会累计「次数」。

用法：python3 -I pipeline/mark_failed.py 环节名
"""
import datetime as dt
import json
import sys
from pathlib import Path

STATUS = Path(__file__).resolve().parent.parent / "看板" / "状态.json"


def mark(step: str, now: dt.datetime = None) -> dict:
    try:
        j = json.loads(STATUS.read_text(encoding="utf-8"))
        assert isinstance(j, dict)
    except (OSError, ValueError, AssertionError):   # 状态文件本身坏了：只写这一笔，菜单读不到「更新」会直接报红
        j = {}
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    prev = j.get("云端失败") if isinstance(j.get("云端失败"), dict) else {}
    j["云端失败"] = {"时间": now.strftime("%Y-%m-%d %H:%M"), "环节": step or "不详", "次数": int(prev.get("次数", 0)) + 1}
    STATUS.write_text(json.dumps(j, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return j["云端失败"]


if __name__ == "__main__":
    print(mark(sys.argv[1] if len(sys.argv) > 1 else ""))
