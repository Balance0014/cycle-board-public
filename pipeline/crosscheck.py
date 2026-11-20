"""第二来源核对：同一个价格用另一家独立来源再拿一遍，对不上就不许出图。

- 标普：席勒月均价 对 美联储数据库的标普日收盘算出来的月均价（重叠的完整月份）
- 比特币、以太坊：币量参考价 对 Coinbase 交易所日线收盘（看板用到的每个年末；比特币还有每一轮顶和底那天）
- 纳指：只有纳斯达克官方一家（经美联储数据库转发），登记为单一来源
- 十年期国债利率：美联储数据库 对 美国财政部官网，最近 60 个共同交易日
- 政策利率：目标区间（上下限）对 每天实际成交的联邦基金利率，实际利率应落在区间里
- 衰退月份、萨姆规则：美国经济研究局 / 美联储数据库各一家，登记为单一来源
- 长短利率差：美联储数据库每天的十年期减三个月 对 财政部官网的十年期减三个月，最近 60 个共同交易日
- 全国活动指数：芝加哥联储一家编制，登记为单一来源
- 金价：世界银行粉单月均 对 国际货币基金组织月均（1992 年起所有共同月份）
- 原油：美联储数据库 WTI 月均 对 世界银行粉单 WTI 月均（2000 年起所有共同月份，中位差 1% 以内、单月 6% 以内）
- 信用利差：Baa 月均减十年期国债月均（美联储数据库两条序列相减），对 美联储数据库每天的 BAA10Y 取月均（1986 年起所有完整月份，中位差 0.01 以内、单月 0.03 以内）
- 金融状况指数：芝加哥联储编制、美联储数据库转载，只有一家权威来源
- 实际利率、物价：美联储数据库一家（实际利率＝财政部通胀保值国债收益率），登记为单一来源
"""
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import coinbase_close, parse, treasury_rates  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "crosscheck.json"
SP_TOL = 0.005      # 月均价相差 0.5% 以内算对上
CRYPTO_TOL = 0.02   # 年末价相差 2% 以内算对上（参考价和单一交易所收盘本来就有小差）


def check_sp():
    shiller = {(d.year, d.month): v for d, v in parse("sp500_monthly")}
    daily = defaultdict(list)
    for d, v in parse("sp500_daily"):
        daily[(d.year, d.month)].append(v)
    today = dt.date.today()
    months = sorted(k for k in daily if k in shiller and k != (today.year, today.month) and len(daily[k]) >= 15)
    months = months[1:]  # 第一个月可能不完整
    diffs = {f"{y}-{m:02d}": round(shiller[(y, m)] / (sum(daily[(y, m)]) / len(daily[(y, m)])) - 1, 5)
             for y, m in months}
    worst = max(diffs.values(), key=abs) if diffs else None
    return {"项目": "标普月均价", "对比月数": len(diffs), "最大差": worst,
            "通过": bool(diffs) and abs(worst) <= SP_TOL, "明细": diffs}


def check_crypto(asset, product, first_year):
    cm = dict(parse(asset))
    today = dt.date.today()
    rows, ok = {}, True
    prev = None
    for y in range(first_year, today.year):
        d = dt.date(y, 12, 31)
        a, b = cm.get(d), coinbase_close(product, d)
        if a is None or b is None:
            rows[str(y)] = "缺数据"
            ok = False
            continue
        diff = a / b - 1
        sign_ok = True
        if prev:
            sign_ok = (a / prev[0] > 1) == (b / prev[1] > 1)
        rows[str(y)] = {"币量": round(a, 2), "Coinbase": round(b, 2), "差": round(diff, 4), "年涨跌方向一致": sign_ok}
        ok = ok and abs(diff) <= CRYPTO_TOL and sign_ok
        prev = (a, b)
    return {"项目": f"{asset} 年末价", "通过": ok, "明细": rows}


_TRE = {}


def _treasury():
    """财政部近两年每日利率，一次运行只下载一次。"""
    if not _TRE:
        today = dt.date.today()
        for y in (today.year - 1, today.year):
            for c, rows in treasury_rates(y).items():
                _TRE.setdefault(c, {}).update(rows)
    return _TRE


def check_btc_turns():
    """比特币每一轮顶和底那天的收盘价：币量参考价 对 Coinbase 当天收盘（2015 年 2 月后的才能对）。"""
    import json as _j
    p = ROOT / "results" / "board1.json"
    if not p.exists():
        return {"项目": "比特币顶底价", "通过": False, "明细": "图一还没算"}
    clock = _j.loads(p.read_text())["明细"]["加密时钟"]["比特币"]
    pts = [(x["顶日"], x["顶价"]) for x in clock["周期顶"]] + [(x["底日"], x["底价"]) for x in clock["周期底"]]
    rows, ok = {}, True
    for d, v in pts:
        day = dt.date.fromisoformat(d)
        if day < dt.date(2015, 2, 1):   # Coinbase 交易所 2015 年 1 月 26 日才开张
            continue
        b = coinbase_close("BTC-USD", day)
        if b is None:
            rows[d] = "缺数据"
            ok = False
            continue
        rows[d] = {"币量": round(v, 2), "Coinbase": round(b, 2), "差": round(v / b - 1, 4)}
        ok = ok and abs(v / b - 1) <= CRYPTO_TOL
    return {"项目": "比特币顶底价", "通过": ok and len(rows) >= 4, "明细": rows}


def check_gold():
    """金价：世界银行月均 对 国际货币基金组织月均，1992 年起所有共同月份，相差 1% 以内算对上。"""
    wb, imf = dict(parse("gold")), dict(parse("gold_imf"))
    days = sorted(d for d in wb if d in imf)
    diffs = {d.isoformat()[:7]: round(wb[d] / imf[d] - 1, 4) for d in days}
    worst = max(diffs.values(), key=abs) if diffs else None
    return {"项目": "金价月均", "对比月数": len(days), "最大差": worst,
            "通过": len(days) >= 300 and abs(worst) <= 0.01, "明细": dict(list(diffs.items())[-24:])}


def check_oil():
    """原油：美联储数据库 WTI 月均 对 世界银行粉单「Crude oil, WTI」，2000 年起所有共同月份。
    两家取价的报价源略有不同，单月最多差几个百分点（26 年 10 月差 4.3%）：中位数 1% 以内、单月 6% 以内算对上。"""
    import fetch
    fred = dict(parse("oil"))
    wb = dict(fetch._parse_wb((fetch.RAW / fetch.SERIES["gold"]["file"]).read_bytes(), "Crude oil, WTI"))
    days = sorted(d for d in fred if d in wb and d.year >= 2000)
    diffs = {d.isoformat()[:7]: round(wb[d] / fred[d] - 1, 4) for d in days}
    worst = max(diffs.values(), key=abs) if diffs else None
    mid = sorted(abs(x) for x in diffs.values())[len(diffs) // 2] if diffs else None
    return {"项目": "油价月均", "对比月数": len(days), "最大差": worst, "中位差": mid,
            "通过": len(days) >= 300 and abs(worst) <= 0.06 and mid <= 0.01, "明细": dict(list(diffs.items())[-24:])}


def check_spread():
    """信用利差：（Baa 月均 − GS10 月均）对 BAA10Y 每天值的月均，1986 年起所有完整月份。
    两边是同一家数据库里不同序列（月均相减 vs 每天相减再平均），只差取平均的先后和四舍五入。"""
    baa, gs = dict(parse("baa")), dict(parse("gs10"))
    daily = defaultdict(list)
    for d, v in parse("baa10y"):
        daily[(d.year, d.month)].append(v)
    today = dt.date.today()
    diffs = {}
    for (y, m), xs in sorted(daily.items()):
        d = dt.date(y, m, 1)
        if (y, m) == (today.year, today.month) or d not in baa or d not in gs or len(xs) < 15:
            continue
        diffs[f"{y}-{m:02d}"] = round(baa[d] - gs[d] - sum(xs) / len(xs), 4)
    worst = max(diffs.values(), key=abs) if diffs else None
    mid = sorted(abs(x) for x in diffs.values())[len(diffs) // 2] if diffs else None
    return {"项目": "信用利差月均", "对比月数": len(diffs), "最大差": worst, "中位差": mid,
            "通过": len(diffs) >= 300 and abs(worst) <= 0.03 and mid <= 0.01, "明细": dict(list(diffs.items())[-24:])}


def check_10y():
    fred = dict(parse("dgs10"))
    tre = _treasury()["10 Yr"]
    days = sorted(d for d in fred if d in tre)[-60:]
    diffs = {d.isoformat(): round(fred[d] - tre[d], 3) for d in days}
    worst = max(diffs.values(), key=abs) if diffs else None
    return {"项目": "十年期国债利率", "对比天数": len(days), "最大差": worst,
            "通过": len(days) >= 20 and abs(worst) <= 0.02, "明细": diffs}


def check_10y3m():
    """长短利率差：美联储数据库每天的「十年期减三个月」对 财政部十年期减三个月（最近 60 个共同交易日）。
    两家三个月利率口径略有不同（美联储数据库用二级市场贴现率换算），容差放宽到 0.05 个百分点。"""
    fred = dict(parse("t10y3m"))
    t = _treasury()
    tre = {d: t["10 Yr"][d] - t["3 Mo"][d] for d in t["10 Yr"] if d in t["3 Mo"]}
    days = sorted(d for d in fred if d in tre)[-60:]
    diffs = {d.isoformat(): round(fred[d] - tre[d], 3) for d in days}
    worst = max(diffs.values(), key=abs) if diffs else None
    return {"项目": "长短利率差", "对比天数": len(days), "最大差": worst,
            "通过": len(days) >= 20 and abs(worst) <= 0.05, "明细": diffs}


def check_policy():
    lo, hi = dict(parse("target_lo")), dict(parse("target_hi"))
    days = [(d, v) for d, v in parse("dff") if d in lo and d in hi]
    out = [d.isoformat() for d, v in days if not lo[d] - 0.01 <= v <= hi[d] + 0.01]
    recent_out = [d for d in out if d >= days[-30][0].isoformat()]
    share = 1 - len(out) / len(days)
    return {"项目": "政策利率", "对比天数": len(days), "落在区间里的比例": round(share, 4),
            "通过": share >= 0.99 and not recent_out, "明细": out[-20:]}


def run():
    res = [check_sp(), check_crypto("btc", "BTC-USD", 2015), check_crypto("eth", "ETH-USD", 2016),
           check_btc_turns(), check_gold(), check_oil(), check_spread(), check_10y(), check_10y3m(), check_policy(),
           {"项目": "纳指", "通过": True, "说明": "单一官方来源（纳斯达克经美联储数据库发布），无第二来源"},
           {"项目": "衰退月份、萨姆规则", "通过": True, "说明": "美国经济研究局认定 / 美联储数据库发布，各只有一家权威来源"},
           {"项目": "全国活动指数", "通过": True, "说明": "芝加哥联储编制、美联储数据库转载，只有一家权威来源"},
           {"项目": "金融状况指数", "通过": True, "说明": "芝加哥联储编制、美联储数据库转载，只有一家权威来源"},
           {"项目": "实际利率、物价", "通过": True, "说明": "美联储数据库转载财政部、劳工统计局，各只有一家权威来源"}]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    for r in run():
        print(r["项目"], "通过" if r["通过"] else "不通过", r.get("最大差", ""), r.get("对比月数", ""))
        if not r["通过"]:
            print(json.dumps(r.get("明细"), ensure_ascii=False)[:800])
