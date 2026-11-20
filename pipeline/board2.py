"""图二 利率周期：看板上的每个字、每个数都由这里算出来，写进 results/board2.json。

口径全部来自 defs.py「利率周期」一节；这里只负责按口径计算。
核心问题：美联储现在在周期哪一步；第一次加息之后，股市、利率、经济历史上怎么走；什么信号会翻转结论。
"""
import bisect
import calendar
import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board2.json"


def ym(d):
    return d.year * 12 + d.month - 1


def eom(k):
    y, m = divmod(k + 1, 12)
    return dt.date(y, m + 1, 1) - K.DAY


def monthly(key):
    return {ym(d): v for d, v in parse(key)}


# ── 定日子（口径见 defs.py）──────────────────────────────────────
def date_events(ff, target, ma_k, th_pre):
    """返回 [{日期, 类, 水平, 极值, 时代}]，类 H=第一次加息、C=第一次降息；极值 = 翻转前的最低点（H）或最高点（C）。"""
    months = sorted(k for k in ff if k <= ym(K.TARGET_START))
    ma = {k: sum(ff[j] for j in range(k - ma_k + 1, k + 1)) / ma_k for k in months[ma_k - 1:]}
    ks = sorted(ma)
    events, state, ext = [], "E", ma[ks[0]]

    def step(day, v, th, era):
        nonlocal state, ext
        if state == "E":
            if v < ext:
                ext = v
            elif v - ext >= th - 1e-9:
                events.append({"日期": day, "类": "H", "水平": round(v, 2), "极值": round(ext, 2), "时代": era})
                state, ext = "T", v
        else:
            if v > ext:
                ext = v
            elif ext - v >= th - 1e-9:
                events.append({"日期": day, "类": "C", "水平": round(v, 2), "极值": round(ext, 2), "时代": era})
                state, ext = "E", v

    for k in ks[1:]:
        step(eom(k), ma[k], th_pre, "实际利率")
    ext = target[0][1]                        # 目标利率时代从第一天的目标值重新记极值，状态沿用
    for d, v in target[1:]:
        step(d, v, K.RATE_TH_TARGET, "目标利率")
    return events, ma, state


def confirm(events, i, ma, target):
    """第 i 个事件（H）之后、下一个事件之前，利率有没有涨到 最低点 + RATE_CONFIRM。返回确认日或 None。"""
    e = events[i]
    nxt = events[i + 1]["日期"] if i + 1 < len(events) else dt.date(2100, 1, 1)
    goal = e["极值"] + K.RATE_CONFIRM - 1e-9
    if e["时代"] == "实际利率":
        for k in sorted(ma):
            if ym(e["日期"]) <= k and eom(k) < nxt and ma[k] >= goal:
                return eom(k)
        return None
    return next((d for d, v in target if e["日期"] <= d < nxt and v >= goal), None)


# ── 收益和对照 ─────────────────────────────────────────────────
class Study:
    def __init__(self, today):
        self.today = today
        self.ff = monthly("fedfunds")
        self.rec = monthly("usrec")
        self.gs = monthly("gs10")
        self.target = sorted(parse("target") + parse("target_hi"))
        sp = monthly("sp500_monthly")
        self.sp = {k: v for k, v in sp.items() if k < ym(today)}       # 去掉还没走完的当月
        self.nq = parse("nasdaq")
        self.btc = parse("btc")
        self.start = ym(K.RATE_START)
        self.rec_starts = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k - 1, 0) == 0
                                 and k >= self.start)

    def sp_ret(self, b, h):
        return self.sp[b + h] / self.sp[b] - 1 if b in self.sp and b + h in self.sp else None

    def daily_ret(self, series, d, h):
        ds = [x[0] for x in series]
        i = bisect.bisect_right(ds, d) - 1
        if i < 0:
            return None
        y, m = divmod(d.year * 12 + d.month - 1 + h, 12)
        t = dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))
        if t > ds[-1]:
            return None
        return series[bisect.bisect_right(ds, t) - 1][1] / series[i][1] - 1

    def rec_within(self, k, h):
        return any(k < s <= k + h for s in self.rec_starts)

    def rec_ok(self, k, h):
        """这个月能不能拿来算「h 个月内开始衰退」：当时不在衰退里，且后面 h 个月的衰退数据都出了。"""
        return self.rec.get(k) == 0 and k + h <= max(self.rec)

    # 平时：每个月都当起点
    def base_sp(self, h):
        xs = [self.sp_ret(b, h) for b in range(self.start + 1, max(self.sp) - h + 1)]
        xs = [x for x in xs if x is not None]
        return sum(x > 0 for x in xs) / len(xs)

    def base_rec(self, h):
        ms = [k for k in range(self.start, max(self.rec) - h + 1) if self.rec.get(k) == 0]
        return sum(self.rec_within(k, h) for k in ms) / len(ms)

    def base_gs(self, h):
        xs = [self.gs[k + h] - self.gs[k] for k in range(self.start, max(self.gs) - h + 1)]
        return sum(x > 0 for x in xs) / len(xs)

    def base_daily(self, series, h):
        xs = [self.daily_ret(series, series[i][0], h) for i in range(0, len(series), 21)]
        xs = [x for x in xs if x is not None]
        return sum(x > 0 for x in xs) / len(xs)

    def spread(self, e):
        k = ym(e["日期"])
        return self.gs[k] - (self.ff[k] if e["时代"] == "实际利率" else e["水平"])


def stats_for(S: Study, ma_k, th_pre):
    """按一种定日子做法，算出看板要用的全部统计。"""
    events, ma, state = date_events(S.ff, S.target, ma_k, th_pre)
    hs = [(i, e) for i, e in enumerate(events) if e["类"] == "H"]
    done_h = [(i, e) for i, e in hs if i + 1 < len(events) or confirm(events, i, ma, S.target)]   # 结局已定的
    out = {"事件": events, "状态": state}

    def count(sel, fn):
        vals = [v for v in (fn(e) for e in sel) if v is not None]
        return sum(1 for v in vals if v), len(vals)

    H = [e for _, e in hs]
    sp12 = count(H, lambda e: None if S.sp_ret(ym(e["日期"]) + 1, 12) is None else S.sp_ret(ym(e["日期"]) + 1, 12) > 0)
    sp24 = count(H, lambda e: None if S.sp_ret(ym(e["日期"]) + 1, 24) is None else S.sp_ret(ym(e["日期"]) + 1, 24) > 0)
    nq12 = count(H, lambda e: (lambda r: None if r is None else r > 0)(S.daily_ret(S.nq, e["日期"], 12)))
    gs12 = count(H, lambda e: None if ym(e["日期"]) + 12 not in S.gs else S.gs[ym(e["日期"]) + 12] > S.gs[ym(e["日期"])])
    rec36 = count(H, lambda e: S.rec_within(ym(e["日期"]), 36) if S.rec_ok(ym(e["日期"]), 36) else None)
    pos = [e for e in H if S.spread(e) > 0]
    norec12 = count(pos, lambda e: (not S.rec_within(ym(e["日期"]), 12)) if S.rec_ok(ym(e["日期"]), 12) else None)
    inv = [e for e in H if S.spread(e) <= 0]
    inv_rec = count(inv, lambda e: S.rec.get(ym(e["日期"])) == 1 or S.rec_within(ym(e["日期"]), 12))
    btc = [S.daily_ret(S.btc, e["日期"], 12) for e in H]
    btc = [r for r in btc if r is not None]
    confirmed = sum(1 for i, _ in done_h if confirm(events, i, ma, S.target))
    # 加息被确认（涨够 RATE_CONFIRM）那天起，1 年后标普更高吗？回答「到了确认线怎么办」（2026-11-19）
    k_days = [confirm(events, i, ma, S.target) for i, _ in done_h]
    sp_k = count([d for d in k_days if d], lambda d: None if S.sp_ret(ym(d) + 1, 12) is None else S.sp_ret(ym(d) + 1, 12) > 0)
    # 降息之后：有没有衰退决定股市（事后才分得清）
    C = [e for e in events if e["类"] == "C"]

    def c_rec(e):
        k = ym(e["日期"])
        return S.rec.get(k) == 1 or S.rec_within(k, 12)
    c_sp = [(c_rec(e), S.sp_ret(ym(e["日期"]) + 1, 12)) for e in C if S.rec_ok(ym(e["日期"]), 12) or S.rec.get(ym(e["日期"])) == 1]
    c_norec = [r for rec, r in c_sp if not rec and r is not None]
    c_yesrec = [r for rec, r in c_sp if rec and r is not None]
    out.update({
        "标普12": sp12, "标普24": sp24, "纳指12": nq12, "十年期12": gs12, "三年内衰退": rec36,
        "曲线正一年不衰退": norec12, "曲线倒挂衰退": inv_rec, "比特币12": [round(r, 4) for r in btc],
        "确认": (confirmed, len(done_h)), "确认后标普12": sp_k,
        "降息后标普12_没衰退": (sum(r > 0 for r in c_norec), len(c_norec)),
        "降息后标普12_衰退": (sum(r > 0 for r in c_yesrec), len(c_yesrec)),
        "标普12中位": st.median([S.sp_ret(ym(e["日期"]) + 1, 12) for e in H
                              if S.sp_ret(ym(e["日期"]) + 1, 12) is not None]),
    })
    return out


def month_ends(today, n):
    """最近 n 个月的月底日期（不含本月），再加今天：小走势图的横轴。"""
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(dt.date(y, m, calendar.monthrange(y, m)[1]))
    return sorted(out) + [today]


def last_at(rows, d):
    """rows 按日期排好；d 当天或之前最后一个值。"""
    i = bisect.bisect_right([r[0] for r in rows], d) - 1
    return rows[i][1] if i >= 0 else None


def minus_months(d, k):
    y, m = d.year, d.month - k
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def trend(name, now, month_ago, year_ago, series, alarm, toward_alarm_is_down, nd=2, unit=""):
    """报警卡片上的趋势：箭头、比上月、比去年、离报警线还差多少、最近两年走势。nd 位小数，unit 跟在数后面（如「 点」）。"""
    dm, dy = now - month_ago, now - year_ago
    eps = 0.5 * 10 ** -nd
    arrow = "↑" if dm > eps else "↓" if dm < -eps else "→"
    toward = (dm < -eps) if toward_alarm_is_down else (dm > eps)
    gap = (now - alarm) if toward_alarm_is_down else (alarm - now)
    return {"箭头": arrow, "箭头色": "顶" if toward else "平",
            "比上月": f"{dm:+.{nd}f}{unit}", "比去年": f"{dy:+.{nd}f}{unit}",
            "离报警": f"离报警线还差 {gap:.{nd}f}{unit}" if gap > 0 else "已过报警线",
            "走势": [round(v, 2) for v in series], "报警线": alarm, "报警在下": toward_alarm_is_down,
            "报警月数": sum(1 for v in series[:-1] if (v <= alarm if toward_alarm_is_down else v >= alarm))}


def card_when(key, d, month=False):
    """报警卡上的「多久更新一次、数据到哪天」（2026-11-20）：更新字从 fetch.SERIES 来，各题目共用；按月公布的只写到月。"""
    return {"数据键": key, "更新": updates(key), "截至": f"{d.month}月" if month else f"{d.month}月{d.day}日"}


def so_line(signals, rows, curve_now):
    """对现在：按报警状态和表里的判断词自动写一句大白话。"""
    hit = [s["名"] for s in signals if s["报警"]]
    if hit:
        return {"字": f"对现在：要小心。{'、'.join(hit)}已报警，衰退可能来了",
                "色": "顶", "依据": "报警响时，历史上衰退多半已开始或 1 年内开始"}
    curve_row = next((r for r in rows if r["名"].startswith("曲线为正")), None)
    calm = curve_now > 0 and curve_row and curve_row["判断"] in K.VERDICT_WORDS[:2]
    return {"字": "对现在：不看空。加息不用怕" + ("；曲线为正，一年内衰退可能偏低" if calm else ""),
            "色": "平", "依据": "加息后的涨跌都跟平时一样；两个报警都没响"}


def build():
    target = sorted(parse("target") + parse("target_hi"))
    today = target[-1][0]
    S = Study(today)
    base = {"标普12": S.base_sp(12), "标普24": S.base_sp(24), "纳指12": S.base_daily(S.nq, 12),
            "十年期12": S.base_gs(12), "三年内衰退": S.base_rec(36), "曲线正一年不衰退": 1 - S.base_rec(12)}
    runs = {v: stats_for(S, *v) for v in K.RATE_VARIANTS}
    main = runs[K.RATE_VARIANTS[0]]
    events = main["事件"]

    # ── 表格：每一行 = 一条「第一次加息之后会怎样」，和平时对照，换口径也要站得住 ──
    # 用词统一在 defs.py：有用 / 有点用 / 跟平时一样
    judged = {}
    for key in base:
        k, n = main[key]
        ok = K.verdict(k, n, base[key])
        robust = all(K.verdict(*runs[v][key], base[key]) for v in K.RATE_VARIANTS)
        word = K.verdict_word(k, n, base[key], robust)
        alt = [runs[v][key] for v in K.RATE_VARIANTS[1:]]
        judged[key] = {"k": k, "n": n, "平时": f"{base[key] * 100:.0f}%", "判断": word, "主口径过关": ok,
                       "换算法": [f"{a}/{c}" for a, c in alt],
                       "最小差": min((a / c - base[key]) * 100 for a, c in [(k, n)] + alt)}

    def tail(key):
        j = judged[key]
        if j["判断"] == K.VERDICT_WORDS[1] and j["主口径过关"]:
            return "。换算法优势变小，只算有点用"
        if j["判断"] == K.VERDICT_WORDS[1]:
            return f"。成立不到 {K.STRONG * 100:.0f}%，只算有点用"
        return ""

    J = judged
    why = {
        "标普12": f"{J['标普12']['n']} 次第一次加息里，{J['标普12']['k']} 次 12 个月后标普更高；平时 {J['标普12']['平时']}。"
                 f"看 2 年也一样：{J['标普24']['k']}/{J['标普24']['n']}，平时 {J['标普24']['平时']}",
        "纳指12": f"1972 年起 {J['纳指12']['n']} 次里，{J['纳指12']['k']} 次 12 个月后纳指更高；平时 {J['纳指12']['平时']}",
        "三年内衰退": f"加息时不在衰退里的 {J['三年内衰退']['n']} 次中，{J['三年内衰退']['k']} 次 3 年内开始衰退；平时 {J['三年内衰退']['平时']}",
        "曲线正一年不衰退": f"加息时曲线为正的 {J['曲线正一年不衰退']['n']} 次里 {J['曲线正一年不衰退']['k']} 次 1 年内没衰退；"
                         f"平时 {J['曲线正一年不衰退']['平时']}",
    }
    names = {"标普12": "1 年后标普更高", "纳指12": "1 年后纳指更高", "三年内衰退": "3 年内开始衰退", "曲线正一年不衰退": "曲线为正时\n1 年内不衰退"}
    colors = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))
    rows = [{"名": names[key], "之后": f"{J[key]['k']}/{J[key]['n']}", "比例": f"{J[key]['k'] / J[key]['n'] * 100:.0f}%",
             "平时": J[key]["平时"], "判断": J[key]["判断"], "色": colors[J[key]["判断"]], "依据": why[key] + tail(key)}
            for key in names]
    n_h = sum(1 for e in events if e["类"] == "H")
    head_why = (f"第一次加息＝降息停下后，利率比最低点高出 {K.RATE_TH_TARGET} 点；"
                f"1954 年以来 {n_h} 次，满 1 年的 {J['标普12']['n']} 次算进表里")

    # ── 现在在哪（实时状态，每天跟着数据走，不用认可）──
    last = events[-1]
    lvl_now = target[-1][1]
    if last["类"] == "H":
        idx = len(events) - 1
        kd = confirm(events, idx, {}, target) if last["时代"] == "目标利率" else None
        goal = last["极值"] + K.RATE_CONFIRM
        c, n = main["确认"]
        kk, kn = main["确认后标普12"]
        same = K.verdict_word(kk, kn, base["标普12"], True) == K.VERDICT_WORDS[2]
        after = "结论不变，要看利率曲线" if same else "见下表"
        now = {"字": f"{K.fmt_ym(last['日期'])}加息到 {last['水平']:.2f}%；"
                     + (f"{K.fmt_ymd(kd)}已确认新一轮加息，{after}" if kd else f"到 {goal:.2f}% 算新一轮加息，{after}"),
               "依据": f"确认加息后 1 年标普更高 {kk}/{kn} 次，平时 {base['标普12'] * 100:.0f}%；"
                       f"历史 {n} 次里 {c} 次加到确认线"}
    else:
        now = {"字": f"降息中：{K.fmt_ymd(last['日期'])}起从 {last['极值']:.2f}% 降到 {lvl_now:.2f}%", "依据": ""}

    now["字"] += f"（截至 {today.month}月{today.day}日）"   # 目标利率每个交易日核对，一眼看到是哪天的

    # ── 报警信号（各卡片自带更新频率）：一触发，形势就变了；菜单栏会变橙。卡片上带最近两年走势、箭头、比上月比去年 ──
    dgs = parse("dgs10")
    sahm_rows = parse("sahm")

    def curve_at(d):
        return last_at(dgs, d) - last_at(target, d)

    ends = month_ends(today, K.TREND_MONTHS)
    curve = curve_at(today)
    ct = trend("利率曲线", curve, curve_at(minus_months(today, 1)), curve_at(minus_months(today, 12)),
               [curve_at(d) for d in ends], 0.0, True)
    sahm = sahm_rows[-1]
    st_ = trend("失业率预警", sahm[1], sahm_rows[-2][1], sahm_rows[-13][1],
                [v for _, v in sahm_rows[-(K.TREND_MONTHS + 1):]], K.SAHM_ALARM, False)
    ic, inn = main["曲线倒挂衰退"]
    signals = [
        {"名": "利率曲线", "说明": "10 年国债利率减政策利率", "值": f"{curve:+.2f}", "状态": "正常" if curve > 0 else "倒挂", "报警": curve <= 0, "报警字": "利率曲线倒挂",
         "色": "顶" if curve <= 0 else "平", **ct, **card_when("dgs10", dgs[-1][0]), "走势起": K.fmt_ym(ends[0]),
         "依据": f"降到 0 以下叫倒挂；倒挂时第一次加息，{inn} 次里 {ic} 次已在衰退或 1 年内衰退"},
        {"名": "失业率预警", "说明": "失业率升幅（萨姆规则）", "值": f"{sahm[1]:.2f}", "状态": "正常" if sahm[1] < K.SAHM_ALARM else "报警", "报警字": "失业率预警响了",
         "报警": sahm[1] >= K.SAHM_ALARM, "色": "顶" if sahm[1] >= K.SAHM_ALARM else "平", **st_, **card_when("sahm", sahm[0], True),
         "走势起": K.fmt_ym(sahm_rows[-(K.TREND_MONTHS + 1)][0]),
         "依据": f"失业率三个月平均比过去一年最低点高出多少；到 {K.SAHM_ALARM} 报警，衰退可能已经开始"},
    ]

    cy, cn = main["降息后标普12_没衰退"]
    ry, rn = main["降息后标普12_衰退"]
    if K.VERDICT_WORDS[0] in [r["判断"] for r in rows]:
        line = {"字": "第一次加息之后，有用的规律见下表", "依据": ""}
    else:
        line = {"字": "历史规律：加息本身不预示涨跌，决定涨跌的是有没有衰退",
                "依据": f"降息后 1 年标普：没衰退 {cy}/{cn} 次涨，衰退 {ry}/{rn} 次涨；降息时分不出会不会衰退"}

    so = so_line(signals, rows, curve)
    display = {"利率": {"标题": "利率周期", "对现在": so, "一句话": line, "现在": now,
                       "表头": ["刚开始加息后，历史上", "发生概率", "平时", "有没有用"], "表头依据": head_why,
                       "行": rows, "信号": signals,
                       "怎么读": K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"]),
                       "历史更新": K.HIST_LIVE},
               "数据截至": today.isoformat(),
               "最新数据": f"{today.month}月{today.day}日 · 利率{updates('dgs10')}，失业率{updates('sahm')}"}
    detail = {"行键": list(names),
              "全部判断": judged,
              "事件": [{**e, "日期": e["日期"].isoformat()} for e in events],
              "平时": {k: round(v, 4) for k, v in base.items()},
              "各口径": {f"{a}/{b}": {k: v for k, v in r.items() if k not in ("事件",)} for (a, b), r in runs.items()},
              "现在": {"政策利率上限": lvl_now, "十年期": dgs[-1], "萨姆": sahm, "状态": main["状态"]}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    print(json.dumps(disp, ensure_ascii=False, indent=1))
    ev = det["事件"]
    print("H:", " ".join(f"{e['日期'][:10]}({e['水平']})" for e in ev if e["类"] == "H"))
    print("C:", " ".join(f"{e['日期'][:10]}({e['水平']})" for e in ev if e["类"] == "C"))
