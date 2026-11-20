"""金融状况：看板上的每个字、每个数都由这里算出来，写进 results/board7.json。

口径全部来自 defs.py「金融状况」一节。核心问题：市场的钱紧不紧、企业借钱难不难；紧到什么程度，历史上会跟着衰退或美股下跌。
页面和利率周期一样只有一页：对现在、现在、历史统计表、两张报警卡。
"""
import collections
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from board2 import last_at, minus_months, month_ends, monthly, trend, card_when, ym  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board7.json"
COLORS = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))
WORKS = K.VERDICT_WORDS[:2]


def ym_str(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def ym_date(k):
    return dt.date(k // 12, k % 12 + 1, 1)


def spread_series():
    """信用利差月均 = Baa 月均 − 十年期国债月均（两边都有的月份）。"""
    baa, gs = monthly("baa"), monthly("gs10")
    return {k: baa[k] - gs[k] for k in baa if k in gs}


def nfci_monthly(obs_end):
    """金融状况指数每月的周平均值（只到 obs_end）。"""
    g = collections.defaultdict(list)
    for d, v in parse("nfci"):
        g[ym(d)].append(v)
    return {k: sum(v) / len(v) for k, v in g.items() if k <= obs_end}


def first_times(hit, ks):
    """每一轮只记第一次：这个月 hit 为真，且之前至少 EPISODE_GAP 个月都不为真。ks 是能算的月份（排好序）。"""
    out, last = [], ks[0] - 1
    for k in ks:
        if hit(k):
            if k - last > K.EPISODE_GAP:
                out.append(k)
            last = k
    return out


class Study:
    def __init__(self, today):
        self.obs_end = ym(dt.date(today.year - 1, 12, 1))     # 历史统计只用到上一年 12 月，每年 1 月更新
        self.sp = {k: v for k, v in monthly("sp500_monthly").items() if k <= self.obs_end}
        self.rec = monthly("usrec")
        self.rec_last = min(max(self.rec), self.obs_end)
        self.spr = {k: v for k, v in spread_series().items() if k <= self.obs_end}
        self.nf = nfci_monthly(self.obs_end)
        self.k1 = sorted(k for k in self.spr if k - 12 in self.spr)     # 规律一能算的月份
        self.k2 = sorted(self.nf)                                       # 规律二能算的月份

    def chg(self, k, s=None):
        s = s or self.spr
        return s[k] - s[k - 12] if k in s and k - 12 in s else None

    def ev1(self, th):
        return first_times(lambda k: self.chg(k) >= th - 1e-9, self.k1)

    def ev2(self, th):
        return first_times(lambda k: self.nf[k] > th + 1e-9, self.k2)

    def in_rec(self, k, h=K.REC_HORIZON_INV):
        """事件月到之后 h 个月里有没有衰退月。"""
        return any(self.rec.get(j, 0) == 1 for j in range(k, k + h + 1))

    def rec_any(self, months, h=K.REC_HORIZON_INV):
        ok = [k for k in months if k + h <= self.rec_last]
        return {"k": sum(self.in_rec(k, h) for k in ok), "n": len(ok)}

    def up_after(self, months, h=12):
        xs = [self.sp[k + 1 + h] / self.sp[k + 1] - 1 for k in months if k + 1 in self.sp and k + 1 + h in self.sp]
        return {"k": sum(x > 0 for x in xs), "n": len(xs)}


def so_line(signals, rows):
    """对现在：钱紧不紧、信用利差有没有扩大 + 历史上之后衰退的概率。全由下面的数拼出来。"""
    nf, sp = signals[0], signals[1]
    r1, r2 = rows[0], rows[2]
    if not nf["报警"] and not sp["报警"]:
        return {"字": f"对现在：钱不紧（指数 {nf['值']}），信用利差没扩大，没有衰退信号", "色": "平",
                "依据": f"利差一年扩大后 2 年内衰退概率 {r1['比例']}，指数高于 0 后 {r2['比例']}（平时 {r1['平时']}、{r2['平时']}）"}
    if sp["报警"] and nf["报警"]:
        head, r = "钱紧、信用利差也在扩大", r1
    elif sp["报警"]:
        head, r = f"信用利差一年扩大 {sp['值'].lstrip('+')} 点", r1
    else:
        head, r = f"钱比平时紧（指数 {nf['值']}）", r2
    return {"字": f"对现在：要小心。{head}，以前这样 2 年内衰退概率 {r['比例']}（平时 {r['平时']}）", "色": "顶",
            "依据": f"表里「当时或 2 年内有衰退」：利差扩大 {r1['之后']}，金融状况紧 {r2['之后']}"}


def build():
    nf_rows = parse("nfci")
    today = nf_rows[-1][0]
    S = Study(today)
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

    ev1 = {th: S.ev1(th) for th in K.FIN_SPREAD_VARIANTS}
    ev2 = {th: S.ev2(th) for th in K.FIN_NFCI_VARIANTS}
    rb1, rb2 = S.rec_any(S.k1), S.rec_any(S.k2)
    ub1, ub2 = S.up_after(S.k1), S.up_after(S.k2)
    rb1, rb2, ub1, ub2 = (x["k"] / x["n"] for x in (rb1, rb2, ub1, ub2))
    rec1 = {th: {**S.rec_any(e), "平时": rb1} for th, e in ev1.items()}
    up1 = {th: {**S.up_after(e), "平时": ub1} for th, e in ev1.items()}
    rec2 = {th: {**S.rec_any(e), "平时": rb2} for th, e in ev2.items()}
    up2 = {th: {**S.up_after(e), "平时": ub2} for th, e in ev2.items()}
    T1, T2 = K.FIN_SPREAD_JUMP, K.FIN_NFCI_LINE
    n1, n2 = len(ev1[T1]), len(ev2[T2])
    hind = "。指数每周重估，有后见之明"
    spec = [
        ("利差衰退", f"利差一年扩大超 {T1:g} 点\n当时或 2 年内衰退", rec1[T1], list(rec1.values()),
         f"这种情况共 {n1} 轮，{rec1[T1]['k']} 轮当时或 2 年内有衰退；平时 {rb1 * 100:.0f}%"),
        ("利差标普", f"利差一年扩大超 {T1:g} 点\n1 年后标普更高", up1[T1], list(up1.values()),
         f"这种情况共 {n1} 轮，{up1[T1]['k']} 轮 1 年后标普更高；平时 {ub1 * 100:.0f}%"),
        ("指数衰退", f"金融状况比平时紧\n当时或 2 年内衰退", rec2[T2], list(rec2.values()),
         f"第一次变紧共 {n2} 轮，{rec2[T2]['k']} 轮当时或 2 年内有衰退；平时 {rb2 * 100:.0f}%" + hind),
        ("指数标普", f"金融状况比平时紧\n1 年后标普更高", up2[T2], list(up2.values()),
         f"第一次变紧共 {n2} 轮，{up2[T2]['k']} 轮 1 年后标普更高；平时 {ub2 * 100:.0f}%" + hind),
    ]
    rows = []
    for key, name, m, runs, why in spec:
        w = judge(key, runs, m)
        rows.append({"名": name, "之后": f"{m['k']}/{m['n']}", "比例": f"{m['k'] / m['n'] * 100:.0f}%",
                     "平时": f"{m['平时'] * 100:.0f}%", "判断": w, "色": COLORS[w], "依据": why + tail(key)})

    # ── 现在（实时，每天跟着数据走，不用认可）──
    spr_all = spread_series()
    kmax = max(spr_all)
    sp_now = spr_all[kmax]
    c_now = spr_all[kmax] - spr_all[kmax - 12]
    nf_d, nf_v = nf_rows[-1]
    now = {"字": f"指数 {nf_v:+.2f}（{nf_d.month}月{nf_d.day}日，{updates('nfci')}）；"
                 f"利差 {K.fmt_ym(ym_date(kmax))} {sp_now:.2f}（{updates('baa')}），比一年前{'多' if c_now >= 0 else '少'} {abs(c_now):.2f}",
           "依据": "指数每周公布，高于 0＝比平时紧；利差按月，单位个百分点，企业债减十年国债利率"}

    # ── 报警卡片 ──
    ends = month_ends(nf_d, K.TREND_MONTHS)
    series_nf = [last_at(nf_rows, d) for d in ends]
    t1 = trend("金融状况指数", nf_v, last_at(nf_rows, minus_months(nf_d, 1)), last_at(nf_rows, minus_months(nf_d, 12)),
               series_nf, K.FIN_NFCI_LINE, False)
    ks = list(range(kmax - K.TREND_MONTHS, kmax + 1))
    chg = {k: spr_all[k] - spr_all[k - 12] for k in ks + [kmax - 1, kmax - 12]}
    t2 = trend("利差比一年前", c_now, chg[kmax - 1], chg[kmax - 12], [chg[k] for k in ks], K.FIN_SPREAD_JUMP, False)
    hot1, hot2 = nf_v > K.FIN_NFCI_LINE, c_now >= K.FIN_SPREAD_JUMP
    signals = [
        {"名": "金融状况指数", "说明": "高于 0＝比平时紧", "值": f"{nf_v:+.2f}",
         "状态": "比平时紧" if hot1 else "没比平时紧", "报警字": "金融状况比平时紧", "报警": hot1, "色": "顶" if hot1 else "平", **t1, **card_when("nfci", nf_d),
         "走势起": K.fmt_ym(ends[0]),
         "依据": f"报警线 {K.FIN_NFCI_LINE:g}：过了就是比平时紧。第一次变紧后，2 年内有衰退 {rows[2]['之后']}"},
        {"名": "利差比一年前", "说明": "企业债减十年国债利率", "值": f"{c_now:+.2f}",
         "状态": "扩大超线" if hot2 else "没扩大",
         "报警字": f"信用利差一年扩大超 {T1:g} 个百分点", "报警": hot2, "色": "顶" if hot2 else "平", **t2, **card_when("baa", ym_date(kmax), True),
         "走势起": K.fmt_ym(ym_date(ks[0])),
         "依据": f"报警线 +{T1:g}：过了就是表里说的「信用利差一年扩大」。当时或 2 年内有衰退 {rows[0]['之后']}"},
    ]
    so = so_line(signals, rows)
    names = [n for n, r in (("信用利差扩大", rows[0]), ("金融状况变紧", rows[2]))
             if r["判断"] in WORKS and int(r["比例"][:-1]) > int(r["平时"][:-1])]
    line = {"字": "历史规律：" + ("、".join(n[2:] if n.startswith("信用") else n for n in names) + "后衰退更常见" if names else "衰退跟平时一样")
                 ,   # 美股那两行看表；一句话只留一行，页面离高度上限太近（11-20 云端超限）
            "依据": "每一行都和平时比；差不到 15 个百分点就算跟平时一样"}
    display = {
        "金融": {"标题": "金融状况", "对现在": so, "一句话": line, "现在": now,
               "表头": ["出现后，历史上", "发生概率", "平时", "有没有用"],
               "表头依据": "利差＝信用利差，单位个百分点；每一轮只记第一次，之前 12 个月都没有才算；利差 1954 年起、指数 1971 年起",
               "行": rows, "信号": signals, "怎么读": K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"]),
               "历史更新": K.HIST_YEARLY},
        "数据截至": None,   # 指数每周、利差每月公布，不拉低全看板的「数据截至」；断更由验收的新鲜度检查拦
        "最新数据": f"指数 {nf_d.month}月{nf_d.day}日 · {updates('nfci')}",
    }
    detail = {"全部判断": judged, "行键": [x[0] for x in spec],
              "利差事件": {str(th): [ym_str(k) for k in e] for th, e in ev1.items()},
              "利差事件变化": {str(th): {ym_str(k): round(S.chg(k), 3) for k in e} for th, e in ev1.items()},
              "指数事件": {str(th): [ym_str(k) for k in e] for th, e in ev2.items()},
              "现在": {"指数": [nf_d.isoformat(), nf_v], "利差": [ym_str(kmax), sp_now, c_now]}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    for r in disp["金融"]["行"]:
        print(r["名"].replace("\n", " "), r["之后"], r["比例"], r["平时"], r["判断"], "|", r["依据"])
    print(disp["金融"]["对现在"]["字"], len(disp["金融"]["对现在"]["字"]))
    print(disp["金融"]["一句话"]["字"])
    print(disp["金融"]["现在"]["字"])
    for s in disp["金融"]["信号"]:
        print(s["名"], s["值"], s["状态"], s["比上月"], s["比去年"], s["离报警"])
    print(det["利差事件变化"], det["指数事件"], det["全部判断"])
