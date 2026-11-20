#!/usr/bin/env python3
"""Offline smoke test for the public edition.

Does not download, does not call vendor or chain APIs, and does not modify
results/ or 看板/. A labeled synthetic curve exercises cycle math. Shipped
results are only read, to prove the real chart HTML still builds.
"""
import datetime as dt
import importlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "demo"))

PUBLIC_XEN = "0x06450dee7fd2fb8e39061434babcfc05599a6fb8"
TEXT_EXT = {".py", ".md", ".swift", ".yml", ".txt", ".json", ".sh"}
SECRET_RES = [
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("bearer", re.compile(r"(?i)bearer [A-Za-z0-9._-]{12,}")),
]


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" " + detail) if detail else ""))
    if not ok:
        raise SystemExit(1)


def test_layout():
    check("no git dir", not (ROOT / ".git").exists())
    check("xen snapshot absent", not (ROOT / "data" / "xen_state.json").exists())
    check("raw vendor dir absent", not (ROOT / "data" / "raw").exists())
    check("sources registry present", (ROOT / "data" / "sources.json").is_file())
    check("charts present", len(list((ROOT / "看板").rglob("*.png"))) == 15)
    yml = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    active = [ln for ln in yml.splitlines() if ln.strip() == "schedule:" or ln.strip().startswith("- cron:")]
    check("schedule not active", active == [])


def test_definitions():
    import defs as K
    import board1
    import synthetic

    check("election 2024", K.election_day(2024) == dt.date(2024, 11, 5))
    check("election 2020", K.election_day(2020) == dt.date(2020, 11, 3))
    check("cycle year 2024", K.cycle_year(2024) == 0)
    check("label strong up", K.direction_label(8, 10) == "涨")
    check("label lean up", K.direction_label(6, 10) == "偏涨")
    check("label flat", K.direction_label(5, 10) == "不稳")
    series = board1.Series(synthetic.monthly(), monthly=True)
    stats = board1.cycle_stats(series, dt.date(2026, 1, 15))
    check("synthetic cycles populated", all(stats[c]["n"] >= 10 for c in range(4)))
    # 1978→1979 stays on the rising half of the wobble, so the synthetic year is up.
    check("synthetic year return", board1.year_return(series, 1979) > 0)
    check("synthetic complete years", len(board1.complete_years(series, dt.date(2026, 1, 15))) > 40)
    check("fixture is labeled", "SYNTHETIC" in Path(synthetic.__file__).read_text(encoding="utf-8"))


def test_imports_and_calibration_meaning():
    import inspect
    import xen_model
    for name in (
        "acceptance", "board0", "board1", "board2", "board3", "board4", "board5",
        "board6", "board7", "crosscheck", "defs", "fetch", "render", "review",
        "run_all", "topics", "xen", "xen_model",
    ):
        importlib.import_module(name)
    src = inspect.getsource(xen_model.calibrate)
    check("per_position is issuance over new ranks", "registered / ranks_added" in src and "per_position" in src)


def test_real_results_render_html():
    import render
    pages = {
        "board0": render.pages_board0,
        "board1": render.pages_board1,
        "board2": render.pages_board2,
        "board3": render.pages_board3,
        "board4": render.pages_board4,
        "board5": render.pages_board5,
        "board6": render.pages_board6,
        "board7": render.pages_board7,
    }
    made = 0
    for key, fn in pages.items():
        data = json.loads((ROOT / "results" / f"{key}.json").read_text(encoding="utf-8"))["显示"]
        for name, body in fn(data, 0).items():
            html = render.page(800, body + render.sources(key))
            check(f"html {key} {name}", len(html) > 500 and "data-tip" in html)
            made += 1
    xen = json.loads((ROOT / "results" / "xen.json").read_text(encoding="utf-8"))
    check("xen display kept", "对现在" in xen["显示"] and xen["显示"]["行"])
    check("real pages rendered", made == 14)


def test_one_screenshot():
    """Draw one shipped page with the same Chrome flags as render.shoot.

    In this sandbox Chrome writes the PNG and then waits on DBus, so the
    process is killed after the file appears. Exit code is not required.
    """
    import render
    data = json.loads((ROOT / "results" / "board0.json").read_text(encoding="utf-8"))["显示"]
    body = next(iter(render.pages_board0(data, 0).values()))
    html = render.page(800, body + render.sources("board0"))
    tmp = Path(tempfile.mkdtemp(prefix="cycle-board-smoke-"))
    src = tmp / "page.html"
    out = tmp / "page.png"
    src.write_text(html, encoding="utf-8")
    cmd = [render.chrome(), "--headless=new", f"--user-data-dir={tmp}/prof", "--disable-gpu",
           "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=3",
           "--window-size=400,800", f"--screenshot={out}", src.as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=40)
    except subprocess.TimeoutExpired:
        pass
    ok = out.exists() and out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and out.stat().st_size > 8000
    check("chrome screenshot of shipped page", ok, str(out.stat().st_size if out.exists() else 0))


def test_text_hygiene():
    bad_marks = ("老板", "开发项目", "Codex/XEN", "x-access-token")
    mark_hits = {mark: [] for mark in bad_marks}
    secret_hits = {name: 0 for name, _ in SECRET_RES}
    eth_other = 0
    emails = 0
    files = 0
    email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.(?:com|org|net|io|edu|gov|cn|uk)\b")
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_EXT:
            continue
        if any(part in {".venv", "__pycache__", "build"} for part in path.parts):
            continue
        files += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        # This test names the markers it searches for, so skip itself.
        if path.name != "test_public_smoke.py":
            for mark in bad_marks:
                if mark in text:
                    mark_hits[mark].append(str(path.relative_to(ROOT)))
        for name, cre in SECRET_RES:
            secret_hits[name] += len(cre.findall(text))
        for addr in re.findall(r"0x[a-fA-F0-9]{40}", text):
            if addr.lower() != PUBLIC_XEN.lower():
                eth_other += 1
        emails += sum(
            1 for e in email_re.findall(text)
            if not e.lower().endswith("@users.noreply.github.com")
        )
    for mark, paths in mark_hits.items():
        check(f"no marker {mark}", paths == [], f"files={len(paths)}")
    for name, n in secret_hits.items():
        check(f"secret {name}", n == 0, f"count={n}")
    check("no other eth address", eth_other == 0, f"count={eth_other}")
    check("no mailbox in text", emails == 0, f"count={emails} files={files}")
    # workflow identity is the public GitHub Actions bot, which is allowed
    yml = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    check("actions bot identity only", "github-actions[bot]" in yml)


def main():
    test_layout()
    test_definitions()
    test_imports_and_calibration_meaning()
    test_real_results_render_html()
    test_one_screenshot()
    test_text_hygiene()
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
