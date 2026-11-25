"""图三 景气与衰退：看板上的每个字、每个数都由这里算出来，写进 results/board3.json。

口径全部来自 defs.py「景气与衰退」一节；这里只负责按口径计算。
核心问题：经济现在在景气四个阶段（增长×通胀）的哪一个；在哪个阶段对股票、黄金、原油有没有影响；衰退信号历史上准不准、衰退来了会怎样。
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from board2 import last_at, minus_months, month_ends, monthly, trend, card_when, ym  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board3.json"
INV_START = dt.date(1953, 4, 1)


def ym_str(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def ym_date(k):
    return dt.date(k // 12, k % 12 + 1, 1)


class Study:
    def __init__(self, today):
        self.rec = monthly("usrec")
        self.cf = monthly("cfnai")
        gs, tb = monthly("gs10"), monthly("tb3ms")
        self.spread = {k: gs[k] - tb[k] for k in gs if k in tb and k >= ym(INV_START)}
        self.obs_end = ym(dt.date(today.year - 1, 12, 1))   # 历史统计只用到上一年 12 月（见 defs.py），每年 1 月更新一次
        self.sp = {k: v for k, v in monthly("sp500_monthly").items() if k <= self.obs_end}
        self.px = {"标普": self.sp,
                   "黄金": {k: v for k, v in monthly("gold").items() if k <= self.obs_end and k >= ym(K.GOLD_START)},
                   "原油": {k: v for k, v in monthly("oil").items() if k <= self.obs_end and k >= ym(K.OIL_START)}}
        cpi = self.cpi = monthly("cpi")
        self.infl = {k: (cpi[k] / cpi[k - 12] - 1) * 100 for k in cpi if k - 12 in cpi}   # 物价比一年前涨了多少（%）
        self.starts = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k - 1, 0) == 0)
        self.ends = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k + 1, 0) == 0)
        self.rec_last = min(max(self.rec), self.obs_end)

    def ret(self, b, h):
        return self.sp[b + h] / self.sp[b] - 1 if b in self.sp and b + h in self.sp else None

    def start_within(self, o, h):
        return any(o < s <= o + h for s in self.starts)

    # ── 景气阶段（增长 × 通胀）──
    def stage(self, k, lag):
        if k not in self.cf or k not in self.infl or k - lag not in self.infl:
            return None
        return K.STAGE_OF[(self.cf[k] > 0, self.infl[k] > self.infl[k - lag])]

    def stage_months(self, lag):
        ks = [k for k in sorted(self.cf) if k <= self.obs_end and self.stage(k, lag)]
        return ks

    def after(self, asset, months):
        """某月的活动指数、物价指数都在下个月才公布，所以从再下一个月（k+2）的月均价起算 12 个月。"""
        px = self.px[asset]
        if asset in K.STAGE_START:
            months = [k for k in months if k >= ym(K.STAGE_START[asset])]
        xs = [px[k + 14] / px[k + 2] - 1 for k in months if k + 2 in px and k + 14 in px]
        return sum(x > 0 for x in xs), len(xs)

    def sp_after(self, months):
        return self.after("标普", months)

    def base_months(self):
        return list(range(min(self.cf) + K.BASE_SKIP, min(max(self.cf), self.obs_end) + 1))

    def stage_stats(self, lag):
        ms = self.stage_months(lag)
        out = {"平时": {a: self.after(a, ms) for a in K.STAGE_ASSETS}}
        for p in K.STAGE_NAMES:
            sel = [k for k in ms if self.stage(k, lag) == p]
            out[p] = {"月数": len(sel), **{a: self.after(a, sel) for a in K.STAGE_ASSETS}}
        return out

    # ── 衰退信号 ──
    def inversions(self, gap):
        sp = self.spread
        return [k for k in sorted(sp) if sp[k] < 0 and all(sp.get(j, 1) >= 0 for j in range(k - gap, k))]

    def inv_stats(self, gap):
        ev = self.inversions(gap)
        ok = [k for k in ev if self.rec.get(k) == 0 and k + K.REC_HORIZON_INV <= self.rec_last]
        hit = [k for k in ok if self.start_within(k, K.REC_HORIZON_INV)]
        base_m = [k for k in sorted(self.spread) if self.rec.get(k) == 0 and k + K.REC_HORIZON_INV <= self.rec_last]
        base = sum(self.start_within(k, K.REC_HORIZON_INV) for k in base_m) / len(base_m)
        return {"事件": [ym_str(k) for k in ev], "k": len(hit), "n": len(ok), "平时": base,
                "落空": [ym_str(k) for k in ok if k not in hit],
                "提前月数": [min(s for s in self.starts if s > k) - k for k in hit]}

    @staticmethod
    def episodes(ks):
        """离上一次不到 EPISODE_GAP 个月的算同一轮，只留第一次。"""
        out = []
        for k in ks:
            if not out or k - out[-1] >= K.EPISODE_GAP:
                out.append(k)
        return out

    def alarms(self, th):
        return self.episodes([k for k in sorted(self.cf) if self.cf[k] <= th and self.cf.get(k - 1, 0) > th])

    def alarm_stats(self, th):
        ev = self.alarms(th)
        h = K.REC_HORIZON_CFNAI
        ok = [k for k in ev if k + h <= self.rec_last]
        hit = [k for k in ok if self.rec.get(k) == 1 or self.start_within(k, h)]
        base_m = [k for k in sorted(self.cf) if k + h <= self.rec_last]
        base = sum(self.rec.get(k) == 1 or self.start_within(k, h) for k in base_m) / len(base_m)
        return {"事件": [ym_str(k) for k in ev], "k": len(hit), "n": len(ok), "平时": base,
                "已在衰退": sum(self.rec.get(k) == 1 for k in ok)}

    def clears(self, th):
        out, armed = [], False
        for k in sorted(self.cf):
            if self.cf[k] <= th:
                armed = True
            elif armed:
                out.append(k)
                armed = False
        return self.episodes(out)

    def clear_stats(self, th):
        ev = self.clears(th)
        k, n = self.sp_after(ev)
        bk, bn = self.sp_after(self.base_months())
        return {"事件": [ym_str(x) for x in ev], "k": k, "n": n, "平时": bk / bn,
                "各次": {ym_str(x): round(self.ret(x + 2, 12), 4) for x in ev if self.ret(x + 2, 12) is not None}}

    def maxdd(self, a, b):
        peak, dd = None, 0.0
        for k in range(a, b + 1):
            if k not in self.sp:
                return None
            peak = self.sp[k] if peak is None else max(peak, self.sp[k])
            dd = min(dd, self.sp[k] / peak - 1)
        return dd

    def dd_stats(self, lead):
        recs = [(s, e) for s, e in zip(self.starts, self.ends) if s - lead in self.sp and e in self.sp]
        dds = {ym_str(s): round(self.maxdd(s - lead, e), 4) for s, e in recs}
        ks = sorted(self.sp)
        cache, bases = {}, []
        for s, e in recs:
            L = e - (s - lead)
            if L not in cache:
                w = [self.maxdd(a, a + L) for a in range(ks[0], ks[-1] - L + 1)]
                w = [x for x in w if x is not None]
                cache[L] = sum(x <= -K.DD_BIG for x in w) / len(w)
            bases.append(cache[L])
        return {"各次": dds, "k": sum(1 for d in dds.values() if d <= -K.DD_BIG), "n": len(dds),
                "平时": sum(bases) / len(bases)}


VERDICT_CLS = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))
REV = {p: gi for gi, p in K.STAGE_OF.items()}    # 阶段 → (增长高于正常, 通胀在升)


def stage_view(cell, short=False):
    """这个阶段对三种资产的历史结论，一句大白话；全从各资产的判断词和比例来。"""
    names = {a: (K.STAGE_ASSET_SHORT[a] if short else a if a != "标普" else "股票") for a in K.STAGE_ASSETS}
    up, dn, same = [], [], []
    for a in K.STAGE_ASSETS:
        if cell[f"{a}判断"] not in K.VERDICT_WORDS[:2]:
            same.append(names[a])
        elif int(cell[a].rstrip("%")) > int(cell[f"{a}平时"].rstrip("%")):
            up.append(names[a])
        else:
            dn.append(names[a])
    if len(same) == 3:
        return f"{'、'.join(same)}都和平时差不多"
    parts = ([f"{'、'.join(up)}更容易涨"] if up else []) + ([f"{'、'.join(dn)}更难涨"] if dn else []) \
        + ([f"{'、'.join(same)}和平时差不多"] if same else [])
    return "，".join(parts)


def flip_text(stage):
    """现在这个阶段，什么变了会转去哪个阶段（增长先翻、通胀先翻各一种）。"""
    g, i = REV[stage]
    return (f"活动指数{'跌破' if g else '升过'} 0 转{K.STAGE_OF[(not g, i)]}；"
            f"物价同比{'回落' if i else '回升'}转{K.STAGE_OF[(g, not i)]}")


def so_line(signals, stage, view, page):
    """对现在：按报警状态和景气阶段自动写一句大白话。page＝景气（第一张）或 衰退（第二张）。"""
    hit = [s["名"] for s in signals if s["报警"]]
    if hit:
        return {"字": f"对现在：要小心。{'、'.join(hit)}已报警，衰退可能来了",
                "色": "顶", "依据": "报警响时，历史上衰退多半已开始或两年内开始"}
    if page == "衰退":
        return {"字": "对现在：两个衰退报警都没响，这张表先不用看", "色": "平",
                "依据": "两个报警在「现在在景气哪个阶段」那张图上，各按自己的公布频率更新"}
    return {"字": f"对现在：处在{stage}阶段；历史上这个阶段{view}",
            "色": "平", "依据": f"现在在「{stage}」阶段；每个阶段之后 1 年，标普、黄金、原油更高的概率和平时比"}


def build():
    t3 = parse("t10y3m")
    today = t3[-1][0]
    S = Study(today)

    # ── 景气阶段：每个阶段 = 历史上落在这个阶段的月份，之后 1 年标普、黄金、原油怎么走，和平时比 ──
    runs = {lag: S.stage_stats(lag) for lag in K.INFL_VARIANTS}
    main = runs[K.INFL_LAG]
    base = {a: main["平时"][a][0] / main["平时"][a][1] for a in K.STAGE_ASSETS}
    cells, judged = [], {}
    for p in K.STAGE_NAMES:
        g, i = REV[p]
        cell = {"名": p, "定义": f"{'增长高' if g else '增长低'} · 通胀{'升' if i else '降'}"}
        tips = []
        for a in K.STAGE_ASSETS:
            k, n = main[p][a]
            w = K.verdict_word(k, n, base[a], all(K.verdict(*runs[v][p][a], base[a]) for v in K.INFL_VARIANTS))
            judged[f"{p}{a}"] = {"k": k, "n": n, "平时": round(base[a], 4), "判断": w,
                                 "换算法": [f"{runs[v][p][a][0]}/{runs[v][p][a][1]}" for v in K.INFL_VARIANTS if v != K.INFL_LAG]}
            cell.update({a: f"{k / n * 100:.0f}%", f"{a}次数": f"{k}/{n}", f"{a}平时": f"{base[a] * 100:.0f}%",
                         f"{a}判断": w, f"{a}色": VERDICT_CLS[w]})
            tips.append(f"{a}{k}/{n}")
        cell["依据"] = f"1 年后更高：{'，'.join(tips)}；平时 " + "，".join(f"{a}{base[a] * 100:.0f}%" for a in K.STAGE_ASSETS)
        cells.append(cell)
    avg = {a: f"{base[a] * 100:.0f}%" for a in K.STAGE_ASSETS}
    clock_head = {"字": "历史统计 · 落在这个阶段之后 1 年更高",
                  "平时": "平时：" + "，".join(f"{a}上涨概率 {avg[a]}" if a == "标普" else f"{a} {avg[a]}" for a in K.STAGE_ASSETS),
                  "依据": f"活动指数高于 0 为增长高于正常；物价同比比 {K.INFL_LAG} 个月前高为通胀在升；平时＝同样这些月份不分阶段",
                  "平时值": avg}

    # 现在在哪个阶段（实时，跟着数据走，不用认可）
    # 阶段要活动指数和物价同比两样都有：取两样都有的最新一个月（11-24 云端崩过：活动指数已有 10 月，
    # 但 10 月物价同比算不出——一年前那个月官方没公布物价，直接按活动指数最新月份去取就 KeyError，整次更新失败）
    kcf = max(S.cf)
    kst = max(k for k in S.cf if S.stage(k, K.INFL_LAG))
    v = S.cf[kst]
    ci, ci0 = S.infl[kst], S.infl[kst - K.INFL_LAG]
    ph = S.stage(kst, K.INFL_LAG)
    near = abs(v) < K.PHASE_NEAR
    now_cell = next(c for c in cells if c["名"] == ph)
    gap = gap_why = ""   # 活动指数比阶段新：说清新那个月增长怎样、为什么阶段还按旧月，不让人以为数停了
    if kcf != kst:
        why = "一年前那月官方没公布" if kcf in S.cpi and kcf - 12 not in S.cpi else "物价还没公布"
        vn = S.cf[kcf]
        # 页面离高度上限近（加一小句就超），图上不加字：活动指数最新月的值本页报警卡上就有；缺月原因放悬停和菜单第一行
        gap = f"（{ym_date(kcf).month}月缺物价）"
        gap_why = f"{ym_date(kcf).month}月活动指数 {vn:+.2f}；{ym_date(kcf).month}月缺物价同比：{why}"
    now = {"字": f"{ph}阶段 · 活动指数 {v:+.2f}（{ym_date(kst).month}月，{updates('cfnai')}"
                 + ("，贴着 0" if near else "") + f"）；物价比去年涨 {ci:.2f}%，{K.INFL_LAG} 个月前 {ci0:.2f}%",
           "阶段": ph,
           "依据": gap_why or (f"活动指数每月下旬公布上个月的数；物价同比{'升' if ci > ci0 else '降'}，所以通胀在{'升' if ci > ci0 else '降'}"
                               + ("；活动指数贴着 0，随时会变" if near else ""))}
    g_txt = ("略" if near else "") + ("高于正常" if v > 0 else "低于正常")
    stage_line = {"字": f"阶段：{ph}（增长{g_txt}、通胀在{'升' if ci > ci0 else '降'}）；历史上这个阶段{stage_view(now_cell, True)}",
                  "依据": flip_text(ph) + (f"；{gap_why}" if gap_why else "")}

    # ── 报警信号（每天更新）──
    ends = month_ends(today, K.TREND_MONTHS)
    sv = last_at(t3, today)
    tt = trend("长短利率差", sv, last_at(t3, minus_months(today, 1)), last_at(t3, minus_months(today, 12)),
               [last_at(t3, d) for d in ends], 0.0, True)
    cf_rows = parse("cfnai")
    cv = cf_rows[-1][1]
    ct = trend("活动指数", cv, cf_rows[-2][1], cf_rows[-13][1],
               [x for _, x in cf_rows[-(K.TREND_MONTHS + 1):]], K.CFNAI_ALARM, True)
    inv = {g: S.inv_stats(g) for g in K.INV_VARIANTS}
    alm = {t: S.alarm_stats(t) for t in K.CFNAI_VARIANTS}
    I, A = inv[K.INV_GAP], alm[K.CFNAI_ALARM]
    signals = [
        {"名": "长短利率差", "说明": "10 年减 3 个月国债利率", "值": f"{sv:+.2f}", "状态": "正常" if sv > 0 else "倒挂", "报警": sv <= 0, "报警字": "长短利率差倒挂",
         "色": "顶" if sv <= 0 else "平", **tt, **card_when("t10y3m", t3[-1][0]), "走势起": K.fmt_ym(ends[0]),
         "依据": f"降到 0 以下叫倒挂；1953 年以来 {I['n']} 次倒挂，{I['k']} 次 2 年内开始衰退"},
        {"名": "活动指数", "说明": "芝加哥联储，0＝正常增速", "值": f"{cv:+.2f}", "状态": "正常" if cv > K.CFNAI_ALARM else "报警", "报警字": "活动指数跌破报警线",
         "报警": cv <= K.CFNAI_ALARM, "色": "顶" if cv <= K.CFNAI_ALARM else "平", **ct, **card_when("cfnai", cf_rows[-1][0], True),
         "走势起": K.fmt_ym(cf_rows[-(K.TREND_MONTHS + 1)][0]),
         "依据": f"三个月平均跌到 {K.CFNAI_ALARM} 报警：{A['n']} 次报警 {A['k']} 次已在衰退或半年内开始"},
    ]

    # ── 衰退信号准不准：每一行 = 一个信号出现后历史上会怎样，和平时比，换口径也要站得住 ──
    clr = {t: S.clear_stats(t) for t in K.CFNAI_VARIANTS}
    dd = {d: S.dd_stats(d) for d in K.DD_VARIANTS}
    C, D = clr[K.CFNAI_ALARM], dd[K.DD_LEAD]

    def judge(key, runs_, main_):
        k, n, b = main_["k"], main_["n"], main_["平时"]
        robust = all(K.verdict(r["k"], r["n"], r["平时"]) for r in runs_.values())
        w = K.verdict_word(k, n, b, robust)
        judged[key] = {"k": k, "n": n, "平时": round(b, 4), "判断": w, "主口径过关": K.verdict(k, n, b),
                       "换算法": [f"{r['k']}/{r['n']}" for x, r in runs_.items() if r is not main_]}
        return w

    def why_word(key):
        j = judged[key]
        if j["判断"] == K.VERDICT_WORDS[1] and j["主口径过关"]:
            return "。换算法有一种不过，只算有点用"
        if j["判断"] == K.VERDICT_WORDS[1]:
            return f"。成立不到 {K.STRONG * 100:.0f}%，只算有点用"
        return ""

    rows_spec = [
        ("倒挂", "长短利率倒挂\n2 年内开始衰退", I, inv,
         f"{I['n']} 次倒挂里 {I['k']} 次 2 年内开始衰退，平时 {I['平时'] * 100:.0f}%"
         + (f"；最近 {I['落空'][-1][:4]} 年那次落空" if I["落空"] else "")),   # 最近一次落空是读今天的关键风险，不能删
        ("报警", "活动指数报警后\n半年内处在衰退中", A, alm,
         f"{A['n']} 次报警 {A['k']} 次已在衰退或半年内开始，平时 {A['平时'] * 100:.0f}%；"
         f"{A['已在衰退']} 次报警时衰退已开始，是确认不是预告"),
        ("解除", "报警解除后\n1 年后标普更高", C, clr,
         f"报警后回到 {K.CFNAI_ALARM} 以上算解除；{C['n']} 次里 {C['k']} 次 1 年后标普更高，平时 {C['平时'] * 100:.0f}%"),
        ("大跌", "衰退期间标普\n从高点跌超 20%", D, dd,
         f"{D['n']} 次衰退里 {D['k']} 次标普从高点跌超 {K.DD_BIG * 100:.0f}%，平时 {D['平时'] * 100:.0f}%；按月均价算，实际跌得更深"),
    ]
    rows = []
    for key, name, m, rs, why in rows_spec:
        w = judge(key, rs, m)
        rows.append({"名": name, "之后": f"{m['k']}/{m['n']}", "比例": f"{m['k'] / m['n'] * 100:.0f}%",
                     "平时": f"{m['平时'] * 100:.0f}%", "判断": w,
                     "色": dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))[w], "依据": why + why_word(key)})
    already = "都" if A["已在衰退"] == A["n"] else "多半"
    rule = {"字": f"历史规律：倒挂能提前预告衰退，但会落空；活动指数报警很准，可报警时衰退{already}已经开始",
            "依据": f"倒挂 {I['k']}/{I['n']} 次 2 年内衰退；活动指数报警 {A['k']}/{A['n']} 次对，其中 {A['已在衰退']} 次衰退已经开始"}

    how = K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"])
    how_cycle = K.legend(list(K.STAGE_NAMES) + ["平时", "有用", "有点用", "跟平时一样", "报警信号"])
    display = {
        "景气": {"标题": "景气与衰退", "对现在": so_line(signals, ph, stage_view(now_cell), "景气"), "现在": now, "阶段说明": clock_head, "阶段": cells,
                 "总表句": stage_line, "信号": signals, "怎么读": how_cycle,
                 "历史更新": K.HIST_YEARLY},
        "衰退": {"标题": "衰退信号准不准", "对现在": so_line(signals, ph, stage_view(now_cell), "衰退"), "一句话": rule,
                 "表头": ["信号出现后，历史上", "发生概率", "平时", "有没有用"],
                 "表头依据": "每一行：这个信号出现后，历史上真的发生的比例（发生概率）；和平时（不看信号）的比例对照，看是不是明显更常发生",
                 "行": rows, "怎么读": how, "历史更新": K.HIST_YEARLY},
        "数据截至": today.isoformat(),
        "最新数据": f"阶段 {ym_date(kst).month}月{gap} · {updates('cfnai')}；利率差{updates('t10y3m')}",
    }
    detail = {"全部判断": judged, "行键": [r[0] for r in rows_spec],
              "阶段各口径": {str(lag): r for lag, r in runs.items()},
              "倒挂": {str(g): r for g, r in inv.items()}, "报警": {str(t): r for t, r in alm.items()},
              "解除": {str(t): r for t, r in clr.items()}, "大跌": {str(d): r for d, r in dd.items()},
              "衰退": [f"{ym_str(s)}~{ym_str(e)}" for s, e in zip(S.starts, S.ends)],
              "现在": {"活动指数": [ym_str(kcf), v], "物价同比": [round(ci, 3), round(ci0, 3)], "长短利率差": [today.isoformat(), sv]}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    print(json.dumps(disp, ensure_ascii=False, indent=1))
    print(json.dumps({k: det[k] for k in ("倒挂", "报警")}, ensure_ascii=False)[:1500])
