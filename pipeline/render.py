"""出图：只读各题目 results/<键>.json 的「显示」内容拼网页，再转成高清图。这里不许写任何数字。"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topics import TOPICS  # noqa: E402
from defs import SOURCES, SOURCE_TAIL, STAGE_ASSETS  # noqa: E402
import fetch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
HASHES = ROOT / "results" / "render_hash.json"
STATUS = ROOT / "看板" / "状态.json"   # 菜单栏程序读它，自己判断健康（数据旧了、核对不过、待复核都会亮警告）
W = 400       # 图宽（点）。2026-11-18嫌字小：最小字号 12，图放宽到 400
# 看板上的图和状态只由云端出（生产环境只有一个）。本机跑只出预览图到 build/预览/，不碰「看板」和出图校验值，
# 这样本机调试永远不会改到菜单显示的东西，也不会和云端用不同字体来回改图。
IN_CLOUD = os.environ.get("GITHUB_ACTIONS") == "true"

# 图上只放结论；依据、口径、对照数都挂在 data-tip 上，出图时量出每块的位置，存成同名 .json，
# 菜单程序据此在鼠标停上去时浮出说明（2026-11-18：注释用浮现，不要密密麻麻的字）。
# 颜色统一（定义见 defs.py COLOR_WORDS）：红＝多数涨 · 绿＝多数跌 · 灰＝说不准 · 橙＝见顶或要注意 · 蓝＝有用的规律
CSS = """*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%dpx;height:%dpx;background:#fff;color:#1d1d1f;overflow:hidden;
 font-family:"PingFang SC","Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif}
.wrap{padding:14px 14px 12px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.top b{font-size:19px;letter-spacing:.5px}.top .sub{font-size:13px;color:#8a8a8e;font-weight:400;margin-left:8px}
.right{display:flex;gap:6px;align-items:center}
.how{font-size:12px;color:#6e6e73;background:#f2f2f4;border-radius:10px;padding:2px 6px 2px 9px;display:flex;align-items:center;gap:4px}
.src{margin-top:10px;font-size:12px;color:#8a8a8e;display:flex;flex-wrap:wrap;gap:3px 9px}.src a{color:#0a64d8}
.how i{font-style:normal;width:15px;height:15px;border-radius:8px;background:#8a8a8e;color:#fff;font-size:12px;line-height:15px;text-align:center;font-weight:700}
.warn{color:#fff;background:#d9480f;border-radius:10px;padding:2px 8px;font-size:12px}
.grid{display:grid;grid-template-columns:50px repeat(4,1fr);gap:4px}
.h{text-align:center;border-radius:8px;padding:5px 0 6px;background:#f4f4f6;position:relative}
.h .y{font-size:12px;color:#8a8a8e;line-height:1.3}.h .n{font-size:13px;line-height:1.35}
.h .m{font-size:18px;font-weight:700;line-height:1.3}
.now{outline:2px solid #1d1d1f;outline-offset:-2px}
.tag{position:absolute;top:-8px;right:-2px;background:#1d1d1f;color:#fff;font-size:12px;border-radius:6px;padding:0 5px;line-height:16px}
.lab{font-size:15px;font-weight:600;display:flex;align-items:center;color:#3a3a3c}
.c{text-align:center;border-radius:8px;font-size:16px;font-weight:700;padding:6px 0 5px;line-height:1.25}
.c small{display:block;font-size:12px;font-weight:500;opacity:.85}
.涨{background:#fde8e8;color:#c8102e}.跌{background:#e3f4ea;color:#0b7a3b}
.平{background:#f0f0f2;color:#6e6e73}.顶{background:#fff1dc;color:#b45a00}
.蓝{background:#e8effc;color:#1f4fbf}.浅蓝{background:#f0f4fb;color:#5a7bbf}
.t涨{color:#c8102e}.t跌{color:#0b7a3b}.t顶{color:#b45a00}.t平{color:#8a8a8e}
.b涨{background:#e98a96}.b跌{background:#7fc79a}.b顶{background:#f0a447}.b平{background:#b8b8be}
.tl{display:grid;grid-template-columns:50px 1fr;gap:4px;margin-top:10px}
.track{position:relative;height:96px}
.line{position:absolute;left:0;right:0;top:46px;height:4px;background:#d8d8dc;border-radius:2px}
.band{position:absolute;top:42px;height:12px;border-radius:6px;min-width:12px}
.lb{position:absolute;font-size:12px;line-height:1.3;text-align:center;white-space:nowrap;transform:translateX(-50%%)}
.lb b{font-size:14px}.up1{top:0}.dn1{top:60px}
.box{margin-top:10px;font-size:13px;line-height:1.5;border-radius:8px;padding:6px 10px}
.box b{font-weight:700}
.warnbox{background:#fff6e5;color:#3a3a3c}.warnbox b{color:#b45a00}
.qgrid{display:grid;grid-template-columns:50px repeat(4,1fr);gap:4px}
.qh{text-align:center;font-size:13px;color:#8a8a8e}
.one{font-size:16px;font-weight:700;line-height:1.45;margin-bottom:8px}
.nowbox{font-size:13px;line-height:1.5;background:#f4f4f6;border-radius:8px;padding:6px 10px;margin-bottom:8px}
.rrow{display:grid;grid-template-columns:1fr 80px 72px 70px;gap:4px;align-items:center;padding:5px 0;border-top:1px solid #efeff2}
.rrow.th{font-size:12px;color:#8a8a8e;border-top:none;padding:0 0 2px}
.rrow.th div{text-align:center}.rrow.th div:first-child{text-align:left}
.rrow .nm{font-size:13px;line-height:1.35;white-space:pre-line}
.rrow .v{text-align:center;font-size:16px;font-weight:700;line-height:1.2}
.rrow .v small{display:block;font-size:12px;font-weight:400;color:#8a8a8e;white-space:nowrap}
.rrow .bs{text-align:center;font-size:15px;color:#6e6e73}
.rrow .j{text-align:center;font-size:13px;font-weight:700;border-radius:7px;padding:5px 0}
.sec{font-size:12px;color:#8a8a8e;margin:10px 0 5px}
.sig{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.sc{border-radius:8px;padding:7px 9px}
.sh{display:flex;justify-content:space-between;align-items:baseline}.sh .nm{font-size:13px;font-weight:600}
.sh .st{font-size:12px;font-weight:600}
.sv{font-size:22px;font-weight:700;line-height:1.2}.sv .ar{font-size:18px;margin-left:5px}
.sp{display:block;margin-top:3px}
.sx{display:flex;justify-content:space-between;font-size:12px;color:#8a8a8e;line-height:1.3}
.sd{font-size:12px;color:#3a3a3c;line-height:1.5}
.so{font-size:15px;font-weight:700;line-height:1.45;background:#f4f4f6;border-left:4px solid #1d1d1f;border-radius:6px;
 padding:7px 10px;margin-bottom:9px;color:#1d1d1f}
.so.顶{background:#fff1dc;border-left-color:#d9480f}
.rule{font-size:14px;font-weight:600;color:#3a3a3c;line-height:1.45;margin-bottom:6px}
.crow{display:grid;grid-template-columns:88px 1fr 1fr 1fr 1fr;gap:4px;align-items:center;padding:5px 0;
 border-top:1px solid #efeff2;text-align:center;font-size:15px;font-weight:700}
.crow.c4{grid-template-columns:130px 58px 58px 1fr}
.crow.c4o{grid-template-columns:70px 58px 1fr 100px;padding:3px 0}
.crow.th{font-size:12px;color:#8a8a8e;font-weight:400;border-top:none;padding:0 0 2px}
.crow .nm{text-align:left;font-size:13px;font-weight:600}.crow.th div:first-child{text-align:left}
.crow small{display:block;font-size:12px;font-weight:500;color:#b45a00}.crow.cur{background:#fff8ec;border-radius:6px}
.nowbox.stg{font-size:13px;line-height:1.25;padding:3px 10px;margin-bottom:4px}
.clk{display:grid;grid-template-columns:1fr 1fr;gap:5px}
.ax{text-align:center;font-size:12px;color:#5a6b8c}
.avg{font-size:12px;color:#3a3a3c;margin-bottom:5px}
.mod{border-radius:10px;padding:7px 8px 8px;margin-top:8px}
.mod.hist{background:#f2f6fd;border:1px solid #d6e1f6}.mod.alarm{background:#fff7ec;border:1px solid #f3d9b3}
.mt{font-size:13px;font-weight:700;margin-bottom:5px;display:flex;justify-content:space-between;align-items:center}
.mt .up{font-size:12px;font-weight:400;color:#6e6e73}
.mod.sum{background:#fafafb;border:1px solid #e3e3e8}.mod.sum .mt{color:#3a3a3c}
.qh{display:flex;justify-content:space-between;align-items:center;margin-top:6px;padding-top:6px;border-top:1px solid #e6e6ea;
 font-size:14px;font-weight:700}
.mod .qh:nth-child(2){border-top:none;margin-top:2px;padding-top:2px}
.qh span:first-child{color:#1d1d1f}
.qb{font-size:12px;font-weight:700;border-radius:6px;padding:2px 8px}
.ql{display:grid;grid-template-columns:64px 50px 1fr;gap:6px;align-items:center;font-size:12.5px;line-height:1.35;padding:2px 0}
.mod.sum .ql{padding:0}
.ql .f{color:#6e6e73}.ql .w{font-weight:700;border-radius:5px;text-align:center;padding:1px 0;font-size:12px}
.ql .x{color:#3a3a3c}
.mod.hist .mt{color:#1f4fbf}.mod.alarm .mt{color:#b45a00}
.mod .cell,.mod .sc.平{background:#fff}.mod .rrow{border-top-color:#e2e8f4}.mod .crow{border-top-color:#e2e8f4}
.sn{font-size:12px;color:#8a8a8e;line-height:1.35}
.cell .pn i{display:inline;margin-left:6px;font-style:normal;font-size:12px;font-weight:400;color:#8a8a8e}
.cell{border-radius:8px;padding:5px 9px 4px;background:#f7f7f9;position:relative}
.cell .pn{display:flex;justify-content:space-between;align-items:center;font-size:16px;font-weight:700;margin-bottom:1px}
.cell .pn .j{font-size:12px;font-weight:600;border-radius:6px;padding:1px 6px}
.cell .ln{font-size:13px;line-height:1.35;color:#3a3a3c;display:flex;justify-content:space-between;align-items:center}.cell .ln .j{font-size:12px;font-weight:600;border-radius:6px;padding:0 5px}.cell .ln b{font-size:15px;color:#1d1d1f}"""

e = html.escape


def tip(x):
    """悬停说明：挂在元素上，出图时量位置；空的不挂。"""
    return f' data-tip="{e(x)}"' if x else ""


def sources(key):
    """每页最下面的出处行：名字可点（data-link，菜单程序点了打开网页），悬停说明支撑哪句；定义见 defs.SOURCES。"""
    links = "".join(f'<a data-link="{e(u)}"{tip(t)}>{e(n)}↗</a>' for n, u, t in SOURCES.get(key, []))
    return f'<div class="src">出处：{links}<span>{SOURCE_TAIL}</span></div>' if links else ""


def page(h, body):
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS % (W, h)}</style></head><body><div class="wrap">{body}</div></body></html>'


def head(title, how, pending, sub=""):
    badge = f'<span class="warn">待复核 {pending} 处</span>' if pending else ""
    sub = f'<span class="sub">{e(sub)}</span>' if sub else ""
    return (f'<div class="top"><div><b>{e(title)}</b>{sub}</div><div class="right">{badge}'
            f'<span class="how"{tip(chr(10).join(how))}>怎么读<i>?</i></span></div></div>')


def so_box(x):
    """「对现在」：每张图最上面一句大白话（2026-11-18：正常人不被解释也能看懂）。"""
    return f'<div class="so {x.get("色", "")}"{tip(x["依据"])}>{e(x["字"])}</div>'


def spark(vals, alarm, alarm_below, w=150, h=36):
    """报警卡片上的小走势图：灰线＝每月的值，橙虚线＝报警线，浅橙底＝报警那一侧，黑点＝现在。只画程序给的数。"""
    lo, hi = min(min(vals), alarm), max(max(vals), alarm)
    pad = (hi - lo) * 0.12 or 0.1
    lo, hi = lo - pad, hi + pad

    def x(i):
        return 3 + i * (w - 7) / (len(vals) - 1)

    def y(v):
        return h - 2 - (v - lo) / (hi - lo) * (h - 4)

    ya = y(alarm)
    zone = (f'<rect x="0" y="{ya:.1f}" width="{w}" height="{h - ya:.1f}" fill="#fff1dc"/>' if alarm_below
            else f'<rect x="0" y="0" width="{w}" height="{ya:.1f}" fill="#fff1dc"/>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
    return (f'<svg class="sp" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{zone}'
            f'<line x1="0" x2="{w}" y1="{ya:.1f}" y2="{ya:.1f}" stroke="#f0a447" stroke-width="1.2" stroke-dasharray="3 3"/>'
            f'<polyline points="{pts}" fill="none" stroke="#6e6e73" stroke-width="1.6" stroke-linejoin="round"/>'
            f'<circle cx="{x(len(vals) - 1):.1f}" cy="{y(vals[-1]):.1f}" r="3" fill="#1d1d1f"/></svg>')


def board_main(g, pending):
    out = [head(g["标题"], g["怎么读"], pending, "统计" + g["历史更新"]), so_box(g["对现在"]), '<div class="grid"><div></div>']
    for c in g["列"]:
        now = ' now' if c["今年"] else ''
        tag = '<span class="tag">今年</span>' if c["今年"] else ''
        out.append(f'<div class="h{now}"{tip(c["依据"])}>{tag}<div class="y">{c["年"]}</div><div class="n">{e(c["周期"])}</div>'
                   f'<div class="m t{c["色"]}">{e(c["结论"])}</div></div>')
    for r in g["行"]:
        out.append(f'<div class="lab"{tip(r["依据"])}>{e(r["名称"])}</div>')
        for c in r["格子"]:
            out.append(f'<div class="c {c["色"]}"{tip(c["依据"])}>{e(c["字"])}<small>{e(c["数"])}</small></div>')
    out.append(f'</div><div class="tl"><div class="lab"{tip(g["时间线说明"])}>比特币</div><div class="track"><div class="line"></div>')
    for t in g["时间线"]:
        a, b = t["起"] * 100, t["止"] * 100
        mid = min(max((a + b) / 2, 15), 85)
        out.append(f'<div class="band b{t["色"]}" style="left:{a:.2f}%;width:{max(b - a, 0):.2f}%"></div>')
        cls = "up1" if t["上"] else "dn1"
        out.append(f'<div class="lb {cls}" style="left:{mid:.2f}%"{tip(t["依据"])}><b class="t{t["色"]}">{e(t["名"])}</b>'
                   f'<br>{e(t["字"])}</div>')
    out.append('</div></div>')
    if g["失效条件"]:
        f = g["失效条件"]
        out.append(f'<div class="box warnbox"{tip(f["依据"])}><b>失效条件：</b>{e(f["字"])}</div>')
    return "".join(out)


def board_next(b, pending):
    out = [head(b["标题"], b["怎么读"], pending, b["周期"] + " · 统计" + b["历史更新"]), so_box(b["对现在"]), '<div class="qgrid"><div></div>']
    out += [f'<div class="qh">{q}</div>' for q in ("一季度", "二季度", "三季度", "四季度")]
    for r in b["行"]:
        out.append(f'<div class="lab"{tip(r["依据"])}>{e(r["名称"])}</div>')
        for c in r["格子"]:
            out.append(f'<div class="c {c["色"]}"{tip(c["依据"])}>{e(c["字"])}<small>{e(c["数"])}</small></div>')
    low = b["低点"]
    color = "蓝" if low["判断"] == "有用" else "平"
    out.append(f'</div><div class="box {color}"{tip(low["依据"])}><b>{e(low["判断"])} · </b>{e(low["字"])}</div>')
    out.append('<div class="box warnbox"><b>要防</b>' + "".join(f'<div{tip(x["依据"])}>· {e(x["字"])}</div>' for x in b["风险"])
               + "</div>")
    return "".join(out)


def table(g):
    """「某件事之后历史上会怎样」表：发生概率（小字几次里几次）、平时、有没有用。利率周期、景气与衰退、比特币周期共用。"""
    h0, *hs = g["表头"]
    out = [f'<div class="rrow th"><div{tip(g["表头依据"])}>{e(h0)}</div>' + "".join(f"<div>{e(x)}</div>" for x in hs) + "</div>"]
    for r in g["行"]:
        out.append(f'<div class="rrow"{tip(r["依据"])}><div class="nm">{e(r["名"])}</div>'
                   f'<div class="v">{e(r["比例"])}<small>{times(r["之后"])}</small></div><div class="bs">{e(r["平时"])}</div>'
                   f'<div class="j {r["色"]}">{e(r["判断"])}</div></div>')
    return "".join(out)


def times(kn):
    """「6/8」写成「8 次里 6 次」：一眼看出是次数，不会当成涨幅。"""
    k, n = kn.split("/")
    return f"{e(n)} 次里 {e(k)} 次"


def mod(kind, title, inner, extra=""):
    """模块框：hist＝历史统计（蓝），alarm＝报警信号（橙）。2026-11-18：每个模块要有颜色区分。
    extra＝标题右边的小字：历史表写多久更新一次（2026-11-20「更新频次必须披露」）。"""
    return f'<div class="mod {kind}"><div class="mt"><span>{e(title)}</span>{extra}</div>{inner}</div>'


def upnote(g):
    """历史表标题右边的小字：这张表多久更新一次（数据里的「历史更新」）。"""
    return f'<span class="up">{e(g["历史更新"])}</span>'


def board_rates(g, pending):
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    out.append(f'<div class="nowbox"{tip(g["现在"]["依据"])}><b>现在：</b>{e(g["现在"]["字"])}</div>')
    rule = f'<div class="rule"{tip(g["一句话"]["依据"])}>{e(g["一句话"]["字"])}</div>'
    out.append(mod("hist", "历史统计", rule + table(g), upnote(g)))
    out.append(signal_cards(g["信号"]))
    return "".join(out)


def board_cycle(g, pending):
    """景气与衰退第一张：景气四阶段（增长 × 通胀，现在在哪一个）+ 两个报警卡片。"""
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    out.append(f'<div class="nowbox"{tip(g["现在"]["依据"])}><b>现在：</b>{e(g["现在"]["字"])}</div>')
    h = g["阶段说明"]
    cell = {c["名"]: c for c in g["阶段"]}

    def box(name):
        c = cell[name]
        mark = ' now' if name == g["现在"]["阶段"] else ""
        tag = '<span class="tag">现在</span>' if mark else ""
        lines = "".join(f'<div class="ln"><span>{e(a)} <b>{e(c[a])}</b></span><span class="j {c[a + "色"]}">{e(c[a + "判断"])}</span></div>'
                        for a in STAGE_ASSETS)
        return (f'<div class="cell{mark}"{tip(c["依据"])}>{tag}<div class="pn"><span>{e(name)}<i>{e(c["定义"])}</i></span></div>'
                f'{lines}</div>')
    clk = (f'<div class="avg"{tip(h["依据"])}>{e(h["平时"])}</div>'
           f'<div class="clk"><div class="ax">增长低于正常</div><div class="ax">增长高于正常</div>'
           f'{box("滞胀")}{box("过热")}{box("低迷")}{box("复苏")}</div>')
    out.append(mod("hist", h["字"], clk, upnote(g)))
    out.append(signal_cards(g["信号"]))
    return "".join(out)


def board_rules(g, pending):
    """「规律准不准」那一张：对现在、一句话、表格。几个题目共用。"""
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    rule = f'<div class="rule"{tip(g["一句话"]["依据"])}>{e(g["一句话"]["字"])}</div>'
    out.append(mod("hist", "历史统计", rule + table(g), upnote(g)))
    return "".join(out)


def board_btc(g, pending):
    """比特币周期第一张：每一轮的节奏表 + 两个报警卡片。"""
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    out.append(f'<div class="nowbox"{tip(g["现在"]["依据"])}><b>现在：</b>{e(g["现在"]["字"])}</div>')
    h0, *hs = g["表头"]
    rows = [f'<div class="crow th"><div{tip(g["表头依据"])}>{e(h0)}</div>' + "".join(f"<div>{e(x)}</div>" for x in hs) + "</div>"]
    for c in g["轮"]:
        flag = "" if c["完"] else "<small>还没完</small>"
        rows.append(f'<div class="crow{"" if c["完"] else " cur"}"{tip(c["依据"])}><div class="nm">{e(c["名"])}</div>'
                    f'<div>{e(c["减半后"])}</div><div>{e(c["倍数"])}</div><div>{e(c["最深"])}{flag}</div>'
                    f'<div>{e(c["见底"])}</div></div>')
    out.append(mod("hist", "历史统计 · 每一轮的节奏", "".join(rows), upnote(g)))
    out.append(signal_cards(g["信号"]))
    return "".join(out)


def board_gold(g, pending):
    """黄金第一张：跌超两成的每一轮 + 离历史最高的报警卡片。"""
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    out.append(f'<div class="nowbox"{tip(g["现在"]["依据"])}><b>现在：</b>{e(g["现在"]["字"])}</div>')
    h0, *hs = g["表头"]
    rows = [f'<div class="crow c4 th"><div{tip(g["表头依据"])}>{e(h0)}</div>' + "".join(f"<div>{e(x)}</div>" for x in hs) + "</div>"]
    for c in g["轮"]:
        flag = f"<small>{e(c['旗'])}</small>" if c["旗"] else ""
        rows.append(f'<div class="crow c4{"" if c["完"] else " cur"}"{tip(c["依据"])}><div class="nm">{e(c["名"])}{flag}</div>'
                    f'<div>{e(c["顶价"])}</div><div>{e(c["最深"])}</div><div>{e(c["回到最高"])}</div></div>')
    out.append(mod("hist", "历史统计 · 金价跌超两成的每一轮", "".join(rows), upnote(g)))
    out.append(signal_cards(g["信号"]))
    return "".join(out)


def board_oil_now(g, pending):
    """原油第一张：现在 + 报警卡片。"""
    return "".join([head(g["标题"], g["怎么读"], pending), so_box(g["对现在"]),
                    f'<div class="nowbox"{tip(g["现在"]["依据"])}><b>现在：</b>{e(g["现在"]["字"])}</div>',
                    signal_cards(g["信号"])])


def board_oil_hist(g, pending):
    """原油第二张：历次油价一年涨超五成，每一轮之后衰退、标普怎么走；今年这一轮标出来。"""
    out = [head(g["标题"], g["怎么读"], pending), so_box(g["对现在"])]
    h0, *hs = g["表头"]
    rows = [f'<div class="crow c4o th"><div{tip(g["表头依据"])}>{e(h0)}</div>' + "".join(f"<div>{e(x)}</div>" for x in hs) + "</div>"]
    for c in g["轮"] + ([dict(g["现在"], 旗="这一轮")] if g["现在"] else []):
        flag = f"<small>{e(c['旗'])}</small>" if c.get("旗") else ""
        rows.append(f'<div class="crow c4o{" cur" if c.get("旗") else ""}"{tip(c["依据"])}><div class="nm">{e(c["名"])}{flag}</div>'
                    f'<div>{e(c["新高"])}</div><div>{e(c["衰退"])}</div><div>{e(c["标普"])}</div></div>')
    out.append(mod("hist", "历史统计 · 油价涨超五成的每一轮", "".join(rows), upnote(g)))
    return "".join(out)


RES_CLS = {"看涨": "涨", "看跌": "跌", "风险高": "顶", "风险低": "蓝", "说不准": "平",
           "共振": "蓝", "打架": "顶", "单张": "浅蓝"}


def board_res(g, pending):
    """共振总表：每件事一段，标题行右边是合起来的词，下面每张图一行（图名、方向词、一句话）。"""
    out = [head(g["标题"], g["怎么读"], pending, g["副标题"]), so_box(g["对现在"]),
           f'<div class="nowbox stg"{tip(g["阶段"]["依据"])}>{e(g["阶段"]["字"])}</div>']
    body = []
    for q in g["事"]:
        body.append(f'<div class="qh"{tip(q["依据"])}><span>{e(q["名"])}</span>'
                    f'<span class="qb {RES_CLS[q["合起来"]]}">{e(q["合起来字"])}</span></div>')
        for o in q["看法"]:
            body.append(f'<div class="ql"{tip(o["依据"])}><span class="f">{e(o["图"])}</span>'
                        f'<span class="w {RES_CLS[o["向"]]}">{e(o["向"])}</span><span class="x">{e(o["字"])}</span></div>')
    out.append(mod("sum", "各件事 · 各图怎么看（悬停看依据）", "".join(body)))
    return "".join(out)


def signal_cards(signals, title="报警信号"):
    """报警卡片：值、箭头、最近两年小走势图、比上月比去年、离报警线多远。各题目共用。
    标题不写更新频率：各张卡的数据频率不同，每张卡左下写自己多久更新一次、右下写数据到哪天（2026-11-20）。"""
    out = ['<div class="sig">']
    for s in signals:
        out.append(f'<div class="sc {s["色"]}"{tip(s["依据"] + "；走势图从" + s["走势起"] + "起")}>'
                   f'<div class="sh"><span class="nm">{e(s["名"])}</span><span class="st t{s["色"]}">{e(s["状态"])}</span></div>'
                   f'<div class="sn">{e(s.get("说明", ""))}</div>'
                   f'<div class="sv">{e(s["值"])}<span class="ar t{s["箭头色"]}">{e(s["箭头"])}</span></div>'
                   + spark(s["走势"], s["报警线"], s["报警在下"]) +
                   f'<div class="sx"><span>{e(s["更新"])}</span><span>{e(s["截至"])}</span></div>'
                   f'<div class="sd">比上月 {e(s["比上月"])}</div><div class="sd">比去年 {e(s["比去年"])}</div>'
                   f'<div class="sd">{e(s["离报警"])}</div></div>')
    out.append("</div>")
    return mod("alarm", title, "".join(out))


def chrome():
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",):
        if os.path.exists(p):
            return p
    for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(n):
            return shutil.which(n)
    raise RuntimeError("找不到浏览器，没法出图")


MAX_H = 760   # 菜单里一张图最高 760 点，再高说明内容失控了（11-18 加模块色框、卡片说明后从 600 放宽到 720；11-19 每页加出处行再放宽 40）


PROBE = """<script>addEventListener('load',()=>{
const tips=[...document.querySelectorAll('[data-tip]')].map(el=>{const r=el.getBoundingClientRect();
 return {x:+r.left.toFixed(1),y:+r.top.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1),t:el.dataset.tip,l:el.dataset.link||''}});
const o=document.createElement('pre');o.id='probe';
o.textContent=JSON.stringify({h:Math.ceil(document.querySelector('.wrap').getBoundingClientRect().height),tips});
document.body.appendChild(o)})</script>"""


def measure(body, name=""):
    """按实际内容量出图的高度（不手填，内容多了也不会被截掉），并量出每块悬停说明的位置（单位＝菜单里的点）。"""
    probe = page(2000, body).replace("</body>", PROBE + "</body>")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "m.html"
        src.write_text(probe, encoding="utf-8")
        r = subprocess.run([chrome(), "--headless=new", f"--user-data-dir={tmp}/prof", "--disable-gpu", "--no-sandbox",
                            f"--window-size={W},2000", "--virtual-time-budget=3000", "--dump-dom", src.as_uri()],
                           capture_output=True, text=True, timeout=120)
    m = re.search(r'<pre id="probe">(.*?)</pre>', r.stdout, re.S)
    if not m:
        raise RuntimeError("量不出图的高度")
    got = json.loads(html.unescape(m.group(1)))
    h = got["h"] + 2
    # 云端（Linux 字体）比本机渲染高几点（11-20 实测 758→762，云端超限失败）：本机预览多留 10 点余量，免得本机过、云端挂
    if not 100 <= h <= (MAX_H if IN_CLOUD else MAX_H - 10):
        raise RuntimeError(f"{name} 图高 {h} 点，超出范围")
    tips = [{"x": x["x"], "y": x["y"], "w": x["w"], "h": x["h"], "字": x["t"]} | ({"链": x["l"]} if x["l"] else {})
            for x in got["tips"]]
    return h, tips


def shoot(html_text, h, out_png: Path):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "p.html"
        src.write_text(html_text, encoding="utf-8")
        shot = Path(tmp) / "out.png"
        subprocess.run([chrome(), "--headless=new", f"--user-data-dir={tmp}/prof", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", "--force-device-scale-factor=3", f"--window-size={W},{h}",
                        f"--screenshot={shot}", src.as_uri()], capture_output=True, timeout=120)
        if not shot.exists() or shot.stat().st_size < 10_000:
            raise RuntimeError(f"出图失败：{out_png.name}")
        shutil.move(str(shot), out_png)


def find_alarms(x):
    """显示内容里所有 报警=真 的信号（行情触发了报警线），菜单栏单列提醒；每张信号卡都要带「报警字」。"""
    if isinstance(x, dict):
        if x.get("报警") is True:
            yield x
        for v in x.values():
            yield from find_alarms(v)
    elif isinstance(x, list):
        for v in x:
            yield from find_alarms(v)


# 每个题目的出图函数：显示内容 + 本题待复核数 → {图片文件名: 网页正文}
def pages_board1(d, pending):
    return {"01 四年周期总表.png": board_main(d["总表"], pending),
            f"02 {d['明年']['标题']}.png": board_next(d["明年"], pending)}


def pages_board2(d, pending):
    return {"01 加息之后怎么走.png": board_rates(d["利率"], pending)}


def pages_xen(d, pending):
    import xen   # 置顶项目的版式在 xen.py 里，照用这里的标题、悬停说明和量图
    return xen.pages(d, pending)


def pages_board3(d, pending):
    return {"01 现在在景气哪个阶段.png": board_cycle(d["景气"], pending),
            "02 衰退信号准不准.png": board_rules(d["衰退"], pending)}


def pages_board4(d, pending):
    return {"01 比特币这一轮走到哪.png": board_btc(d["节奏"], pending),
            "02 比特币规律准不准.png": board_rules(d["规律"], pending)}


def pages_board5(d, pending):
    return {"01 黄金现在在哪.png": board_gold(d["现在"], pending),
            "02 黄金规律准不准.png": board_rules(d["规律"], pending)}


def pages_board6(d, pending):
    return {"01 原油现在在哪.png": board_oil_now(d["现在"], pending),
            "02 历次油价一年涨超五成.png": board_oil_hist(d["历次"], pending),
            "03 原油规律准不准.png": board_rules(d["规律"], pending)}


def pages_board7(d, pending):
    return {"01 金融状况紧不紧.png": board_rates(d["金融"], pending)}


def pages_board0(d, pending):
    return {"00 共振总表.png": board_res(d["现在"], pending)}


PAGES = {"board0": pages_board0, "board1": pages_board1, "board2": pages_board2, "board3": pages_board3, "board4": pages_board4,
         "board5": pages_board5, "board6": pages_board6, "board7": pages_board7, "xen": pages_xen}


def run():
    review = json.loads((ROOT / "results" / "review.json").read_text())
    cross = json.loads((ROOT / "results" / "crosscheck.json").read_text())
    BUILD.mkdir(exist_ok=True)
    for f in [*BUILD.glob("*.html"), *BUILD.glob("*.json")]:
        f.unlink()
    hashes = json.loads(HASHES.read_text()) if HASHES.exists() else {}
    made, asofs, alarms, pinned, latest = [], [], [], [], {}
    for t in TOPICS:
        data = json.loads((ROOT / "results" / f"{t['键']}.json").read_text())["显示"]
        if t.get("置顶"):   # 项目类有自己的断更判断（菜单程序看这两个日期），不拉低周期题目的「数据截至」
            pinned.append({"目录": t["目录"], "网站截至": data["网站截至"], "最近成功": data["最近成功"],
                           "失败": data["失败"]})
        elif data["数据截至"]:   # 只有月度和每周数据的题目（原油）不拉低「数据截至」，断更由验收的新鲜度检查拦
            asofs.append(data["数据截至"])
        # 菜单最上面的报警：每个响了报警的题目一条——报警字（信号卡自带，直接拼名字和状态会读成「比200周均线低于均线」）
        # + 那一页「对现在」的结论（2026-11-19「结论是啥」：菜单里直接写结论，不让人再点进去找）
        for pg in (v for v in data.values() if isinstance(v, dict)):
            hit = list(find_alarms(pg))
            if hit and "对现在" in pg:
                alarms.append({"报警": "；".join(s["报警字"] for s in hit),
                               "结论": pg["对现在"]["字"].removeprefix("对现在：")})
                break
        if t["目录"] and not t.get("置顶"):   # 菜单里每个题目第一行：最新数据到哪天
            latest[t["目录"]] = data.get("最新数据") or data["数据截至"]
        pending = sum(1 for c in review["变动"] if c["图"] == t["名"])
        board_dir = (ROOT / "看板" if IN_CLOUD else BUILD / "预览") / t["目录"]
        board_dir.mkdir(parents=True, exist_ok=True)
        pages = {}
        for name, body in PAGES[t["键"]](data, pending).items():
            body += sources(t["键"])
            h, tips = measure(body, name)
            pages[name] = (h, page(h, body), tips)
        for name, (h, text, tips) in pages.items():
            key = f"{t['目录']}/{name}"
            stem = name.removesuffix(".png")
            (BUILD / f"{t['键']}__{stem}.html").write_text(text, encoding="utf-8")
            # 悬停说明和图放在一起（同名 .json），菜单程序读它；内容不变时写出来也一样，不会多出提交
            tip_json = json.dumps({"宽": W, "高": h, "浮现": tips}, ensure_ascii=False, indent=1) + "\n"
            (BUILD / f"{t['键']}__{stem}.json").write_text(tip_json, encoding="utf-8")
            (board_dir / f"{stem}.json").write_text(tip_json, encoding="utf-8")
            digest = hashlib.sha256(text.encode()).hexdigest()
            if IN_CLOUD and hashes.get(key) == digest and (board_dir / name).exists():
                continue
            shoot(text, h, board_dir / name)
            if IN_CLOUD:
                hashes[key] = digest
        stems = {n.removesuffix(".png") for n in pages}
        for f in [*board_dir.glob("*.png"), *board_dir.glob("*.json")]:   # 清掉过期的图和说明（比如年份变了）
            if f.stem not in stems and f.name != STATUS.name:   # 共振总表放在根目录，和状态文件同一层，状态文件别删
                f.unlink()
                hashes.pop(f"{t['目录']}/{f.name}", None)
        made += [f"{t['目录']}/{n}".lstrip("/") for n in pages]
    if not IN_CLOUD:
        return made
    HASHES.write_text(json.dumps(hashes, ensure_ascii=False, indent=1))
    ok = all(c["通过"] for c in cross)
    # 数据截至取所有题目里最旧的那个：哪个题目断了更新，菜单栏都会报警
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))   # 北京时间，菜单里写「几月几日几点更新」
    STATUS.write_text(json.dumps({"数据截至": min(asofs), "第二来源核对通过": ok, "待复核": review["待复核数"],
                                  "更新": now.strftime("%Y-%m-%d %H:%M"), "最新数据": latest,
                                  "信号报警": alarms, "置顶": pinned, "数据清单": fetch.data_list(),
                                  "题目顺序": [t["目录"] for t in TOPICS if not t.get("置顶") and t["目录"]]},
                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return made


if __name__ == "__main__":
    print(run())
    sys.exit(0)
