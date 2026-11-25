"""数据层：每条数据只认一个一手来源，下载到 data/raw，并在 data/sources.json 登记来源、时间、校验值。

另外检查「历史数据有没有被来源悄悄改过」：上次登记时截止日之前的数据，这次重新算校验值，对不上就报警。
"""
import csv
import datetime as dt
import hashlib
import io
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SOURCES = ROOT / "data" / "sources.json"
UA = {"User-Agent": "cycle-board/1.0 (research; https://x.com/balance0014)"}
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # 云端用系统证书
    SSL_CTX = ssl.create_default_context()

SERIES = {
    "nasdaq": {"名称": "纳斯达克综合指数（日收盘）", "来源": "美联储圣路易斯分行数据库，原始提供方为纳斯达克",
               "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM", "file": "fred_NASDAQCOM.csv", "频率": "每天", "公布": "每个交易日", "简名": "纳斯达克指数"},
    "sp500_daily": {"名称": "标普 500（日收盘，近 10 年，只用来核对）", "来源": "美联储圣路易斯分行数据库，原始提供方为标普道琼斯指数公司",
                    "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", "file": "fred_SP500.csv", "频率": "每天", "公布": "每个交易日",
                    "滚动窗口": True},   # 只给最近 10 年，最早的几天会自己掉出去，不算改了旧历史
    "sp500_monthly": {"名称": "标普综合指数（月均价，1871 年起）", "来源": "耶鲁大学席勒教授数据集",
                      "url": "https://shillerdata.com/", "file": "shiller_ie_data.xls", "频率": "每月", "公布": "每月更新当月月均", "简名": "标普指数（月均价）"},
    "btc": {"名称": "比特币（每日参考价、每日出块数）", "来源": "币量（Coin Metrics）社区版",
            "url": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=PriceUSD,BlkCnt&frequency=1d&page_size=10000&start_time=2009-01-03",
            "file": "cm_btc.json", "频率": "每天", "公布": "每天，含前一天", "简名": "比特币价格"},
    "eth": {"名称": "以太坊（每日参考价）", "来源": "币量（Coin Metrics）社区版",
            "url": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=eth&metrics=PriceUSD&frequency=1d&page_size=10000&start_time=2015-07-30",
            "file": "cm_eth.json", "频率": "每天", "公布": "每天，含前一天", "简名": "以太坊价格"},
    # ── 利率周期用 ──
    "fedfunds": {"名称": "联邦基金实际利率（月均，1954 年起）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS", "file": "fred_FEDFUNDS.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "联邦基金利率（月均）"},
    "target": {"名称": "联邦基金目标利率（1982–2008）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTAR", "file": "fred_DFEDTAR.csv", "频率": "不定期", "公布": "2008 年底已停更", "简名": "联邦基金目标利率（至 2008）"},
    "target_hi": {"名称": "联邦基金目标区间上限（2008 年起）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU", "file": "fred_DFEDTARU.csv", "频率": "每天", "公布": "每个交易日", "简名": "联邦基金目标利率"},
    "target_lo": {"名称": "联邦基金目标区间下限（2008 年起，只用来核对）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL", "file": "fred_DFEDTARL.csv", "频率": "每天", "公布": "每个交易日"},
    "dff": {"名称": "联邦基金实际利率（每日，只用来核对）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF", "file": "fred_DFF.csv", "频率": "每天", "公布": "每个交易日"},
    "usrec": {"名称": "美国经济衰退月份（美国经济研究局认定）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=USREC", "file": "fred_USREC.csv", "频率": "不定期", "公布": "事后认定，不定期", "简名": "衰退月份", "按月": True},
    "gs10": {"名称": "十年期国债利率（月均）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GS10", "file": "fred_GS10.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "十年期国债利率（月均）"},
    "dgs10": {"名称": "十年期国债利率（每日）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", "file": "fred_DGS10.csv", "频率": "每天", "公布": "每个交易日", "简名": "十年期国债利率"},
    "sahm": {"名称": "萨姆规则失业率预警（实时值）", "来源": "美联储圣路易斯分行数据库",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SAHMREALTIME", "file": "fred_SAHMREALTIME.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "失业率预警"},
    "cfnai": {"名称": "芝加哥联储全国活动指数（三个月平均，1967 年起）", "来源": "美联储圣路易斯分行数据库（转载芝加哥联储）",
              "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CFNAIMA3", "file": "fred_CFNAIMA3.csv", "频率": "每月", "公布": "每月下旬公布上个月", "简名": "全国活动指数",
              "会重估": True},   # 每月重算旧值
    "tb3ms": {"名称": "三个月国库券利率（月均，1934 年起）", "来源": "美联储圣路易斯分行数据库",
              "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS", "file": "fred_TB3MS.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "三个月国库券利率"},
    "t10y3m": {"名称": "十年期减三个月国债利率（每天）", "来源": "美联储圣路易斯分行数据库",
               "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y3M", "file": "fred_T10Y3M.csv", "频率": "每天", "公布": "每个交易日", "简名": "长短利率差"},
    # ── 黄金用 ──
    "gold": {"名称": "伦敦金价（月均，1960 年起）", "来源": "世界银行大宗商品价格「粉单」",
             "url": "https://www.worldbank.org/en/research/commodity-markets", "file": "wb_cmo_monthly.xlsx", "频率": "每月", "公布": "每月初公布上个月", "简名": "金价（月均）"},
    "gold_imf": {"名称": "伦敦金价（月均，1992 年起，只用来核对）", "来源": "国际货币基金组织初级商品价格",
                 "url": "https://api.imf.org/external/sdmx/2.1/data/IMF.RES,PCPS/G001.PGOLD.USD.M?startPeriod=1960",
                 "file": "imf_pgold.xml", "频率": "每月", "公布": "每月初公布上个月"},
    "dfii10": {"名称": "十年期通胀保值国债利率＝实际利率（每天，2003 年起）", "来源": "美联储圣路易斯分行数据库",
               "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10", "file": "fred_DFII10.csv", "频率": "每天", "公布": "每个交易日", "简名": "实际利率"},
    "cpi": {"名称": "美国消费者物价指数（月度，1947 年起）", "来源": "美联储圣路易斯分行数据库（转载美国劳工统计局）",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL", "file": "fred_CPIAUCSL.csv", "频率": "每月", "公布": "每月中公布上个月", "简名": "物价指数",
            "会重估": True},   # 季节调整后的数，劳工统计局每年 2 月重算前 5 年
    # ── 原油用 ──（第二来源＝上面世界银行粉单里的「Crude oil, WTI」列，不另下载）
    "oil": {"名称": "美国原油价格 WTI（月均，1946 年起）", "来源": "美联储圣路易斯分行数据库（转载道琼斯、美国能源信息署）",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WTISPLC", "file": "fred_WTISPLC.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "原油价格（月均）"},
    "oil_daily": {"名称": "美国原油价格 WTI（每天，1986 年起）", "来源": "美联储圣路易斯分行数据库（转载美国能源信息署）",
                  "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO", "file": "fred_DCOILWTICO.csv", "频率": "每周", "公布": "每周三公布上周", "简名": "原油价格（日价）"},
    # ── 金融状况用 ──（第二来源：信用利差用 FRED 的 BAA10Y 每天值取月均核对；金融状况指数只有芝加哥联储一家）
    "nfci": {"名称": "芝加哥联储全国金融状况指数（每周，1971 年起）", "来源": "美联储圣路易斯分行数据库（转载芝加哥联储）",
             "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NFCI", "file": "fred_NFCI.csv", "频率": "每周", "公布": "每周三公布上周", "简名": "金融状况指数",
             "会重估": True},   # 每周重算旧值
    "baa": {"名称": "穆迪 Baa 企业债收益率（月均，1919 年起）", "来源": "美联储圣路易斯分行数据库（转载穆迪）",
            "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA", "file": "fred_BAA.csv", "频率": "每月", "公布": "每月初公布上个月", "简名": "企业债收益率（月均）"},
    "baa10y": {"名称": "穆迪 Baa 企业债减十年国债利率（每天，1986 年起，只用来核对）", "来源": "美联储圣路易斯分行数据库",
               "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAA10Y", "file": "fred_BAA10Y.csv", "频率": "每天", "公布": "每个交易日"},
}


# ── 更新频率（2026-11-20「更新频次必须披露，不要制造信息差」）：整个看板只在这里认一处 ──
# 每条数据最多停多少个日历天还算正常：按它自己的公布节奏，算上周末、节假日和来源晚贴的几天。
# 超过了只在菜单里橙色提示「某数据停在某天」，别的照常更新（fetch.problems → 状态.json「数据问题」）。
# 11-24 前这是验收硬拦：一条数据晚了整个看板都不更新；菜单又按「所有题目里最旧的日期超过 4 天」报红，
# 实际利率周五的数下周一才贴出来，周末一过就误报红（11-23 查出）。新加数据必须在这里写一条，验收查。
MAX_AGE = {"btc": 4, "eth": 4, "nasdaq": 8, "sp500_daily": 8, "sp500_monthly": 62, "target_hi": 5, "target_lo": 5,
           "dff": 7, "dgs10": 7, "fedfunds": 70, "gs10": 70, "sahm": 70, "usrec": 70,
           "t10y3m": 7, "tb3ms": 70, "cfnai": 95,   # 活动指数晚三四个星期才公布，月初记日
           "gold": 70, "gold_imf": 80, "dfii10": 7, "cpi": 80,   # 物价指数月中才公布上个月
           "oil": 70, "oil_daily": 12,   # 原油日价每周公布一次
           "nfci": 14, "baa": 70, "baa10y": 7,   # 金融状况指数每周三公布上周五的值，加节假日最多晚两周；Baa 月均月初公布上个月
           "target": None}   # 2008 年就停了的旧目标利率，只当历史用，不查新鲜度
RHYTHM_WORDS = ("每天", "每周", "每月", "每年", "不定期")


def rhythm(key: str) -> str:
    """短标签，写在图上：每天 / 每周三 / 每月初 / 每月中 / 每月下旬 / 每月 / 不定期（取自 SERIES 里的「公布」）。"""
    s = SERIES[key]
    if s["频率"] == "每天":
        return "每天"
    if s["频率"] == "不定期":
        return "不定期"
    m = re.match(r"每周.|每月[初中]|每月下旬|每月", s["公布"])
    return m.group(0)


def label(key: str) -> str:
    """长标签，写在数据清单里：每天 / 每周三（上周） / 每月初（上个月）。"""
    s = SERIES[key]
    m = re.match(r"(每周.|每月[初中]|每月下旬)公布(.+)", s["公布"])
    return f"{m.group(1)}（{m.group(2)}）" if m else rhythm(key)


def updates(key: str) -> str:
    """信号卡上的一句：每月初更新。"""
    return rhythm(key) + "更新"


def is_check_only(key: str) -> bool:
    return "只用来核对" in SERIES[key]["名称"]


def data_list() -> list:
    """数据清单：看板上用到的每条数据（不含只用来核对的），写进状态.json，菜单里「数据清单」子菜单照着显示。
    「到」＝最新一条的日期；按月公布的写到月（YYYY-MM）。全部从 SERIES 和 data/sources.json 生成，不手填。"""
    reg = json.loads(SOURCES.read_text())
    out = []
    for key, s in SERIES.items():
        if is_check_only(key):
            continue
        last = reg.get(key, {}).get("末日") or "没有"
        out.append({"名": s["简名"], "公布": s["公布"],
                    "到": last[:7] if (s.get("频率") == "每月" or s.get("按月")) else last})
    return out


# 下载限时（11-25 查出：原来一次下载最多等 90 秒、试 4 次，一个网站卡住不回应，几条数据就能拖过云端时限，
# 整班被掐掉、所有题目都不更新）。现在：单次有时限，同一个网站连续失败就这次不再连它，所有下载加起来有总时限；
# 超了的数据算「这次没取到」，只有用到它的题目回到上一版。
TIMEOUT = 30          # 连接、每读一块最多等几秒
PER_TRY = 90          # 一次下载最多几秒（网站一点一点慢慢吐也算超时）
BUDGET = 8 * 60       # 一次运行里所有下载（含第二来源核对）加起来最多几秒
HOST_FAILS = 2        # 同一个网站连着几条连不上，这次就不再连它
_CLOCK = []           # 第一次下载的时刻
_DOWN = {}            # 网站 → 连着连不上几条


class DownloadError(RuntimeError):
    """下载失败。reason 是给菜单看的短句，str 里有地址和细节（看云端运行日志）。"""
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}：{detail}" if detail else reason)
        self.reason = reason


def _why(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"网站报错 {e.code}"
    if isinstance(e, TimeoutError) or "timed out" in str(e):
        return "网站超时"
    if isinstance(e, (urllib.error.URLError, ConnectionError)):
        return "网站连不上"
    return f"下载出错（{type(e).__name__}）"


def http_get(url: str, tries: int = 3, ua: bool = False) -> bytes:
    """默认用 Python 自带身份（美联储数据库会拒绝自定义程序名）；Coinbase 需要带程序名。"""
    host = urllib.parse.urlsplit(url).hostname or url
    if not _CLOCK:
        _CLOCK.append(time.monotonic())
    if _DOWN.get(host, 0) >= HOST_FAILS:
        raise DownloadError("网站连不上，这次跳过", host)
    err = None
    for i in range(tries):
        left = BUDGET - (time.monotonic() - _CLOCK[0])
        if left <= 1:
            raise DownloadError("下载总时间超了，这次跳过", url)
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(url, headers=UA if ua else {})
            with urllib.request.urlopen(req, timeout=min(TIMEOUT, left), context=SSL_CTX) as r:
                parts = []
                while chunk := r.read(1 << 16):
                    parts.append(chunk)
                    if time.monotonic() - t0 > min(PER_TRY, left):
                        raise TimeoutError("下载太慢")
            _DOWN[host] = 0
            return b"".join(parts)
        except Exception as e:  # noqa: BLE001  网络抖动重试
            err = e
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code != 429:
                raise DownloadError(_why(e), f"{url}：{e}")   # 地址不对、没这条：重试没用，也不算网站连不上
            if i + 1 < tries:   # 最后一次失败后不用再等
                time.sleep(min(2 * (i + 1), max(0.0, BUDGET - (time.monotonic() - _CLOCK[0]))))
    _DOWN[host] = _DOWN.get(host, 0) + 1
    raise DownloadError(_why(err), f"{url}：{err}")


def _download(key: str) -> bytes:
    s = SERIES[key]
    if key == "sp500_monthly":
        page = http_get(s["url"]).decode("utf-8", "ignore")
        m = re.search(r'(//img1\.wsimg\.com/[^"]+/ie_data\.xls[^"]*)', page)
        if not m:
            raise RuntimeError("席勒数据页上找不到下载链接，页面可能改版了")
        return http_get("https:" + m.group(1).replace("&amp;", "&"))
    if key == "gold":   # 世界银行的文件地址每月变，先从页面上找当月的链接
        page = http_get(s["url"], ua=True).decode("utf-8", "ignore")
        m = re.search(r'(https://thedocs\.worldbank\.org/[^"]*CMO-Historical-Data-Monthly\.xlsx)', page)
        if not m:
            raise RuntimeError("世界银行大宗商品页上找不到月度价格文件，页面可能改版了")
        return http_get(m.group(1), ua=True)
    if s["file"].startswith("cm_"):
        rows, url = [], s["url"]
        while url:
            j = json.loads(http_get(url))
            rows += j["data"]
            url = j.get("next_page_url")
        return json.dumps(rows).encode()
    return http_get(s["url"])


# ── 解析：统一成 [(日期, 数值)] ─────────────────────────────────
def _parse_fred(b: bytes):
    out = []
    for r in csv.reader(io.StringIO(b.decode())):
        if len(r) < 2 or not re.match(r"\d{4}-\d\d-\d\d", r[0]) or r[1] in (".", ""):
            continue
        out.append((dt.date.fromisoformat(r[0]), float(r[1])))
    return out


def _parse_shiller(b: bytes):
    import xlrd
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name("Data")
    out = []
    for r in range(sh.nrows):
        d, p = sh.cell_value(r, 0), sh.cell_value(r, 1)
        if isinstance(d, float) and isinstance(p, float) and d > 1800:
            y = int(d)
            m = int(round((d - y) * 100))
            out.append((dt.date(y, m, 1), p))
    return out


def _parse_cm(b: bytes, metric: str):
    out = []
    for r in json.loads(b):
        v = r.get(metric)
        if v not in (None, ""):
            out.append((dt.date.fromisoformat(r["time"][:10]), float(v)))
    return out


def _parse_wb(b: bytes, header: str = "Gold"):
    """世界银行粉单：「Monthly Prices」表（sheet2），表头写着 header 的那一列（金价「Gold」、原油「Crude oil, WTI」）；
    A 列是「1960M01」。只用标准库解析。"""
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(b))
    ss = [re.sub(r"<[^>]+>", "", x) for x in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    rows = re.findall(r'<row [^>]*r="(\d+)"[^>]*>(.*?)</row>', z.read("xl/worksheets/sheet2.xml").decode(), re.S)

    def cells(r):
        return {ref: (ss[int(v)] if 't="s"' in t else v)
                for ref, t, v in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<f>.*?</f>)?<v>([^<]*)</v>', r)}
    col = next(k for _, r in rows[:8] for k, v in cells(r).items() if str(v).strip() == header)
    out = []
    for _, r in rows:
        c = cells(r)
        m = re.fullmatch(r"(\d{4})M(\d\d)", str(c.get("A", "")))
        if m and re.fullmatch(r"[\d.]+", str(c.get(col, ""))):
            out.append((dt.date(int(m[1]), int(m[2]), 1), float(c[col])))
    return out


def _parse_imf(b: bytes):
    return [(dt.date(int(y), int(m), 1), float(v))
            for y, m, v in re.findall(r'<Obs TIME_PERIOD="(\d{4})-M(\d\d)" OBS_VALUE="([^"]+)"', b.decode())]


def parse(key: str, metric: str = "PriceUSD"):
    b = (RAW / SERIES[key]["file"]).read_bytes()
    if key == "sp500_monthly":
        return _parse_shiller(b)
    if key == "gold":
        return _parse_wb(b)
    if key == "gold_imf":
        return _parse_imf(b)
    if SERIES[key]["file"].startswith("cm_"):
        return _parse_cm(b, metric)
    return _parse_fred(b)


def treasury_rates(year: int, cols=("10 Yr", "3 Mo")):
    """第二来源（只用来核对）：美国财政部官网公布的每日国债利率，返回 {列名: {日期: 利率}}。"""
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
    rows = list(csv.reader(io.StringIO(http_get(url).decode())))
    out = {}
    for c in cols:
        i = rows[0].index(c)
        out[c] = {}
        for r in rows[1:]:
            if len(r) > i and r[i]:
                m, d, y = map(int, r[0].split("/"))
                out[c][dt.date(y, m, d)] = float(r[i])
    return out


def _fingerprint(rows, cutoff: str, start: str = "") -> str:
    h = hashlib.sha256()
    for d, v in rows:
        if start <= d.isoformat() <= cutoff:
            h.update(f"{d}:{v:.6g};".encode())
    return h.hexdigest()


def fetch_all(offline: bool = False) -> dict:
    """下载全部数据并登记来源。offline=True 时只用已有文件（本地调试用）。"""
    RAW.mkdir(parents=True, exist_ok=True)
    old = json.loads(SOURCES.read_text()) if SOURCES.exists() else {}
    reg = {}
    for key, s in SERIES.items():
        f = RAW / s["file"]
        fresh = not offline
        prev = old.get(key, {})
        try:   # 一条数据下载或解析失败不中断别的（11-24 前任何一条出错整次更新都失败）
            if offline and not f.exists():   # 公开版不附带原始文件：离线时缺哪条就记哪条没取到，不偷偷下载
                raise RuntimeError(f"离线模式缺少原始文件 {s['file']}，先不加 --offline 跑一次")
            if fresh:
                f.write_bytes(_download(key))
            b = f.read_bytes()
            rows = parse(key)
            if not rows:
                raise RuntimeError("解析出 0 行")
        except Exception as e:  # noqa: BLE001
            f.unlink(missing_ok=True)   # 坏文件不留：用到它的题目会出错、回到上一版，不会拿坏数算
            reg[key] = {**prev, "名称": s["名称"], "这次失败": short_reason(e)}
            print(f"⚠︎ {s['名称']} 这次没取到：{e}")
            continue
        # 旧历史有没有被改：只比两次都有的那一段 [校验起点, 上次校验截止]。
        # 11-25 查出：标普日收盘只给最近 10 年，窗口一往前挪，最早几天掉出去，整段指纹就变，被当成「改了旧历史」
        # （11-24 前这会让整个看板停更）。滚动窗口的数据把校验起点放在窗口里面一年多，窗口越过它再重新定。
        first = rows[0][0].isoformat()
        start = prev.get("历史校验起点") or prev.get("首日") or first
        changed = None
        if prev.get("历史校验截止"):
            if first > start:   # 最早的数据没了
                changed = None if s.get("滚动窗口") else True
            else:
                changed = _fingerprint(rows, prev["历史校验截止"], start) != prev["历史校验值"]
        # 改了旧历史：校验基准不往前挪，下一班照样报，直到有人核过（python pipeline/fetch.py --ack）或来源改回去。
        # 11-25 查出：原来每班都把基准换成新的，这个报警只亮一班（约两个半小时）就自己消失了，没人核过。
        # 官方本来就定期重算旧值的（会重估），不报、基准照常往前挪。
        hold = changed is True and not s.get("会重估")
        if not hold and (first > start or not prev.get("历史校验起点")):
            start = (rows[0][0] + dt.timedelta(days=400)).isoformat() if s.get("滚动窗口") else first
        cutoff = prev["历史校验截止"] if hold else (rows[-1][0] - dt.timedelta(days=60)).isoformat()
        reg[key] = {
            "名称": s["名称"], "来源": s["来源"], "下载地址": s["url"],
            "下载时间": (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") if fresh
                       else prev.get("下载时间", "未知")),   # 离线调试不改下载时间
            "文件校验值": hashlib.sha256(b).hexdigest(), "行数": len(rows),
            "首日": rows[0][0].isoformat(), "末日": rows[-1][0].isoformat(),
            "历史校验起点": start, "历史校验截止": cutoff,
            "历史校验值": prev["历史校验值"] if hold else _fingerprint(rows, cutoff, start),
            "旧历史被改": changed,
        }
    SOURCES.write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    return reg


def short_reason(e: Exception) -> str:
    """出错原因写给菜单看：我们自己写的中文原因照抄，别的只写类别，细节在云端运行日志里。"""
    if isinstance(e, DownloadError):
        return e.reason
    msg = str(e)
    if isinstance(e, RuntimeError) and msg and not msg.isascii():
        return msg[:40]
    return {"KeyError": "缺数（某个月份或日期没有）", "FileNotFoundError": "缺数据文件（没下载到）",
            "URLError": "网站连不上", "HTTPError": "网站报错", "TimeoutError": "网站超时"}.get(type(e).__name__, f"程序出错（{type(e).__name__}）")


def cn_day(iso: str) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return f"{d.month}月{d.day}日"


def problems(reg: dict = None, today: dt.date = None) -> list:
    """数据有问题的清单，写进状态.json「数据问题」，菜单橙色提示；不拦更新（别的题目照常）。
    三种：这次没下载到；按自己的公布节奏停太久（MAX_AGE）；来源改了旧数据（会重估的不算，见 SERIES「会重估」）。"""
    reg = reg if reg is not None else json.loads(SOURCES.read_text())
    today = today or dt.date.today()
    out = []
    for key, s in SERIES.items():
        r, name = reg.get(key, {}), s.get("简名") or s["名称"].split("（")[0]   # 只用来核对的数据没有简名，去掉括号里的说明
        if r.get("这次失败"):
            out.append({"名": name, "问题": f"这次没取到：{r['这次失败']}"})
        last, days = r.get("末日"), MAX_AGE.get(key)
        if last and days and (today - dt.date.fromisoformat(last)).days > days:
            out.append({"名": name, "问题": f"停在 {cn_day(last)}，平时{s['公布']}，超过 {days} 天没新数"})
        if r.get("旧历史被改") is True and not s.get("会重估"):
            out.append({"名": name, "问题": "来源改了旧数据，要人核过（维护手册情况二）"})
    return out


def coinbase_close(product: str, day: dt.date):
    """第二来源（只用来核对）：Coinbase 交易所当天（世界时）日线收盘。"""
    a = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    url = (f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
           f"&start={a.isoformat()}&end={(a + dt.timedelta(days=1)).isoformat()}")
    for c in json.loads(http_get(url, ua=True)):
        if dt.datetime.fromtimestamp(c[0], dt.timezone.utc).date() == day:
            return float(c[4])
    return None


def ack() -> list:
    """人核过「来源改了旧数据」之后运行：python -I pipeline/fetch.py --ack，再提交 data/sources.json。
    下一班以那时的数据为新基准重新开始比。"""
    reg = json.loads(SOURCES.read_text())
    done = [k for k, r in reg.items() if r.get("旧历史被改") is True]
    for k in done:
        reg[k]["旧历史被改"] = None
        reg[k].pop("历史校验截止", None)   # 没有截止＝下一班不比，只重新定基准
    SOURCES.write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    return done


if __name__ == "__main__":
    import sys
    if "--ack" in sys.argv:
        print("已核过，下一班重新定基准：", "、".join(ack()) or "没有要核的")
        sys.exit(0)
    for k, v in fetch_all(offline="--offline" in sys.argv).items():
        print(k, v["首日"], "→", v["末日"], v["行数"], "行", "旧历史被改" if v["旧历史被改"] else "")
