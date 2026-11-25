"""一键全流程（本地和云端都只跑这一个）：下载 → 第二来源核对 → 计算 → 复核对比 → 出图 → 验收。

用法：python pipeline/run_all.py            正常更新
      python pipeline/run_all.py --offline  不下载，用已有数据（调试用）

坏一处不拖垮全部（11-24 起）：
- 一条数据没下载到：记下原因，接着下别的（fetch.fetch_all）；
- 一个题目算不出、出不了图、或它自己的验收不过：这个题目回到上一版（上一次发布的结果和图），别的题目照常更新；
  出错的题目和原因写进 results/broken.json 和状态.json「出错」（带从哪天起），菜单橙色提示；
- 只有全看板共用的检查不过，整次更新才算失败（云端发邮件，菜单按「几天没更新成功」报红）。
自测：python pipeline/selftest.py（故意弄坏一条数据、一个题目，看别的是不是照常更新）。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib  # noqa: E402

import acceptance  # noqa: E402
import crosscheck  # noqa: E402
import fetch  # noqa: E402
import render  # noqa: E402
import review  # noqa: E402
from topics import TOPICS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BROKEN = ROOT / "results" / "broken.json"
BY_KEY = {t["键"]: t for t in TOPICS}


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def restore(key: str):
    """题目回到上一版：结果和图都取仓库里最后一次提交的（云端＝上一次发布的）；这一班新写出的图（比如换了名字的）删掉。
    共振总表的图在看板根目录、和状态文件同一层（11-25 查出原来没还原它）。"""
    t = BY_KEY[key]
    if t["目录"]:
        paths = [f"看板/{t['目录']}"]
        git("clean", "-fq", "--", paths[0])
    else:
        mine = lambda p: "/" not in p.removeprefix("看板/") and p != "看板/状态.json"   # noqa: E731
        paths = [p for p in git("ls-tree", "-z", "--name-only", "HEAD", "看板/").split("\0") if p and mine(p)]
        for p in git("ls-files", "-z", "--others", "--", "看板/").split("\0"):
            if p and mine(p):
                (ROOT / p).unlink(missing_ok=True)
    for p in [f"results/{key}.json"] + paths:
        git("checkout", "-q", "HEAD", "--", p)


def restore_hashes(broken: dict):
    """回到上一版的题目，出图记账（哪张图按什么内容出的）也回到上一版。
    11-25 查出：不还原的话，记账说「新图出过了」、实际图是旧的，下一班内容没变就不重出，旧图会一直挂着。"""
    if not (render.IN_CLOUD and render.HASHES.exists()):
        return
    try:
        head = json.loads(git("show", "HEAD:results/render_hash.json") or "{}")
    except ValueError:
        head = {}
    cur = json.loads(render.HASHES.read_text())
    for key in broken:   # 原地改，不打乱顺序（不然每次有题目回到上一版，这个文件都白白多一处改动）
        if key in BY_KEY:
            pre = f"{BY_KEY[key]['目录']}/"
            for k in [k for k in cur if k.startswith(pre) and k not in head]:
                del cur[k]
            for k, v in head.items():
                if k.startswith(pre):
                    cur[k] = v
    render.HASHES.write_text(json.dumps(cur, ensure_ascii=False, indent=1))


def build(key: str, broken: dict):
    try:
        importlib.import_module(key).build()
    except Exception as e:  # noqa: BLE001  一个题目出错只影响它自己
        broken[key] = fetch.short_reason(e)
        print(f"⚠︎ {BY_KEY[key]['名']} 算不出，回到上一版：{e!r}")
        restore(key)


def main():
    offline = "--offline" in sys.argv
    broken = {}   # 题目键 → 出错原因（给菜单看的短句）
    src = fetch.fetch_all(offline=offline)
    print("数据：", "；".join(f"{v['名称']} 到 {v.get('末日', '没有')}" + ("（这次没取到）" if v.get("这次失败") else "")
                           for v in src.values()))
    try:
        cross = crosscheck.run()
        print("第二来源核对：", "；".join(c["项目"] + {True: "通过", False: "不通过"}.get(c["通过"], "没核成") for c in cross))
    except Exception as e:  # noqa: BLE001  核对程序本身出错：留着上一次的核对结果，菜单「出错」里写明
        print("⚠︎ 第二来源核对没跑成：", repr(e))
        broken["crosscheck"] = fetch.short_reason(e)
    for t in TOPICS:
        build(t["键"], broken)
    fails = []
    for _ in range(len(TOPICS)):   # 每一轮都可能多出回到上一版的题目，最多每个题目一轮
        before = set(broken)
        try:
            print("待复核：", len(review.diff()), "处")
        except Exception as e:  # noqa: BLE001  复核对比本身出错：沿用上一次的对比结果，菜单「出错」里写明
            print("⚠︎ 复核对比没跑成：", repr(e))
            broken["review"] = fetch.short_reason(e)
        print("出图：", len(render.run(broken)), "张")
        fails = acceptance.run(skip=set(broken))
        for key, msg in fails:
            if key and key not in broken:
                broken[key] = "验收不过：" + msg[:30]
                print(f"⚠︎ {BY_KEY[key]['名']} 验收不过，回到上一版：{msg}")
        new = set(broken) - before
        if not new:
            break
        for key in new:
            if key in BY_KEY:
                restore(key)
        if "board0" not in broken:   # 共振总表由各题目拼成，有题目回到上一版就重拼
            build("board0", broken)
    for key in broken:   # 最后再还原一次：出图出错的题目在后面几轮里可能又被写了一半
        if key in BY_KEY:
            restore(key)
    restore_hashes(broken)
    BROKEN.write_text(json.dumps(broken, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fails = [m for k, m in fails if k is None]
    if fails:
        print("验收不通过：\n" + "\n".join(fails))
        return 1
    print("验收通过" + (f"（回到上一版：{'、'.join(BY_KEY[k]['名'] if k in BY_KEY else k for k in broken)}）" if broken else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
