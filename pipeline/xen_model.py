#!/usr/bin/env python3
"""XEN 流通进度对照 SOL：模型和取数（只用标准库加系统 curl）。

看板置顶项「XEN 流通进度」由 xen.py 每天调用 sync() 和 save()；快照历史只由云端写入 data/xen_state.json。
本机直接运行本文件只打印、不写任何文件：
  python pipeline/xen_model.py                        完整表（含上次对照）
  python pipeline/xen_model.py --percent 81.64        任意比例
  python pipeline/xen_model.py --eth 2027-06-30=3000 --eth 2028-11-30=16000   ETH 情景
流通比例与 SOL 同一口径：链上现存（含质押，烧掉的不算）除以现存加预计未来铸造。公开版不附带本地研究笔记。
"""
import argparse
import bisect
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / 'data' / 'xen_state.json'
KEEP_DAYS = 75      # 校准要 14–45 天前的逐日快照，留 75 天足够；更早的在 git 历史里
URL = 'https://xen.pub/xen-supply.php'
DASHBOARD = 'https://xen.pub/index-xen-eth.php'
CURL = ['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
        '--connect-timeout', '10', '--max-time', '25', '--max-filesize', '5000000',
        '--silent', '--show-error']
# Dynamic projection (boss-approved 2026-11-05): new mints keep growing the denominator.
SCENARIOS = (('cold', '冷'), ('neutral', '中性'), ('hot', '热'))
CALIBRATION_DAYS = (14, 45)
HORIZON_DAYS = 10 * 366
ETH_PRICE = 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd'
# ETH what-if (elasticities measured 2026-11-05, handoff 0.6.1):
# (key, label, gas fee vs ETH price, new positions vs gas fee, new positions vs AMP)
ETH_SCENARIOS = (('eth', 'ETH情景', 0.47, 0.5, 0.5),
                 ('eth_fast', '最早', 1.0, 0.64, 0.64),
                 ('eth_slow', '最晚', 0.0, 0.5, 0.0))
# Circulation basis (boss 2026-11-18, aligned with SOL): read on chain at the page's time.
XEN_CONTRACT = '0x06450dee7fd2fb8e39061434babcfc05599a6fb8'
SELECTORS = (('liquid_T', '0x18160ddd'), ('staked_T', '0x069612a5'))  # totalSupply, totalXenStaked
# First node answers block lookups only; the rest serve historical calls (checked 2026-11-18).
CHAIN_RPCS = ('https://ethereum-rpc.publicnode.com', 'https://eth.drpc.org',
              'https://gateway.tenderly.co/public/mainnet', 'https://eth-mainnet.public.blastapi.io',
              'https://rpc.mevblocker.io', 'https://eth-pokt.nodies.app')
T = Decimal(10) ** 12
# Keep the thresholds accepted in the conversation, including Jan 5 precision.
TARGETS = (
    ('2022-12-26', '68.34', '68.34'),
    ('2023-06-05', '72.37', '72.37'),
    ('2023-09-11', '73.74', '73.74'),
    ('2024-03-20', '77.58', '77.58'),
    ('2024-11-18', '80.63', '80.63'),
    ('2025-01-05', '81.64', '81.64128798054438'),
    ('2025-01-13', '81.81', '81.81'),
    ('2025-09-22', '89.02', '89.02'),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_time(value):
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (EDT|EST)', value)
    require(match is not None, '无法识别供应页面时区/时间，停止同步')
    offset = -4 if match[2] == 'EDT' else -5
    return datetime.strptime(match[1], '%Y-%m-%d %H:%M:%S').replace(
        tzinfo=timezone(timedelta(hours=offset)))


def rpc(url, method, params):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    response = subprocess.run(CURL + ['-X', 'POST', '-H', 'content-type: application/json',
                                      '--data', body, url],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
    require(response.returncode == 0, '链上节点请求失败')
    result = json.loads(response.stdout).get('result')
    require(isinstance(result, (str, dict)), '链上节点未返回结果')
    return result


def any_rpc(method, params):
    for url in CHAIN_RPCS:
        try:
            return rpc(url, method, params)
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
    raise ValueError('所有链上节点都没回应：' + method)


def block_at(ts):
    """Last block at or before ts: estimate by 12-second slots, then step to it exactly."""
    stamp = lambda b: int(any_rpc('eth_getBlockByNumber', [hex(b), False])['timestamp'], 16)
    latest = int(any_rpc('eth_blockNumber', []), 16)
    b = min(latest, latest - int((stamp(latest) - ts) / 12))
    for _ in range(4):
        drift = stamp(b) - ts
        if abs(drift) < 24:
            break
        b -= int(drift / 12)
    while stamp(b) > ts:
        b -= 1
    while b < latest and stamp(b + 1) <= ts:
        b += 1
    return b


CARD_TOL = Decimal(1)   # 网站链上流通卡和链上读数最多差 1T（约一小时内的流量），否则时间对不上


def fetch_chain(snapshot):
    """All XEN in existence when the page was fetched = liquid totalSupply + staked principal
    (burned XEN is already gone from both). Two historical nodes must agree exactly.
    Read at the fetch moment, not at 'Last Update': the site's cards refresh hourly while its
    stamp marks only the long curve recalculation (checked 2026-11-18 over 12 snapshots: its
    on-chain card matched chain liquid at fetch time within 0.02T in 10, off by up to 5.7T at the
    stamp time). The site's own on-chain card is the timing check.
    2026-11-20 the site's own chain read broke (card shows 0.00 T) while everything else on the page was
    normal: with no usable card there is nothing to time against, so the check is skipped and recorded,
    never faked. The numerator never came from the card anyway (our own fetch-time read, two nodes agree),
    and the site's other count cards lag the chain by days (checked 11-20: ranks 564,509 behind), so none
    can stand in. A card that is present but off by more than CARD_TOL still stops the sync."""
    block = block_at(int(datetime.fromisoformat(snapshot['fetched_at_utc']).timestamp()))
    readings = {}
    for url in CHAIN_RPCS[1:]:
        try:
            value = tuple(int(rpc(url, 'eth_call', [{'to': XEN_CONTRACT, 'data': selector},
                                                    hex(block)]), 16)
                          for _, selector in SELECTORS)
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
        readings[url] = value
        if list(readings.values()).count(value) >= 2:
            break
    agreed = [v for v in readings.values() if list(readings.values()).count(v) >= 2]
    require(agreed, f'链上读数不足两家一致（区块{block}，回应{len(readings)}家），停止同步')
    chain = {key: str(Decimal(v) / T / Decimal(10) ** 18)
             for (key, _), v in zip(SELECTORS, agreed[0])}
    chain['existing_T'] = str(Decimal(chain['liquid_T']) + Decimal(chain['staked_T']))
    card = Decimal(snapshot['cards_T'].get('onchain') or 0)
    if card > 0:
        gap = card - Decimal(chain['liquid_T'])
        require(abs(gap) <= CARD_TOL, f'网站链上流通卡与链上读数相差{gap:+.2f}T，网站数据时间对不上，停止同步')
        chain['card_check'] = f'{gap:+.4f}'
    else:
        chain['card_check'] = '网站自己的链上流通卡读不到（显示 0 或没有），本次没对时'
    chain.update({'block': block, 'card_gap_T': chain['card_check'],
                  'sources': [u for u, v in readings.items() if v == agreed[0]]})
    return chain


def basis(snapshot):
    """XEN circulation ratio (boss 2026-11-18, same dimension as SOL): numerator = all XEN
    existing on chain (liquid + staked; burned is excluded), denominator = numerator + the
    site's future mints. The site curve is shifted by (on-chain existing - site claimed).
    Snapshots without a chain reading keep the old site-only basis.
    Returns (numerator_T, denominator_T, curve_offset_tokens)."""
    cards = snapshot['cards_T']
    if snapshot.get('chain'):
        now = Decimal(snapshot['chain']['existing_T'])
        return now, now + Decimal(cards['future']), (now - Decimal(cards['existing'])) * T
    return Decimal(cards['existing']), Decimal(cards['total']), Decimal(0)


def progress_text(snapshot):
    num, den, _ = basis(snapshot)
    if snapshot.get('chain'):
        return (f"当前XEN流通进度：链上现存{num:.2f}T ÷（现存＋未来mint "
                f"{Decimal(snapshot['cards_T']['future']):.2f}T）= {num / den * 100:.2f}%")
    return f'当前XEN释放进度（旧口径，未扣烧毁）：{num} ÷ {den} = {num / den * 100:.2f}%'


def target_result(snapshot, threshold):
    """Respect the source's sampling precision; never turn a monthly bucket into a day."""
    series = snapshot.get('series')
    if not series:
        old = next((snapshot['results'].get(day) for day, _, p in TARGETS
                    if Decimal(p) == Decimal(threshold)), None)
        return {'label': old or '无可复算曲线', 'day': old}
    _, den, offset = basis(snapshot)
    target = den * T * Decimal(threshold) / 100 - offset
    index = bisect.bisect_left(series['cumulative'], target)
    if index >= len(series['dates']):
        return {'label': '曲线内未达到', 'day': None}
    day = date.fromisoformat(series['dates'][index])
    previous = date.fromisoformat(series['dates'][index - 1]) if index else None
    following = (date.fromisoformat(series['dates'][index + 1])
                 if index + 1 < len(series['dates']) else None)
    gaps = [abs((other - day).days) for other in (previous, following) if other]
    if gaps and max(gaps) == 1:
        return {'label': day.isoformat(), 'day': day.isoformat()}
    if day.day == 1 and any(other and other.day == 1 and
                           28 <= abs((other - day).days) <= 31
                           for other in (previous, following)):
        return {'label': day.strftime('%Y-%m') + '（月级，日不确定）', 'day': None}
    return {'label': day.isoformat() + '（稀疏采样，日不确定）', 'day': None}


def query_report(snapshot, percentages, days):
    _, den, offset = basis(snapshot)
    lines = [f"页面更新时间：{snapshot['source_updated']}；固定分母{den:.2f}T。",
             progress_text(snapshot) + '。']
    for value in percentages:
        p = Decimal(value)
        require(p.is_finite() and 0 < p <= 100, '目标比例必须大于0且不超过100')
        line = f"{p}%：{target_result(snapshot, p)['label']}"
        if snapshot.get('dynamic'):
            line += (f"；动态推演中性{dynamic_label(snapshot, p, 'neutral')}，冷～热"
                     f"{dynamic_label(snapshot, p, 'cold')}～{dynamic_label(snapshot, p, 'hot')}")
        lines.append(line + '。')
    series = snapshot.get('series')
    for value in days:
        day = date.fromisoformat(value).isoformat()
        if snapshot.get('dynamic'):
            months = {m: end for m, _, end in snapshot['dynamic']['scenarios']['neutral']['months']}
            if day[:7] in months:
                lines.append(f'{day[:7]}：动态推演（中性）月底约{months[day[:7]] * 100:.2f}%。')
        if not series or day not in series['dates']:
            lines.append(f'{day}：曲线无该日数据，不编造日级比例。')
            continue
        i = series['dates'].index(day)
        neighbors = series['dates'][max(0, i - 1):min(len(series['dates']), i + 2)]
        if any(abs((date.fromisoformat(d) - date.fromisoformat(day)).days) > 1
               for d in neighbors):
            lines.append(f'{day}：仅有稀疏／月级数据，无法可靠计算该日比例。')
            continue
        p = (Decimal(series['cumulative'][i]) + offset) / (den * T) * 100
        lines.append(f'{day}：{p:.2f}%（固定本次分母的曲线值，未来为估算）。')
    lines.append('后续新增mint及网站修订会改变比例与日期；月份不可当作具体达标日。')
    if datetime.now(timezone.utc) - source_time(snapshot['source_updated']) > timedelta(hours=48):
        lines.append('注意：此快照已超过48小时，不能视为当天数据。')
    return '\n'.join(lines) + '\n'


def daily_queries_available(snapshot, percentages=(), days=()):
    """Check the actual requested dates, not just the chart title or array size."""
    targets = percentages or [p for _, _, p in TARGETS]
    if not all(target_result(snapshot, p)['day'] for p in targets):
        return False
    series = snapshot['series']
    for value in days:
        if value not in series['dates']:
            return False
        i = series['dates'].index(value)
        neighbors = series['dates'][max(0, i - 1):min(len(series['dates']), i + 2)]
        if any(abs((date.fromisoformat(d) - date.fromisoformat(value)).days) > 1
               for d in neighbors):
            return False
    return True


def fetch_snapshot(percentages=(), days=()):
    """At most two bounded requests; a cache-buster is not a daily-data API."""
    best = None
    attempts = []
    for attempt in range(2):
        request_url = URL
        if attempt:
            request_url += '?_xen_sync=' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
        command = list(CURL)
        if attempt:
            command += ['-H', 'Cache-Control: no-cache', '-H', 'Pragma: no-cache']
        try:
            response = subprocess.run(command + [request_url], capture_output=True,
                                      text=True, encoding='utf-8', timeout=30)
            require(response.returncode == 0, '网络请求失败：' + response.stderr.strip()[-300:])
            candidate = parse_page(response.stdout)
            candidate['request_url'] = request_url
            attempts.append({'request_url': request_url, 'source_updated': candidate['source_updated'],
                             'html_sha256': candidate['html_sha256'],
                             'cards_T': candidate['cards_T'],
                             'points': len(candidate['series']['dates']),
                             'daily_queries_available': daily_queries_available(candidate, percentages, days)})
            if best and source_time(candidate['source_updated']) < source_time(best['source_updated']):
                attempts[-1]['ignored'] = '来源更新时间倒退，不用旧曲线冒充最新'
                continue
            best = candidate
            if daily_queries_available(best, percentages, days):
                break
        except (ValueError, InvalidOperation, OSError, subprocess.SubprocessError) as exc:
            attempts.append({'request_url': request_url, 'error': str(exc)[:500]})
    require(best is not None, '两次有限请求均未取得可校验页面：' +
            '；'.join(a.get('error', '') for a in attempts))
    best['fetch_audit'] = attempts
    return best


def comparison_snapshot(history, current):
    """Prefer the last comparable daily snapshot, retaining all coarse history."""
    if daily_queries_available(current):
        for snapshot in reversed(history):
            if same_snapshot(snapshot, current):
                continue
            if snapshot.get('series') and daily_queries_available(snapshot):
                return snapshot
    return next((s for s in reversed(history) if not same_snapshot(s, current)), None)


def fetch_dashboard():
    """One bounded request for the current AMP and the daily-max Global Rank history."""
    response = subprocess.run(CURL + [DASHBOARD], capture_output=True, text=True,
                              encoding='utf-8', timeout=30)
    require(response.returncode == 0, '开仓数据请求失败：' + response.stderr.strip()[-300:])
    return parse_dashboard(response.stdout)


def parse_dashboard(raw):
    text = re.sub(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>',
                  ' ', raw, flags=re.S | re.I)
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).split())
    amp = re.search(r'\bAMP\s*([\d,]+)\s*Max Term', text)
    require(amp is not None, '仪表盘未找到AMP')
    amp = int(amp[1].replace(',', ''))
    require(1 <= amp <= 3000, 'AMP数值异常')
    require('getElementById("chart8")' in raw, '仪表盘开仓曲线缺失')
    chart = raw[raw.index('getElementById("chart8")'):]
    chart = chart[:chart.index('</script>')]
    dates = re.search(r'xAxis:.*?data:\s*(\[.*?\])', chart, re.S)
    ranks = re.search(r'name:\s*"Global Rank",\s*data:\s*(\[.*?\])', chart, re.S)
    require(dates is not None and ranks is not None, '仪表盘开仓曲线结构改变')
    dates, ranks = json.loads(dates[1]), [int(x) for x in json.loads(ranks[1])]
    require(len(dates) == len(ranks) > 400, '开仓曲线长度异常')
    require(all(date.fromisoformat(a) < date.fromisoformat(b) for a, b in zip(dates, dates[1:])),
            '开仓曲线日期非严格递增')
    require(all(a <= b for a, b in zip(ranks, ranks[1:])), 'Global Rank出现倒退')
    return {'amp': amp, 'amp_date': dates[-1], 'rank_dates': dates, 'ranks': ranks}


def rank_on(dash, day):
    """Daily-max Global Rank on the latest sampled date not after day (the source has gaps)."""
    i = bisect.bisect_right(dash['rank_dates'], day.isoformat()) - 1
    require(i >= 0, '开仓曲线早于所需日期')
    return date.fromisoformat(dash['rank_dates'][i]), dash['ranks'][i]


def rank_rate(dash, start, end):
    (a, first), (b, last) = rank_on(dash, start), rank_on(dash, end)
    require(b > a, '开仓曲线区间过短')
    return (last - first) / (b - a).days


def activity_rates(dash):
    """New positions per day: neutral = last 365 days; cold = slowest full calendar year;
    hot = busiest full month within the last 365 days."""
    first = date.fromisoformat(dash['rank_dates'][0])
    last = date.fromisoformat(dash['rank_dates'][-1])
    years = range(first.year + 1, last.year)
    require(years, '开仓历史不足一个完整年份')
    yearly = {y: rank_rate(dash, date(y - 1, 12, 31), date(y, 12, 31)) for y in years}
    cold = min(yearly, key=yearly.get)
    monthly = {}
    month_end = date(last.year, last.month, 1) - timedelta(days=1)
    while True:
        previous_end = date(month_end.year, month_end.month, 1) - timedelta(days=1)
        if previous_end < last - timedelta(days=365):
            break
        monthly[month_end.strftime('%Y-%m')] = rank_rate(dash, previous_end, month_end)
        month_end = previous_end
    require(monthly, '近一年没有完整月份')
    hot = max(monthly, key=monthly.get)
    return {'cold': {'label': f'{cold}年全年平均', 'rate': yearly[cold]},
            'neutral': {'label': '近一年平均', 'rate': rank_rate(dash, last - timedelta(days=365), last)},
            'hot': {'label': f'近一年最高月（{hot}）', 'rate': monthly[hot]}}


def fully_daily(snapshot):
    """Every day present, history included; some responses bucket history by month."""
    dates = snapshot.get('series', {}).get('dates', [])
    return len(dates) > 1 and all((date.fromisoformat(b) - date.fromisoformat(a)).days == 1
                                  for a, b in zip(dates, dates[1:]))


def calibrate(base, current, dash):
    """Reward per new position and its maturity offsets, measured from how the site's
    future curve grew between two daily snapshots."""
    require(fully_daily(base) and fully_daily(current), '校准快照的历史不是逐日数据')
    ta = date.fromisoformat(base['source_updated'][:10])
    tb = date.fromisoformat(current['source_updated'][:10])
    old_future = dict(zip(base['series']['dates'], base['series']['future']))
    new_future = dict(zip(current['series']['dates'], current['series']['future']))
    mined = dict(zip(current['series']['dates'], current['series']['mined']))
    window = [d for d in mined if ta < date.fromisoformat(d) <= tb]
    # Positions opened and already matured inside the window.
    short = sum(mined[d] for d in window) - sum(old_future.get(d, 0) for d in window)
    later = {d: new_future.get(d, 0) - old_future.get(d, 0)
             for d in set(old_future) | set(new_future) if date.fromisoformat(d) > tb}
    registered = sum(later.values()) + max(short, 0)
    ranks_added = rank_on(dash, tb)[1] - rank_on(dash, ta)[1]
    require(ranks_added > 0 and registered > 0, '校准窗口内没有可用的新开仓数据')
    middle = ta + timedelta(days=(tb - ta).days // 2)
    offsets = {}
    for d, value in later.items():
        if value > 0:
            k = (date.fromisoformat(d) - middle).days
            offsets[k] = offsets.get(k, 0) + value
    span = (tb - ta).days
    if short > 0:
        for k in range(1, span + 1):
            offsets[k // 2 + 1] = offsets.get(k // 2 + 1, 0) + short / span
    total = sum(offsets.values())
    return {'window': [base['source_updated'], current['source_updated']],
            'registered_T': round(registered / 10 ** 12, 3), 'ranks_added': ranks_added,
            'per_position': registered / ranks_added,
            'offsets': {k: v / total for k, v in offsets.items()}}


def parse_eth_path(values):
    """`YYYY-MM-DD=USD` anchors; flat before the first and after the last, geometric between."""
    path = []
    for value in values:
        day, sep, price = value.partition('=')
        require(sep == '=', 'ETH路径格式应为 日期=美元，如 2027-08-01=3000')
        price = float(price.replace(',', '').lstrip('$'))
        require(0 < price < 10 ** 6, 'ETH价格异常')
        path.append((date.fromisoformat(day), price))
    path.sort()
    require(all(a[0] < b[0] for a, b in zip(path, path[1:])), 'ETH路径日期重复')
    return path


def eth_price_on(path, day):
    if day <= path[0][0]:
        return path[0][1]
    for (a, pa), (b, pb) in zip(path, path[1:]):
        if day <= b:
            return pa * (pb / pa) ** ((day - a).days / (b - a).days)
    return path[-1][1]


def fetch_eth_price():
    response = subprocess.run(CURL + [ETH_PRICE], capture_output=True, text=True,
                              encoding='utf-8', timeout=30)
    require(response.returncode == 0, 'ETH现价请求失败：' + response.stderr.strip()[-300:])
    price = float(json.loads(response.stdout)['ethereum']['usd'])
    require(10 < price < 10 ** 6, 'ETH现价异常')
    return price


def project(current, dash, per_position, offsets, rate):
    """Daily simulation: existing queue follows the site curve; new positions arrive at
    `rate(day)` per day with reward scaled by the contract AMP (minus 1 per day, floor 1)."""
    t0 = date.fromisoformat(current['source_updated'][:10])
    amp_day = date.fromisoformat(dash['amp_date'])
    _, den, offset = basis(current)
    total = float(den * T)
    existing, running, base = {}, float(offset), float(offset)
    for d, m, f in zip(current['series']['dates'], current['series']['mined'],
                       current['series']['future']):
        running += m + f
        existing[date.fromisoformat(d)] = running
        if date.fromisoformat(d) <= t0:
            base = running
    matured = [0.0] * (HORIZON_DAYS + 1)
    registered = released = 0.0
    months = {}
    for i in range(1, HORIZON_DAYS + 1):
        day = t0 + timedelta(days=i)
        amp = max(1, dash['amp'] - (day - amp_day).days)
        new = rate(day) * per_position * amp / dash['amp']
        registered += new
        for k, w in offsets.items():
            if i + k <= HORIZON_DAYS:
                matured[i + k] += new * w
        released += matured[i]
        base = existing.get(day, base)
        ratio = (base + released) / (total + registered)
        key = day.strftime('%Y-%m')
        months[key] = [max(months.get(key, [0])[0], ratio), ratio]
    return [[k, round(high, 6), round(end, 6)] for k, (high, end) in months.items()]


def dynamic_projection(history, current, dash, eth=None):
    require(daily_queries_available(current), '本次曲线不是日级')
    # Calibration compares day by day, so it uses the latest fully daily pair; the
    # projection itself still starts from this response's curve and cards.
    day_of = lambda s: date.fromisoformat(s['source_updated'][:10])
    daily = [s for s in history + [current] if fully_daily(s)]
    require(daily and (day_of(current) - day_of(daily[-1])).days <= CALIBRATION_DAYS[1],
            '近45天没有逐日完整的快照，无法校准新开仓')
    end = daily[-1]
    bases = [s for s in daily
             if CALIBRATION_DAYS[0] <= (day_of(end) - day_of(s)).days <= CALIBRATION_DAYS[1]]
    require(bases, '缺少14至45天前的逐日快照，无法校准新开仓')
    calibration = calibrate(bases[0], end, dash)
    offsets = calibration.pop('offsets')
    result = {'amp': dash['amp'], 'amp_date': dash['amp_date'], 'source_url': DASHBOARD,
              'calibration': calibration, 'scenarios': {}}
    rates = activity_rates(dash)
    for key, rate in rates.items():
        result['scenarios'][key] = {
            'label': rate['label'], 'ranks_per_day': round(rate['rate']),
            'months': project(current, dash, calibration['per_position'], offsets,
                              lambda day, r=rate['rate']: r)}
    if eth:
        # New positions = neutral rate scaled by gas (which follows ETH) and by AMP incentive.
        amp_day = date.fromisoformat(dash['amp_date'])
        result['eth'] = {'now': eth['now'], 'scenarios': {},
                         'path': [[day.isoformat(), price] for day, price in eth['path']]}
        for key, label, gas, activity, amp_weight in ETH_SCENARIOS:
            def rate(day, gas=gas, activity=activity, amp_weight=amp_weight):
                amp = max(1, dash['amp'] - (day - amp_day).days)
                return (rates['neutral']['rate'] * (amp / dash['amp']) ** amp_weight
                        * (eth_price_on(eth['path'], day) / eth['now']) ** (-gas * activity))
            result['eth']['scenarios'][key] = {
                'label': label,
                'months': project(current, dash, calibration['per_position'], offsets, rate)}
    return result


def dynamic_label(snapshot, threshold, key):
    """Month of the first simulated day at or above the threshold."""
    p = float(Decimal(threshold) / 100)
    dynamic = snapshot['dynamic']
    scenario = dynamic['scenarios'].get(key) or dynamic['eth']['scenarios'][key]
    return next((month for month, high, _ in scenario['months'] if high >= p), '十年内到不了')


def eth_report(snapshot):
    eth = snapshot['dynamic']['eth']
    path = ' → '.join(f'{day} ${price:,.0f}' for day, price in eth['path'])
    lines = [f"页面更新时间：{snapshot['source_updated']}；{progress_text(snapshot)}。",
             f"ETH情景：现价${eth['now']:,.0f}；路径 {path}（首日前按首价，末日后持平，中间等比）。",
             '',
             '| SOL历史日期 | 对照比例 | 默认中性 | ETH情景 | 最早～最晚 |',
             '|---|---:|---|---|---|']
    for sol_date, display, threshold in TARGETS:
        cells = [sol_date, display + '%', dynamic_label(snapshot, threshold, 'neutral'),
                 dynamic_label(snapshot, threshold, 'eth'),
                 dynamic_label(snapshot, threshold, 'eth_fast') + '～'
                 + dynamic_label(snapshot, threshold, 'eth_slow')]
        if sol_date == '2025-01-05':
            cells = ['**' + cell + '**' for cell in cells]
        else:
            cells[3] = '**' + cells[3] + '**'
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', 'ETH涨通过推高手续费减少新开仓（手续费随ETH弹性0.47，开仓随手续费弹性−0.5），'
              '放大系数每天减1也减少开仓（弹性0.5）；最早＝手续费完全跟涨、弹性0.64，'
              '最晚＝手续费不跟涨且不计放大系数。XEN币价不进模型：实测开仓对它不敏感。'
              '参数为2026-11-05实测弹性；只报月份。']
    return '\n'.join(lines) + '\n'


def parse_page(raw):
    text = re.sub(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>',
                  ' ', raw, flags=re.S | re.I)
    text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).split())
    stamp = re.search(r'Last Update:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (?:EDT|EST))', text)
    require(stamp is not None, '未找到页面更新时间')
    source_time(stamp[1])
    patterns = {
        'existing': r'Mint Supply\s*\(existing\)\s*([\d,.]+)\s*Trillion',
        'future': r'Future Mint Supply\s*\(upcoming\)\s*([\d,.]+)\s*Trillion',
        'total': r'Total Mint Supply\s*\(all\)\s*([\d,.]+)\s*Trillion',
    }
    # 只用来对时 / 只做记录的卡：坏了或没了不拦（11-20 网站自己的链上卡显示 0.00 T）
    optional = {
        'onchain': r'On-Chain Total Supply\s*([\d,.]+)\s*T\b',
        'burn': r'Total Burned\s*([\d,.]+)\s*T\b',
    }
    cards = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        require(match is not None, '页面卡片缺失或布局改变：' + key)
        cards[key] = match[1].replace(',', '')
    for key, pattern in optional.items():
        match = re.search(pattern, text)
        if match is not None:
            cards[key] = match[1].replace(',', '')
    values = {key: Decimal(value) for key, value in cards.items()}
    require(all(x.is_finite() and x >= 0 for x in values.values()), '卡片值异常')
    require(values['total'] > values['existing'] > 0, '总量/已领取量关系异常')
    require(abs(values['existing'] + values['future'] - values['total']) <= Decimal('.02'),
            'M+F与D不符，停止同步')
    require('var cumulativeTotal1' in raw, '未找到网站累计曲线')
    chart = raw[raw.index('var cumulativeTotal1'):]
    if 'Chart Error:' in chart:
        chart = chart[:chart.index('Chart Error:')]

    def array(pattern):
        match = re.search(pattern, chart, re.S)
        require(match is not None, '网站曲线结构改变，停止同步')
        return json.loads(match[1])

    cumulative = array(r'var cumulativeTotal1\s*=\s*(\[.*?\]);')
    dates = array(r'xAxis:.*?data:\s*(\[.*?\])')
    mined = array(r"name: 'Mined Supply'.*?data:\s*(\[.*?\])")
    future = array(r"name: 'Future Supply'.*?data:\s*(\[.*?\])")
    require(len(dates) == len(cumulative) == len(mined) == len(future) > 0,
            '曲线长度不一致')
    require(all(isinstance(x, str) and date.fromisoformat(x) for x in dates), '日期格式异常')
    require(all(a < b for a, b in zip(dates, dates[1:])), '日期非严格递增')
    require(all(type(x) is int and x >= 0 for seq in (cumulative, mined, future) for x in seq),
            '曲线不是非负整数，需人工核实')
    running = 0
    for m, f, c in zip(mined, future, cumulative):
        running += m + f
        require(c == running, '累计曲线与逐期mint求和不一致')
    require(abs(Decimal(sum(mined)) / T - values['existing']) <= Decimal('.01'),
            '图表已领取总量与卡片不符，停止同步')
    discrepancy = Decimal(cumulative[-1]) / T - values['total']
    require(abs(discrepancy) / values['total'] <= Decimal('.01'),
            '图表终值与卡片总量差异超过1%，停止同步')
    snapshot = {
        'source_updated': stamp[1], 'source_url': URL,
        'provenance': 'downloaded_page_and_validated_embedded_series',
        'fetched_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'html_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
        'cards_T': cards, 'graph_total_T': str(Decimal(cumulative[-1]) / T),
        'graph_card_difference_T': str(discrepancy),
        'results': {},
        'thresholds_percent': {day: threshold for day, _, threshold in TARGETS},
        'series': {'dates': dates, 'cumulative': cumulative, 'mined': mined, 'future': future},
    }
    snapshot['verification'] = {
        'cumulative_equals_prefix_sum': True,
        'mined_card_difference_T': str(Decimal(sum(mined)) / T - values['existing']),
        'graph_card_relative_difference_percent': str(discrepancy / values['total'] * 100),
    }
    refresh_results(snapshot)
    return snapshot


def refresh_results(snapshot):
    """Recompute stored results and audit brackets under the snapshot's current basis."""
    series = snapshot['series']
    cumulative, dates = series['cumulative'], series['dates']
    _, den, offset = basis(snapshot)
    snapshot['results'] = {day: target_result(snapshot, threshold)['label']
                           for day, _, threshold in TARGETS}
    verification = snapshot.setdefault('verification', {})
    verification['daily_targets_available'] = daily_queries_available(snapshot)
    verification['curve_offset_tokens'] = str(offset)
    verification['target_brackets'] = {}
    for sol_date, _, threshold in TARGETS:
        target = den * T * Decimal(threshold) / 100 - offset
        i = bisect.bisect_left(cumulative, target)
        verification['target_brackets'][sol_date] = {
            'threshold_tokens': str(target),
            'before_date': dates[i - 1] if i else None,
            'before_tokens': cumulative[i - 1] if i else None,
            'crossing_date': dates[i] if i < len(dates) else None,
            'crossing_tokens': cumulative[i] if i < len(dates) else None,
            'display': snapshot['results'][sol_date],
        }


def same_snapshot(a, b):
    return (a['source_updated'] == b['source_updated']
            and a['cards_T'] == b['cards_T']
            and (a.get('series') == b.get('series') if a.get('series')
                 else a['results'] == b['results']))


def render(current, previous, checked_at):
    cards = current['cards_T']
    dynamic = current.get('dynamic')
    _, den, offset = basis(current)
    chain = current.get('chain')
    lines = [
        f"页面更新时间：**{current['source_updated']}**；本次查询：{checked_at}。",
        '',
        f"按最新释放曲线、固定最新分母 **{den:.2f}T**，重新对应SOL；**{progress_text(current)}**。",
    ]
    if chain:
        lines.append(f"链上读数（区块{chain['block']}，{len(chain['sources'])}家节点一致）："
                     f"流通{Decimal(chain['liquid_T']):.2f}T＋质押{Decimal(chain['staked_T']):.2f}T；"
                     f"比网站累计已领取{cards['existing']}T多{offset / T:.2f}T，网站曲线整体上移该差额。")
    old_basis = bool(previous and chain and not previous.get('chain'))
    lines += [
        '',
        '| SOL历史日期 | 对照比例 | 上次XEN估算' + ('（旧口径）' if old_basis else '') + ' | 最新XEN估算 |'
        + (' 动态推演（中性） | 冷～热区间 |' if dynamic else ''),
        '|---|---:|---|---|' + ('---|---|' if dynamic else ''),
    ]
    shifts = []
    coarse = False
    for sol_date, display, threshold in TARGETS:
        old_result = target_result(previous, threshold) if previous else None
        new_result = target_result(current, threshold)
        old = old_result['label'] if old_result else None
        new = new_result['label']
        coarse = coarse or not new_result['day'] or bool(old_result and not old_result['day'])
        focus = sol_date == '2025-01-05'
        cells = [sol_date, display + '%', old or '无可用上次结果', new or '曲线内未达到']
        if dynamic:
            cells += [dynamic_label(current, threshold, 'neutral'),
                      dynamic_label(current, threshold, 'cold') + '～'
                      + dynamic_label(current, threshold, 'hot')]
        if focus:
            cells = ['**' + cell + '**' for cell in cells]
        else:
            cells[3] = '**' + cells[3] + '**'
            if dynamic:
                cells[4] = '**' + cells[4] + '**'
        lines.append('| ' + ' | '.join(cells) + ' |')
        if old_result and old_result['day'] and new_result['day']:
            shifts.append((date.fromisoformat(new_result['day']) -
                           date.fromisoformat(old_result['day'])).days)
    lines += ['', '上次快照：' + (previous['source_updated'] if previous else '无') + '。']
    if dynamic:
        scenarios, calibration = dynamic['scenarios'], dynamic['calibration']
        rates = '；'.join(f"{name}＝{scenarios[key]['label']}每天"
                         f"{scenarios[key]['ranks_per_day'] / 10000:.1f}万个" for key, name in SCENARIOS)
        lines += ['', f"动态推演：总量不再定死，把每天新开仓计入分母（{rates}）。每个新仓位约"
                  f"{calibration['per_position'] / 10000:.0f}万枚，按{calibration['window'][0]}至"
                  f"{calibration['window'][1]}两份快照实测；放大系数按合约每天减1（当前{dynamic['amp']}）。"
                  '只报月份。']
    elif current.get('dynamic_error'):
        lines += ['', '动态推演本次未出：' + current['dynamic_error'] + '。']
    if coarse:
        lines += ['', '**精度提示：部分曲线为月级／稀疏采样，仅报来源支持的月份或采样点；'
                  '不把每月1号当作准确达标日，不计算这些行的天数偏移。**']
    else:
        lines += ['', '精度校验：本表各节点均使用本次响应的日级数据；逐日加总与累计曲线一致，'
                  '并逐项验证达标前一天低于目标、当日达到目标。']
    audit = current.get('fetch_audit', [])
    if len(audit) > 1:
        lines += ['', '获取记录：首份响应缺少所需日级数据或校验失败，已额外尝试一次防缓存获取；'
                  '采用同一份有效响应的卡片和曲线，不跨响应拼接。']
    if previous and current.get('series') and previous.get('series'):
        lines += ['', '对照规则：当前为日级时，优先对比上一份可按日比较的快照；中间月级快照仍完整保留。']
    if old_basis:
        shifts = []
        lines += ['', '上次为旧口径（未扣烧毁），与本次不可直接比天数。']
    if shifts:
        if all(x == 0 for x in shifts):
            conclusion = '相对上次，这些目标日期均未改变。'
        elif all(x >= 0 for x in shifts):
            conclusion = f'相对上次，目标日期持平或推后，最多推后{max(shifts)}天。'
        elif all(x <= 0 for x in shifts):
            conclusion = f'相对上次，目标日期持平或提前，最多提前{-min(shifts)}天。'
        else:
            conclusion = f'相对上次，部分提前、部分推后，变化范围为{min(shifts):+d}至{max(shifts):+d}天。'
        lines += ['', conclusion]
    discrepancy = Decimal(current.get('graph_card_difference_T', '0'))
    if discrepancy:
        lines += ['', f'数据校验：网站图表终值与其卡片总量相差{discrepancy:+.6f}T；本表仍以卡片数计算。']
    elapsed = datetime.now(timezone.utc) - source_time(current['source_updated'])
    if elapsed > timedelta(hours=48):
        lines += ['', '**数据陈旧：页面已超过48小时未更新，以上是最新可用页面快照，并非当天数据。**']
    elif elapsed < -timedelta(hours=24):
        lines += ['', '**注意：页面时间领先系统时间超过24小时，需要核对本机时钟及来源。**']
    lines += [
        '', '口径（2026-11-18已定，与SOL同维度）：XEN为链上现存（流通＋质押，已烧掉的不算）'
        '÷（链上现存＋网站预计未来mint）；SOL为历史流通量（含质押）÷当时总量（已烧掉的不在内）。'
        '仅对照比例；「最新XEN估算」是固定本次分母的网站曲线估算，会随新增mint系统性推后；'
        '动态推演另把新开仓计入分母，主要不确定性是未来每天开仓多少。',
        '', '[XEN供应页面](https://xen.pub/xen-supply.php) · '
        'SOL 对照阈值写在本文件 TARGETS，只比较流通比例',
    ]
    return '\n'.join(lines) + '\n'


def atomic_write(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix='.' + path.name + '.',
                                         suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_state():
    state = json.loads(STATE.read_text(encoding='utf-8'))
    require(state.get('schema_version') == 1 and state.get('snapshots'), '状态文件格式异常')
    return state


def sync(history, eth_path=None, percentages=(), days=(), raw=None):
    """One fresh reading: site page + on-chain numerator + dynamic projection. Writes nothing."""
    current = parse_page(raw) if raw is not None else fetch_snapshot(percentages, days)
    # The ratio's numerator is on chain; without an agreed reading nothing is reported.
    current['chain'] = fetch_chain(current)
    refresh_results(current)
    if raw is None:
        require(source_time(current['source_updated']) >= source_time(history[-1]['source_updated']),
                '页面返回了比最后成功快照更旧的数据，未覆盖状态')
        # The original table never depends on these extra requests.
        eth = None
        if eth_path:
            try:
                eth = {'now': fetch_eth_price(), 'path': eth_path}
            except (ValueError, KeyError, TypeError, OSError,
                    subprocess.SubprocessError) as exc:
                current['eth_error'] = str(exc)[:300]
        try:
            current['dynamic'] = dynamic_projection(history, current, fetch_dashboard(), eth)
        except (ValueError, KeyError, ZeroDivisionError, OSError,
                subprocess.SubprocessError) as exc:
            current['dynamic_error'] = str(exc)[:300]
    return current


def remember(history, current):
    """Same page again replaces the last snapshot; a new page is appended."""
    if same_snapshot(history[-1], current):
        history[-1] = current
    else:
        history.append(current)


def save(state, current):
    """只在云端写入：保留最近 KEEP_DAYS 天的快照。公开版不附带这份文件。"""
    remember(state['snapshots'], current)
    cutoff = source_time(current['source_updated']) - timedelta(days=KEEP_DAYS)
    state['snapshots'] = [s for s in state['snapshots'] if source_time(s['source_updated']) >= cutoff]
    atomic_write(STATE, json.dumps(state, ensure_ascii=False, indent=1) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--html', type=Path, help='读取保存的页面（链上数仍联网读）')
    parser.add_argument('--saved', action='store_true', help='仅用最近成功快照复算，不联网')
    parser.add_argument('--percent', action='append', default=[], help='查询任意目标百分比，可重复指定')
    parser.add_argument('--date', action='append', default=[], help='查询YYYY-MM-DD的比例，可重复指定')
    parser.add_argument('--eth', action='append', default=[],
                        help='假设ETH价格路径，日期=美元，可重复指定，如 --eth 2028-11-30=16000')
    args = parser.parse_args()
    history = load_state()['snapshots']
    last_success_updated = history[-1]['source_updated']
    try:
        if args.saved:
            require(not args.html, '--saved与--html不能同时使用')
            require(not args.eth, 'ETH情景需要联网同步，不能与--saved同用')
            print(query_report(history[-1], args.percent, args.date) if args.percent or args.date
                  else render(history[-1], comparison_snapshot(history[:-1], history[-1]),
                              datetime.now(timezone.utc).isoformat(timespec='seconds')), end='')
            return 0
        # Validate query arguments before any network request or state mutation.
        for value in args.percent:
            p = Decimal(value)
            require(p.is_finite() and 0 < p <= 100, '目标比例必须大于0且不超过100')
        for value in args.date:
            date.fromisoformat(value)
        eth_path = parse_eth_path(args.eth) if args.eth else None
        require(not (eth_path and (args.html or args.percent or args.date)),
                'ETH情景需要联网同步，不与--html/--percent/--date同用')
        raw = args.html.read_text(encoding='utf-8') if args.html else None
        current = sync(history, eth_path, args.percent, args.date, raw)
        previous = comparison_snapshot(history, current)
        remember(history, current)
        report = render(current, previous, datetime.now(timezone.utc).isoformat(timespec='seconds'))
        if eth_path:
            if 'eth' not in current.get('dynamic', {}):
                print('ETH情景本次未出：' + (current.get('eth_error') or current.get('dynamic_error')
                                         or '未知原因'), file=sys.stderr)
                return 1
            print(eth_report(current), end='')
            return 0
        print(query_report(current, args.percent, args.date) if args.percent or args.date
              else report, end='')
    except (ValueError, InvalidOperation, OSError, subprocess.SubprocessError) as exc:
        print('同步失败：' + str(exc), file=sys.stderr)
        print('最后成功页面快照：' + last_success_updated +
              '；旧结果未被标为最新。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
