"""自测「坏一处不拖垮全部」（11-24 加）：在临时副本里故意弄坏一处，看整次更新是不是照样成功、只有坏的那个题目回到上一版。

用法：.venv/bin/python -I pipeline/selftest.py      （约 20 分钟；不碰本目录：每一项都在临时副本里跑）
每一项写「通过 / 不通过」，全部通过退出码 0。改了 run_all / render / acceptance / fetch / crosscheck 的出错处理，必须跑一遍。
全程断网跑（第二来源、XEN 连不上外面），结果不随外部网站好坏变；「云端」几项按云端的方式出图、写状态文件。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")


def copy() -> Path:
    """临时副本：克隆本仓库（有提交历史，回到上一版靠它），再带上没进仓库的原始数据和本目录未提交的改动。"""
    top = Path(tempfile.mkdtemp(prefix="看板自测-"))
    TEMPS.append(top)
    d = top / "repo"
    subprocess.run(["git", "clone", "-q", "--local", str(ROOT), str(d)], check=True)
    shutil.copytree(ROOT / "data" / "raw", d / "data" / "raw")
    for sub in ("pipeline", "results"):   # 本目录里改了还没提交的程序一起带上，测的是现在这份
        shutil.copytree(ROOT / sub, d / sub, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=自测", "-c", "user.email=selftest@local",
                    "commit", "-q", "-m", "自测起点", "--allow-empty"], check=True)
    return d


NET_OFF = {"HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
           "HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "ALL_PROXY": "", "all_proxy": ""}
BOARDS = {"board0", "board1", "board2", "board3", "board4", "board5", "board6", "board7"}


def run(d: Path, env=None, cloud=False) -> tuple:
    e = {**os.environ, **NET_OFF, **(env or {})}
    e.pop("GITHUB_ACTIONS", None)
    if cloud:
        e["GITHUB_ACTIONS"] = "true"
    r = subprocess.run([PY, "-I", "pipeline/run_all.py", "--offline"], cwd=d, env=e, capture_output=True, text=True)
    broken = json.loads((d / "results" / "broken.json").read_text()) if (d / "results" / "broken.json").exists() else None
    return r.returncode, broken, r.stdout + r.stderr


def unchanged(d: Path, *paths: str) -> bool:
    return subprocess.run(["git", "-C", str(d), "diff", "--quiet", "HEAD", "--", *paths]).returncode == 0


def boards(broken) -> set:
    """回到上一版的周期题目（XEN、第二来源核对另算：断网时它们本来就取不到）"""
    return set(broken or {}) & BOARDS


def commit(d: Path, msg: str):
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=自测", "-c", "user.email=selftest@local",
                    "commit", "-q", "-m", msg, "--allow-empty"], check=True)


def patch(d: Path, rel: str, old: str, new: str):
    f = d / rel
    s = f.read_text()
    assert s.count(old) == 1, f"{rel} 里找不到要改的地方：{old[:40]}"
    f.write_text(s.replace(old, new))


LONG_TIP = '''


_real_build = build


def build():   # 自测加的：照常算完，再把第一条悬停说明加长到超字数
    _real_build()
    import json as _j
    from pathlib import Path as _P
    f = _P(__file__).resolve().parent.parent / "results" / "board7.json"
    d = _j.loads(f.read_text())

    def first(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "依据" and isinstance(v, str):
                    x[k] = v + "自测故意加长" * 12
                    return True
                if first(v):
                    return True
        elif isinstance(x, list):
            return any(first(v) for v in x)
        return False
    assert first(d["显示"])
    f.write_text(_j.dumps(d, ensure_ascii=False, indent=1))
'''

RESULTS = []
TEMPS = []   # 每一项的临时副本（约 20 兆一份），跑完删掉


def case(name, ok, out=""):
    RESULTS.append((name, ok))
    print(("通过  " if ok else "不通过") + name)
    if not ok:
        print(out[-2500:])


def main():
    # 1 正常（断网）：整次成功、没有题目出错；第二来源连不上＝「没核成」，不算「对不上」
    d = copy()
    rc, broken, out = run(d)
    cross = json.loads((d / "results" / "crosscheck.json").read_text())
    case("正常跑（断网）：整次成功、没有题目出错、第二来源连不上记「没核成」不记「对不上」",
         rc == 0 and boards(broken) == set() and any(c.get("没核成") for c in cross)
         and not any(c.get("通过") is False for c in cross), out)

    # 2 一个题目算不出（程序异常）：整次照样成功，只有它回到上一版
    d = copy()
    patch(d, "pipeline/board5.py", "def build():", "def build():\n    raise KeyError(24321)\n\n\ndef _build_off():")
    (d / "results" / "board5.json").write_text("{}")   # 先弄脏，看是不是真回到了上一版
    rc, broken, out = run(d)
    case("黄金算不出：整次成功、只有黄金回到上一版", rc == 0 and boards(broken) == {"board5"} and unchanged(d, "results/board5.json"), out)

    # 3 一条数据没下载到（网连不上）：用到它的题目回到上一版，别的照常；状态里写明这条数据这次没取到
    d = copy()
    (d / "data" / "raw" / "fred_DFII10.csv").unlink()
    rc, broken, out = run(d)
    src = json.loads((d / "data" / "sources.json").read_text())
    case("实际利率没下载到：整次成功、用到它的黄金回到上一版、来源登记写明这次失败",
         rc == 0 and "board5" in broken and "board1" not in broken and bool(src["dfii10"].get("这次失败")), out)

    # 4 出图出错（比如字多了超高）：只有它回到上一版
    d = copy()
    patch(d, "pipeline/render.py", '    data = json.loads((ROOT / "results" / f"{t[\'键\']}.json").read_text())["显示"]',
          '    data = json.loads((ROOT / "results" / f"{t[\'键\']}.json").read_text())["显示"]\n'
          '    if t["键"] == "board7":\n        raise RuntimeError("自测：图高超出范围")')
    rc, broken, out = run(d)
    case("金融状况出图出错：整次成功、只有金融状况回到上一版", rc == 0 and boards(broken) == {"board7"}, out)

    # 5 某个题目自己的验收不过：只有它回到上一版
    d = copy()
    patch(d, "pipeline/acceptance.py", "    with part(None):\n        check_disclosure()",
          "    with part('board6'):\n        check(False, '自测：故意不过')\n    with part(None):\n        check_disclosure()")
    rc, broken, out = run(d)
    case("原油验收不过：整次成功、只有原油回到上一版", rc == 0 and boards(broken) == {"board6"} and unchanged(d, "results/board6.json"), out)

    # 5b 数一变、某条悬停说明超字数（会随数据变的检查，11-24 前是全看板共用的）：只有它回到上一版
    d = copy()
    with open(d / "pipeline" / "board7.py", "a") as fh:
        fh.write(LONG_TIP)
    rc, broken, out = run(d)
    case("金融状况悬停说明超字数：整次成功、只有金融状况回到上一版",
         rc == 0 and boards(broken) == {"board7"} and broken["board7"].startswith("验收不过")
         and unchanged(d, "results/board7.json"), out)

    # 5c 共用检查里查到某个题目时程序出错（11-25 前算全看板的，整次失败）：只算那个题目
    d = copy()
    patch(d, "pipeline/acceptance.py", '        CUR[0] = t["键"]\n        d = json.loads(',
          '        CUR[0] = t["键"]\n        if t["键"] == "board6":\n            raise KeyError("自测")\n        d = json.loads(')
    rc, broken, out = run(d)
    case("共用检查里查原油时程序出错：整次成功、只有原油回到上一版", rc == 0 and boards(broken) == {"board6"}, out)

    # 5d 某个题目的结果缺页（验收一读就出错，11-25 前整次验收崩掉）：验收只记在它头上
    d = copy()
    subprocess.run([PY, "-I", "pipeline/run_all.py", "--offline"], cwd=d, env={**os.environ, **NET_OFF}, capture_output=True)
    f6 = d / "results" / "board6.json"
    j6 = json.loads(f6.read_text())
    del j6["显示"]["历次"]
    f6.write_text(json.dumps(j6, ensure_ascii=False))
    r = subprocess.run([PY, "-I", "-c", "import sys,json; sys.path.insert(0,'pipeline'); import acceptance; "
                        "print(json.dumps(acceptance.run(), ensure_ascii=False))"], cwd=d, capture_output=True, text=True)
    try:
        fails = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        fails = None
    case("原油结果缺页：验收不崩、只记在原油头上", bool(fails) and {k for k, _ in fails} == {"board6"}, r.stdout + r.stderr)

    # 6 全看板共用的检查不过：整次失败（不发布）
    d = copy()
    patch(d, "pipeline/acceptance.py", "    with part(None):\n        check_disclosure()",
          "    with part(None):\n        check(False, '自测：共用检查不过')\n    with part(None):\n        check_disclosure()")
    rc, broken, out = run(d)
    case("共用检查不过：整次失败（而且是因为这条检查，不是程序崩了）", rc == 1 and "自测：共用检查不过" in out, out)

    # 7 官方缺一个月（11-24 真事：一年前那个月物价没公布）：景气页照样算出阶段，不崩
    d = copy()
    f = d / "data" / "raw" / "fred_CPIAUCSL.csv"
    rows = f.read_text().splitlines()
    k = max(i for i, r in enumerate(rows) if r[:4].isdigit() and r.split(",")[1])
    rows[k - 12] = rows[k - 12].split(",")[0] + ","   # 最新一个月往前 12 个月挖空
    f.write_text("\n".join(rows) + "\n")
    rc, broken, out = run(d)
    case("物价缺一个月：整次成功、景气页没出错", rc == 0 and "board3" not in (broken or {}), out)

    # 7b 改了旧历史的判断（11-25 真事：标普日收盘只给最近 10 年，窗口一挪就被当成改了旧历史）
    d = copy()

    def fetch_off():
        subprocess.run([PY, "-I", "-c", "import sys; sys.path.insert(0, 'pipeline'); import fetch; fetch.fetch_all(offline=True)"],
                       cwd=d, check=True, capture_output=True)
        return json.loads((d / "data" / "sources.json").read_text())
    fetch_off()   # 先用本机已有的原始数据定一次基准
    f = d / "data" / "raw" / "fred_SP500.csv"
    rows = f.read_text().splitlines()
    f.write_text("\n".join(rows[:1] + rows[6:]) + "\n")   # 窗口往前挪：最早 5 天掉出去
    g = d / "data" / "raw" / "fred_GS10.csv"
    rows = g.read_text().splitlines()
    day, val = rows[5].split(",")
    rows[5] = f"{day},{float(val) + 1:.2f}"   # 1953 年的旧值被改
    g.write_text("\n".join(rows) + "\n")
    src = fetch_off()
    src2 = fetch_off()   # 下一班：报警不能自己消失（11-25 前只亮一班）
    subprocess.run([PY, "-I", "pipeline/fetch.py", "--ack"], cwd=d, check=True, capture_output=True)
    src3 = fetch_off()   # 有人核过：以现在的数据为新基准
    src4 = fetch_off()
    flags = [x["gs10"].get("旧历史被改") for x in (src, src2, src3, src4)]
    case("旧历史：标普窗口往前挪不报；长期利率改了旧值要报，下一班照样报，核过后不再报",
         src["sp500_daily"]["旧历史被改"] is not True and flags[:2] == [True, True] and flags[2] is not True
         and flags[3] is False, json.dumps({"标普": src["sp500_daily"].get("旧历史被改"), "长期利率四班": flags}, ensure_ascii=False))

    # 7c 下载限时：一个网站接上了却不回话（11-25 审查查出：原来能拖过云端时限，整班被掐、全部不更新）
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(50)   # 只接不答
    port = srv.getsockname()[1]
    code = ("import sys,time,json; sys.path.insert(0,'pipeline'); import fetch\n"
            "fetch.TIMEOUT, fetch.PER_TRY, fetch.BUDGET = 1, 2, 60\n"
            "t=time.monotonic(); why=[]\n"
            f"for i in range(6):\n"
            f"    try: fetch.http_get('http://127.0.0.1:{port}/x%d' % i)\n"
            "    except fetch.DownloadError as e: why.append(e.reason)\n"
            "a=time.monotonic()-t\n"
            "fetch.BUDGET=a+3\n"
            "try: fetch.http_get('http://localhost:9/y')\n"
            "except fetch.DownloadError as e: why.append(e.reason)\n"
            "print(json.dumps({'秒':round(a,1),'原因':why}, ensure_ascii=False))")
    r = subprocess.run([PY, "-I", "-c", code], cwd=ROOT, capture_output=True, text=True, env={**os.environ, "NO_PROXY": "*", "no_proxy": "*"})
    srv.close()
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    why = got.get("原因", [])
    case("下载限时：网站不回话，连着两条失败就跳过这个网站，总时间超了剩下的跳过",
         len(why) == 7 and why[0] == "网站超时" and why[2:6] == ["网站连不上，这次跳过"] * 4 and got.get("秒", 99) < 25
         and why[6] in ("下载总时间超了，这次跳过", "网站连不上"), r.stdout + r.stderr)

    # 8 云端：浏览器没了（所有题目都出不了图）：整次照样跑完、看板上的图一张没动、出图记账没动、状态文件逐个写明
    d = copy()
    patch(d, "pipeline/render.py", "def chrome():", 'def chrome():\n    raise RuntimeError("找不到浏览器，没法出图")\n\n\ndef _chrome_off():')
    rc, broken, out = run(d, cloud=True)
    st = json.loads((d / "看板" / "状态.json").read_text())
    case("云端浏览器没了：整次跑完、图一张没动、状态文件写明每个题目没更新",
         rc == 0 and boards(broken) == BOARDS and unchanged(d, "看板/黄金", "看板/00 共振总表.png", "results/render_hash.json")
         and len(st.get("出错", [])) >= len(BOARDS), out)

    # 9 云端：原油第二张图出不了（第一张已出过）：原油的图和出图记账都回到上一版；断网时第二来源「没核成」只进数据问题、不报红；
    #   上一班记的「云端失败」被这一班成功冲掉
    d = copy()
    hf = d / "results" / "render_hash.json"
    h = json.loads(hf.read_text())
    for k in [k for k in h if k.startswith("原油/")]:
        h[k] = "自测旧值"   # 上一版记账和现在内容不一样，第一张图一定会重出
    hf.write_text(json.dumps(h, ensure_ascii=False, indent=1))
    subprocess.run([PY, "-I", "pipeline/mark_failed.py", "自测"], cwd=d, check=True, capture_output=True)
    commit(d, "自测：上一版")
    patch(d, "pipeline/render.py", "def shoot(html_text, h, out_png: Path):",
          'def shoot(html_text, h, out_png: Path):\n    if out_png.name.startswith("02 历次"):\n        raise RuntimeError("自测：第二张图出不了")\n    _shoot(html_text, h, out_png)\n\n\ndef _shoot(html_text, h, out_png: Path):')
    rc, broken, out = run(d, cloud=True)
    st = json.loads((d / "看板" / "状态.json").read_text())
    h2 = json.loads(hf.read_text())
    case("云端原油第二张图出不了：原油的图和出图记账回到上一版，第二来源没核成不报红，上一班的云端失败消掉",
         rc == 0 and boards(broken) == {"board6"} and unchanged(d, "看板/原油")
         and all(v == "自测旧值" for k, v in h2.items() if k.startswith("原油/")) and any(k.startswith("原油/") for k in h2)
         and st.get("第二来源核对通过") is True and any("没核成" in x["问题"] for x in st.get("数据问题", []))
         and "云端失败" not in st and [x["题目"] for x in st.get("出错", []) if x["题目"] in ("原油",)] == ["原油"], out)

    # 10 云端那一班没跑成：状态文件记一笔、连着失败累计次数、别的内容不丢
    d = copy()
    before = json.loads((d / "看板" / "状态.json").read_text())
    for _ in range(2):
        subprocess.run([PY, "-I", "pipeline/mark_failed.py", "计算、出图、验收"], cwd=d, check=True, capture_output=True)
    after = json.loads((d / "看板" / "状态.json").read_text())
    case("云端没跑成记一笔：次数累计、原来的内容不丢",
         after.get("云端失败", {}).get("次数") == 2 and after["云端失败"]["环节"] == "计算、出图、验收"
         and {k: v for k, v in after.items() if k != "云端失败"} == {k: v for k, v in before.items() if k != "云端失败"})

    # 8 菜单提示的拼法：数据停太久、这次没取到，按每条数据自己的节奏
    sys.path.insert(0, str(ROOT / "pipeline"))
    import datetime as dt
    import fetch
    reg = {k: {"末日": "2026-11-19"} for k in fetch.SERIES}
    reg["nasdaq"]["这次失败"] = "网站连不上"
    probs = fetch.problems(reg, dt.date(2026, 11, 23))   # 周一：实际利率停在上周四，4 天，没超 7 天，不该报
    names = {p["名"] for p in probs}
    case("数据问题：周末晚贴的不报，没取到的报", "实际利率" not in names and any("这次没取到" in p["问题"] for p in probs))
    probs = fetch.problems(reg, dt.date(2026, 12, 1))
    case("数据问题：每天更新的停了 12 天要报", any(p["名"] == "实际利率" for p in probs))

    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} 项通过" + (f"；不通过：{'、'.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for t in TEMPS:
            shutil.rmtree(t, ignore_errors=True)
    sys.exit(code)
