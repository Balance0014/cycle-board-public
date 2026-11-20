"""图四 比特币周期：看板上的每个字、每个数都由这里算出来，写进 results/board4.json。

口径全部来自 defs.py「比特币周期」一节；周期顶、周期底沿用图一（board1.crypto_clock），不另算。
核心问题：这一轮走到哪了；每轮的节奏（减半后多久见顶、见顶后跌多深、多久见底）；跌破 200 周均线之后历史上怎么走。
"""
import bisect
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board1 as B  # noqa: E402
import defs as K  # noqa: E402
from board2 import last_at, minus_months, month_ends, trend, card_when  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board4.json"
COLORS = dict(zip(K.VERDICT_WORDS, ("蓝", "浅蓝", "平")))


def wan(x):
    """价格写成「几万」，一万以下照写。"""
    return f"{x / 1e4:.1f}万".replace(".0万", "万") if x >= 1e4 else f"{x:,.0f}"


class Study:
    def __init__(self, rows):
        self.d = [r[0] for r in rows]
        self.v = [r[1] for r in rows]
        self.last = self.d[-1]

    def idx(self, day):
        return bisect.bisect_right(self.d, day) - 1

    def at(self, day):
        i = self.idx(day)
        return self.v[i] if i >= 0 else None

    def wma(self, i):
        n = K.BTC_WMA_WEEKS
        if i - 7 * (n - 1) < 0:
            return None
        return sum(self.v[i - 7 * j] for j in range(n)) / n

    def ratio(self, i):
        w = self.wma(i)
        return self.v[i] / w if w else None

    def fwd(self, i, days):
        t = self.d[i] + dt.timedelta(days=days)
        if t > self.last:
            return None
        return self.v[self.idx(t)] / self.v[i] - 1

    def worst_after(self, i, days, from_peak=True):
        """i 之后 days 天里（含 i），收盘价相对 期间高点（from_peak）或 i 当天 的最大跌幅。"""
        end = self.d[i] + dt.timedelta(days=days)
        peak, worst, j = self.v[i], 0.0, i
        while j < len(self.v) and self.d[j] <= end:
            if from_peak:
                peak = max(peak, self.v[j])
            worst = min(worst, self.v[j] / peak - 1)
            j += 1
        return worst

    def month_end_idx(self):
        return [i for i in range(len(self.d) - 1) if self.d[i + 1].month != self.d[i].month]

    # ── 跌破 200 周均线 ──
    def zone_entries(self, zone):
        out, last_in = [], None
        for i in range(len(self.v)):
            r = self.ratio(i)
            if r is None or r > zone:
                continue
            if last_in is None or (self.d[i] - last_in).days > K.BTC_EPISODE_DAYS:
                out.append(i)
            last_in = self.d[i]
        return out

    def zone_stats(self, zone, days):
        ent = self.zone_entries(zone)
        rs = [(i, self.fwd(i, days)) for i in ent]
        done = [(i, r) for i, r in rs if r is not None]
        base = [self.fwd(i, days) for i in self.month_end_idx() if self.wma(i)]
        base = [x for x in base if x is not None]
        return {"事件": [self.d[i].isoformat() for i in ent], "k": sum(r > 0 for _, r in done), "n": len(done),
                "平时": sum(x > 0 for x in base) / len(base),
                "各次": {self.d[i].isoformat(): round(r, 3) for i, r in done},
                "之后再跌": {self.d[i].isoformat(): round(self.worst_after(i, days, from_peak=False), 3) for i, _ in done}}

    def deep_base(self, depth):
        """平时：每一天都当起点，之后 365 天里从高点跌到 depth 的比例。"""
        hit = tot = 0
        for i in range(len(self.v)):
            if self.d[i] + dt.timedelta(days=365) > self.last:
                break
            tot += 1
            hit += self.worst_after(i, 365) <= -depth
        return hit / tot


def so_line(signals, zone_row, this_dd365, deep):
    """对现在：按 200 周均线、这轮跌的深浅、报警自动写一句。"""
    sig = {s["名"]: s for s in signals}
    below = sig["比200周均线"]["报警"]
    k, n = map(int, zone_row["之后"].split("/"))
    parts = []
    if below:
        parts.append(f"以前 {n} 次跌破 200 周均线，1 年后" + ("都更高" if k == n else f"{k} 次更高"))
    else:
        parts.append("价格在 200 周均线上方")
    if sig["离这轮顶"]["报警"]:
        parts.append("已跌到以前大底的深度")
    elif this_dd365 is not None and this_dd365 > -deep:
        parts.append("但这轮跌得浅，可能不一样")
    head = "在大底区" if below else "还没到大底区"
    return {"字": f"对现在：{head}。" + "；".join(parts), "色": "顶" if any(s["报警"] for s in signals) else "平",
            "依据": "前三轮大底都在 200 周均线或以下；深浅＝见顶后一年最多跌了多少，和前几轮比"}


def build():
    rows = parse("btc")
    S = Study(rows)
    today = S.last
    clock = B.crypto_clock(B.Series(rows), today)
    tops, bots = clock["周期顶"], clock["周期底"]
    first_ath = max(v for d, v in rows if d < K.HALVINGS[0])
    prev = [first_ath] + [t["顶价"] for t in tops[:-1]]

    # ── 每一轮的节奏 ──
    cycles = []
    for i, t in enumerate(tops):
        td = dt.date.fromisoformat(t["顶日"])
        h = K.HALVINGS[i]
        b = next((x for x in bots if x["中期选举年"] == t["大选年"] + 2), None)
        ti = S.idx(td)
        full = td + dt.timedelta(days=365) <= today
        dd365 = S.worst_after(ti, 365) if full else None
        dd_all = (b["底价"] / t["顶价"] - 1) if b else None
        bd = dt.date.fromisoformat(b["底日"]) if b else None
        done = bool(b and b["已确认"])
        cycles.append({"名": f"{td.year % 100}年顶" + ("（这轮）" if i == len(tops) - 1 else ""),
                       "减半后": f"{(td - h).days} 天", "倍数": f"{t['顶价'] / prev[i]:.1f} 倍",
                       "最深": f"{dd_all * 100:.0f}%" if dd_all is not None else "—", "完": done,
                       "见底": f"{(bd - td).days} 天" if done else "未确认",
                       "色": "平" if done else "顶",
                       "依据": f"见顶 {K.fmt_ymd(td)} {wan(t['顶价'])}，"
                               + (f"{'见底' if done else '最低'} {K.fmt_ymd(bd)} {wan(b['底价'])}，" if b else "")
                               + (f"一年内最深跌 {dd365 * 100:.0f}%" if dd365 is not None else "见顶还不满一年")
                               + ("" if done else "；再高过顶才算见底")})

    # ── 规律准不准 ──
    judged = {}

    def judge(key, runs, main):
        robust = all(K.verdict(r["k"], r["n"], r["平时"]) for r in runs.values())
        w = K.verdict_word(main["k"], main["n"], main["平时"], robust)
        judged[key] = {"k": main["k"], "n": main["n"], "平时": round(main["平时"], 4), "判断": w,
                       "主口径过关": K.verdict(main["k"], main["n"], main["平时"]),
                       "换算法": [f"{r['k']}/{r['n']}" for r in runs.values() if r is not main]}
        return w

    def tail(key):
        j = judged[key]
        if j["判断"] == K.VERDICT_WORDS[1] and j["主口径过关"]:
            return "。换算法有一种不过，只算有点用"
        if j["判断"] == K.VERDICT_WORDS[1]:
            return f"。成立不到 {K.STRONG * 100:.0f}%，只算有点用"
        return ""

    full_tops = [S.idx(dt.date.fromisoformat(t["顶日"])) for t in tops
                 if dt.date.fromisoformat(t["顶日"]) + dt.timedelta(days=365) <= today]
    deep = {}
    for dep in K.BTC_DEEP_VARIANTS:
        hits = [S.worst_after(i, 365) <= -dep for i in full_tops]
        deep[dep] = {"k": sum(hits), "n": len(hits), "平时": S.deep_base(dep)}
    Dp = deep[K.BTC_DEEP]
    zone1 = {z: S.zone_stats(z, 365) for z in K.BTC_ZONE_VARIANTS}
    zone2 = {z: S.zone_stats(z, 730) for z in K.BTC_ZONE_VARIANTS}
    Z1, Z2 = zone1[K.BTC_ZONE], zone2[K.BTC_ZONE]
    spec = [
        ("深跌", "见顶后 1 年内\n从顶跌超 70%", Dp, deep,
         f"{Dp['n']} 轮见顶满一年的里，{Dp['k']} 轮一年内从顶跌超 {K.BTC_DEEP * 100:.0f}%；平时 {Dp['平时'] * 100:.0f}%"),
        ("均线1年", "跌破 200 周均线\n1 年后价格更高", Z1, zone1,
         f"2014 年以来跌破 {Z1['n']} 次，{Z1['k']} 次 1 年后更高；平时 {Z1['平时'] * 100:.0f}%。"
         f"跌破后一年里最多再跌 {min(Z1['之后再跌'].values()) * 100:.0f}%"),
        ("均线2年", "跌破 200 周均线\n2 年后价格更高", Z2, zone2,
         f"同样这 {Z2['n']} 次，{Z2['k']} 次 2 年后更高；平时 {Z2['平时'] * 100:.0f}%"),
    ]
    table = []
    for key, name, m, runs, why in spec:
        w = judge(key, runs, m)
        table.append({"名": name, "之后": f"{m['k']}/{m['n']}", "比例": f"{m['k'] / m['n'] * 100:.0f}%",
                      "平时": f"{m['平时'] * 100:.0f}%", "判断": w, "色": COLORS[w], "依据": why + tail(key)})

    # ── 现在（每天跟着数据走）──
    t = tops[-1]
    td = dt.date.fromisoformat(t["顶日"])
    low_d, low_v = min(((d, v) for d, v in rows if d > td), key=lambda r: r[1])
    now_v = S.v[-1]
    now = {"字": f"离这轮顶（{K.fmt_ym(td)} {wan(t['顶价'])}）{(today - td).days} 天；"
                 f"最低到 {wan(low_v)}（{(low_v / t['顶价'] - 1) * 100:.0f}%），{today.month}月{today.day}日 {wan(now_v)}（{(now_v / t['顶价'] - 1) * 100:.0f}%）",
           "依据": f"这轮顶 {K.fmt_ymd(td)} 收盘 {wan(t['顶价'])}；之后最低 {K.fmt_ymd(low_d)} 收盘 {wan(low_v)}"}

    # ── 报警卡片 ──
    ends = month_ends(today, K.TREND_MONTHS)

    def ratio_at(d):
        return S.ratio(S.idx(d))

    r_now = ratio_at(today)
    rt = trend("比200周均线", r_now, ratio_at(minus_months(today, 1)), ratio_at(minus_months(today, 12)),
               [ratio_at(d) for d in ends], K.BTC_ZONE, True)
    shallow = max(x["底价"] / tp["顶价"] - 1 for x, tp in zip(bots, tops) if x["已确认"])   # 前几轮最浅的底

    def dd_at(d):
        top_to_d = max(v for day, v in rows if day <= d)   # 当时为止的历史最高
        return (last_at(rows, d) / top_to_d - 1) * 100

    dt_ = trend("离这轮顶", dd_at(today), dd_at(minus_months(today, 1)), dd_at(minus_months(today, 12)),
                [dd_at(d) for d in ends], round(shallow * 100, 1), True, nd=0, unit=" 个百分点")
    bot_ratios = [ratio_at(dt.date.fromisoformat(b["底日"])) for b in bots if b["已确认"]]
    signals = [
        {"名": "比200周均线", "说明": "价格除以 200 周均线", "值": f"{r_now:.2f}", "状态": "低于均线" if r_now <= K.BTC_ZONE else "高于均线", "报警字": "比特币跌破200周均线",
         "报警": r_now <= K.BTC_ZONE, "色": "顶" if r_now <= K.BTC_ZONE else "平", **rt, **card_when("btc", today), "走势起": K.fmt_ym(ends[0]),
         "依据": "1 以下＝跌破均线；前几轮大底时是 " + "、".join(f"{x:.2f}" for x in bot_ratios)},
        {"名": "离这轮顶", "说明": "价格比历史最高跌了多少", "值": f"{dd_at(today):.0f}%", "状态": "到大底深度" if dd_at(today) <= shallow * 100 else "没到大底深度", "报警字": "比特币从最高跌到以前大底的深度",
         "报警": dd_at(today) <= shallow * 100, "色": "顶" if dd_at(today) <= shallow * 100 else "平", **dt_, **card_when("btc", today),
         "走势起": K.fmt_ym(ends[0]),
         "依据": f"报警线 {shallow * 100:.0f}% 是前几轮里最浅的大底；跌到这里，这轮也到了大底的深度"},
    ]
    this_full = td + dt.timedelta(days=365) <= today
    so = so_line(signals, table[1], S.worst_after(S.idx(td), 365) if this_full else None, K.BTC_DEEP)
    mult = [t["顶价"] / p_ for t, p_ in zip(tops, prev)]
    shrinking = all(a > b for a, b in zip(mult, mult[1:]))
    how = K.legend(["发生概率", "平时", "有用", "有点用", "跟平时一样", "报警信号"])
    display = {
        "节奏": {"标题": "比特币周期", "对现在": so, "现在": now,
                 "表头": ["每一轮", "减半后见顶", "比上轮顶", "见顶后最深", "见顶后见底"],
                 "表头依据": "周期顶、周期底和四年周期那张图同一个定义：大选后两年里的最高收盘是顶；顶之后、再高过顶之前的最低收盘是底",
                 "轮": cycles, "信号": signals, "怎么读": how, "历史更新": K.HIST_LIVE},
        "规律": {"标题": "比特币规律准不准", "对现在": so,
                 "一句话": {"字": ("历史规律：每轮顶比上轮涨得越来越少；" if shrinking else "历史规律：")
                                 + f"跌破 200 周均线后，1 年后价格{'都更高' if Z1['k'] == Z1['n'] else '多半更高'}，但只有 {Z1['n']} 次",
                           "依据": "顶是上轮几倍：" + "、".join(c["倍数"] for c in cycles) + f"。跌破 200 周均线一共 {Z1['n']} 次"},
                 "表头": ["出现后，历史上", "发生概率", "平时", "有没有用"],
                 "表头依据": "每一行：这件事出现后，历史上真的发生的比例（发生概率）；和不看信号时的平时对照",
                 "行": table, "怎么读": how, "历史更新": K.HIST_LIVE},
        "数据截至": today.isoformat(),
        "最新数据": f"{today.month}月{today.day}日 · {updates('btc')}",
    }
    detail = {"全部判断": judged, "行键": [x[0] for x in spec], "周期顶": tops, "周期底": bots,
              "深跌": {str(k): v for k, v in deep.items()}, "均线1年": {str(k): v for k, v in zone1.items()},
              "均线2年": {str(k): v for k, v in zone2.items()},
              "现在": {"比200周均线": r_now, "离顶": dd_at(today), "价格": now_v}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    for c in disp["节奏"]["轮"]:
        print(c["名"], c["减半后"], c["倍数"], c["最深"], c["见底"])
    for r in disp["规律"]["行"]:
        print(r["名"].replace("\n", " "), r["之后"], r["平时"], r["判断"], "|", r["依据"][:160])
    print(disp["节奏"]["对现在"]["字"])
    print(disp["节奏"]["现在"]["字"])
    for s in disp["节奏"]["信号"]:
        print(s["名"], s["值"], s["状态"], s["比上月"], s["比去年"], s["离报警"], s["走势"][-5:])
