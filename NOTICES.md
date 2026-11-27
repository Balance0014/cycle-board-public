# Third-party notices

The MIT license in `LICENSE` covers the author’s source code and original documentation only. It does not cover third-party data, third-party libraries, or calculated figures that a data provider’s own terms still restrict; those terms are in `DATA.md` and below.

The dependencies below are not MIT and are not vendored; install them from `requirements.txt`.

## xlrd 2.0.1

BSD license. Copyright (c) 2005–2018 Stephen John Machin and other contributors. Used only to read the Shiller `.xls` workbook after you download it. Upstream: https://github.com/python-excel/xlrd

## certifi 2026.10.23

Mozilla Public License 2.0. It ships the Mozilla CA certificate bundle used for HTTPS. Upstream: https://github.com/certifi/python-certifi

## Fonts and browser

Chart rendering shells out to a local Chrome or Chromium and uses fonts already installed on the machine (the stylesheet asks for PingFang SC, Noto Sans CJK, Noto Sans SC, then Microsoft YaHei). Those programs and fonts are not included here. Noto fonts are under the SIL Open Font License; install them from your OS packages if you redraw charts.
