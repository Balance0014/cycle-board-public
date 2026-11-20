"""置顶项目「XEN 流通进度」（2026-11-18 定：项目放菜单最上面，和周期模型「图 N」分开）。

和图一、图二走同一条生产线（run_all.py 调 build()，render.py 出图，验收第 10 条查图上每个数字），区别只有三处：
1. 不走复核闸：表是固定模型对网站和链上数据的机械计算（口径已定），数据一变就更新，
   月份变了自动在「改动记录.md」记一笔；改模型或口径才算改结论。
2. 失败只标 XEN：网站或链上取不到、自检不过，保留上一次的表，在「失败」里写原因，不拖累图一、图二；
   菜单程序看「最近成功」和「网站截至」两个日期自己报警（断更规则写在 app/main.swift）。
3. 第二来源 = 两家历史节点读同一区块，读数必须完全一致（xen_model.fetch_chain）。
模型和口径在 xen_model.py；快照历史 data/xen_state.json 只由云端写。
"""
import datetime as dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xen_model as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "xen.json"
LOG = ROOT / "改动记录.md"
IN_CLOUD = os.environ.get("GITHUB_ACTIONS") == "true"
FOCUS = "2025-01-05"            # 对照用的一行（SOL 2025-01-05 的 81.64%）
FOCUS_NAME = "2025 年初"         # 这一行在「对现在」里的叫法
NAMES = {"cold": "最早", "neutral": "预计", "hot": "最晚"}   # 图上的叫法（2026-11-18 问「冷热什么意思」，换成不用解释的词）
SHOWN = {"中性": "预计", "区间": "最早～最晚"}                 # 行里两个月份格在图上的叫法（改动记录用）


def _check(cur):
    """XEN 自己的验收：任何一条不过，这次的新表不用，菜单上报 XEN 失败。"""
    fails = []
    num, den, off = M.basis(cur)
    p = num / den
    if not Decimal("0.5") < p < 1:
        fails.append(f"当前比例 {p:.4f} 不合理")
    if len(cur["chain"]["sources"]) < 2:
        fails.append("链上读数不足两家一致")
    if cur["verification"].get("daily_targets_available"):
        for day, b in cur["verification"]["target_brackets"].items():
            thr = Decimal(cur["thresholds_percent"][day]) / 100
            if b["before_tokens"] is None or b["crossing_tokens"] is None or not (
                    (b["before_tokens"] + off) / (den * M.T) < thr <= (b["crossing_tokens"] + off) / (den * M.T)):
                fails.append(f"{day} 达标日前后不夹住目标")
    dyn = cur.get("dynamic")
    if not dyn:
        fails.append("动态推演没出：" + cur.get("dynamic_error", "未知原因"))
        return fails
    first = dyn["scenarios"]["neutral"]["months"][0]
    if abs(Decimal(str(first[2])) - p) > Decimal("0.01"):
        fails.append(f"推演起点 {first[2]} 和当前比例 {p:.4f} 对不上")
    if not 3e6 <= dyn["calibration"]["per_position"] <= 3e7:
        fails.append(f"每仓奖励 {dyn['calibration']['per_position']:.0f} 超出合理范围")
    late = lambda m: "9999" if m == "十年内到不了" else m   # noqa: E731
    for key in NAMES:
        seq = [late(M.dynamic_label(cur, t, key)) for _, _, t in M.TARGETS]
        if seq != sorted(seq):
            fails.append(f"{NAMES[key]}情形比例越高月份反而越早")
    for _, _, t in M.TARGETS:
        c, n, h = (late(M.dynamic_label(cur, t, k)) for k in ("cold", "neutral", "hot"))
        if not c <= n <= h:
            fails.append(f"{t}% 冷、中性、热的先后不对")
    return fails


def ym(label):
    """「2028-10」→「2028 年 10 月」；不是日期的（十年内到不了）原样返回。"""
    if len(label) >= 7 and label[:4].isdigit() and label[4] == "-" and label[5:7].isdigit():
        return f"{label[:4]} 年 {int(label[5:7])} 月"
    return label


def month_ago(cur, snaps):
    """一个月前的比例（存档里离 30 天前最近、相差不超过 7 天的那份；没有就不报走势）。"""
    t = dt.datetime.fromisoformat(cur["fetched_at_utc"]) - dt.timedelta(days=30)
    old = [s for s in snaps if s.get("chain") and s.get("fetched_at_utc")]
    if not old:
        return None
    s = min(old, key=lambda s: abs(dt.datetime.fromisoformat(s["fetched_at_utc"]) - t))
    if abs(dt.datetime.fromisoformat(s["fetched_at_utc"]) - t) > dt.timedelta(days=7):
        return None
    n, d, _ = M.basis(s)
    return n / d


def display(cur, today, snaps=()):
    """菜单图上显示的全部内容（图上的每个字和数都从这里来）。
    2026-11-19「我需要直接结论，不要写长作文」：顶上一句结论 ≤50 字、悬停 ≤60 字、怎么读每条 ≤30 字（验收第 12 条卡）。"""
    num, den, _ = M.basis(cur)
    p = num / den
    sc = cur["dynamic"]["scenarios"]
    rates = {k: f"{sc[k]['ranks_per_day'] / 10000:.1f} 万" for k in NAMES}
    label = {k: {t: M.dynamic_label(cur, t, k) for _, _, t in M.TARGETS} for k in NAMES}
    rows, focus = [], None
    for sol_date, shown, t in M.TARGETS:
        fixed = M.target_result(cur, t)["label"]
        floor = f"；就算以后没人再开仓，也要 {ym(fixed)}" if ym(fixed) != fixed else ""
        row = {
            "日期": sol_date, "比例": shown + "%",
            "中性": label["neutral"][t],
            "区间": label["cold"][t] + "～" + label["hot"][t],
            "重点": sol_date == FOCUS,
            "依据": f"XEN 预计 {ym(label['neutral'][t])}到 {shown}%{floor}",
        }
        rows.append(row)
        if row["重点"]:
            focus = (sol_date, shown, t)
    ft = focus[2]
    when = ym(label["neutral"][ft])
    so = (f"对现在：XEN 约 {when}流通到 SOL {FOCUS_NAME}的比例（现在 {p * 100:.2f}%）" if when != label["neutral"][ft]
          else f"对现在：XEN 十年内流通不到 SOL {FOCUS_NAME}的比例（现在 {p * 100:.2f}%）")
    then = month_ago(cur, snaps)
    trend = (f"比一个月前 {'↑' if p >= then else '↓'}{abs(p - then) * 100:.2f} 个点" if then is not None else "")
    future = Decimal(cur["cards_T"]["future"])
    cold_year = sc["cold"]["label"][:4]
    return {
        "数据截至": today.isoformat(),
        "标题": "XEN 流通进度",
        "对现在": {"字": so,
                 "依据": f"照近一年开仓速度推算；开仓少最早 {ym(label['cold'][ft])}，开仓多最晚 {ym(label['hot'][ft])}",
                 "色": "平"},
        "现在": {"比例": f"{p * 100:.2f}%",
                 "走势": trend,
                 "字": f"已在链上 {num:.2f} 万亿，还会挖出 {future:.2f} 万亿",
                 "依据": (f"已在链上＝流通 {Decimal(cur['chain']['liquid_T']):.2f}＋质押 "
                        f"{Decimal(cur['chain']['staked_T']):.2f} 万亿，烧掉的不算；"
                        f"{len(cur['chain']['sources'])} 家节点读数一致")},
        "表头": ["SOL 日期", "流通比例", "XEN 预计", "最早～最晚"],
        "表头依据": "SOL 在这天流通到这个比例；XEN 预计哪个月到同一比例",
        "行": rows,
        "图例": f"以后每天新开仓位：最早 {rates['cold']} · 预计 {rates['neutral']} · 最晚 {rates['hot']} 个",
        "怎么读": [
            "流通比例：链上 XEN（含质押）÷ 将来总量",
            "烧掉的不算，和 SOL 流通比例同一算法",
            "预计：照近一年每天开仓速度推算",
            f"最早：开仓少，按 {cold_year} 年全年平均",
            "最晚：开仓多，按近一年最旺的月份",
            "网站隔几天重算一次，表跟着换；只报到月",
        ],
        "网站截至": M.source_time(cur["source_updated"]).date().isoformat(),
        "最近成功": today.isoformat(),
        "失败": None,
    }


def _plain(exc):
    """菜单上显示在菜单上的失败原因，一句人话；原文另存在明细里。"""
    s = str(exc)
    # 先认最具体的：「网站链上流通卡…」也含「链上」，11-20 被错报成节点的问题
    for key, words in (("流通卡", "网站自己的链上数和链上读数对不上，没收"),
                       ("不符", "网站的图和卡片数对不上，没收"), ("链上", "链上两家节点读数对不上或读不到"),
                       ("网络请求失败", "网站打不开"), ("更旧", "网站返回了更旧的数据"),
                       ("自检不过", "新算出的表没过自检"), ("页面卡片缺失", "网站改版了，读不到数")):
        if key in s:
            return words
    return "取数出错"


def _log_changes(old, new, today):
    """月份变了自动记一笔（不走复核闸，但并在「改动记录」里看得到）。"""
    lines = []
    for a, b in zip(old.get("行", []), new["行"]):
        for k in ("中性", "区间"):
            if a.get(k) != b[k]:
                lines.append(f"- XEN {b['比例']}（SOL {b['日期']} 的流通比例）{SHOWN[k]}：{a.get(k)} → {b[k]}")
    if not lines:
        return
    title = f"## {today.isoformat()} · XEN 表随网站新数据自动更新"
    head, _, rest = LOG.read_text().partition("\n## ") if LOG.exists() else ("# 看板改动记录\n", "", "")
    LOG.write_text(head.rstrip() + "\n\n" + "\n".join([title] + lines) + ("\n\n## " + rest if rest else "\n"))


def build():
    today = dt.datetime.now(dt.timezone.utc).date()
    old = json.loads(OUT.read_text()) if OUT.exists() else None
    if not M.STATE.is_file():
        # 公开版不附带 xen.pub 快照，也不去抓该站。保留已附带的结果表。
        print("XEN 跳过：没有本地快照，不访问 xen.pub")
        if old is None:
            raise FileNotFoundError("没有 data/xen_state.json，也没有已附带的 results/xen.json")
        result = old
        result["显示"]["失败"] = "没有本地快照，未做现场校准"
        result["明细"]["失败详情"] = f"{today.isoformat()} 未访问 xen.pub"
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        return result
    try:
        state = M.load_state()
        cur = M.sync(state["snapshots"])
        fails = _check(cur)
        if fails:
            raise ValueError("自检不过：" + "；".join(fails))
        disp = display(cur, today, state["snapshots"])
        # 每天都查一遍（顺路、免费，断更靠它发现），但只在网站重算了未来曲线时（「更新时间」变了，
        # 平时 2–6 天一次）才换表、存快照、记改动；其余日子用最后一份存档快照重新出图（数不动、历史不涨，
        # 改了图上的字当天就生效），「最近成功」写今天
        last = state["snapshots"][-1]
        fresh = cur["source_updated"] != last["source_updated"]
        if IN_CLOUD and (fresh or old is None):
            M.save(state, cur)
            if old:
                _log_changes(old["显示"], disp, today)
        if old and not fresh:
            got = dt.date.fromisoformat(last["fetched_at_utc"][:10])
            disp = dict(display(last, got, state["snapshots"]), 最近成功=today.isoformat())
        result = {"显示": disp, "明细": {
            "页面更新时间": cur["source_updated"], "链上": cur["chain"],
            "校准": cur["dynamic"]["calibration"], "放大系数": cur["dynamic"]["amp"],
            "固定总量的网站曲线": cur["results"]}}
    except Exception as exc:   # 失败只标 XEN，保留上一次的表
        print("XEN 本次失败：", exc)
        if old is None:          # 第一次上线就失败：用最后一份存档快照出表，日期照实写
            snaps = M.load_state()["snapshots"]
            last = snaps[-1]
            if not last.get("dynamic") or _check(last):
                raise
            got = dt.date.fromisoformat(last["fetched_at_utc"][:10])
            old = {"显示": display(last, got, snaps), "明细": {"页面更新时间": last["source_updated"], "链上": last["chain"]}}
        result = old
        result["显示"]["失败"] = _plain(exc)
        result["明细"]["失败详情"] = f"{today.isoformat()} {str(exc)[:300]}"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ── 出图（render.py 调用；这里只拼字，不写任何数字）────────────────────────
CSS = """<style>
.xnow{display:flex;align-items:baseline;gap:10px;background:#f4f4f6;border-radius:8px;padding:7px 10px;margin-bottom:8px}
.xnow b{font-size:24px;line-height:1.2}.xnow span{font-size:12px;color:#6e6e73;line-height:1.4}
.xnow em{font-style:normal;color:#3a3a3c;font-weight:600}
.xrow{display:grid;grid-template-columns:92px 58px 66px 1fr;gap:6px;align-items:center;padding:5px 6px;border-top:1px solid #efeff2;font-size:14px}
.xrow.th{font-size:12px;color:#8a8a8e;border-top:none;padding:0 6px 2px}
.xrow .r{text-align:right}.xrow .m{text-align:center;font-weight:700}.xrow .g{text-align:center;color:#6e6e73;font-size:13px}
.xrow.f{background:#f4f4f6;border-radius:8px;border-top-color:transparent;font-weight:700}.xrow.f .g{color:#3a3a3c}
.xleg{font-size:12px;color:#8a8a8e;margin-top:8px;line-height:1.5}
</style>"""


def pages(d, pending):
    import render as R   # 用看板同一套标题、悬停说明和转义，不另造
    out = [CSS, R.head(d["标题"], d["怎么读"], pending), R.so_box(d["对现在"])]
    n = d["现在"]
    trend = f'<em>{R.e(n["走势"])}</em><br>' if n.get("走势") else ""
    out.append(f'<div class="xnow"{R.tip(n["依据"])}><b>{R.e(n["比例"])}</b><span>{trend}{R.e(n["字"])}</span></div>')
    h = d["表头"]
    out.append(f'<div class="xrow th"{R.tip(d["表头依据"])}><div>{R.e(h[0])}</div><div class="r">{R.e(h[1])}</div>'
               f'<div class="m">{R.e(h[2])}</div><div class="g">{R.e(h[3])}</div></div>')
    for r in d["行"]:
        out.append(f'<div class="xrow{" f" if r["重点"] else ""}"{R.tip(r["依据"])}><div>{R.e(r["日期"])}</div>'
                   f'<div class="r">{R.e(r["比例"])}</div><div class="m">{R.e(r["中性"])}</div>'
                   f'<div class="g">{R.e(r["区间"])}</div></div>')
    out.append(f'<div class="xleg">{R.e(d["图例"])}</div>')
    return {"01 XEN 流通进度.png": "".join(out)}


if __name__ == "__main__":
    r = build()["显示"]
    print(r["现在"]["比例"], r["网站截至"], r["失败"] or "成功")
    for row in r["行"]:
        print(row["日期"], row["比例"], row["中性"], row["区间"])
