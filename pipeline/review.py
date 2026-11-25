"""复核闸：每个题目看板上显示的内容，和它的「已认可版」逐条对比。

- 有变动 → 看板右上角挂「待复核」，菜单栏变橙；不会自己悄悄改掉结论。
- 复核通过后运行：python pipeline/review.py --approve "一句话标题（40 字内）" "细节 1" "细节 2" …
  把所有题目的当前显示存成新的已认可版，并在「改动记录.md」最上面追加一条（菜单栏「改动记录」里能看到）。不写说明不让认可。
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topics import TOPICS  # noqa: E402
NAME = {t["键"]: t["名"] for t in TOPICS}

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = RES / "review.json"
LOG = ROOT / "改动记录.md"
# 不算结论变动的：每天都会变的日期；时间线色块的位置（只是画图用的比例，日期本身在「字」里，变了照样会查出来）；
# 「现在」「信号」是每天跟着数据走的实时状态，不是结论，不用认可（信号报警另有菜单栏提醒）
IGNORE = {"数据截至", "最新数据", "起", "止", "现在", "信号", "对现在", "总表句"}   # 「对现在」由已认可的结论加实时报警拼成，跟着日子走；「最新数据」是菜单里写的数据日期
# 「总表句」＝现在处在哪个阶段（共振总表顶上那行），每月跟着数据变，和「现在」一样是实时状态；不放进来，每次换阶段或缺月
# 都会挂「待复核」，没人维护时菜单就一直橙（11-24 查出）。历史统计、判断词照样要认可
SHOWN = {"字", "数", "结论", "名", "标题", "周期", "之后", "平时", "判断"}   # 写进改动记录的字段（颜色、开关这类跟着字变，不重复记）


def cur_path(t):
    return RES / f"{t['键']}.json"


def approved_path(t):
    return RES / "approved" / f"{t['键']}.json"


def flatten(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            # 第一层是整页（黄金、原油的第一页也叫「现在」）：整页不能被当成「现在」那行跳过，
            # 不然金价历次大跌那张表改了没人管（11-19 查出来补的）
            if k not in IGNORE or (path == "" and isinstance(v, dict) and "标题" in v):
                yield from flatten(v, f"{path}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from flatten(v, f"{path}[{i}]")
    else:
        yield path, x


def diff():
    changes = []
    for t in TOPICS:
        if t.get("置顶") or not cur_path(t).exists():   # 置顶项目不走复核闸（见 xen.py 开头）
            continue
        if not t["目录"]:   # 共振总表全由各题目已认可的结论加实时信号拼成，不单独复核（各题目的结论变了在各自那里拦）
            continue
        if not approved_path(t).exists():
            changes.append({"图": t["名"], "位置": "全部", "原来": None, "现在": "首次生成，尚未认可"})
            continue
        try:
            cur = dict(flatten(json.loads(cur_path(t).read_text())["显示"]))
            old = dict(flatten(json.loads(approved_path(t).read_text())))
        except (OSError, ValueError, KeyError, TypeError) as e:   # 一个题目对比不了：当作有变动、要人看，不拖垮别的题目
            changes.append({"图": t["名"], "位置": "全部", "原来": None, "现在": f"对比不了：{type(e).__name__}"})
            continue
        changes += [{"图": t["名"], "位置": k, "原来": old.get(k), "现在": cur.get(k)}
                    for k in sorted(set(cur) | set(old)) if old.get(k) != cur.get(k)]
    OUT.write_text(json.dumps({"待复核数": len(changes), "变动": changes}, ensure_ascii=False, indent=1))
    return changes


def where(topic, path, disp):
    """把对比路径翻成人话，例如 四年周期 /总表/行[0]/格子[1]/字 → 四年周期 标普 2027年。认不出的照原样写。"""
    try:
        if topic == NAME["board1"]:
            if m := re.match(r"/总表/行\[(\d+)\]/格子\[(\d+)\]", path):
                r, c = map(int, m.groups())
                return f"{topic} {disp['总表']['行'][r]['名称']} {disp['总表']['列'][c]['年']}年"
            if m := re.match(r"/总表/列\[(\d+)\]", path):
                return f"{topic} {disp['总表']['列'][int(m[1])]['年']}年表头"
            if m := re.match(r"/明年/行\[(\d+)\]/格子\[(\d+)\]", path):
                r, q = map(int, m.groups())
                return f"{topic} {disp['明年']['标题']} {disp['明年']['行'][r]['名称']} {q + 1}季度"
            if m := re.match(r"/总表/行\[(\d+)\]", path):
                return f"{topic} {disp['总表']['行'][int(m[1])]['名称']}"
            if m := re.match(r"/明年/行\[(\d+)\]", path):
                return f"{topic} {disp['明年']['标题']} {disp['明年']['行'][int(m[1])]['名称']}"
            for key, name in (("/总表/时间线", "时间线"), ("/总表/失效条件", "失效条件"), ("/总表/怎么读", "怎么读"),
                              ("/明年/低点", "明年 低点"), ("/明年/风险", "明年 要防"), ("/明年/怎么读", "明年 怎么读"),
                              ("/明年/标题", "明年 标题"), ("/明年/周期", "明年 周期")):
                if path.startswith(key):
                    return f"{topic} {name}"
    except (IndexError, KeyError):
        pass
    try:
        if topic == NAME["board2"]:
            if m := re.match(r"/利率/行\[(\d+)\]", path):
                return f"{topic} {disp['利率']['行'][int(m[1])]['名']}"
            for key, name in (("/利率/一句话", "一句话"), ("/利率/表头", "表头"), ("/利率/怎么读", "怎么读")):
                if path.startswith(key):
                    return f"{topic} {name}"
    except (IndexError, KeyError):
        pass
    return f"{topic} {path}"


def approve(note: str, details=()):
    if not note.strip() or len(note) > 40:
        raise SystemExit("认可要写一句 40 字内的标题，细节另写：review.py --approve \"标题\" \"细节1\" \"细节2\"")
    changes = diff()
    disps = {t["名"]: json.loads(cur_path(t).read_text())["显示"] for t in TOPICS
             if not t.get("置顶") and cur_path(t).exists()}
    lines = [f"## {dt.date.today().isoformat()} · {note.strip()}"] + [f"- {x}" for x in details if x.strip()]
    # 版面改了（有格子新增或删掉），按位置逐格对比会把不同的行错位比在一起，写出误导人的记录；这时只认人写的说明
    layout = any(c["原来"] is None or c["现在"] is None for c in changes if c["位置"] != "全部")
    if layout:
        lines.append("- 版面改了，逐格前后对比不适用，以上面几条为准")
    for c in ([] if layout else changes):
        last = re.split(r"[/\[]", c["位置"])[-1]
        if c["位置"] == "全部":
            lines.append(f"- {c['图']}：首次上板")
        elif last in SHOWN or re.search(r"/怎么读\[\d+\]$", c["位置"]):
            lines.append(f"- {where(c['图'], c['位置'], disps[c['图']])}：{c['原来'] if c['原来'] is not None else '（无）'}"
                         f" → {c['现在'] if c['现在'] is not None else '（删掉）'}")
    head, _, rest = LOG.read_text().partition("\n## ") if LOG.exists() else ("# 看板改动记录\n", "", "")
    LOG.write_text(head.rstrip() + "\n\n" + "\n".join(lines) + ("\n\n## " + rest if rest else "\n"))
    for t in TOPICS:
        if t["名"] in disps:
            approved_path(t).parent.mkdir(parents=True, exist_ok=True)
            approved_path(t).write_text(json.dumps(disps[t["名"]], ensure_ascii=False, indent=1))
    return diff()


if __name__ == "__main__":
    if "--approve" in sys.argv:
        i = sys.argv.index("--approve")
        ch = approve(sys.argv[i + 1] if len(sys.argv) > i + 1 else "", sys.argv[i + 2:])
    else:
        ch = diff()
    print("待复核", len(ch), "处")
    for c in ch[:40]:
        print(c["图"], c["位置"], "：", c["原来"], "→", c["现在"])
