"""共振总表：放在看板根目录（菜单最上面），把各张图对同一件事的看法排在一起，看哪些同向（共振）、哪些打架。

不另算任何统计：只读各图已经算好的结果（results/boardN.json）。方向词和合起来的词见 defs.py「共振总表」一节。
一件事的方向只从三种地方来：「有用」「有点用」的规律、已经响了的报警、四年周期的年份规律；其余一律「说不准」。
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from topics import TOPICS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board0.json"
WORKS = K.VERDICT_WORDS[:2]          # 有用、有点用
N = {t["键"]: t["名"] for t in TOPICS}   # 各图的名字只在 topics.py 写一次


def load(key):
    return json.loads((ROOT / "results" / f"{key}.json").read_text())["显示"]


def op(fig, kind, d, text, why):
    """一张图的一个看法。d：+1 看涨/风险高，-1 看跌/风险低，0 说不准。"""
    word = K.RES_UP[kind] if d > 0 else K.RES_DOWN[kind] if d < 0 else K.RES_NONE
    return {"图": fig, "向": word, "号": d, "字": text, "依据": why}


def row_by(rows, prefix):
    return next(r for r in rows if r["名"].replace("\n", "").startswith(prefix))


def pct_gt(a, b):
    return int(a.rstrip("%")) > int(b.rstrip("%"))


def plain(none, up_word, pct, base, verdict, label="上涨概率"):
    """先说结论、数字放括号（2026-11-19：「油价大涨后 1 年标普更高 75%，跟平时一样」读不懂）。
    跟平时一样就直说「没影响 / 说不准」；比平时高或低就说「更容易 X」。"""
    if verdict not in WORKS:
        head = none
    else:
        head = up_word[0] if pct_gt(pct, base) else up_word[1]
    return f"{head}（{label} {pct}，平时 {base}）"


def stage_op(c3, asset, name, kind="资产"):
    """景气与衰退：现在这个阶段，历史上这个阶段之后 1 年这件资产更容易涨还是更难涨；只认「有用」「有点用」。"""
    w, pct, base = c3[f"{asset}判断"], c3[asset], c3[f"{asset}平时"]
    d = 0 if w not in WORKS else (1 if pct_gt(pct, base) else -1)
    st = c3["名"]
    return op(N["board3"], kind, d,
              f"景气阶段对{name}没影响" if d == 0 else
              plain("", (f"在{st}阶段，{name}更容易涨", f"在{st}阶段，{name}更难涨"), pct, base, w),
              f"{N['board3']}：落在{st}阶段的月份，1 年后{asset}更高 {c3[asset + '次数']}；平时 {base}")


def fin_op(b7, kind):
    """金融状况：信用利差一年扩大、金融状况比平时紧，哪条响了就看那条规律的表（美股看「1 年后标普更高」两行，衰退看「当时或 2 年内有衰退」两行）；
    只认「有用」「有点用」，两条同时响了又方向相反就说不准。"""
    g = b7["金融"]
    sig = {s["名"]: s for s in g["信号"]}
    rows = g["行"]
    a, b = (1, 3) if kind == "资产" else (0, 2)
    rules = [("信用利差扩大", sig["利差比一年前"]["报警"], rows[a]), ("金融状况变紧", sig["金融状况指数"]["报警"], rows[b])]
    act = [(n, r) for n, on, r in rules if on]
    fig = N["board7"]
    if not act:
        return op(fig, kind, 0, "钱不紧、信用利差没扩大，没有信号", f"{fig}：利差一年扩大超 1 点、指数高于 0 才算信号")
    ds = [0 if r["判断"] not in WORKS else (1 if pct_gt(r["比例"], r["平时"]) else -1) for _, r in act]
    d = ds[0] if len(set(ds)) == 1 else 0
    if kind == "资产":
        words, label = (lambda n: (f"{n}后美股更容易涨", f"{n}后美股更容易跌")), "上涨概率"
        none = lambda n: f"{n}对美股没影响"
    else:
        words, label = (lambda n: (f"{n}后更容易衰退", f"{n}后更不容易衰退")), "衰退概率"
        none = lambda n: f"{n}对衰退没影响"
    text = "；".join(plain(none(n), words(n), r["比例"], r["平时"], r["判断"], label) for n, r in act)
    return op(fig, kind, d, text, f"{fig}：" + "；".join(f"{n} {r['之后']}，平时 {r['平时']}" for n, r in act))


def join(ops):
    signs = {o["号"] for o in ops if o["号"]}
    n = sum(1 for o in ops if o["号"])
    if not signs:
        return K.RES_JOIN[3], 0
    if len(signs) == 2:
        return K.RES_JOIN[1], 0
    return (K.RES_JOIN[0] if n >= 2 else K.RES_JOIN[2]), signs.pop()


def year_dir(word):
    return 1 if word in ("涨", "偏涨") else -1 if word in ("跌", "偏跌", "见顶") else 0


def opinions(today):
    b1, b2, b3 = load("board1"), load("board2"), load("board3")
    b4, b5, b6, b7 = load("board4"), load("board5"), load("board6"), load("board7")
    # 四年周期：明年那一列
    t1 = b1["总表"]
    # 明年那一列；表上没有明年（比如表只排到今年）就找同一种周期年份（四年一轮，年份除以 4 的余数相同）
    i = next((j for j, c in enumerate(t1["列"]) if c.get("年") == today.year + 1),
             next(j for j, c in enumerate(t1["列"]) if c.get("年") % 4 == (today.year + 1) % 4))
    cell = {r["名称"]: r["格子"][i] for r in t1["行"]}
    yy = f"{(today.year + 1) % 100}年"
    # 利率周期：利率曲线、失业率预警
    sig2 = {s["名"]: s for s in b2["利率"]["信号"]}
    curve_row = row_by(b2["利率"]["行"], "曲线为正")
    hit2 = [n for n, s in sig2.items() if s["报警"]]
    curve_pos = float(sig2["利率曲线"]["值"]) > 0
    # 景气与衰退：现在在哪个阶段、两个衰退报警
    g3 = b3["景气"]
    c3 = next(c for c in g3["阶段"] if c["名"] == g3["现在"]["阶段"])
    hit3 = [s["名"] for s in g3["信号"] if s["报警"]]
    # 比特币周期：跌破 200 周均线
    s4 = {s["名"]: s for s in b4["节奏"]["信号"]}
    r4 = row_by(b4["规律"]["行"], "跌破 200 周均线1 年后")
    # 黄金：离历史最高
    s5 = b5["现在"]["信号"][0]
    r5 = row_by(b5["规律"]["行"], "金价从最高跌超两成")
    # 原油：油价比一年前、离 5 年最高
    s6 = {s["名"]: s for s in b6["现在"]["信号"]}
    rows6 = b6["规律"]["行"]
    r6rec, r6hi = row_by(rows6, "油价一年涨超五成当时或"), row_by(rows6, "其中创了5年新高")
    r6sp, r6oil = row_by(rows6, "油价一年涨超五成1 年后标普"), row_by(rows6, "油价一年涨超五成1 年后油价")
    shock, high = s6["油价比一年前"]["报警"], s6["离5年最高"]["报警"]

    sp_c, nq_c, bt_c = cell["标普"], cell["纳指"], cell["比特币"]
    out = {}
    out["美股"] = [
        op(N["board1"], "资产", year_dir(sp_c["字"]), f"{yy}标普{sp_c['字']}、纳指{nq_c['字']}（四年周期）",
           f"{N['board1']}明年那一列：{sp_c['依据'].split('；')[0].split('、')[0]}；"
           f"纳指 {nq_c['依据'].split('：', 1)[-1].split('；')[0].split('、')[0]}。按日历年算"),
        stage_op(c3, "标普", "美股"),
        fin_op(b7, "资产"),
    ]
    if shock:
        out["美股"].append(op(N["board6"], "资产", 0 if r6sp["判断"] not in WORKS else (1 if pct_gt(r6sp["比例"], r6sp["平时"]) else -1),
                            plain("油价大涨对美股没影响", ("油价大涨后美股更容易涨", "油价大涨后美股更容易跌"),
                                  r6sp["比例"], r6sp["平时"], r6sp["判断"]),
                            f"{N['board6']}：油价一年涨超五成以后 1 年标普更高 {r6sp['之后']}，平时 {r6sp['平时']}"))
    out["衰退"] = [
        op(N["board2"], "衰退", 1 if hit2 else (-1 if curve_pos and curve_row["判断"] in WORKS else 0),
           f"{'、'.join(hit2)}报警了" if hit2 else (f"利率曲线为正，1 年内衰退风险低（{curve_row['之后']} 次没衰退）" if curve_pos else "利率曲线倒挂，报警没响"),
           N["board2"] + "：" + (f"{'、'.join(hit2)}报警，历史上衰退多半已开始或 1 年内开始" if hit2 else
                      f"利率曲线 {sig2['利率曲线']['值']}；曲线为正时 1 年内不衰退 {curve_row['之后']}，"
                      f"平时 {curve_row['平时']}，{curve_row['判断']}。说的是 1 年内")),
        op(N["board3"], "衰退", 1 if hit3 else 0, f"{'、'.join(hit3)}报警了" if hit3 else "两个衰退报警都没响",
           N["board3"] + "：长短利率差倒挂、活动指数跌破报警线，历史上衰退多半跟着来；没响就给不出方向"),
        fin_op(b7, "衰退"),
    ]
    if shock:
        r = r6hi if high else r6rec
        out["衰退"].append(op(N["board6"], "衰退", 0 if r["判断"] not in WORKS else (1 if pct_gt(r["比例"], r["平时"]) else -1),
                            plain("油价大涨对衰退没影响", (f"月均油价一年涨 {s6['油价比一年前']['值'].lstrip('+')}，2 年内更容易衰退",
                                                          "油价大涨后更不容易衰退"),
                                  r["比例"], r["平时"], r["判断"], "衰退概率"),
                            f"{N['board6']}：{r['名'].replace(chr(10), '，')} {r['之后']}，平时 {r['平时']}，{r['判断']}。说的是当时或 2 年内"))
    else:
        out["衰退"].append(op(N["board6"], "衰退", 0, "油价没涨超五成", N["board6"] + "：油价一年涨超五成才算信号"))
    out["比特币"] = [
        op(N["board1"], "资产", year_dir(bt_c["字"]), f"{yy}比特币{bt_c['字']}（四年周期）", f"{N['board1']}明年那一列：{bt_c['依据'].split('；')[0]}。按日历年算"),
        op(N["board4"], "资产", (1 if pct_gt(r4["比例"], r4["平时"]) else -1) if s4["比200周均线"]["报警"] and r4["判断"] in WORKS else 0,
           (f"跌破 200 周均线，以前 {r4['之后'].split('/')[1]} 次 1 年后"
            + ("都更高" if r4["之后"].split("/")[0] == r4["之后"].split("/")[1] else f"有 {r4['之后'].split('/')[0]} 次更高")
            + f"（平时 {r4['平时']}）") if s4["比200周均线"]["报警"] else "没跌破 200 周均线",
           f"{N['board4']}：跌破 200 周均线以后 1 年价格更高 {r4['之后']}，平时 {r4['平时']}，{r4['判断']}"),
    ]
    out["黄金"] = [
        stage_op(c3, "黄金", "金价"),
        op(N["board5"], "资产", (1 if pct_gt(r5["比例"], r5["平时"]) else -1) if s5["报警"] and r5["判断"] in WORKS else 0,
           plain("金价跌超两成，之后涨跌说不准", ("金价跌超两成后更容易涨", "金价跌超两成后更难涨"), r5["比例"], r5["平时"], r5["判断"])
           if s5["报警"] else f"常说的规律都预测不了金价（月均价离最高 {s5['值']}）",
           N["board5"] + "：衰退、降息、实际利率这几条对黄金都跟平时一样；跌超两成才有一条有点用的规律"),
    ]
    out["原油"] = [
        stage_op(c3, "原油", "油价"),
        op(N["board6"], "资产", 0 if not shock or r6oil["判断"] not in WORKS else (1 if pct_gt(r6oil["比例"], r6oil["平时"]) else -1),
           plain("油价大涨后，接下来油价说不准", ("油价大涨后更容易接着涨", "油价大涨后更容易回落"),
                 r6oil["比例"], r6oil["平时"], r6oil["判断"]) if shock else "油价没涨超五成，没有信号",
           f"{N['board6']}：油价一年涨超五成以后 1 年油价更高 {r6oil['之后']}，平时 {r6oil['平时']}"),
    ]
    return out


NAMES = {"美股": "美股 · 接下来一年", "衰退": "衰退 · 接下来一两年", "比特币": "比特币 · 接下来一年",
         "黄金": "黄金 · 接下来一年", "原油": "原油 · 接下来一年"}


def so_line(groups):
    """对现在：先说共振、再说打架、再说单张，最后列说不准的。"""
    parts, none = [], []
    for q, g in groups.items():
        dirs = [o for o in g["看法"] if o["号"]]
        if g["合起来"] == K.RES_JOIN[0]:
            parts.append((0, f"{q}{dirs[0]['向']}（{len(dirs)} 张图都这么说）"))
        elif g["合起来"] == K.RES_JOIN[1]:
            parts.append((1, f"{q}：图和图打架"))
        elif g["合起来"] == K.RES_JOIN[2]:
            parts.append((2, f"{q}{dirs[0]['向']}（只有{dirs[0]['图']}）"))
        else:
            none.append(q)
    text = "；".join(t for _, t in sorted(parts, key=lambda x: x[0]))
    if none:
        text += ("；" if text else "") + "、".join(none) + "说不准"
    hot = any(g["合起来"] == K.RES_JOIN[1] for g in groups.values()) or any(
        g["合起来"] == K.RES_JOIN[0] and g["方向"] > 0 and q == "衰退" for q, g in groups.items())
    return {"字": "对现在：" + text, "色": "顶" if hot else "平",
            "依据": "只算有用的规律和响了的报警。打架的常常是说的时间长短不同"}


def b3_stage():
    """表顶一行：现在的景气阶段，句子和「什么变了会转阶段」都由景气与衰退那页算好，这里只搬过来。"""
    return load("board3")["景气"]["总表句"]


def build():
    today = dt.date.today()
    ops = opinions(today)
    groups = {}
    for q, g in ops.items():
        word, sign = join(g)
        kind = "衰退" if q == "衰退" else "资产"
        groups[q] = {"名": NAMES[q], "看法": g, "合起来": word, "方向": sign,
                     "合起来字": word + (f"：{K.RES_UP[kind] if sign > 0 else K.RES_DOWN[kind]}" if sign else ""),
                     "依据": "、".join(f"{o['图']}{o['向']}" for o in g)}
    so = so_line(groups)
    how = K.legend(["看涨", "看跌", "风险高", "风险低", "说不准", "共振", "打架", "单张"])
    display = {"现在": {"标题": "共振总表", "副标题": "各图对同一件事怎么看", "阶段": b3_stage(), "对现在": so,
                        "事": list(groups.values()), "怎么读": how},
               "数据截至": None}   # 只读各图的结果，不另取数据
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": {}}, ensure_ascii=False, indent=1))
    return display


if __name__ == "__main__":
    d = build()["现在"]
    print(d["对现在"]["字"])
    for g in d["事"]:
        print(g["名"], g["合起来字"])
        for o in g["看法"]:
            print("   ", o["图"], o["向"], o["字"])
