"""图六 原油：看板上的每个字、每个数都由这里算出来，写进 results/board6.json。

口径全部来自 defs.py「原油」一节。核心问题：油价一年涨超五成（俗称油价冲击）之后，衰退、股市、油价自己历史上怎么走；衰退期间油价会不会大跌。
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from board2 import monthly, trend, card_when, ym  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board6.json"
COLORS = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))


def ym_str(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def ym_date(k):
    return dt.date(k // 12, k % 12 + 1, 1)


def pct(v):
    return f"{v * 100:+.0f}%"


class Study:
    def __init__(self, today):
        self.all = {ym(d): v for d, v in parse("oil")}
        self.start = ym(K.OIL_START)
        self.obs_end = ym(dt.date(today.year - 1, 12, 1))     # 历史统计只用到上一年 12 月，每年 1 月更新
        self.o = {k: v for k, v in self.all.items() if k <= self.obs_end}
        self.sp = {k: v for k, v in monthly("sp500_monthly").items() if k <= self.obs_end}
        self.rec = monthly("usrec")
        self.starts = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k - 1, 0) == 0)
        self.ends = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k + 1, 0) == 0)
        self.rec_last = min(max(self.rec), self.obs_end)

    def yoy(self, k, s=None):
        s = s or self.all
        return s[k] / s[k - 12] - 1 if k in s and k - 12 in s else None

    def shocks(self, th, s=None):
        """月均价比一年前涨超 th 的每一轮：[(第一次的月份, 这一轮里所有涨超的月份)]。离上一次不到 EPISODE_GAP 个月算同一轮。"""
        s = s or self.o
        out, last = [], None
        for k in sorted(s):
            if k < self.start:
                continue
            y = self.yoy(k, s)
            if y is not None and y >= th:
                if last is None or k - last > K.EPISODE_GAP:
                    out.append((k, []))
                out[-1][1].append(k)
                last = k
        return out

    def in_rec(self, k, h=K.REC_HORIZON_INV):
        """事件月到之后 h 个月里有没有衰退月。"""
        return any(self.rec.get(j, 0) == 1 for j in range(k, k + h + 1))

    def rec_any(self, months, h=K.REC_HORIZON_INV):
        ok = [k for k in months if k + h <= self.rec_last]
        return {"k": sum(self.in_rec(k, h) for k in ok), "n": len(ok)}

    def rec_any_base(self, h=K.REC_HORIZON_INV):
        c = self.rec_any([k for k in self.o if k >= self.start], h)
        return c["k"] / c["n"]

    def high_ref(self, k, yrs=K.OIL_HIGH_YEARS, s=None):
        """之前 yrs 年里的最高月均价（不含这个月）。"""
        s = s or self.all
        prev = [s[j] for j in range(k - 12 * yrs, k) if j in s]
        return max(prev) if len(prev) == 12 * yrs else None

    def new_high(self, months, yrs=K.OIL_HIGH_YEARS, s=None):
        s = s or self.all
        return any(self.high_ref(j, yrs, s) is not None and s[j] > self.high_ref(j, yrs, s) for j in months)

    def rec_start_after(self, k, h=K.REC_HORIZON_INV):
        """事件月之后 h 个月内开始的衰退（月份），没有就 None。要 k+h 的衰退认定已知才算数。"""
        return next((s for s in self.starts if k < s <= k + h), None)

    def rec_count(self, months, h=K.REC_HORIZON_INV):
        ok = [k for k in months if k + h <= self.rec_last]
        return {"k": sum(self.rec_start_after(k, h) is not None for k in ok), "n": len(ok)}

    def rec_base(self, h=K.REC_HORIZON_INV):
        c = self.rec_count([k for k in self.o if k >= self.start], h)
        return c["k"] / c["n"]

    def up_after(self, s, months, h=12):
        xs = [s[k + 1 + h] / s[k + 1] - 1 for k in months if k + 1 in s and k + 1 + h in s]
        return {"k": sum(x > 0 for x in xs), "n": len(xs)}

    def up_base(self, s, h=12):
        c = self.up_after(s, [k for k in s if k >= self.start - 1], h)
        return c["k"] / c["n"]

    def maxdd(self, a, b):
        peak, dd = None, 0.0
        for k in range(a, b + 1):
            if k not in self.o:
                return None
            peak = self.o[k] if peak is None else max(peak, self.o[k])
            dd = min(dd, self.o[k] / peak - 1)
        return dd

    def dd_stats(self, lead, th):
        recs = [(s, e) for s, e in zip(self.starts, self.ends) if s - lead >= self.start and e in self.o]
        dds = {ym_str(s): round(self.maxdd(s - lead, e), 4) for s, e in recs}
        ks = [k for k in sorted(self.o) if k >= self.start]
        cache, bases = {}, []
        for s, e in recs:
            L = e - (s - lead)
            if L not in cache:
                w = [self.maxdd(a, a + L) for a in range(ks[0], ks[-1] - L + 1)]
                w = [x for x in w if x is not None]
                cache[L] = sum(x <= -th for x in w) / len(w)
            bases.append(cache[L])
        return {"各次": dds, "k": sum(1 for d in dds.values() if d <= -th), "n": len(dds), "平时": sum(bases) / len(bases)}


def so_line(signals, rows):
    """对现在：油价有没有涨超五成、有没有创 5 年新高 + 历史上之后衰退的概率。全由下面的数拼出来。"""
    sig, hi = signals[0], signals[1]
    r_all, r_hi = rows[0], rows[1]
    if not sig["报警"]:
        return {"字": f"对现在：月均油价比一年前 {sig['值']}，没过五成线，没有衰退信号", "色": "平",
                "依据": f"过了五成线，历史上 2 年内衰退的概率 {r_all['比例']}（平时 {r_all['平时']}）"}
    r = r_hi if hi["报警"] else r_all
    head = (f"对现在：要小心。月均油价一年涨了 {sig['值'].lstrip('+')}" + ("，又创 5 年新高" if hi["报警"] else "")
            + f"，以前这样 2 年内衰退的概率 {r['比例']}（平时 {r['平时']}）")
    return {"字": head, "色": "顶",
            "依据": f"创了 5 年新高的那几轮更危险：衰退概率 {r_hi['比例']}；这一轮离 5 年新高还差 {hi['值'].lstrip('-')}"}


def build():
    daily = parse("oil_daily")
    S = Study(daily[-1][0])
    judged = {}

    def judge(key, runs, main):
        robust = all(K.verdict(r["k"], r["n"], r["平时"]) for r in runs)
        w = K.verdict_word(main["k"], main["n"], main["平时"], robust)
        judged[key] = {"k": main["k"], "n": main["n"], "平时": round(main["平时"], 4), "判断": w,
                       "主口径过关": K.verdict(main["k"], main["n"], main["平时"]),
                       "换算法": [f"{r['k']}/{r['n']}" for r in runs if r is not main]}
        return w

    def tail(key):
        j = judged[key]
        if j["判断"] == K.VERDICT_WORDS[1] and j["主口径过关"]:
            return "。换算法有一种不过，只算有点用"
        if j["判断"] == K.VERDICT_WORDS[1]:
            return f"。成立不到 {K.STRONG * 100:.0f}%，只算有点用"
        return ""

    eps = {th: S.shocks(th) for th in K.OIL_SHOCK_VARIANTS}
    ev = {th: [k for k, _ in e] for th, e in eps.items()}
    E = ev[K.OIL_SHOCK]
    rb, sb, ob = S.rec_any_base(), S.up_base(S.sp), S.up_base(S.o)
    rec = {th: {**S.rec_any(e), "平时": rb} for th, e in ev.items()}
    hi_ev = {(th, y): [k for k, ms in eps[th] if S.new_high(ms, y)] for th in K.OIL_SHOCK_VARIANTS for y in K.OIL_HIGH_VARIANTS
             if th == K.OIL_SHOCK or y == K.OIL_HIGH_YEARS}
    rech = {key: {**S.rec_any(e), "平时": rb} for key, e in hi_ev.items()}
    spu = {th: {**S.up_after(S.sp, e), "平时": sb} for th, e in ev.items()}
    oiu = {th: {**S.up_after(S.o, e), "平时": ob} for th, e in ev.items()}
    dd = {(lead, th): S.dd_stats(lead, th) for lead in K.DD_VARIANTS for th in K.OIL_DD_VARIANTS
          if lead == K.DD_LEAD or th == K.OIL_DD_BIG}
    D_ = dd[(K.DD_LEAD, K.OIL_DD_BIG)]
    R0, H0, S0, O0 = rec[K.OIL_SHOCK], rech[(K.OIL_SHOCK, K.OIL_HIGH_YEARS)], spu[K.OIL_SHOCK], oiu[K.OIL_SHOCK]
    reb = S.rec_any([k for k in E if k not in hi_ev[(K.OIL_SHOCK, K.OIL_HIGH_YEARS)]])
    # 标普：涨跌幅平均也算一遍，放进悬停说明（11-19 独立重算提出：上涨概率跟平时一样时，平均涨幅可能差很多）
    def mean_ret(months):
        xs = [S.sp[k + 13] / S.sp[k + 1] - 1 for k in months if k + 1 in S.sp and k + 13 in S.sp]
        return sum(xs) / len(xs)
    base_ks = [k for k in S.sp if k >= S.start - 1]
    when = f"油价一年涨超 {K.OIL_SHOCK * 100:.0f}% 共 {len(E)} 轮"
    spec = [
        ("衰退", "油价一年涨超五成\n当时或2年内有衰退", R0, list(rec.values()),
         f"{when}，其中 {R0['k']} 轮当时或 2 年内有衰退；平时 {rb * 100:.0f}%"),
        ("新高", "其中创了5年新高的\n当时或2年内有衰退", H0, list(rech.values()),
         f"创 {K.OIL_HIGH_YEARS} 年新高的 {H0['n']} 轮里 {H0['k']} 轮有衰退，没创的 {reb['n']} 轮只有 {reb['k']} 轮；平时 {rb * 100:.0f}%"),
        ("标普", "油价一年涨超五成\n1 年后标普更高", S0, list(spu.values()),
         f"{when}，{S0['k']} 轮 1 年后标普更高；平时 {sb * 100:.0f}%。"
         f"但平均涨跌幅 {mean_ret(E) * 100:+.0f}%，平时 {mean_ret(base_ks) * 100:+.0f}%"),
        ("油价", "油价一年涨超五成\n1 年后油价更高", O0, list(oiu.values()),
         f"{when}，{O0['k']} 轮 1 年后油价更高；平时 {ob * 100:.0f}%"),
        ("衰退大跌", "衰退期间油价\n从高点跌超三成", D_, list(dd.values()),
         f"1974 年以来 {D_['n']} 次衰退，{D_['k']} 次期间油价从高点跌超 {K.OIL_DD_BIG * 100:.0f}%；平时 {D_['平时'] * 100:.0f}%"),
    ]
    rows = []
    for key, name, m, runs, why in spec:
        w = judge(key, runs, m)
        rows.append({"名": name, "之后": f"{m['k']}/{m['n']}", "比例": f"{m['k'] / m['n'] * 100:.0f}%",
                     "平时": f"{m['平时'] * 100:.0f}%", "判断": w, "色": COLORS[w], "依据": why + tail(key)})

    # ── 历次涨超五成（历史行只用到上一年 12 月，每年更新；今年的这一轮单独放在「现在」，每天跟着数据变）──
    def row(k, months, live):
        rs = S.rec_start_after(k)
        known = k + K.REC_HORIZON_INV <= (max(S.rec) if live else S.rec_last)
        recw = ("当时在衰退" if S.rec.get(k) == 1 else f"{rs - k}个月后" if rs else "没有" if known else "还没满2年")
        sp = S.sp if not live else {ym(d): v for d, v in parse("sp500_monthly")}
        r1 = sp[k + 13] / sp[k + 1] - 1 if k + 13 in sp and k + 1 in sp else None
        top = max(S.yoy(j) for j in months)
        hi = S.new_high(months)
        ref = S.high_ref(k)
        return {"名": f"{k // 12 % 100:02d}年{k % 12 + 1}月", "新高": "是" if hi else ("还没有" if live else "否"),
                "衰退": recw, "标普": pct(r1) if r1 is not None else "还没满1年",
                "依据": f"{ym_str(k)} 月均价 {S.all[k]:.2f} 美元，比一年前高 {S.yoy(k) * 100:.0f}%，这轮最多 {top * 100:.0f}%；"
                        f"之前 {K.OIL_HIGH_YEARS} 年最高 {ref:.2f}"}
    hist = [row(k, ms, False) for k, ms in S.shocks(K.OIL_SHOCK)]
    live_eps = [x for x in S.shocks(K.OIL_SHOCK, S.all) if x[0] > S.obs_end]
    kmax = max(S.all)
    cur = row(*live_eps[-1], True) if live_eps and kmax - live_eps[-1][1][-1] <= K.EPISODE_GAP else None

    # ── 报警卡片：月均价比一年前 ──
    ks = sorted(S.all)[-(K.TREND_MONTHS + 1):]
    y_now = S.yoy(kmax) * 100
    t = trend("油价比一年前", y_now, S.yoy(kmax - 1) * 100, S.yoy(kmax - 12) * 100, [S.yoy(k) * 100 for k in ks],
              K.OIL_SHOCK * 100, False, nd=0, unit=" 个百分点")
    hot = y_now >= K.OIL_SHOCK * 100

    def gap(k):
        return (S.all[k] / S.high_ref(k) - 1) * 100
    g_now = gap(kmax)
    t2 = trend("离5年最高", g_now, gap(kmax - 1), gap(kmax - 12), [gap(k) for k in ks], 0.0, False, nd=0, unit=" 个百分点")
    ref_k = max(range(kmax - 12 * K.OIL_HIGH_YEARS, kmax), key=lambda j: S.all[j])
    new = g_now > 0
    signals = [{"名": "油价比一年前", "说明": "美国原油月均价比 12 个月前涨了多少", "值": f"{y_now:+.0f}%",
                "状态": "涨超五成" if hot else "没涨超五成", "报警字": "油价比一年前涨超五成", "报警": hot, "色": "顶" if hot else "平", **t, **card_when("oil", ym_date(kmax), True),
                "走势起": K.fmt_ym(ym_date(ks[0])),
                "依据": f"报警线 +{K.OIL_SHOCK * 100:.0f}%：过了这条线，就是后两张图说的「油价一年涨超五成」"},
               {"名": "离5年最高", "说明": f"月均价比之前 5 年最高（{K.fmt_ym(ym_date(ref_k))}）低多少", "值": f"{g_now:+.0f}%",
                "状态": "创了5年新高" if new else "没创新高", "报警字": "油价创了5年新高", "报警": new, "色": "顶" if new else "平", **t2, **card_when("oil", ym_date(kmax), True),
                "走势起": K.fmt_ym(ym_date(ks[0])),
                "依据": f"过了 0 就是创 {K.OIL_HIGH_YEARS} 年新高；创新高的油价大涨，比没创的更常跟着衰退。"
                        f"之前 {K.OIL_HIGH_YEARS} 年最高 {S.all[ref_k]:.2f} 美元"}]
    # 2026-11-19 拿当天油价核对对不上：规律全按月均价算（日价只有 1986 年起），这里把最新日价和它一年前也并排写出来，
    # 两种口径一眼分清。一年前取那天往前最近一个有价的交易日。
    dd_, dv = daily[-1]
    ago = [v for d, v in daily if d <= dd_ - 365 * K.DAY]
    dy = (dv / ago[-1] - 1) * 100
    now = {"字": f"{K.fmt_ym(ym_date(kmax))}月均价 {S.all[kmax]:.2f} 美元（{updates('oil')}），比一年前{'高' if y_now >= 0 else '低'} {abs(y_now):.0f}%；"
                 f"日价 {dd_.month}月{dd_.day}日 {dv:.2f} 美元（{updates('oil_daily')}），比一年前{'高' if dy >= 0 else '低'} {abs(dy):.0f}%",
           "依据": "美国原油（西德州中质油）；规律都按月均价算。新闻常报的布伦特是另一种油，价格不同"}
    so = so_line(signals, rows)
    how = K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"])
    display = {
        "现在": {"标题": "原油", "对现在": so, "现在": now, "信号": signals, "怎么读": how},
        "历次": {"标题": "历次油价一年涨超五成", "对现在": so,
                 "表头": ["那个月", "5年新高", "当时或2年内衰退", "1年后标普涨跌"],
                 "表头依据": f"1974 年以来月均价比一年前涨超 {K.OIL_SHOCK * 100:.0f}% 的每一轮，记第一次涨超的月份；"
                             f"5年新高＝高过之前 {K.OIL_HIGH_YEARS} 年最高月均价",
                 "轮": hist, "现在": cur, "怎么读": how,
                 "历史更新": K.HIST_YEARLY + (f"，这一轮{updates('oil')}" if cur else "")},
        "规律": {"标题": "原油规律准不准", "对现在": so,
                 "一句话": {"字": ("历史规律：油价大涨后衰退更常见；之后股市、油价跟平时一样"
                                   if rows[0]["判断"] != K.VERDICT_WORDS[2] and rows[2]["判断"] == K.VERDICT_WORDS[2]
                                   else "历史规律：有用的见标色那几行")
                     + ("；衰退时油价常大跌" if rows[4]["判断"] != K.VERDICT_WORDS[2]
                        and int(rows[4]["比例"][:-1]) > int(rows[4]["平时"][:-1]) else ""),
                           "依据": "每一行都和平时比；差不到 15 个百分点就算跟平时一样"},
                 "表头": ["出现后，历史上", "发生概率", "平时", "有没有用"],
                 "表头依据": "每一行：这件事出现后，历史上真的发生的比例；和平时（不看信号）的比例对照",
                 "行": rows, "怎么读": how, "历史更新": K.HIST_YEARLY},
        "数据截至": None,   # 原油只有月均价和每周公布的日价，不拉低全看板的「数据截至」；断更由验收的新鲜度检查拦
        "最新数据": f"{int(ym_str(max(S.all))[5:])}月月均价 · {updates('oil')}；日价 {dd_.month}月{dd_.day}日",   # 菜单里这个题目第一行写「最新数据」用；图上的「现在」都按这个月算
    }
    detail = {"全部判断": judged, "行键": [x[0] for x in spec],
              "涨超五成": {str(th): [ym_str(k) for k in e] for th, e in ev.items()},
              "创新高的": {f"{th}|{y}": [ym_str(k) for k in e] for (th, y), e in hi_ev.items()},
              "衰退大跌": {f"{lead}|{th}": v for (lead, th), v in dd.items()},
              "现在": {"月均价": [ym_str(kmax), S.all[kmax]], "日价": [dd_.isoformat(), dv]}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    for c in disp["历次"]["轮"] + ([disp["历次"]["现在"]] if disp["历次"]["现在"] else []):
        print(c["名"], c["新高"], c["衰退"], c["标普"])
    for r in disp["规律"]["行"]:
        print(r["名"].replace("\n", " "), r["之后"], r["平时"], r["判断"], "|", r["依据"][-90:])
    print(disp["现在"]["对现在"]["字"])
    print(disp["现在"]["现在"]["字"])
    for s in disp["现在"]["信号"]:
        print(s["名"], s["值"], s["状态"], s["比上月"], s["比去年"], s["离报警"])
    print(det["涨超五成"], det["衰退大跌"]["1|0.3"])
