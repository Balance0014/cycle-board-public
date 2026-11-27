# 经济周期结论看板 / Cycle Board

公开维护身份 / Public identity: [Balance0014](https://github.com/Balance0014) · [X](https://x.com/balance0014)

这是一套可运行的经济与加密周期统计看板，写给关注宏观和加密市场的人。它用公开的宏观、利率、商品和加密货币历史，计算「现在落在哪一格、历史上这种格子之后更常发生什么」，并出中文图。代码、口径、已算好的结论和图都在这个归档里。原始第三方数据文件不在归档里，程序会在你自己运行时去各来源下载。

This is a working economic and crypto cycle dashboard for people who track macro and crypto markets. It uses public macro, rate, commodity, and crypto history to compute where the present sits in a cycle and what has happened more often after similar episodes, then draws Chinese charts. The code, definitions, calculated results, and charts are in this archive. Vendor data files are not bundled; the program downloads them when you run it.

## 不是投资建议 / Not investment advice

这里的「涨」「跌」「有用」只表示历史样本里发生过的次数，不是对未来收益的承诺，也不是买卖建议。样本会改、指数会修订、有的序列很短。不要用它下单。

“Up”, “down”, and “useful” only describe how often something happened in a historical sample. They are not a promise of future returns and not a recommendation to buy or sell. Samples change, indexes are revised, and some series are short. Do not trade on this.

## 安装 / Install

需要 Python 3.11 或更新版本，以及能出图的 Chrome / Chromium。中文图建议安装 Noto CJK 或文泉驿字体。

Python 3.11+ and Chrome or Chromium. For Chinese glyphs, install Noto CJK or WenQuanYi.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

依赖版本钉在 `requirements.txt`（`xlrd` 读席勒的 `.xls`，`certifi` 提供证书）。第三方库的许可证见 `NOTICES.md`，不在 MIT 范围里。

Pinned in `requirements.txt`. `xlrd` reads Shiller’s `.xls`; `certifi` supplies CA certificates. Their licenses are in `NOTICES.md` and are not MIT.

## 归档里有什么 / What ships

不联网就能看：

- `results/`：已经算好的结论，含已认可版 `results/approved/`
- `看板/`：15 张图和同名悬停说明
- `data/sources.json`：来源名称、地址、行数、日期范围和校验值，不是价格序列本身
- `改动记录.md`

不在归档里，所以不能靠这份压缩包离线重算：

- `data/raw/`：FRED、席勒、Coin Metrics、世界银行、IMF 的原始文件
- `data/xen_state.json`：xen.pub 页面快照

You can read the shipped results and charts with no network. You cannot recompute them from this archive alone. `data/sources.json` is a registry, not the price files. Raw vendor files and xen.pub snapshots are not included.

## 重新计算 / Recompute from public sources

在线重算按 `pipeline/fetch.py` 逐条下载公开序列，再用美国财政部日收益率和 Coinbase 公开日线做第二来源核对。不使用密钥。这一步不访问 xen.pub。先读 `DATA.md`。

A live recompute downloads the public series and checks Treasury and Coinbase. It uses no API key and does not contact xen.pub. Read `DATA.md` first.

```bash
.venv/bin/python -I pipeline/run_all.py
```

顺序：下载 → 第二来源核对 → 计算 → 和已认可版对比 → 出图 → 验收。本机只把预览图写到 `build/预览/`，不改归档里的 `看板/`。只有设置了 `GITHUB_ACTIONS=true` 才改 `看板/`。

Order: download, second-source check, calculate, compare with the approved snapshot, draw, accept. A local run writes previews under `build/预览/` and leaves the shipped `看板/` charts in place. `看板/` is updated only when `GITHUB_ACTIONS=true`.

`--offline` 只使用已经放在 `data/raw/` 里的文件，不会改为去下载。缺哪条文件，就记哪条「这次没取到」，用到它的题目保留上一版，别的照常算：

```bash
.venv/bin/python -I pipeline/run_all.py --offline
```

`--offline` reads `data/raw/` only and never downloads. A missing file is recorded as not fetched; boards that need it keep their previous version and the rest are recomputed.

这不是从空目录把 XEN 动态校准再跑一遍。XEN 现场校准依赖未附带的 xen.pub 快照；本版不抓该站。运行后周期题目可以按新下载的数据重算，XEN 保留已附带的结果表，并注明没有做现场校准。

This is not a claim that every number is reproducible from an empty directory. Cycle boards can be recomputed from the public downloads. XEN’s live calibration cannot: the snapshots are omitted, the program does not fetch xen.pub, and the shipped XEN table stays, marked as not recalibrated.

## 坏一处只标一处 / One failure stays local

一条数据没下载到、一个网站不回话、一个题目算不出或出不了图、或它自己的验收没过：只有这个题目保留上一版的结果和图，别的题目照常更新。哪个题目、什么原因、从哪天起，写进 `results/broken.json` 和 `看板/状态.json` 的「出错」。只有全看板共用的检查没过，整次才算失败。

- 下载有时限（`pipeline/fetch.py` 的 `TIMEOUT` `PER_TRY` `BUDGET` `HOST_FAILS`）：同一个网站连着两条失败就这次不再连它，所有下载加起来最多 8 分钟。
- 第二来源每一项单独核：对方连不上或没给数记「没核成」，不算「对不上」。
- 数据按自己的公布节奏停太久（`fetch.MAX_AGE`）、来源改了旧历史，写进「数据问题」，不拦别的题目。来源改了旧历史会一直报到有人核过：`.venv/bin/python -I pipeline/fetch.py --ack`。官方定期重算旧值的序列在 `SERIES` 里标 `"会重估": True`，不报。

A missing download, a silent host, or a board that fails to build, draw, or pass its own checks only freezes that board at its previous version. Everything else updates. Only a shared check fails the whole run. Downloads are time-boxed; each second-source check runs on its own and records “not checked” instead of “mismatch” when the other side is down. Stale series and revised history are reported in `状态.json` without blocking other boards.

故意弄坏一处的自测（约 20 分钟，全程断网，在临时副本里跑，不改本目录；要先在线跑过一次，`data/raw/` 里有原始文件）：

Fault-injection self-test (about 20 minutes, offline, in temporary clones; needs `data/raw/` from one online run first):

```bash
.venv/bin/python -I pipeline/selftest.py
```

## 可选合成自检 / Optional synthetic check

不下载、不改 `results/`、不改 `看板/`：

```bash
.venv/bin/python -I tests/test_public_smoke.py
```

`demo/synthetic.py` 里的曲线标明是合成的，只给测试用。`run_all.py` 不会读它，它也不代替任何真实序列。

`demo/synthetic.py` is labeled synthetic and is for tests only. `run_all.py` does not read it, and it does not replace any real series.

## 复核 / Review

```bash
.venv/bin/python -I pipeline/review.py
.venv/bin/python -I pipeline/review.py --approve "40 字内标题" "细节"
```

不写说明不能认可。认可会在 `改动记录.md` 最上面追加一条。

A blank approval is rejected. Approval prepends an entry to `改动记录.md`.

## macOS 菜单栏 / macOS menu bar

仅 macOS，需要 Swift 编译器。`bash app/build_app.sh` 会把应用装到 `$HOME/Applications/美国四年周期.app`，并安装一个登录时打开的 LaunchAgent。程序崩了会被系统重新拉起；手动退出后不会被拉起。菜单读取的目录是 `$HOME/Library/Application Support/经济周期看板-菜单副本`（把本归档克隆到那里，并设置你自己的 git remote）。程序按 remote 执行 `git fetch` 和 `git reset --hard origin/main`，不会内置仓库地址或凭证。

macOS only. `bash app/build_app.sh` installs `$HOME/Applications/美国四年周期.app` and a login item. A crash is restarted; quitting stays quit. The menu reads `$HOME/Library/Application Support/经济周期看板-菜单副本`. Clone this archive there and set your own git remote. The app runs `git fetch` and `git reset --hard origin/main` against that remote. No repo URL or credential is embedded.

菜单栏图标自己报警，只读 `看板/状态.json` 和今天的日期，不靠外部服务：

- 红＋⚠︎：自动更新超过 2 天没成功；某个题目连着 2 天保留上一版；本机 2 天同步不下来（红字写明是本机）；第二来源真核了对不上。
- 橙＋⚠︎：某个题目这一班保留上一版；某条数据停太久、这次没取到、第二来源没核成、来源改了旧历史；云端某一班没跑成；有结论待复核。
- 橙、不加 ⚠︎：行情报警（比如比特币跌破 200 周均线），下拉直接写结论。

Red: no successful update for 2 days, a board frozen for 2 days, local sync failing for 2 days, or a real second-source mismatch. Orange with ⚠︎: a board frozen this run, a data problem, a failed cloud run, or pending review. Orange without ⚠︎: a market signal.

## 维护手册 / Maintenance

菜单下拉最后一行写着「跟维护助手说……」，照下面对应的情况查。原因写在 `看板/状态.json` 的「出错」「数据问题」「云端失败」；完整报错在 Actions 运行日志里搜「⚠︎」。

**情况一：红。** 看 `gh run list --workflow daily.yml -L 5`，失败的那次 `gh run view 运行编号 --log-failed`。「本机已 N 天没同步下来」：在菜单副本目录里 `git fetch origin main` 看报错（网络或登录）。「某题目已 N 天没更新」：照情况二查它。第二来源对不上：看 `results/crosscheck.json`，先查是不是对方改了旧历史，别放宽阈值。

**情况二：橙，某题目没更新 / 某数据有问题。** 「这次没取到」只出现一班不用管，连着几天多半是来源改了网址或格式，改 `pipeline/fetch.py` 的 `SERIES` 那一条。「停在某天」先去来源页面看是不是真没发新数。「算不出（缺数）」是来源缺某月某天，改那个题目的程序跳过并写明，不许补数。「出不了图」多半是页面超高，缩短文字。「来源改了旧数据」核过后 `.venv/bin/python -I pipeline/fetch.py --ack` 并提交 `data/sources.json`。「第二来源没核成」只出现一班不用管。「云端某一班没跑成」照情况一看日志。

**情况三：有结论待复核。** 见上面「复核」。

**情况四：XEN 没更新。** 公开版不抓 xen.pub，XEN 停在归档里的表，属正常。

改了出错处理（`run_all`、`render`、`acceptance`、`fetch`、`crosscheck`）要跑自测，全部通过才算。不许为了过验收放松检查或手填数字。

When the menu says to ask the maintainer, match the case above: red (check Actions logs or local sync), orange (fix the one source or board named), review pending, or XEN (frozen by design in the public archive). Run the self-test after changing error handling.

## 工作流默认关闭 / Workflow is off

`.github/workflows/daily.yml` 只有 `workflow_dispatch`。定时任务被注释掉了，fork 之后不会自己每天跑、也不会自己提交。要启用，打开该文件里的 `schedule` 注释（两班，第二班是备份）。整班没跑成时，最后一步在 `看板/状态.json` 记一笔「云端失败」，菜单马上提示。工作流使用仓库自带的 `GITHUB_TOKEN`，文件里没有密钥。

`.github/workflows/daily.yml` is `workflow_dispatch` only. The schedule is commented out, so a fork does not run or commit daily. Uncomment `schedule` to enable it (two slots; the second is a backup). A failed run records 「云端失败」 in `看板/状态.json` so the menu shows it at once. The workflow uses the repository `GITHUB_TOKEN`. No secret is stored in the file.

## 口径 / Definitions

中文口径、词表、验收和题目说明在 `METHODOLOGY.md`。改口径要改 `pipeline/defs.py`，并走复核。

Chinese definitions, the word list, acceptance rules, and topic notes are in `METHODOLOGY.md`. Changing definitions means editing `pipeline/defs.py` and passing review.

## 许可证 / License

作者自己的代码用 MIT，见 `LICENSE`。数据条款、出处限制和第三方库声明分开，见 `DATA.md` 和 `NOTICES.md`。MIT 不覆盖数据，也不表示任何来源为本项目背书。

The author’s code is MIT, see `LICENSE`. Data terms and third-party notices are separate, in `DATA.md` and `NOTICES.md`. MIT does not cover data and does not mean any source endorses this project.

## 局限 / Limits

- 规律要过 `pipeline/defs.py` 里的 `EDGE` 才上板；过不了的只留在明细。
- 月均价和当天价不是同一个数。金、油的表是月均。
- 金融状况指数的历史每周会重估，回测带有后见之明。
- 比特币、XEN 的样本短，很多格子不给概率。
- XEN 动态校准依赖 xen.pub 的逐日快照。公开版不附带这些快照，也不请求 xen.pub。已附带的 XEN 图是发布时算好的那一张，不能在没有快照时重新校准。见 `DATA.md`。

A pattern is shown only if it clears `EDGE` in `pipeline/defs.py`. Monthly average prices are not daily prices. The financial-conditions index is revised, so backtests peek. Bitcoin and XEN samples are short. XEN live calibration is unavailable in this edition: xen.pub snapshots are not bundled and are not fetched. The shipped XEN chart is the published table.

---

**More from [Balance Zhao](https://github.com/Balance0014):** [Post-quantum blockchain map](https://github.com/Balance0014/post-quantum-blockchains) (open for submissions) · [claim-check](https://github.com/Balance0014/claude-code-claim-check) · [when-to-clear](https://github.com/Balance0014/claude-code-when-to-clear) · [one-person-ai-company](https://github.com/Balance0014/one-person-ai-company) · [telegram-rug-checker](https://github.com/Balance0014/telegram-rug-checker)
