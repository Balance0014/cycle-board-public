"""图五 黄金：看板上的每个字、每个数都由这里算出来，写进 results/board5.json。

口径全部来自 defs.py「黄金」一节。核心问题：金价现在在大涨大跌的哪一段；常说的黄金周期规律（衰退、降息、实际利率）准不准。
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from board2 import last_at, minus_months, monthly, trend, card_when, ym  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board5.json"
COLORS = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))


def ym_str(k):
    return f"{k // 12}-{k % 12 + 1:02d}"


def span(m):
    return f"{m}个月" if m < 12 else f"{m // 12}年" + (f"{m % 12}个月" if m % 12 else "")


def ym_date(k):
    return dt.date(k // 12, k % 12 + 1, 1)


class Study:
    def __init__(self, today):
        self.all = {ym(d): v for d, v in parse("gold") if d >= K.GOLD_START}
        self.obs_end = ym(dt.date(today.year - 1, 12, 1))     # 历史统计只用到上一年 12 月，每年 1 月更新
        self.g = {k: v for k, v in self.all.items() if k <= self.obs_end}
        self.rec = monthly("usrec")
        self.starts = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k - 1, 0) == 0)
        self.ends = sorted(k for k, v in self.rec.items() if v == 1 and self.rec.get(k + 1, 0) == 0)
        gs, cpi = monthly("gs10"), monthly("cpi")
        self.rr = {k: gs[k] - (cpi[k] / cpi[k - 12] - 1) * 100 for k in gs if k in cpi and k - 12 in cpi and k in self.g}

    def ret(self, a, h):
        return self.g[a + h] / self.g[a] - 1 if a in self.g and a + h in self.g else None

    def count_after(self, months, h):
        xs = [self.ret(k + 1, h) for k in months]
        xs = [x for x in xs if x is not None]
        return {"k": sum(x > 0 for x in xs), "n": len(xs)}

    def base(self, h):
        c = self.count_after(sorted(self.g), h)
        return c["k"] / c["n"]

    def recession(self, lead):
        recs = [(s, e) for s, e in zip(self.starts, self.ends) if s - lead in self.g and e in self.g]
        ups = {ym_str(s): round(self.g[e] / self.g[s - lead] - 1, 3) for s, e in recs}
        ks = sorted(self.g)
        bases = []
        for s, e in recs:
            L = e - (s - lead)
            w = [self.ret(a, L) for a in ks]
            w = [x for x in w if x is not None]
            bases.append(sum(x > 0 for x in w) / len(w))
        return {"k": sum(v > 0 for v in ups.values()), "n": len(ups), "平时": sum(bases) / len(bases), "各次": ups}

    def bear_episodes(self, th, series=None):
        """月均价比之前的历史最高低 th 以上：每一轮记第一次跌破的月份；回到历史最高才算这一轮结束。"""
        g = series or self.g
        out, ath, ath_k, inside = [], None, None, None
        for k in sorted(g):
            v = g[k]
            if ath is None or v >= ath:
                if inside:
                    inside["回到最高"] = ym_str(k)
                    out.append(inside)
                    inside = None
                ath, ath_k = v, k
                continue
            dd = v / ath - 1
            if inside is None and dd <= -th:
                inside = {"顶": ym_str(ath_k), "顶价": ath, "跌破": ym_str(k), "最深": dd, "底": ym_str(k), "_k": k}
            elif inside is not None and dd < inside["最深"]:
                inside["最深"], inside["底"] = dd, ym_str(k)
        if inside:
            inside["回到最高"] = None
            out.append(inside)
        return out


def so_line(signals, rows, bear_row):
    """对现在：离两成线多远 + 常说的几条规律灵不灵。全由下面的数拼出来。"""
    dd = signals[0]
    cyc = [r for r in rows if not r["名"].startswith("金价从最高")]
    flat = all(r["判断"] == K.VERDICT_WORDS[2] for r in cyc)
    gap = -K.GOLD_BEAR * 100 - float(dd["值"].rstrip("%"))
    if dd["报警"]:
        head = f"对现在：要小心。月均金价比最高跌超两成，以前 {bear_row['之后'].split('/')[1]} 轮里 1 年后更高的只有 {bear_row['之后'].split('/')[0]} 轮"
    else:
        head = f"对现在：说不准。月均金价比最高低 {dd['值'].lstrip('-')}，再跌 {abs(gap):.0f} 点报警"
    tail = "；常说的规律都预测不了金价" if flat else "；有用的规律见表里标色那几行"
    return {"字": head + tail, "色": "顶" if dd["报警"] else "平",
            "依据": "跌超两成的几轮见本图的表；衰退、降息、实际利率之后金价 1 年后更高的概率都和平时差不多"}


def era_note(S, falling):
    """按年代拆开：金价 1 年后更高的概率年代之间差很多，实际利率在降的月份和本年代平均差不多。"""
    out = []
    for a, b in K.GOLD_ERAS:
        ks = [k for k in S.g if a <= k // 12 <= b]
        base = S.count_after([k - 1 for k in ks], 12)
        fl = S.count_after([k for k in falling if a <= k // 12 <= b], 12)
        if base["n"] and fl["n"]:
            out.append(base["k"] / base["n"] * 100)
    return (f"金价涨不涨主要看大年代：各年代 1 年后更高 {min(out):.0f}%–{max(out):.0f}%；"
            "实际利率分年代看也跟平时一样")


def one_line(rows):
    """第二张图的一句话：三条常说的规律灵不灵 + 跌超两成那行。"""
    cyc, bear = rows[:3], rows[3]
    head = ("历史规律：衰退、降息、实际利率都预测不了金价"
            if all(r["判断"] == K.VERDICT_WORDS[2] for r in cyc) else "历史规律：有用的见标色那几行")
    if bear["判断"] != K.VERDICT_WORDS[2]:
        head += "；跌超两成那行只有几轮，参考就好"
    return head


def build():
    rr_daily = parse("dfii10")
    today = rr_daily[-1][0]
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
        if j["判断"] == K.VERDICT_WORDS[1] and j["k"] / j["n"] < j["平时"]:
            return f"。只有 {j['n']} 轮、换门槛不稳，只算有点用"
        if j["判断"] == K.VERDICT_WORDS[1]:
            return f"。成立不到 {K.STRONG * 100:.0f}%，只算有点用"
        return ""

    # 1 衰退期间
    recs = {lead: S.recession(lead) for lead in K.DD_VARIANTS}
    R = recs[K.DD_LEAD]
    flat0 = sum(1 for v in R["各次"].values() if v == 0)
    # 2 第一次降息后（图二的事件）
    ev = json.loads((ROOT / "results" / "board2.json").read_text())["明细"]["事件"]
    cuts = [ym(dt.date.fromisoformat(e["日期"][:10])) for e in ev if e["类"] == "C"
            and dt.date.fromisoformat(e["日期"][:10]) >= K.GOLD_START]
    cut = {h: {**S.count_after(cuts, h), "平时": S.base(h)} for h in K.GOLD_H_VARIANTS}
    Cm = cut[12]
    # 3 实际利率在降
    falling = [k for k in S.rr if k - 12 in S.rr and S.rr[k] < S.rr[k - 12]]
    rrf = {h: {**S.count_after(falling, h), "平时": S.base(h)} for h in K.GOLD_H_VARIANTS}
    Rr = rrf[12]
    # 4 跌超两成后
    bears = {th: S.bear_episodes(th) for th in K.GOLD_BEAR_VARIANTS}
    bear = {th: {**S.count_after([b["_k"] for b in eps], 12), "平时": S.base(12)} for th, eps in bears.items()}
    B = bear[K.GOLD_BEAR]
    spec = [
        ("衰退", "衰退期间\n金价上涨", R, list(recs.values()),
         f"1971 年以来 {R['n']} 次衰退，{R['k']} 次期间金价上涨" + (f"，{flat0} 次持平" if flat0 else "")
         + f"；平时 {R['平时'] * 100:.0f}%"),
        ("降息", "第一次降息后\n1 年金价更高", Cm, list(cut.values()),
         f"利率周期的第一次降息，金价放开后 {Cm['n']} 次，{Cm['k']} 次 1 年后金价更高；平时 {Cm['平时'] * 100:.0f}%"),
        ("实际利率", "实际利率比一年前低\n1 年后金价更高", Rr, list(rrf.values()),
         f"实际利率比一年前低的 {Rr['n']} 个月里，{Rr['k']} 个月 1 年后金价更高；平时 {Rr['平时'] * 100:.0f}%"),
        ("跌两成", "金价从最高跌超两成\n1 年后金价更高", B, list(bear.values()),
         f"从历史最高跌超 {K.GOLD_BEAR * 100:.0f}% 共 {B['n']} 轮，{B['k']} 轮 1 年后更高；平时 {B['平时'] * 100:.0f}%"),
    ]
    rows = []
    for key, name, m, runs, why in spec:
        w = judge(key, runs, m)
        rows.append({"名": name, "之后": f"{m['k']}/{m['n']}", "比例": f"{m['k'] / m['n'] * 100:.0f}%",
                     "平时": f"{m['平时'] * 100:.0f}%", "判断": w, "色": COLORS[w], "依据": why + tail(key)})

    # ── 金价跌超两成的几轮（用全部月份，含今年，看现在在哪）──
    eps = S.bear_episodes(K.GOLD_BEAR, S.all)
    cycles = []
    for b in eps:
        top_k = ym(dt.date.fromisoformat(b["顶"] + "-01"))
        back = b["回到最高"]
        cycles.append({"名": f"{b['顶'][2:4]}年顶", "顶价": f"{b['顶价']:,.0f}",
                       "最深": f"{b['最深'] * 100:.0f}%", "完": back is not None,
                       "回到最高": span(ym(dt.date.fromisoformat(back + '-01')) - top_k) if back else "还没回到",
                       "依据": f"{b['顶']} 见顶 {b['顶价']:,.0f} 美元，{b['跌破']} 跌超两成，"
                               f"{b['底']} 最低" + (f"，{back} 回到最高" if back else "，到现在还没回到")})
    kmax = max(S.all)
    ath_k = max(S.all, key=lambda k: S.all[k])
    now_v = S.all[kmax]
    if not cycles or cycles[-1]["完"]:   # 这一轮还没跌超两成，也列出来对照
        low = min(v for k, v in S.all.items() if k >= ath_k)
        cycles.append({"名": f"{ym_str(ath_k)[2:4]}年顶", "顶价": f"{S.all[ath_k]:,.0f}",
                       "最深": f"{(low / S.all[ath_k] - 1) * 100:.0f}%", "完": False, "旗": "这一轮，还没跌超两成",
                       "回到最高": "还没回到",
                       # 不写当月价（每月都变，会让复核闸月月响）；现价在「现在」那行
                       "依据": f"{ym_str(ath_k)} 见顶 {S.all[ath_k]:,.0f} 美元，之后最低 {low:,.0f}；还没跌超两成"})
    for c in cycles:
        c.setdefault("旗", "" if c["完"] else "这一轮，还没回到最高")
    rv = rr_daily[-1][1]
    rv_y = last_at(rr_daily, minus_months(today, 12))
    rd = rr_daily[-1][0]
    now = {"字": f"{K.fmt_ym(ym_date(kmax))}月均价 {now_v:,.0f} 美元（{updates('gold')}；无官方日价），"
                 f"比最高低 {(1 - now_v / S.all[ath_k]) * 100:.0f}%，"
                 f"比一年前{'高' if now_v >= S.all[kmax - 12] else '低'} {abs(now_v / S.all[kmax - 12] - 1) * 100:.0f}%",
           "依据": f"实际利率 {rd.month}月{rd.day}日 {rv:+.2f}%，比一年前{'高' if rv >= rv_y else '低'} {abs(rv - rv_y):.2f}；"
                   "实际利率低对金价好？验过跟平时一样"}

    # ── 报警卡片 ──
    gm = sorted(S.all.items())

    def dd_at(k):
        return (S.all[k] / max(v for kk, v in gm if kk <= k) - 1) * 100
    ks = [k for k, _ in gm][-(K.TREND_MONTHS + 1):]
    dt_ = trend("离历史最高", dd_at(kmax), dd_at(kmax - 1), dd_at(kmax - 12), [dd_at(k) for k in ks],
                -K.GOLD_BEAR * 100, True, nd=0, unit=" 个百分点")
    d_now = dd_at(kmax)
    signals = [
        {"名": "离历史最高", "说明": "月均价比历史最高低多少", "值": f"{d_now:.0f}%",
         "状态": "跌超两成" if d_now <= -K.GOLD_BEAR * 100 else "没跌超两成", "报警字": "金价比历史最高跌超两成", "报警": d_now <= -K.GOLD_BEAR * 100,
         "色": "顶" if d_now <= -K.GOLD_BEAR * 100 else "平", **dt_, **card_when("gold", ym_date(kmax), True), "走势起": K.fmt_ym(ym_date(ks[0])),
         "依据": f"报警线 -{K.GOLD_BEAR * 100:.0f}%：以前跌破的几轮见上表，有的很多年才回到最高"},
    ]
    so = so_line(signals, rows, rows[3])
    how = K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"])
    display = {
        "现在": {"标题": "黄金", "对现在": so, "现在": now,
                 # 2026-11-19 拿网上的当天最高价核对对不上：表里全是月均价（世界银行没有日价），表头直接写明
                 "表头": ["每一轮", "顶（月均）", "最深跌", "回到最高用了"],
                 "表头依据": f"月均价从历史最高跌超 {K.GOLD_BEAR * 100:.0f}% 的每一轮；按当天价算，顶更高、跌更深",
                 "轮": cycles, "信号": signals, "怎么读": how, "历史更新": updates("gold")},
        "规律": {"标题": "黄金规律准不准", "对现在": so,
                 "一句话": {"字": one_line(rows),
                           "依据": era_note(S, falling)},
                 "表头": ["出现后，历史上", "发生概率", "平时", "有没有用"],
                 "表头依据": "每一行：这件事出现后，历史上金价真的上涨的比例；和平时（不看信号）的比例对照",
                 "行": rows, "怎么读": how, "历史更新": K.HIST_YEARLY},
        "数据截至": today.isoformat(),
        # 2026-11-20：黄金当天大跌，菜单却写「最新数据 11-17」像是已更新——那是实际利率的日期。金价只有世界银行月均价
        # （官方免费的每天金价 2017 年后没有了），菜单照原油的写法写清是哪个月的月均价
        "最新数据": f"{int(ym_str(kmax)[5:])}月月均价 · {updates('gold')}",
    }
    detail = {"全部判断": judged, "行键": [x[0] for x in spec],
              "衰退": {str(k): v for k, v in recs.items()}, "降息": {str(k): v for k, v in cut.items()},
              "实际利率": {str(k): v for k, v in rrf.items()},
              "跌两成": {str(th): [{k: v for k, v in b.items() if k != "_k"} for b in e] for th, e in bears.items()},
              "现在": {"金价": [ym_str(kmax), now_v], "实际利率": [today.isoformat(), rv]}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    for c in disp["现在"]["轮"]:
        print(c["名"], c["顶价"], c["最深"], c["回到最高"])
    for r in disp["规律"]["行"]:
        print(r["名"].replace("\n", " "), r["之后"], r["平时"], r["判断"], "|", r["依据"][-80:])
    print(disp["现在"]["对现在"]["字"])
    print(disp["现在"]["现在"]["字"])
    for s in disp["现在"]["信号"]:
        print(s["名"], s["值"], s["状态"], s["比上月"], s["比去年"], s["离报警"])
    print(det["跌两成"])
