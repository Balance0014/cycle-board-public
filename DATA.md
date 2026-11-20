# 数据条款 / Data terms

代码许可证在 `LICENSE`（MIT，只覆盖作者的代码和作者写的说明）。本文件覆盖数据。两者不要混用。

The code license is `LICENSE` (MIT, author’s code and the author’s own docs only). This file is the data terms. Do not treat them as the same grant.

归档里没有各来源的原始文件（没有 FRED CSV、席勒 xls、Coin Metrics JSON、世界银行 xlsx、IMF XML，也没有 xen.pub 快照）。`pipeline/fetch.py` 的 `SERIES` 是给运行者自己下载用的。`data/sources.json` 只登记来源名称、地址、行数、日期范围和文件校验值，不是序列本身。

This archive does not contain the vendor files. `SERIES` in `pipeline/fetch.py` is how a user downloads them. `data/sources.json` records names, URLs, row counts, date ranges, and file hashes. It is not the series.

`results/` 和 `看板/` 是作者算出的统计和画出的图，保留下来是为了让看板能直接看、直接对照。它们不是把原始库再发布一遍。某一格如果直接使用了 Coin Metrics 的价格，那一格仍然受下面的 CC BY-NC 约束。

`results/` and `看板/` are the author’s statistics and charts, kept so the board can be read and compared. They are not a re-publication of the source databases. A cell that quotes a Coin Metrics price remains under CC BY-NC below.

## 各来源 / Sources

| 序列 | 来源 | 归档里有没有原始文件 | 再发布 | 引用 |
|---|---|---|---|---|
| 联邦基金利率、国债、衰退月份、萨姆规则、活动指数、物价、原油（FRED 转载的公开序列）、实际利率、金融状况指数 | FRED，圣路易斯联储 | 没有，请自己下载 | 视每条序列在 FRED 页面上的版权标记而定。公开领域或「引用即可」的，引用原始机构和 FRED。标成需事先许可的，FRED 不能代为许可 | 例如 “Source: Board of Governors via FRED” |
| 纳斯达克综合、标普 500 日线、穆迪 Baa | 纳斯达克、标普道琼斯、穆迪，经 FRED 转发 | 没有 | FRED 条款把这类标成第三方版权。超出个人或教学使用，需要权利人书面许可。本归档不提供这份许可，也不附带这些原始序列 | 见各序列 FRED 页面的 Notes |
| 标普月均（1871 年起） | 罗伯特·席勒，https://shillerdata.com/ | 没有。工作簿由程序临时下载 | 审阅到的材料没有授予再发布 `ie_data.xls` 的明确许可，所以不附带文件。作者自己的周期统计和图予以保留，并注明出处 | Robert J. Shiller, Yale University, Irrational Exuberance data |
| 比特币、以太坊日参考价和出块数 | Coin Metrics 社区数据 | 没有原始 JSON。结果和图里引用到的价格数字予以保留 | 社区数据为 CC BY-NC 4.0：可以在非商业前提下复制和分享，必须署名，不能把 MIT 套到这些数字上，不能当成商品单独出售 | “Source: Coin Metrics Community Data, CC BY-NC 4.0” https://creativecommons.org/licenses/by-nc/4.0/ |
| 伦敦金月均，以及原油的第二来源 | 世界银行大宗商品粉单 | 没有 | 世界银行数据集默认 CC BY 4.0，另有其数据使用附加条款。粉单可以在署名后再发布；本归档仍不附带文件，因为地址按月变化，且运行时现取即可 | “The World Bank: Commodity Markets (Pink Sheet)” https://www.worldbank.org/en/research/commodity-markets |
| 金价第二来源 | IMF 初级商品价格 | 没有 | IMF 对它自己发布的统计数据允许在准确署名的前提下下载、派生和分发。第三方嵌入的数据另算 | “Source: International Monetary Fund” https://www.imf.org/en/about/copyright-and-terms |
| 美国国债日收益率（只用于核对） | 美国财政部 | 不保存 | 核对时现取 | U.S. Department of the Treasury |
| 币价第二来源（只用于核对） | Coinbase 公开日线 | 不保存 | 核对时现取。交易所条款以 Coinbase 当时的页面为准 | Coinbase Exchange public candles |
| XEN 供应曲线和开仓曲线 | xen.pub | **不附带** `data/xen_state.json` | xen.pub 声明网站上的提取数据和数据集表示归其所有，并禁止未经授权的抓取（https://xen.pub/privacy.php ）。因此快照不进入公开归档 | 页面：https://xen.pub/xen-supply.php |
| XEN 链上流通和质押 | 公共以太坊节点，合约 `0x06450dee7fd2fb8e39061434babcfc05599a6fb8` | 结果表里保留作者自己读到的汇总数，不保留整段曲线 | 合约代码由 FairCrypto 以 MIT 发布（https://github.com/FairCrypto/XEN-crypto ）。链上状态是公开账本。这不构成 xen.pub 对其整理数据集的许可 | 合约地址如上 |

`per_position`（每仓奖励）是协议发行量校准：一段窗口里，网站未来曲线新增的代币除以同期新增的公开开仓排名，不是任何人的持仓、成交或成本。公开版不附带算出它的那批页面快照。

`per_position` is a protocol issuance calibration: tokens added to the public future curve in a window, divided by the public mint-rank increase in that window. It is not a person’s holdings, trades, or cost basis. The page snapshots used to compute it are not included.

## 运行者要自己遵守的限制 / What the person running it must respect

- 不要把密钥、账号或本地绝对路径写进仓库。本程序的下载地址都不带密钥。
- FRED 条款禁止破坏性抓取，并限制把 FRED 内容用于训练机器学习模型。本程序按序列少量下载 CSV，不是把 FRED 做成镜像。
- Coin Metrics 社区接口有频率限制（文档写的是约 10 次 / 6 秒）。派生数字若再分享，保持非商业和署名。
- xen.pub 禁止未经授权的抓取。本版的 `run_all.py` 在没有本地快照时直接跳过，不请求 xen.pub。周期题目不受影响。XEN 页停在归档中的上一张表，并注明未做现场校准。取数函数仍在代码里，供阅读口径；不要把它当成可以忽略该站条款的许可。
- 不要声称圣路易斯联储、席勒、Coin Metrics、世界银行、IMF、财政部、Coinbase 或 xen.pub 认可本项目的结论。

Do not commit credentials or absolute home paths. FRED forbids disruptive scraping and restricts use of FRED content to train machine-learning models. This program downloads individual CSVs; it is not a FRED mirror. Coin Metrics community rate limits apply, and reshared figures stay non-commercial with attribution. xen.pub forbids unauthorized scraping. `run_all.py` skips XEN when no local snapshot is present and does not request xen.pub. The fetch functions remain in the source so the method can be read; they are not permission to ignore that site’s terms. The other boards do not depend on XEN. Do not imply endorsement by any source.

## 合成夹具 / Synthetic fixture

`demo/synthetic.py` 是标明的假曲线，只被 `tests/test_public_smoke.py` 用来检查周期算术。它不是市场数据，流水线不会用它代替 `data/raw/`。

`demo/synthetic.py` is a labeled fake curve used only by `tests/test_public_smoke.py` to check cycle arithmetic. It is not market data, and the pipeline will not substitute it for `data/raw/`.
