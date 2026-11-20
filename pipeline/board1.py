"""图一 美国四年周期：看板上的每个字、每个数都由这里算出来，写进 results/board1.json。

口径全部来自 defs.py；这里只负责按口径计算，不许自己另定规则。
"""
import bisect
import sys
import datetime as dt
import json
import statistics as st
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import defs as K  # noqa: E402
from fetch import parse, updates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "board1.json"


class Series:
    def __init__(self, rows, monthly=False):
        rows = sorted(rows)
        self.d = [r[0] for r in rows]
        self.v = [r[1] for r in rows]
        self.monthly = monthly

    def at(self, day):
        """当天或之前最后一个值。"""
        i = bisect.bisect_right(self.d, day) - 1
        return (self.d[i], self.v[i]) if i >= 0 else (None, None)

    def between(self, a, b):
        i, j = bisect.bisect_left(self.d, a), bisect.bisect_right(self.d, b)
        return list(zip(self.d[i:j], self.v[i:j]))

    @property
    def first(self):
        return self.d[0]

    @property
    def last(self):
        return self.d[-1]


# ── 收益（口径见 defs.py）────────────────────────────────────────
def year_return(s: Series, y: int):
    if s.monthly:
        a, b = s.at(K.D(y - 1, 12, 1)), s.at(K.D(y, 12, 1))
        ok = a[0] == K.D(y - 1, 12, 1) and b[0] == K.D(y, 12, 1) and s.last > K.D(y, 12, 1)
    else:
        a, b = s.at(K.D(y - 1, 12, 31)), s.at(K.D(y, 12, 31))
        ok = a[0] is not None and a[0].year == y - 1 and s.first.year < y and s.last >= K.D(y, 12, 31)
    return b[1] / a[1] - 1 if ok else None


def quarter_return(s: Series, y: int, q: int):
    end_m = 3 * q
    if s.monthly:
        pm = (y, end_m - 3) if q > 1 else (y - 1, 12)
        a, b = s.at(K.D(*pm, 1)), s.at(K.D(y, end_m, 1))
        ok = a[0] == K.D(*pm, 1) and b[0] == K.D(y, end_m, 1)
    else:
        start = K.D(y, end_m - 2, 1) - K.DAY
        end = (K.D(y, end_m + 1, 1) if end_m < 12 else K.D(y + 1, 1, 1)) - K.DAY
        a, b = s.at(start), s.at(end)
        ok = a[0] is not None and a[0] > start - dt.timedelta(days=10) and s.last >= end
    return b[1] / a[1] - 1 if ok else None


def year_low_date(s: Series, y: int):
    rows = s.between(K.D(y, 1, 1), K.D(y, 12, 31))
    return min(rows, key=lambda r: r[1])[0] if rows else None


def complete_years(s: Series, today: dt.date):
    y0 = s.first.year + (0 if (s.monthly and s.first.month == 1) else 1)
    return [y for y in range(y0, today.year) if year_return(s, y) is not None]


def cycle_stats(s: Series, today):
    out = {}
    for c in range(4):
        ys = [y for y in complete_years(s, today) if K.cycle_year(y) == c]
        rets = [(y, year_return(s, y)) for y in ys]
        up = sum(1 for _, r in rets if r > 0)
        out[c] = {"n": len(rets), "up": up, "median": st.median([r for _, r in rets]) if rets else None,
                  "years": {str(y): round(r, 4) for y, r in rets}}
    return out


# ── 加密周期时钟（口径见 defs.py）──────────────────────────────────
def crypto_clock(s: Series, today):
    tops, bottoms, breaks = [], [], []
    for e in range(2008, today.year + 1, 4):
        ed = K.election_day(e)
        # 周期顶
        win = s.between(ed + K.DAY, ed + dt.timedelta(days=K.TOP_WINDOW_DAYS))
        if win and s.first <= ed and today >= ed + dt.timedelta(days=K.TOP_WINDOW_DAYS):
            td, tv = max(win, key=lambda r: r[1])
            tops.append({"大选年": e, "顶日": td.isoformat(), "顶价": tv, "距大选天数": (td - ed).days,
                         "所在年": K.CYCLE_NAMES[K.cycle_year(td.year)]})
            # 周期底：顶之后、再次高过顶之前的最低收盘
            after = s.between(td + K.DAY, today)
            seg = []
            for d, v in after:
                if v > tv:
                    break
                seg.append((d, v))
            done = len(seg) < len(after)
            if seg:
                bd, bv = min(seg, key=lambda r: r[1])
                m = K.election_day(e + 2)
                bottoms.append({"中期选举年": e + 2, "底日": bd.isoformat(), "底价": bv,
                                "距中期选举天数": (bd - m).days, "已确认": done})
        # 破前高：大选前一年那天起，第一次收盘高过那天之前的历史最高
        ref = ed - dt.timedelta(days=K.BREAK_LOOKBACK_DAYS)
        if s.first < ref - dt.timedelta(days=180):
            prior = s.between(s.first, ref - K.DAY)
            ath = max(v for _, v in prior)
            hit = next(((d, v) for d, v in s.between(ref + K.DAY, today) if v > ath), None)
            if hit:
                breaks.append({"大选年": e, "破前高日": hit[0].isoformat(), "距大选天数": (hit[0] - ed).days})
    return {"周期顶": tops, "周期底": bottoms, "破前高": breaks}


def halving_dips(s: Series):
    out = []
    for h in K.HALVINGS:
        w = s.between(h - dt.timedelta(days=K.HALVING_DIP_DAYS), h + dt.timedelta(days=K.HALVING_DIP_DAYS))
        peak = (None, 0)
        best = (0, None, None)
        for d, v in w:
            if v > peak[1]:
                peak = (d, v)
            dd = v / peak[1] - 1
            if dd < best[0]:
                best = (dd, peak[0], d)
        out.append({"减半日": h.isoformat(), "最大回撤": round(best[0], 4), "高点日": best[1].isoformat(),
                    "低点日": best[2].isoformat(), "低点距减半天数": (best[2] - h).days})
    return out


def drawdown_base(s: Series, half_days: int, depth: float):
    """对照：任意一段同样长（2×half_days+1 天）的时间里，最大回撤达到 depth 的比例。"""
    hit = tot = 0
    for i in range(len(s.d)):
        end = s.d[i] + dt.timedelta(days=2 * half_days)
        if end > s.last:
            break
        peak, worst = 0, 0
        j = i
        while j < len(s.d) and s.d[j] <= end:
            peak = max(peak, s.v[j])
            worst = min(worst, s.v[j] / peak - 1)
            j += 1
        tot += 1
        hit += worst <= -depth
    return hit, tot


def next_halving(blk: Series):
    """用每日出块数累计出当前高度，再按出块速度推算下次减半日。"""
    cum, c = {}, 0
    for d, v in zip(blk.d, blk.v):
        c += v
        cum[d] = c
    known = K.HALVINGS[-1] - K.DAY            # 第 840000 块出在 2024-04-20 世界时 0 点后几分钟
    offset = 840_000 - cum[known]
    height = cum[blk.last] + offset
    paces = {
        "近365天": sum(v for d, v in blk.between(blk.last - dt.timedelta(days=364), blk.last)) / 365,
        "近90天": sum(v for d, v in blk.between(blk.last - dt.timedelta(days=89), blk.last)) / 90,
        "10分钟一块": K.TEN_MIN_BLOCKS_PER_DAY,
    }
    remain = K.NEXT_HALVING_HEIGHT - height
    est = {k: blk.last + dt.timedelta(days=remain / p) for k, p in paces.items()}
    # 自检：用同样方法回推 2020 年减半（第 630000 块），误差应在 1 天内
    check_day = K.HALVINGS[-2] - K.DAY
    check_err = cum[check_day] + offset - 630_000
    return {"当前高度": int(height), "剩余块数": int(remain), "出块速度": {k: round(p, 1) for k, p in paces.items()},
            "估计日": est["近365天"].isoformat(), "最早": min(est.values()).isoformat(),
            "最晚": max(est.values()).isoformat(), "回推2020减半误差块数": int(check_err)}


def big_month_linkage(nq: Series, other: Series, start: dt.date):
    def month_ends(s):
        out = {}
        for d, v in zip(s.d, s.v):
            out[(d.year, d.month)] = v
        return out
    a, b = month_ends(nq), month_ends(other)
    keys = sorted(k for k in a if k in b and K.D(k[0], k[1], 1) >= start)
    keys = keys[:-1]  # 去掉还没走完的当月
    down = follow = base_down = months = 0
    for p, k in zip(keys, keys[1:]):
        rn, ro = a[k] / a[p] - 1, b[k] / b[p] - 1
        months += 1
        base_down += ro < 0
        if rn <= -K.BIG_MONTH_MOVE:
            down += 1
            follow += ro < 0
    return down, follow, base_down, months


# ── 组装看板显示内容 ────────────────────────────────────────────
def build():
    nq = Series(parse("nasdaq"))
    sp = Series(parse("sp500_monthly"), monthly=True)
    btc = Series(parse("btc"))
    eth = Series(parse("eth"))
    blk = Series(parse("btc", "BlkCnt"))
    today = btc.last
    start = K.cycle_start(today.year)
    years = [start + i for i in range(4)]

    assets = {"标普": sp, "纳指": nq, "比特币": btc, "以太坊": eth}
    stats = {k: cycle_stats(s, today) for k, s in assets.items()}
    clock = {"比特币": crypto_clock(btc, today), "以太坊": crypto_clock(eth, today)}

    def top_share(name, c):
        tops = clock[name]["周期顶"]
        return sum(1 for t in tops if t["所在年"] == K.CYCLE_NAMES[c]), len(tops)

    def extremes(name):
        """四种年份里中位数和上涨比例都最高 / 都最低的那一年（口径见 defs.py），只写进悬停依据。不同时成立返回 None。"""
        x = stats[name]
        rate = {c: x[c]["up"] / x[c]["n"] for c in range(4)}
        med = {c: x[c]["median"] for c in range(4)}
        best = next((c for c in range(4) if med[c] == max(med.values()) and rate[c] == max(rate.values())), None)
        worst = next((c for c in range(4) if med[c] == min(med.values()) and rate[c] == min(rate.values())), None)
        return best, worst

    def by_cycle(s, fn):
        """每个周期年份里，fn(年) 为真的次数 / 有数据的次数。"""
        out = {}
        for c in range(4):
            vals = [v for v in (fn(y) for y in complete_years(s, today) if K.cycle_year(y) == c) if v is not None]
            out[c] = (sum(1 for v in vals if v), len(vals))
        return out

    def edge(counts, c, floor):
        """过「比平时强」这一关：本身比例 ≥ floor，且比别的周期年份里最高的还高 EDGE。返回 (过没过, 别的年份最高比例)。"""
        k, n = counts[c]
        others = max(counts[o][0] / counts[o][1] for o in range(4) if o != c and counts[o][1])
        return bool(n) and k / n >= floor and k / n - others >= K.EDGE - 1e-9, others

    def count_line(up, n, lab, when, odd=()):
        """格子悬停的依据：按格子上的字说「几轮里几轮」，少数的例外年份也列出来（4 个以内）。"""
        if "涨" in lab:
            s = f"{n} 轮里 {up} 轮{when}收涨"
        elif "跌" in lab:
            s = f"{n} 轮里 {n - up} 轮{when}收跌"
        else:
            return f"{n} 轮里 {up} 轮{when}收涨、{n - up} 轮收跌"
        return s + (f"；例外是 {'、'.join(odd)} 年" if 0 < len(odd) <= 4 else "")

    rows = []
    for name, s in assets.items():
        cells = []
        best, worst = extremes(name)
        for y in years:
            c = K.cycle_year(y)
            x = stats[name][c]
            n, up = x["n"], x["up"]
            lab = K.direction_label(up, n)
            odd = [y for y, r in x["years"].items() if (r <= 0) == ("涨" in lab)]
            why = f"{name} {K.CYCLE_NAMES[c]}：" + count_line(up, n, lab, "全年", odd)
            if c == best:
                why += "；涨的次数和涨幅都是四种年份里最多"
            elif c == worst:
                why += "；涨的次数和涨幅都是四种年份里最少"
            if name in ("比特币", "以太坊"):
                k, m = top_share(name, c)
                if m and k / m >= K.LEAN and c == 1:
                    cells.append({"字": "见顶", "数": f"{k}/{m}", "色": "顶",
                                  "依据": f"{name} {m} 轮里 {k} 轮的最高价出在大选后一年；" + count_line(up, n, "涨", "全年", odd)})
                    continue
            color = "涨" if "涨" in lab else "跌" if "跌" in lab else "平"
            num = f"涨 {up}/{n}" if lab == "不稳" else f"{up if '涨' in lab else n - up}/{n}"
            cells.append({"字": lab, "数": num, "色": color, "依据": why})
        y0 = complete_years(s, today)[0]          # 第一个有完整全年涨跌的年份
        how = f"席勒标普 {y0} 年起，按月均价算" if s.monthly else f"{y0} 年起，按年末收盘算"
        rows.append({"名称": name, "依据": how, "格子": cells})

    # 结论层：每句话都带检验条件，条件不满足就显示「待复核」
    sp_best, sp_worst = extremes("标普")
    nq_best, nq_worst = extremes("纳指")
    b = stats["比特币"]
    q1 = {k: by_cycle(s, lambda y, s=s: (lambda r: None if r is None else r > 0)(quarter_return(s, y, 1)))
          for k, s in (("标普", sp), ("纳指", nq))}
    q1_edge = {k: edge(v, 3, K.STRONG) for k, v in q1.items()}
    W = K.YEAR_WORDS
    checks = {
        2: b[2]["n"] and (b[2]["n"] - b[2]["up"]) / b[2]["n"] >= K.STRONG and sp_worst == 2 and nq_worst == 2,
        3: q1_edge["标普"][0] and q1_edge["纳指"][0],
        0: stats["标普"][0]["up"] / stats["标普"][0]["n"] >= K.LEAN and b[0]["up"] / b[0]["n"] >= K.STRONG,
        1: top_share("比特币", 1)[0] / max(1, top_share("比特币", 1)[1]) >= K.STRONG,
    }
    sq, nqq = q1["标普"][3], q1["纳指"][3]
    other = max(q1_edge["标普"][1], q1_edge["纳指"][1])
    s2, n2 = stats["标普"][2], stats["纳指"][2]
    bt = top_share("比特币", 1)
    whys = {
        2: f"标普、纳指在中期选举年涨的次数和涨幅都是四种年份里最少（标普 {s2['up']}/{s2['n']}、纳指 {n2['up']}/{n2['n']} 收涨）；"
           f"比特币 {b[2]['n'] - b[2]['up']}/{b[2]['n']} 收跌",
        3: f"最硬的一条：大选前一年一季度，标普 {sq[0]}/{sq[1]}、纳指 {nqq[0]}/{nqq[1]} 收涨；"
           f"平时（别的年份一季度）最多 {other * 100:.0f}%。有用",
        0: f"标普 {stats['标普'][0]['up']}/{stats['标普'][0]['n']}、比特币 {b[0]['up']}/{b[0]['n']} 全年收涨",
        1: f"比特币 {bt[1]} 轮里 {bt[0]} 轮的最高价出在大选后一年，见顶后要跑",
    }
    cols = []
    for y in years:
        c = K.cycle_year(y)
        ok = checks[c]
        cols.append({"年": y, "周期": K.CYCLE_NAMES[c], "结论": W[c] if ok else "待复核", "成立": bool(ok),
                     "色": {2: "跌", 3: "涨", 0: "涨", 1: "顶"}[c] if ok else "平", "今年": y == today.year,
                     "依据": whys[c] if ok else "检验条件这次没过，等复核"})

    # 比特币时间线
    ck = clock["比特币"]
    span0, span1 = K.D(start, 1, 1), K.D(start + 3, 12, 31)

    def pos(d):
        return round(max(0, min(1, (d - span0).days / (span1 - span0).days)), 4)

    done_b = [x for x in ck["周期底"] if x["已确认"]]
    bd = [x["距中期选举天数"] for x in done_b]
    m_day = K.election_day(start)
    b_lo, b_hi = m_day + dt.timedelta(days=min(bd)), m_day + dt.timedelta(days=max(bd))
    dips = halving_dips(btc)
    shallow = min(-x["最大回撤"] for x in dips)
    dip_hit, dip_tot = drawdown_base(btc, K.HALVING_DIP_DAYS, shallow)
    nh = next_halving(blk)
    h_est = K.D.fromisoformat(nh["估计日"])
    pres = K.election_day(start + 2)
    brk = [x["距大选天数"] for x in ck["破前高"]]
    brk_after = sorted(x for x in brk if x > 0)
    k_lo, k_hi = pres + dt.timedelta(days=brk_after[0]), pres + dt.timedelta(days=brk_after[-1])
    tp = [x["距大选天数"] for x in ck["周期顶"]]
    t_lo, t_hi = pres + dt.timedelta(days=min(tp)), pres + dt.timedelta(days=max(tp))
    cur_bottom = [x for x in ck["周期底"] if not x["已确认"]]
    brk_before = len(brk) - len(brk_after)
    timeline = [
        {"名": f"大底 {len(bd)}/{len(bd)}", "色": "跌", "上": True, "起": pos(b_lo), "止": pos(b_hi),
         "字": K.fmt_ym_range(b_lo, b_hi), "依据": f"比特币每轮最低价出在中期选举后 {min(bd)}–{max(bd)} 天，{len(bd)} 轮都是"},
        {"名": "减半", "色": "平", "上": False, "起": pos(h_est), "止": pos(h_est),
         "字": f"约{K.fmt_ym(h_est)}", "依据": "下次减半，按出块速度推算；减半前后并不比平时更容易跌，不附带涨跌判断"},
        {"名": f"破前高 {len(brk_after)}/{len(brk)}", "色": "涨", "上": True, "起": pos(k_lo), "止": pos(k_hi),
         "字": K.fmt_ym_range(k_lo, k_hi),
         "依据": f"第一次收盘高过以前的最高价：{len(brk)} 轮里 {len(brk_after)} 轮在大选后 {brk_after[0]}–{brk_after[-1]} 天"
                 + (f"，{brk_before} 轮提前到大选前" if brk_before else "")},
        {"名": f"见顶 {len(tp)}/{len(tp)}", "色": "顶", "上": False, "起": pos(t_lo), "止": pos(t_hi),
         "字": K.fmt_ym_range(t_lo, t_hi), "依据": f"比特币每轮最高价出在大选后 {min(tp)}–{max(tp)} 天，{len(tp)} 轮都是"},
    ]

    # 失效条件：大底规律这一轮成不成立，到哪天能见分晓
    cur = next((x for x in ck["周期底"] if x["中期选举年"] == start), None)
    fail = None
    if cur:
        cd_, price = K.D.fromisoformat(cur["底日"]), f"{cur['底价'] / 1e4:.1f}万"
        inside = b_lo <= cd_ <= b_hi
        rule = f"大底规律说：这一轮最低价出在 {K.fmt_ym_range(b_lo, b_hi)}"
        if cur["已确认"]:
            fail = {"字": f"大底已确认在 {K.fmt_ymd(cd_)}，{'落在' if inside else '不在'}规律时间里", "依据": rule}
        elif inside:
            fail = {"字": f"比特币 {K.fmt_ymd(cd_)} 创本轮新低 {price}，落在大底时间里", "依据": rule + "；再创新高才算大底确认"}
        elif today <= b_hi:
            fail = {"字": f"{K.fmt_ymd(b_hi)}前比特币没跌破 {price}，大底规律这一轮不灵",
                    "依据": f"{K.fmt_ymd(cd_)}的低点是 {price}；" + rule + "，到时没跌破就算不灵"}
        else:
            fail = {"字": f"大底规律这一轮不灵，最低在 {K.fmt_ymd(cd_)}", "依据": rule}
    trust = "可信度：美股＞比特币＞以太坊；只信方向，不信价位"

    # 对现在：按今年、明年两列的结论和比特币时间线，自动写一句大白话（2026-11-18：不被解释也能看懂）
    cy_, ny_ = K.cycle_year(today.year), K.cycle_year(today.year + 1)
    parts = []
    if checks[cy_]:
        parts.append(f"今年{K.YEAR_PLAIN[cy_]}" + ("，快过完了" if today.month >= 10 else ""))
    if checks[ny_]:
        parts.append(f"明年{K.YEAR_PLAIN[ny_]}")
    marks = [("大底", b_lo, b_hi), ("减半", h_est, h_est), ("破前高", k_lo, k_hi), ("见顶", t_lo, t_hi)]
    inside = next((m for m in marks if m[1] <= today <= m[2]), None)
    ahead = next((m for m in marks if today < m[1]), None)
    if inside:
        act = {"大底": "在找大底", "减半": "在减半前后", "破前高": "该破前高了", "见顶": "在见顶"}[inside[0]]
        parts.append(f"比特币按规律{act}（到 {K.fmt_ym(inside[2])}）")
    elif ahead:
        parts.append(f"比特币下一个时间点是{ahead[0]}，约 {K.fmt_ym_range(ahead[1], ahead[2])}")
    so_main = {"字": ("对现在：" + "；".join(parts)) if parts else "对现在：规律都待复核，先别按图操作",
               "依据": "由今年、明年两列的结论和比特币时间线自动写出；每一格的依据，鼠标停在格子上看"}

    # 第二张图：明年（或今年）按季度
    target = today.year + 1 if today.month >= 10 else today.year
    tc = K.cycle_year(target)
    qrows = []
    for name, s in (("标普", sp), ("纳指", nq), ("比特币", btc)):
        ys = [y for y in complete_years(s, today) if K.cycle_year(y) == tc]
        cells = []
        for q in range(1, 5):
            rs = [r for r in (quarter_return(s, y, q) for y in ys) if r is not None]
            up, n = sum(r > 0 for r in rs), len(rs)
            lab = K.direction_label(up, n)
            color = "涨" if "涨" in lab else "跌" if "跌" in lab else "平"
            num = f"涨 {up}/{n}" if lab == "不稳" else f"{up if '涨' in lab else n - up}/{n}"
            cells.append({"字": lab, "数": num, "色": color,
                          "依据": f"{name} {K.CYCLE_NAMES[tc]}第 {q} 季度：" + count_line(up, n, lab, "")})
        jf = by_cycle(s, lambda y, s=s: (lambda d: None if d is None else d.month <= 2)(year_low_date(s, y)))
        ok, other_max = edge(jf, tc, K.LEAN)
        qrows.append({"名称": name, "依据": f"{name} {len(ys)} 轮", "格子": cells,
                      "低点": {"1–2月": f"{jf[tc][0]}/{jf[tc][1]}", "别的年份最高": round(other_max, 4), "上板": ok}})
    post_down = [y for y, r in stats["比特币"][1]["years"].items() if r < 0]
    n_post = stats["比特币"][1]["n"]
    link_n, link_f, base_d, base_m = big_month_linkage(nq, btc, K.D(btc.first.year, btc.first.month, 1))
    risks = []
    if post_down:
        risks.append({"字": f"比特币大选后一年收跌 {len(post_down)}/{n_post}（{'、'.join(post_down)}），规律可能变弱",
                      "依据": f"以前 {n_post - len(post_down)} 轮大选后一年都收涨；见顶跑这条可能在变弱"})
    risks.append({"字": f"纳指单月大跌时，比特币跟跌 {link_f}/{link_n}",
                  "依据": f"大跌＝纳指一个月跌 {K.BIG_MONTH_MOVE * 100:.0f}% 以上；平时比特币 {base_d / base_m * 100:.0f}% 的月份跌"})
    lows_ok = [f"{r['名称']} {r['低点']['1–2月']}" for r in qrows if r["低点"]["上板"]]
    lows_no = [f"{r['名称']} {r['低点']['1–2月']}" for r in qrows if not r["低点"]["上板"]]
    low_why = "平时（别的年份）最多：" + "、".join(f"{r['名称']} {r['低点']['别的年份最高'] * 100:.0f}%" for r in qrows if r["低点"]["上板"])
    if lows_no:
        low_why += "；" + "、".join(lows_no) + " 跟平时一样，没算进来"
    low = ({"字": "全年低点在 1–2 月：" + "、".join(lows_ok), "判断": "有用", "依据": low_why} if lows_ok else
           {"字": "全年低点在哪几个月：跟平时一样", "判断": "跟平时一样", "依据": "没有哪个品种比别的年份明显更常在 1–2 月见低点"})
    when = "明年" if target > today.year else "今年"
    qn = ["一", "二", "三", "四"]
    ups = [[r["名称"] for r in qrows if r["格子"][q]["字"] == "涨"] for q in range(4)]
    best = max(range(4), key=lambda q: len(ups[q]))
    parts = []
    if ups[best]:
        parts.append(f"{when}{qn[best]}季度最稳（{'、'.join(ups[best])}{'都' if len(ups[best]) > 1 else ''}是涨）")
    parts += [f"{r['名称']}{qn[q]}季度容易跌" for r in qrows for q in range(4) if "跌" in r["格子"][q]["字"]]
    if lows_ok:
        parts.append(f"{'、'.join(r['名称'] for r in qrows if r['低点']['上板'])}低点多在 1–2 月")
    so_next = {"字": "对现在：" + "；".join(parts) if parts else "对现在：各季度都说不准，没有明显规律",
               "依据": "由下面各季度的格子和低点规律自动写出：「最稳」＝写着「涨」的品种最多的季度"}
    board2 = {"标题": f"{target} 年怎么走", "对现在": so_next, "周期": K.CYCLE_NAMES[tc], "行": qrows, "低点": low, "风险": risks,
              "怎么读": K.legend(["几/几", "涨", "偏涨", "不稳", "偏跌", "跌", "平时", "有用", "要防"]),
              "历史更新": K.HIST_YEARLY}

    tl_why = "比特币四年周期里的几个时间点：色块是历史上落在的时间段，几/几＝落在这段里的轮数 / 总轮数"
    display = {"总表": {"标题": "美国四年周期", "对现在": so_main, "列": cols, "行": rows, "时间线": timeline, "时间线说明": tl_why, "失效条件": fail,
                        "怎么读": K.legend(["几/几", "涨", "偏涨", "不稳", "偏跌", "跌", "见顶", "最弱", "平时", "有用",
                                            "失效条件"]) + [trust], "历史更新": K.HIST_YEARLY},
               "明年": board2, "数据截至": today.isoformat(),
               "最新数据": f"{today.month}月{today.day}日 · {updates('btc')}；标普每月"}
    detail = {"周期年统计": stats, "加密时钟": clock, "下次减半": nh,
              "减半坑（不上板）": {"各次": dips, "对照": f"任意 {2 * K.HALVING_DIP_DAYS + 1} 天里跌 {shallow:.1%} 以上的比例 "
                                                   f"{dip_hit}/{dip_tot} = {dip_hit / dip_tot:.0%}"},
              "一季度上涨（各周期年份）": {k: {K.CYCLE_NAMES[c]: f"{u}/{n}" for c, (u, n) in v.items()} for k, v in q1.items()},
              "本轮周期底（未确认）": cur_bottom, "失效条件": fail,
              "纳指大跌月联动": {"大跌月": link_n, "比特币跟跌": link_f, "比特币平时下跌月": base_d, "总月数": base_m}}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"显示": display, "明细": detail}, ensure_ascii=False, indent=1, default=str))
    return display, detail


if __name__ == "__main__":
    disp, det = build()
    print(json.dumps(disp, ensure_ascii=False, indent=1)[:3000])
