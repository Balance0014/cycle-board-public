"""验收测试：每次出图后必跑。每段检查标明属于哪个题目（with part(键)）：
- 某个题目的检查不过（包括检查程序本身出错），只让那个题目回到上一版，别的题目照常更新（run_all.py）；
- 全看板共用的检查不过，整次更新算失败（云端会发邮件报警，不会把坏图推上去）。
数据新鲜度、旧历史被改、第二来源核对不在这里拦：它们写进状态文件，菜单直接报（fetch.problems、render）。"""
import calendar
import contextlib
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board1 as B  # noqa: E402
import defs as K  # noqa: E402
import fetch  # noqa: E402
from fetch import parse  # noqa: E402
from topics import TOPICS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAILS = []
SO_MAX, READ_MAX = 50, 30   # 「对现在」一句、「怎么读」每条最多几个字（2026-11-19：要直接结论，不写长段）
TIP_MAX = 60                 # 悬停说明每条最多几个字，2026-11-19：要直接结论
# 图三：11-18 两套独立程序各算一遍对上的历史事件（衰退、倒挂），之后不许变
REC_FROZEN = ("1854-12~1854-12;1857-07~1858-12;1860-11~1861-06;1865-05~1867-12;1869-07~1870-12;1873-11~1879-03;"
              "1882-04~1885-05;1887-04~1888-04;1890-08~1891-05;1893-02~1894-06;1896-01~1897-06;1899-07~1900-12;"
              "1902-10~1904-08;1907-06~1908-06;1910-02~1912-01;1913-02~1914-12;1918-09~1919-03;1920-02~1921-07;"
              "1923-06~1924-07;1926-11~1927-11;1929-09~1933-03;1937-06~1938-06;1945-03~1945-10;1948-12~1949-10;"
              "1953-08~1954-05;1957-09~1958-04;1960-05~1961-02;1970-01~1970-11;1973-12~1975-03;1980-02~1980-07;"
              "1981-08~1982-11;1990-08~1991-03;2001-04~2001-11;2008-01~2009-06;2020-03~2020-04")
INV_FROZEN = "1966-09;1969-01;1973-06;1978-12;2000-08;2006-08;2019-06;2022-11"
# 活动指数报警日期不冻结：活动指数每月重算、旧历史会小改；改到让次数变了，复核闸会挂「待复核」
# 图四：11-18 两套独立程序对上的历史「跌破 200 周均线」日子（同一轮熊市只算一次）
BTC_ZONE_FROZEN = "2015-01-14;2018-12-15;2020-03-12;2022-06-13"
# 图五：11-18 两套独立程序对上的金价「从历史最高跌超两成」（每轮第一次跌破的月份）
GOLD_BEAR_FROZEN = "1973-11;1975-09;1980-04;2008-11;2013-05"
# 图六：11-19 两套独立程序对上的油价「比一年前涨超五成」每一轮第一次的月份
OIL_SHOCK_FROZEN = "1974-01;1979-08;1987-07;1990-09;1999-08;2002-12;2004-09;2007-11;2009-12;2017-01;2018-06;2021-03"
OIL_HIGH_FROZEN = "1974-01;1979-08;1990-09;1999-08;2002-12;2004-09;2007-11;2021-03"   # 其中创了 5 年新高的
RATE_EVENTS_FROZEN = "1955-06-30H;1958-02-28C;1958-09-30H;1960-07-31C;1961-11-30H;1967-03-31C;1968-01-31H;1970-03-31C;1971-06-30H;1971-12-31C;1972-05-31H;1973-12-31C;1974-05-31H;1974-10-31C;1975-08-31H;1975-12-31C;1976-07-31H;1977-01-31C;1977-06-30H;1980-05-31C;1980-10-31H;1981-03-31C;1981-05-31H;1981-09-30C;1982-03-31H;1982-07-31C;1983-05-25H;1984-09-20C;1985-02-14H;1985-04-25C;1985-09-06H;1985-12-18C;1987-04-30H;1987-11-04C;1988-03-30H;1989-06-06C;1994-02-04H;1995-07-06C;1997-03-25H;1998-09-29C;1999-06-30H;2001-01-03C;2004-06-30H;2007-09-18C;2015-12-16H;2019-08-01C;2022-03-17H;2024-09-19C"


CUR = [None]   # 正在查哪个题目（题目键）；None＝全看板共用的检查


def check(cond, msg):
    if not cond:
        FAILS.append((CUR[0], msg))


@contextlib.contextmanager
def part(key):
    """一段检查属于哪个题目。这段里检查不过或程序出错（比如那个题目的数据这次没下载到），只记在这个题目头上，
    run_all 据此只让这个题目回到上一版；key=None 的是全看板共用的检查。"""
    CUR[0] = key
    try:
        yield
    except Exception as e:  # noqa: BLE001  任何出错都只算这一段的；共用段里正在查某个题目时出错，算那个题目的（11-25 补）
        who = CUR[0] or key
        FAILS.append((who, f"{who or '全看板'} 的验收程序出错：{type(e).__name__}: {e}"))
    finally:
        CUR[0] = None


def check_word(label, k, n, base, word):
    """「有用 / 有点用 / 跟平时一样」必须和数字对得上，符合词表里的定义（defs.verdict_word）。"""
    d = k / n - base if n else 0
    if word == K.VERDICT_WORDS[0]:
        check(K.verdict(k, n, base), f"{label} 写成「有用」，可没过「比平时强」那一关")
    elif word == K.VERDICT_WORDS[1]:
        check(abs(d) >= K.EDGE - 1e-9, f"{label} 写成「有点用」，可和平时只差 {d * 100:.0f} 个百分点")
    elif word == K.VERDICT_WORDS[2]:
        check(abs(d) < K.EDGE, f"{label} 写成「跟平时一样」，可实际和平时差了 {K.EDGE * 100:.0f} 个百分点以上，词不达意")
    else:
        check(False, f"{label} 用了词表外的词「{word}」")


def check_disclosure():
    """更新频率必须披露（2026-11-20「不要制造任何信息差让读者误解」）：每个数说明多久更新一次、数据到哪天。"""
    for k, s in fetch.SERIES.items():
        check(s.get("频率") in ("每天", "每周", "每月", "不定期"), f"数据「{k}」缺更新频率")
        check(bool(s.get("公布")) and len(s["公布"]) <= 14, f"数据「{k}」缺公布节奏，或超过 14 字")
        check(fetch.is_check_only(k) or bool(s.get("简名")), f"数据「{k}」缺数据清单里用的简名")
    shown = [k for k in fetch.SERIES if not fetch.is_check_only(k)]
    lst = fetch.data_list()
    check(len(lst) == len(shown), f"数据清单有 {len(lst)} 条，应该和看板用到的 {len(shown)} 条数据一一对应")
    for x in lst:
        check(bool(x["名"]) and bool(x["公布"]) and (x["到"] == "没有" or re.fullmatch(r"\d{4}-\d\d(-\d\d)?", x["到"]) is not None),
              f"数据清单这一条不完整：{x}")
    rhythm_words = fetch.RHYTHM_WORDS
    for t in TOPICS:   # 下面这些按题目记（CUR）：一页没写清只让这个题目回到上一版
        if t.get("置顶") or not t["目录"]:
            continue
        CUR[0] = t["键"]
        d = json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]
        check(any(w in str(d.get("最新数据", "")) for w in rhythm_words), f"{t['名']} 的「最新数据」没写多久更新一次：{d.get('最新数据')}")
        for pg, g in d.items():
            if not (isinstance(g, dict) and "标题" in g):
                continue
            if any(k in g for k in ("行", "轮", "阶段", "列")):
                check(any(w in str(g.get("历史更新", "")) for w in ("每年 1 月", K.HIST_LIVE, "每月")),
                      f"{t['名']}「{pg}」的历史表没写多久更新一次")
            for c in g.get("信号", []):
                check(bool(c.get("更新")) and bool(c.get("截至")) and c.get("数据键") in fetch.SERIES
                      and c["更新"] == fetch.updates(c["数据键"]),
                      f"{t['名']} 的报警卡「{c.get('名')}」没写更新频率和数据到哪天，或和数据来源登记的不一致")
    for key, page in (("board5", "现在"), ("board6", "现在")):   # 只有月度价的页，「现在」那行必须写明每月
        CUR[0] = key
        line = json.loads((ROOT / "results" / f"{key}.json").read_text())["显示"][page]["现在"]["字"]
        check("每月" in line, f"{key} 的「现在」那行只有月均价，必须写明每月更新：{line}")
    for f in (ROOT / "build").glob("*.html"):
        if f.name.startswith("xen__"):
            continue
        CUR[0] = f.name.split("__")[0]
        raw = f.read_text()
        for title in re.findall(r'<div class="mod alarm"><div class="mt"><span>(.*?)</span>', raw):
            check(not any(w in title for w in rhythm_words), f"{f.name} 报警信号标题声称了统一的更新频率：{title}（各张卡频率不同，只在卡上写）")
        body = re.sub(r"<(style|script)>.*?</\1>", "", raw, flags=re.S)
        body = re.sub(r"\sdata-link=\"[^\"]*\"", "", body)
        shown_text = html.unescape(re.sub(r"<[^>]+>", " ", body)) + " ".join(html.unescape(x) for x in re.findall(r'data-tip="([^"]*)"', raw))
        check(not re.search(r"[A-Za-z]", shown_text), f"{f.name} 图上有英文字母：{re.findall(r'[A-Za-z]+', shown_text)[:3]}，要换成中文")


def at(rows, d):
    v = None
    for day, x in rows:
        if day > d:
            break
        v = x
    return v


def run(today=None, skip=()):
    FAILS.clear()
    today = today or dt.date.today()
    # 各题目的结果（出错的题目这时已回到上一版）。逐个读：哪个题目的结果读不出或缺页，只记在它头上、先返回，
    # run_all 让它回到上一版再验一轮（11-25 查出：原来这里一出错整次验收崩掉、整个看板不更新）
    LOAD = (("board1", ("总表", "明年")), ("board2", ("利率",)), ("board3", ("景气", "衰退")),
            ("board4", ("节奏", "规律")), ("board5", ("现在", "规律")), ("board6", ("现在", "历次", "规律")),
            ("board7", ("金融",)), ("board0", ("现在",)))
    R = {}
    for key, pages in LOAD:
        with part(key):
            r = json.loads((ROOT / "results" / f"{key}.json").read_text())
            missing = [p for p in pages if not isinstance(r.get("显示", {}).get(p), dict)]
            check(not missing, f"{key} 的结果缺页：{'、'.join(missing)}")
            if not missing:
                R[key] = r
    if any(k not in R and k not in skip for k, _ in LOAD):
        return [(k, m) for k, m in FAILS if k not in skip]
    PH = {k for k, _ in LOAD if k not in R}
    for key, pages in LOAD:   # 回到上一版了还读不出（极少见）：空页顶上，它自己的检查都记在它头上（已跳过），别的题目照常验
        R.setdefault(key, {"显示": {p: {} for p in pages}, "明细": {}})
    res, r2, r3, r4, r5, r6, r7 = (R[k] for k in ("board1", "board2", "board3", "board4", "board5", "board6", "board7"))
    g4, g5 = r3["显示"]["景气"], r3["显示"]["衰退"]
    g6, g7 = r4["显示"]["节奏"], r4["显示"]["规律"]
    g8, g9 = r5["显示"]["现在"], r5["显示"]["规律"]
    g10, g11, g12 = r6["显示"]["现在"], r6["显示"]["历次"], r6["显示"]["规律"]
    g13 = r7["显示"]["金融"]
    g0 = R["board0"]["显示"]["现在"]
    g1, g2, g3 = res["显示"]["总表"], res["显示"]["明年"], r2["显示"]["利率"]
    PAGES = (g0, g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11, g12, g13)
    GK = {id(g): k for k, gs in (("board0", [g0]), ("board1", [g1, g2]), ("board2", [g3]), ("board3", [g4, g5]),
                                  ("board4", [g6, g7]), ("board5", [g8, g9]), ("board6", [g10, g11, g12]),
                                  ("board7", [g13])) for g in gs}
    check(len(GK) == len(PAGES), "验收里的页和题目对照表漏了页")
    # 1 口径表自检
    with part(None):
        check(K.election_day(2024) == K.D(2024, 11, 5) and K.election_day(2026) == K.D(2026, 11, 3)
              and K.election_day(2028) == K.D(2028, 11, 7), "选举日算法错")
        check(K.cycle_year(2026) == 2 and K.cycle_year(2027) == 3 and K.cycle_year(2028) == 0, "周期年算法错")
        check(set(fetch.MAX_AGE) == set(fetch.SERIES), f"新鲜度阈值 fetch.MAX_AGE 和数据 SERIES 对不上（新加的数据要写最多停几天）："
              f"{sorted(set(fetch.MAX_AGE) ^ set(fetch.SERIES))}")
        check(K.direction_label(11, 13) == "涨" and K.direction_label(2, 3) == "偏涨" and K.direction_label(1, 2) == "不稳",
              "涨跌判定规则错")

    # 2 已知事实对得上（防数据源出错）
    with part('board1'):
        nq, btc, eth = B.Series(parse("nasdaq")), B.Series(parse("btc")), B.Series(parse("eth"))
        sp = B.Series(parse("sp500_monthly"), monthly=True)
        known = [(B.year_return(nq, 2022), -0.331, 0.01, "纳指2022"), (B.year_return(btc, 2022), -0.64, 0.03, "比特币2022"),
                 (B.year_return(eth, 2022), -0.68, 0.03, "以太坊2022"), (B.year_return(nq, 2008), -0.405, 0.01, "纳指2008")]
        for got, want, tol, name in known:
            check(got is not None and abs(got - want) <= tol, f"{name} 年涨跌应约 {want:+.1%}，实际 {got}")
        check(B.year_return(sp, 2008) is not None and B.year_return(sp, 2008) < -0.3, "标普2008 应大跌")

    # 3 样本是否穷尽：按数据起点应有的轮数
    with part('board1'):
        st = res["明细"]["周期年统计"]
        for name, s in (("标普", sp), ("纳指", nq), ("比特币", btc), ("以太坊", eth)):
            for c in range(4):
                want = len([y for y in range(s.first.year + 1, today.year) if K.cycle_year(y) == c
                            and (not s.monthly or y > s.first.year)])
                check(st[name][str(c)]["n"] == want, f"{name}{K.CYCLE_NAMES[c]} 样本 {st[name][str(c)]['n']} 轮，应为 {want} 轮")

    # 6 下次减半推算的自检
    with part('board1'):
        check(abs(res["明细"]["下次减半"]["回推2020减半误差块数"]) <= 300, "出块高度推算回推 2020 年减半误差过大")

    # 7 「比平时强才上板」：减半坑不许回到看板上；上了板的「最硬一条」必须真比别的年份高出 EDGE
    with part('board1'):
        tl = disp_tl = res["显示"]["总表"]["时间线"]
        check(not any("坑" in x["名"] for x in disp_tl), "减半坑没过对照关，不能上板")
        q1 = res["明细"]["一季度上涨（各周期年份）"]
        if any(c["周期"] == "大选前一年" and c["成立"] for c in res["显示"]["总表"]["列"]):
            for name, v in q1.items():
                rates = {k: int(a) / int(b) for k, (a, b) in ((k, x.split("/")) for k, x in v.items())}
                mine = rates.pop("大选前一年")
                check(mine >= K.STRONG and mine - max(rates.values()) >= K.EDGE - 1e-9, f"最硬一条里{name}没过对照关")
        for x in tl:
            a, b = x["名"].split()[-1].split("/") if "/" in x["名"] else (0, 0)
            check(int(a) <= int(b), f"时间线 {x['名']} 次数不对")
    # 8 已过去的历史事实不许变（独立复核 11-18 对过）：四次减半前后最大回撤
    with part('board1'):
        dips = [round(d["最大回撤"], 3) for d in res["明细"]["减半坑（不上板）"]["各次"]]
        check(dips == [-0.218, -0.313, -0.521, -0.232], f"减半前后回撤变了：{dips}")

    # 9 图二 利率周期：1954–2025 的每一次第一次加息/降息，11-18 由两套独立程序各算一遍对上，之后不许变
    with part('board2'):
        ev = ";".join(f"{e['日期'][:10]}{e['类']}" for e in r2["明细"]["事件"] if e["日期"][:10] < "2026-01-01")
        check(ev == RATE_EVENTS_FROZEN, "利率周期的历史加息、降息日期变了，要人工核对数据源")
        # 表里的「有用 / 有点用 / 跟平时一样」必须和数字对得上，也必须符合词表里的定义
        judged = r2["明细"]["全部判断"]
        for key, row in zip(r2["明细"]["行键"], r2["显示"]["利率"]["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"利率周期「{row['名']}」", k, n, r2["明细"]["平时"][key], row["判断"])
            check(row["判断"] == judged[key]["判断"], f"利率周期「{row['名']}」图上的词和明细对不上")
        for key, j in judged.items():
            check_word(f"利率周期 {key}", j["k"], j["n"], r2["明细"]["平时"][key], j["判断"])

    # 14 图三 景气与衰退：表格和四格里的判断词同样要和数字对得上
    with part('board3'):
        j3 = r3["明细"]["全部判断"]
        for key, row in zip(r3["明细"]["行键"], g5["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"图三「{row['名']}」", k, n, j3[key]["平时"], row["判断"])
            check(row["判断"] == j3[key]["判断"] and row["平时"] == f"{j3[key]['平时'] * 100:.0f}%",
                  f"图三「{row['名']}」图上的词或平时和明细对不上")
        for c in g4["阶段"]:
            for a_ in K.STAGE_ASSETS:
                j = j3[f"{c['名']}{a_}"]
                check_word(f"图三 {c['名']}阶段 {a_}", j["k"], j["n"], j["平时"], j["判断"])
                check(c[f"{a_}次数"] == f"{j['k']}/{j['n']}" and c[f"{a_}判断"] == j["判断"],
                      f"图三 {c['名']}阶段 {a_} 次数或判断词和明细对不上")
                check(c[a_] == f"{j['k'] / j['n'] * 100:.0f}%" and c[f"{a_}平时"] == f"{j['平时'] * 100:.0f}%",
                      f"图三 {c['名']}阶段 {a_} 的比例或平时和明细对不上")
        check([c["名"] for c in g4["阶段"]] == list(K.STAGE_NAMES), "图三 四个阶段的名字和词表对不上")
        check(all(len([a_ for a_ in K.STAGE_ASSETS if f"{a_}次数" in c]) == 3 for c in g4["阶段"]), "图三 有阶段缺了标普、黄金、原油之一")
        check(g4["现在"]["阶段"] in K.STAGE_NAMES, "图三 现在在哪个阶段认不出")
        line0 = json.loads((ROOT / "results" / "board0.json").read_text())["显示"]["现在"]["阶段"]["字"]
        check(line0.startswith("阶段：") and g4["现在"]["阶段"] in line0, "共振总表 顶上缺「阶段：」那一行，或和景气页的阶段对不上")
        check(line0 == g4["总表句"]["字"], "共振总表 阶段那一行和景气页算的不一样")
    # 15 图四 比特币周期：判断词、和图一同一套顶底、报警开关
    with part('board4'):
        j4 = r4["明细"]["全部判断"]
        for key, row in zip(r4["明细"]["行键"], g7["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"图四「{row['名']}」", k, n, j4[key]["平时"], row["判断"])
            check(row["判断"] == j4[key]["判断"] and row["平时"] == f"{j4[key]['平时'] * 100:.0f}%",
                  f"图四「{row['名']}」图上的词或平时和明细对不上")
        clock = res["明细"]["加密时钟"]["比特币"]
        check(r4["明细"]["周期顶"] == clock["周期顶"] and r4["明细"]["周期底"] == clock["周期底"], "图四的周期顶底和图一的不是同一套")
        check(len(g6["轮"]) == len(clock["周期顶"]) and sum(not c["完"] for c in g6["轮"]) <= 1, "图四 每一轮的表不全或没完的不止一轮")
        check(";".join(x for x in r4["明细"]["均线1年"][str(K.BTC_ZONE)]["事件"] if x < "2026") == BTC_ZONE_FROZEN,
              "图四 历史上跌破 200 周均线的日子变了，要人工核对数据源")
        import board4 as B4
        calm = [{"名": "比200周均线", "报警": False}, {"名": "离这轮顶", "报警": False}]
        hot = [{"名": "比200周均线", "报警": True}, {"名": "离这轮顶", "报警": False}]
        a, b = B4.so_line(calm, g7["行"][1], -0.5, K.BTC_DEEP), B4.so_line(hot, g7["行"][1], -0.5, K.BTC_DEEP)
        check(a["色"] == "平" and b["色"] == "顶" and a["字"] != b["字"], "图四：报警响了，「对现在」却没跟着变")
    # 16 图五 黄金：判断词、历史跌超两成的月份、第一次降息和图二同一套、报警开关
    with part('board5'):
        j5 = r5["明细"]["全部判断"]
        for key, row in zip(r5["明细"]["行键"], g9["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"图五「{row['名']}」", k, n, j5[key]["平时"], row["判断"])
            check(row["判断"] == j5[key]["判断"] and row["平时"] == f"{j5[key]['平时'] * 100:.0f}%",
                  f"图五「{row['名']}」图上的词或平时和明细对不上")
        check(";".join(b["跌破"] for b in r5["明细"]["跌两成"][str(K.GOLD_BEAR)] if b["跌破"] < "2026") == GOLD_BEAR_FROZEN,
              "图五 历史上金价跌超两成的月份变了，要人工核对数据源")
        cuts = [x for x in r2["明细"]["事件"] if x["类"] == "C" and x["日期"][:10] >= K.GOLD_START.isoformat()]
        check(r5["明细"]["降息"]["12"]["n"] == len(cuts), "图五 第一次降息的次数和图二的不是同一套")
        check(sum(not c["完"] for c in g8["轮"]) <= 1, "图五 每一轮的表里没完的不止一轮")
        import board5 as B5
        calm = [{"名": "离历史最高", "报警": False, "值": "-10%"}]
        hot = [{"名": "离历史最高", "报警": True, "值": "-25%"}]
        a, b = B5.so_line(calm, g9["行"], g9["行"][3]), B5.so_line(hot, g9["行"], g9["行"][3])
        check(a["色"] == "平" and b["色"] == "顶" and "跌超两成" in b["字"] and a["字"] != b["字"], "图五：报警响了，「对现在」却没跟着变")
        gm = [(d, v) for d, v in parse("gold") if d >= K.GOLD_START]
        want5 = [round((v / max(x for _, x in gm[:i + 1]) - 1) * 100, 2) for i, (_, v) in enumerate(gm)][-(K.TREND_MONTHS + 1):]
        for s_ in g8["信号"]:
            check(s_["走势"] == want5, "图五 离历史最高走势图的数和原始数据重算的对不上")
            check(s_["报警"] == (s_["走势"][-1] <= s_["报警线"]), "图五 报警开关和数值对不上")
        page5 = next((ROOT / "build").glob("board5__01*.html"), None)
        if page5:
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', page5.read_text())]
            check(counts == [len(s_["走势"]) for s_ in g8["信号"]], f"图五 走势图画的点数 {counts} 和数据对不上")
    # 17 图六 原油：判断词、历史涨超五成的月份、报警开关、走势重算
    with part('board6'):
        j6 = r6["明细"]["全部判断"]
        for key, row in zip(r6["明细"]["行键"], g12["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"图六「{row['名']}」", k, n, j6[key]["平时"], row["判断"])
            check(row["判断"] == j6[key]["判断"] and row["平时"] == f"{j6[key]['平时'] * 100:.0f}%",
                  f"图六「{row['名']}」图上的词或平时和明细对不上")
        check(";".join(x for x in r6["明细"]["涨超五成"][str(K.OIL_SHOCK)] if x < "2026") == OIL_SHOCK_FROZEN,
              "图六 历史上油价涨超五成的月份变了，要人工核对数据源")
        check(";".join(x for x in r6["明细"]["创新高的"][f"{K.OIL_SHOCK}|{K.OIL_HIGH_YEARS}"] if x < "2026") == OIL_HIGH_FROZEN,
              "图六 创 5 年新高的那几轮变了，要人工核对数据源")
        check(len(g11["轮"]) == len(r6["明细"]["涨超五成"][str(K.OIL_SHOCK)]), "图六 历次表的行数和明细对不上")
        check([c["新高"] == "是" for c in g11["轮"]] == [x in OIL_HIGH_FROZEN for x in r6["明细"]["涨超五成"][str(K.OIL_SHOCK)]],
              "图六 历次表里「5年新高」那一列和明细对不上")
        import board6 as B6
        cases = [("+80%", True, "-5%", False), ("+80%", True, "+3%", True), ("+10%", False, "-30%", False)]
        outs = [B6.so_line([{"名": "油价比一年前", "报警": a1, "值": v1}, {"名": "离5年最高", "报警": a2, "值": v2}], g12["行"])
                for v1, a1, v2, a2 in cases]
        check(outs[0]["色"] == outs[1]["色"] == "顶" and outs[2]["色"] == "平" and "要小心" in outs[0]["字"]
              and "又创 5 年新高" in outs[1]["字"] and "又创 5 年新高" not in outs[0]["字"]
              and "没过五成线" in outs[2]["字"], "图六：报警开关变了，「对现在」却没跟着变")
        om = {(d.year, d.month): v for d, v in parse("oil")}
        oks = sorted(om)[-(K.TREND_MONTHS + 1):]
        seq = sorted(om)

        def hi6(k):
            i = seq.index(k)
            return round((om[k] / max(om[j] for j in seq[i - 12 * K.OIL_HIGH_YEARS:i]) - 1) * 100, 2)
        want6 = {"油价比一年前": [round((om[k] / om[(k[0] - 1, k[1])] - 1) * 100, 2) for k in oks],
                 "离5年最高": [hi6(k) for k in oks]}
        for s_ in g10["信号"]:
            check(s_["走势"] == want6[s_["名"]], f"图六 {s_['名']} 走势图的数和原始数据重算的对不上")
            on = s_["走势"][-1] >= s_["报警线"] if s_["名"] == "油价比一年前" else s_["走势"][-1] > s_["报警线"]
            check(s_["报警"] == on, f"图六 {s_['名']} 报警开关和数值对不上")
        page6 = next((ROOT / "build").glob("board6__01*.html"), None)
        if page6:
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', page6.read_text())]
            check(counts == [len(s_["走势"]) for s_ in g10["信号"]], f"图六 走势图画的点数 {counts} 和数据对不上")
    # 19 金融状况：判断词、利差事件月份、指数事件月份、报警开关、走势重算
    with part('board7'):
        j7 = r7["明细"]["全部判断"]
        for key, row in zip(r7["明细"]["行键"], g13["行"]):
            k, n = map(int, row["之后"].split("/"))
            check_word(f"金融状况「{row['名']}」", k, n, j7[key]["平时"], row["判断"])
            check(row["判断"] == j7[key]["判断"] and row["平时"] == f"{j7[key]['平时'] * 100:.0f}%",
                  f"金融状况「{row['名']}」图上的词或平时和明细对不上")
        baa7, gs7 = dict(parse("baa")), dict(parse("gs10"))
        spr7 = {d: baa7[d] - gs7[d] for d in baa7 if d in gs7}

        def mon(d, k):
            y, m = divmod(d.year * 12 + d.month - 1 - k, 12)
            return dt.date(y, m + 1, 1)

        def chg7(d):
            a = mon(d, 12)
            return spr7[d] - spr7[a] if d in spr7 and a in spr7 else None
        for th_s, evs in r7["明细"]["利差事件"].items():
            th = float(th_s)
            check(len(evs) > 0, f"金融状况 信用利差一年扩大超 {th:g} 的事件一个都没有，查的地方可能错了")
            for m in evs:
                d = dt.date(int(m[:4]), int(m[5:]), 1)
                c = chg7(d)
                check(c is not None and c >= th - 1e-9, f"金融状况 利差事件 {m} 比一年前只多 {c}，不到 {th:g}")
                prev = [chg7(mon(d, j)) for j in range(1, K.EPISODE_GAP + 1)]
                check(all(x is None or x < th - 1e-9 for x in prev), f"金融状况 利差事件 {m} 之前 {K.EPISODE_GAP} 个月里已经出现过，不是第一次")
        nfm = {}
        for d, v in parse("nfci"):
            nfm.setdefault(d.year * 12 + d.month - 1, []).append(v)
        nfm = {k: sum(v) / len(v) for k, v in nfm.items()}
        for th_s, evs in r7["明细"]["指数事件"].items():
            th = float(th_s)
            check(len(evs) > 0, f"金融状况 指数高于 {th:g} 的事件一个都没有，查的地方可能错了")
            for m in evs:
                k = int(m[:4]) * 12 + int(m[5:]) - 1
                check(nfm[k] > th and all(nfm.get(k - j) is None or nfm[k - j] <= th for j in range(1, K.EPISODE_GAP + 1)),
                      f"金融状况 指数事件 {m} 不是第一次高于 {th:g}")
        import board7 as B7
        sig7 = {s["名"]: s for s in g13["信号"]}
        for fake_nf, fake_sp, want in (("-0.5", "-0.2", "钱不紧"), ("+0.3", "+0.2", "钱比平时紧"), ("-0.5", "+1.2", "信用利差一年扩大"),
                                       ("+0.3", "+1.2", "钱紧、信用利差也在扩大")):
            out = B7.so_line([{"名": "金融状况指数", "报警": fake_nf[0] == "+", "值": fake_nf},
                              {"名": "利差比一年前", "报警": fake_sp.lstrip("+") >= "1", "值": fake_sp}], g13["行"])
            check(want in out["字"] and (out["色"] == "平") == (want == "钱不紧") and len(out["字"]) <= SO_MAX,
                  f"金融状况：报警开关变了，「对现在」却没跟着变或太长：{out['字']}")
        nfr = parse("nfci")
        nd, nv = nfr[-1]
        ends7, y, m = [], nd.year, nd.month
        for _ in range(K.TREND_MONTHS):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            ends7.insert(0, dt.date(y, m, calendar.monthrange(y, m)[1]))
        want7 = [round(max((x for x in nfr if x[0] <= d), key=lambda x: x[0])[1], 2) for d in ends7 + [nd]]
        check(sig7["金融状况指数"]["走势"] == want7, "金融状况 指数走势图的数和原始数据重算的对不上")
        km = max(spr7)
        want7b = [round(chg7(mon(km, j)), 2) for j in range(K.TREND_MONTHS, -1, -1)]
        check(sig7["利差比一年前"]["走势"] == want7b, "金融状况 信用利差走势图的数和原始数据重算的对不上")
        for s_ in g13["信号"]:
            check(abs(float(s_["值"]) - s_["走势"][-1]) < 0.006, f"金融状况 {s_['名']} 卡片上的数和走势图最后一点对不上")
        check(sig7["金融状况指数"]["报警"] == (nv > K.FIN_NFCI_LINE) and sig7["利差比一年前"]["报警"] == (want7b[-1] >= K.FIN_SPREAD_JUMP),
              "金融状况 报警开关和数值对不上")
        page7 = next((ROOT / "build").glob("board7__01*.html"), None)
        if page7:
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', page7.read_text())]
            check(counts == [len(s_["走势"]) for s_ in g13["信号"]], f"金融状况 走势图画的点数 {counts} 和数据对不上")
    # 18 共振总表：方向词、合起来的词只用词表里的；合起来按规则重算；「对现在」点到每个共振、打架
    with part('board0'):
        import board0 as B0
        ok_dir = {K.RES_NONE, *K.RES_UP.values(), *K.RES_DOWN.values()}
        for q in g0["事"]:
            for o in q["看法"]:
                check(o["向"] in ok_dir, f"共振总表 {q['名']} 用了词表外的方向词「{o['向']}」")
            check((q["合起来"], q["方向"]) == B0.join(q["看法"]), f"共振总表 {q['名']} 合起来的词和各图方向对不上")
            if q["合起来"] in K.RES_JOIN[:2]:
                check(q["名"].split(" ")[0] in g0["对现在"]["字"], f"共振总表「对现在」漏了 {q['名']}")
        fake = [{"号": 1}, {"号": 1}], [{"号": 1}, {"号": -1}], [{"号": 0}, {"号": 1}], [{"号": 0}]
        check([B0.join(x)[0] for x in fake] == list(K.RES_JOIN), "共振总表 合起来的规则算错")
        d3 = r3["明细"]
        check(";".join(x for x in d3["衰退"] if x < "2026") == REC_FROZEN, "图三 历史衰退日期变了，要人工核对数据源")
        check(";".join(x for x in d3["倒挂"][str(K.INV_GAP)]["事件"] if x < "2026") == INV_FROZEN, "图三 历史倒挂日期变了")

    # 11 用词统一（2026-11-18）：图上的判断词只许用 defs.py 词表里的；旧词出现就不过
    with part(None):
        # 第 11、12 条里会随数据变的检查都按题目记（CUR）：11-24 起一页不合格只让这个题目回到上一版
        allowed = set(K.DIRECTION_WORDS) | {"见顶"}
        CUR[0] = "board1"
        for r in g1["行"] + g2["行"]:
            for c in r["格子"]:
                check(c["字"] in allowed, f"{r['名称']} 格子用了词表外的词「{c['字']}」")
        for c in g1["列"]:
            check(c["结论"] in set(K.YEAR_WORDS.values()) | {"待复核"}, f"年份表头用了词表外的词「{c['结论']}」")
        check(g2["低点"]["判断"] in K.VERDICT_WORDS, f"低点用了词表外的词「{g2['低点']['判断']}」")
        for g in (g3, g5, g7, g9, g12, g13):
            CUR[0] = GK[id(g)]
            for r in g["行"]:
                check(r["判断"] in K.VERDICT_WORDS, f"{r['名']} 用了词表外的词「{r['判断']}」")
        vocab = K.words()
        for g in PAGES:
            CUR[0] = GK[id(g)]
            for line in g["怎么读"]:
                term = line.split("：", 1)[0]
                check(term in vocab or term in ("颜色", "可信度"), f"「怎么读」里的「{term}」不在词表里")
                # 2026-11-19「怎么读信息密度太大」：每条一句短话
                check(len(line) <= READ_MAX, f"「怎么读」这条太长（{len(line)} 字，最多 {READ_MAX}）：{line}")
        shown = {k: json.dumps(json.loads((ROOT / "results" / f"{k}.json").read_text())["显示"], ensure_ascii=False)
                 for k in ("board1", "board2", "board3", "board4", "board5", "board6", "board7", "board0")}
        # 2026-11-18：用词要准确。「1 年后涨 70%」会被读成涨了 70%，比例一律写「上涨概率」「更高」；「随便哪个月」改「所有月份平均」
        for old_word in ("噪音", "弱规律", "最强", "本轮检验", "随便哪个月", "年后涨", "所有月份平均", "看不出",
                         "扩张", "放缓", "收缩"):   # 扩张、放缓、收缩：11-19 景气四格改成增长×通胀四阶段后停用
            for k, txt in shown.items():
                CUR[0] = k
                check(old_word not in txt, f"图上还有已停用的旧词「{old_word}」")

    # 12 不解释也能看懂（2026-11-18）：每张图顶上有「对现在」；报警一响这句话必须跟着变
    with part(None):
        for g in PAGES:
            CUR[0] = GK[id(g)]
            check(g.get("对现在", {}).get("字", "").startswith("对现在："), f"{g['标题']} 缺「对现在」那句话")
            # 2026-11-19「我需要直接结论，不要写长作文」：顶上一句话只写结论加一个关键数，菜单报警也用这句
            if isinstance(g.get("一句话"), dict):
                check(len(g["一句话"]["字"]) <= SO_MAX, f"{g['标题']}「历史规律」那句太长（最多 {SO_MAX} 字）：{g['一句话']['字']}")
            check(len(g.get("对现在", {}).get("字", "")) <= SO_MAX, f"{g['标题']}「对现在」太长（最多 {SO_MAX} 字）：{g['对现在']['字']}")
        # 报警卡都要自带一句菜单栏用的「报警字」（2026-11-19看到「比200周均线低于均线」这种拼出来的话以为出事了）
        def cards(x):
            if isinstance(x, dict):
                if isinstance(x.get("报警"), bool):
                    yield x
                for v in x.values():
                    yield from cards(v)
            elif isinstance(x, list):
                for v in x:
                    yield from cards(v)
        n_cards = 0
        for g in PAGES:
            CUR[0] = GK[id(g)]
            for c in cards(g):
                n_cards += 1
                check(bool(c.get("报警字")), f"{g['标题']} 的报警卡「{c.get('名')}」缺菜单栏用的「报警字」")
        CUR[0] = None
        check(n_cards >= 11 or bool(PH), f"只找到 {n_cards} 张报警卡，应该至少 11 张（利率周期到金融状况），查的地方可能错了")
        # 悬停说明（依据、表头依据）每条一句短话（2026-11-19「我需要直接结论，不要写长作文」）；置顶项目（XEN）同样管
        def tips(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in ("依据", "表头依据") and isinstance(v, str):
                        yield v
                    else:
                        yield from tips(v)
            elif isinstance(x, list):
                for v in x:
                    yield from tips(v)
        n_tips = 0
        for t in TOPICS:
            CUR[0] = t["键"]
            for tip in tips(json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]):
                n_tips += 1
                check(len(tip) <= TIP_MAX, f"{t['名']} 的悬停说明太长（{len(tip)} 字，最多 {TIP_MAX}）：{tip[:20]}…")
        CUR[0] = None
        check(n_tips >= 100, f"只找到 {n_tips} 条悬停说明，应该至少 100 条，查的地方可能错了")
        # 置顶项目（XEN）守同一套字数（2026-11-19「xen 让他自己优化语言表达」）；它的词不是周期模型的，不查词表
        for t in (t for t in TOPICS if t.get("置顶")):
            CUR[0] = t["键"]
            d = json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]
            so = d.get("对现在", {}).get("字", "")
            check(so.startswith("对现在：") and len(so) <= SO_MAX, f"{t['名']}「对现在」缺或太长（{len(so)} 字，最多 {SO_MAX}）：{so}")
            for line in d["怎么读"]:
                check(len(line) <= READ_MAX, f"{t['名']}「怎么读」这条太长（{len(line)} 字，最多 {READ_MAX}）：{line}")
        # 出处（2026-11-19：引用的结论要有出处、点了能跳转）：每个周期题目都要有，网址是正经网页，说明也是一句短话
        for t in TOPICS:
            if t.get("置顶") or not t["目录"]:
                continue
            CUR[0] = t["键"]
            src = K.SOURCES.get(t["键"], [])
            check(src, f"{t['名']} 没有出处行")
            for name, url, note in src:
                check(url.startswith("https://") and len(name) <= 10 and len(note) <= TIP_MAX,
                      f"{t['名']} 的出处「{name}」不合格（要 https 网址、名字 10 字内、说明 {TIP_MAX} 字内）")
        # 复核闸要管到每一页（11-19 查出黄金、原油第一页叫「现在」，和实时那行同名，整页被跳过、历次大跌表改了没人拦）
        import review as R
        for t in TOPICS:
            if t.get("置顶") or not t["目录"]:
                continue
            CUR[0] = t["键"]
            disp = json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]
            seen = {p.split("/")[1] for p, _ in R.flatten(disp)}
            for pg in (k for k, v in disp.items() if isinstance(v, dict) and "标题" in v):
                check(pg in seen, f"{t['名']} 的「{pg}」这一页没进复核闸，上面的结论改了不会拦")
        # 「历史上会怎样」表必须四列齐全：发生概率旁边一定有「平时」对照（11-19 一次批量改词误删过这一列，验收没拦住）
        def tables(x):
            if isinstance(x, dict):
                if isinstance(x.get("表头"), list) and "发生概率" in x["表头"]:
                    yield x
                for v in x.values():
                    yield from tables(v)
            elif isinstance(x, list):
                for v in x:
                    yield from tables(v)
        n_tab = 0
        for t in TOPICS:
            CUR[0] = t["键"]
            for tb in tables(json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]):
                n_tab += 1
                check(tb["表头"][1:] == ["发生概率", "平时", "有没有用"], f"{t['名']} 表头缺列或顺序不对：{tb['表头']}")
        CUR[0] = None
        check(n_tab >= 6, f"只找到 {n_tab} 张「历史上会怎样」表，应该至少 6 张")
        # 用户看到的地方不编「图一、图二」这种号（2026-11-19）：图上、悬停、菜单里的题目名都用名字
        for t in TOPICS:
            CUR[0] = t["键"]
            shown = json.dumps(json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"], ensure_ascii=False)
            hit = re.findall(r"图[一二三四五六七八九十0-9]|第[一二三四五六七八九十0-9、]+张图", shown + t["名"] + t["目录"])
            check(not hit, f"{t['目录'] or t['名']} 给用户看的字里还有编号「{'、'.join(sorted(set(hit)))}」，用题目名")
        CUR[0] = "board3"
        import board3 as B3
        for pg in ("景气", "衰退"):
            so = B3.so_line([{"名": "活动指数", "报警": True}], "滞胀", "x", pg)
            check("已报警" in so["字"] and so["色"] == "顶", f"图三{pg}：报警响了，「对现在」却没跟着变")
            calm = B3.so_line([{"名": "x", "报警": False}], "过热", "x", pg)
            check("已报警" not in calm["字"] and calm["色"] == "平", f"图三{pg}：没报警，「对现在」却写了报警")
        CUR[0] = "board2"
        import board2 as B2
        fake = [{"名": "利率曲线", "报警": True}, {"名": "失业率预警", "报警": False}]
        so = B2.so_line(fake, g3["行"], -0.1)
        check("已报警" in so["字"] and so["色"] == "顶", "报警响了，「对现在」却没跟着变")
        calm = B2.so_line([{"名": "x", "报警": False}], g3["行"], 1.0)
        check("已报警" not in calm["字"] and calm["色"] == "平", "没报警，「对现在」却写了报警")
    # 13 报警卡片的走势图：每个点都用另一段程序从原始数据重算一遍对上；图里画的点数和数据一样多
    with part('board2'):
        dgs, pol, sahm = parse("dgs10"), sorted(parse("target") + parse("target_hi")), parse("sahm")

        now = pol[-1][0]
        ends, y, m = [], now.year, now.month
        for _ in range(K.TREND_MONTHS):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            ends.insert(0, dt.date(y, m, calendar.monthrange(y, m)[1]))
        want = {"利率曲线": [round(at(dgs, d) - at(pol, d), 2) for d in ends + [now]],
                "失业率预警": [round(v, 2) for _, v in sahm[-(K.TREND_MONTHS + 1):]]}
        for s in g3["信号"]:
            check(s["走势"] == want[s["名"]], f"{s['名']} 走势图的数和原始数据重算的对不上")
            check(abs(float(s["值"]) - s["走势"][-1]) < 0.006, f"{s['名']} 卡片上的数和走势图最后一点对不上")
        sv = want["失业率预警"]
        sig = {s["名"]: s for s in g3["信号"]}
        check(sig["失业率预警"]["比上月"] == f"{sv[-1] - sv[-2]:+.2f}" and sig["失业率预警"]["比去年"] == f"{sv[-1] - sv[-13]:+.2f}",
              "失业率预警的比上月、比去年算错")
        page2 = next((ROOT / "build").glob("board2__*.html"), None)
        if page2:
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', page2.read_text())]
            check(counts == [len(s["走势"]) for s in g3["信号"]], f"走势图画的点数 {counts} 和数据对不上")
    # 13c 景气页两张报警卡的走势重算
    with part('board3'):
        # 图三的两张报警卡片同样重算：长短利率差按每月月底（和今天）取每天的数，活动指数取最近 25 个月
        t3, cfr = parse("t10y3m"), parse("cfnai")
        day3 = t3[-1][0]
        ends3, y, m = [], day3.year, day3.month
        for _ in range(K.TREND_MONTHS):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            ends3.insert(0, dt.date(y, m, calendar.monthrange(y, m)[1]))
        want3 = {"长短利率差": [round(at(t3, d), 2) for d in ends3 + [day3]],
                 "活动指数": [round(v, 2) for _, v in cfr[-(K.TREND_MONTHS + 1):]]}
        for s in g4["信号"]:
            check(s["走势"] == want3[s["名"]], f"图三 {s['名']} 走势图的数和原始数据重算的对不上")
            check(abs(float(s["值"]) - s["走势"][-1]) < 0.006, f"图三 {s['名']} 卡片上的数和走势图最后一点对不上")
            check(s["报警"] == (float(s["值"]) <= s["报警线"]), f"图三 {s['名']} 报警开关和数值对不上")
        cv = want3["活动指数"]
        sig3 = {s["名"]: s for s in g4["信号"]}
        check(sig3["活动指数"]["比上月"] == f"{cv[-1] - cv[-2]:+.2f}" and sig3["活动指数"]["比去年"] == f"{cv[-1] - cv[-13]:+.2f}",
              "图三 活动指数的比上月、比去年算错")
    # 13b 比特币页两张报警卡的走势重算
    with part('board4'):
        # 图四两张卡片：200 周均线比值、离历史最高跌了多少，按每月月底（和今天）另算一遍
        bt = parse("btc")
        bd, bv = [x[0] for x in bt], [x[1] for x in bt]
        day4 = bd[-1]
        ends4, y, m = [], day4.year, day4.month
        for _ in range(K.TREND_MONTHS):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            ends4.insert(0, dt.date(y, m, calendar.monthrange(y, m)[1]))

        def ratio4(d):
            i = max(j for j in range(len(bd)) if bd[j] <= d)
            return bv[i] / (sum(bv[i - 7 * j] for j in range(K.BTC_WMA_WEEKS)) / K.BTC_WMA_WEEKS)

        def dd4(d):
            i = max(j for j in range(len(bd)) if bd[j] <= d)
            return (bv[i] / max(bv[:i + 1]) - 1) * 100
        want4 = {"比200周均线": [round(ratio4(d), 2) for d in ends4 + [day4]],
                 "离这轮顶": [round(dd4(d), 2) for d in ends4 + [day4]]}
        for s_ in g6["信号"]:
            check(s_["走势"] == want4[s_["名"]], f"图四 {s_['名']} 走势图的数和原始数据重算的对不上")
            check(s_["报警"] == (s_["走势"][-1] <= s_["报警线"]), f"图四 {s_['名']} 报警开关和数值对不上")
        page4 = next((ROOT / "build").glob("board4__01*.html"), None)
        if page4:
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', page4.read_text())]
            check(counts == [len(s_["走势"]) for s_ in g6["信号"]], f"图四 走势图画的点数 {counts} 和数据对不上")
    # 13d 景气页走势图点数、现在那一格
    with part('board3'):
        page3 = next((ROOT / "build").glob("board3__01*.html"), None)
        if page3:
            raw3 = page3.read_text()
            counts = [len(x.split()) for x in re.findall(r'<polyline points="([^"]*)"', raw3)]
            check(counts == [len(s["走势"]) for s in g4["信号"]], f"图三 走势图画的点数 {counts} 和数据对不上")
            check(raw3.count('class="cell now"') == 1, "图三 四个阶段里「现在」那一格没框出来或框了不止一格")

    # 10 图上不许有手填数字：网页里出现的每个数字，都必须来自程序算出的显示内容
    with part(None):
        #    悬停浮现的说明也算：每个数字同样要来自显示内容；每块说明都要量到位置、落在图里面
        for f in (ROOT / "build").glob("*.html"):
            key = f.name.split("__")[0]
            CUR[0] = key
            pool = json.dumps(json.loads((ROOT / "results" / f"{key}.json").read_text())["显示"], ensure_ascii=False)
            name = next(x["名"] for x in TOPICS if x["键"] == key)          # 右上角「待复核 N 处」的 N 来自复核清单
            pool += f' {sum(1 for c in json.loads((ROOT / "results" / "review.json").read_text())["变动"] if c["图"] == name)}'
            pool += " " + " ".join(n for _, _, n in K.SOURCES.get(key, []))   # 出处说明里的数是外部网页的原话（逐个打开核过），定义只在 defs.SOURCES
            raw = f.read_text()
            tips = [html.unescape(x) for x in re.findall(r'data-tip="([^"]*)"', raw)]
            text = re.sub(r"<style>.*?</style>", "", raw, flags=re.S)
            text = re.sub(r"<[^>]+>", " ", text) + " ".join(tips)
            for num in set(re.findall(r"\d+(?:\.\d+)?", text)):
                check(num in pool, f"{f.name} 里的数字 {num} 不是程序算出来的")
            tj = f.with_suffix(".json")
            got = json.loads(tj.read_text()) if tj.exists() else {"浮现": [], "宽": 0, "高": 0}
            check(len(got["浮现"]) == len(tips), f"{f.name} 有 {len(tips)} 处悬停说明，只量到 {len(got['浮现'])} 处")
            for x in got["浮现"]:
                check(x["w"] > 0 and x["h"] > 0 and x["x"] >= 0 and x["y"] >= 0 and x["x"] + x["w"] <= got["宽"] + 1
                      and x["y"] + x["h"] <= got["高"] + 1, f"{f.name} 悬停区域落在图外：{x['字'][:12]}")
    with part(None):
        check_disclosure()
    return [(k, m) for k, m in FAILS if k not in skip]   # 已经回到上一版的题目，它的检查不算


if __name__ == "__main__":
    fails = run()
    print("验收通过" if not fails else "验收不通过：\n" + "\n".join(f"[{k or '全看板'}] {m}" for k, m in fails))
    sys.exit(1 if fails else 0)
