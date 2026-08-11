"""Shared HTML shell for quarterly-results company pages."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(relative: str) -> str:
    """``?v=<8 hex of the file's sha256>``, or ``''`` when it is not built yet.

    GitHub Pages serves everything with ``max-age=600`` and the shell used to
    link its payload by a bare path, so for ten minutes after a publish a
    returning reader kept the old ``data/<slug>.js`` and saw the previous
    version of the page -- or, worse, a mix, because the HTML and the payload
    expire independently. Keying the query on the content means a changed file
    is a changed URL the browser has to fetch, while an unchanged file keeps its
    URL and stays cached.

    The digest is a pure function of the file, so ``build/all.py && git status``
    stays the drift check. A build timestamp would have dirtied every page on
    every build, which is exactly what `write_js` refuses to do for payloads.
    """
    target = ROOT / relative
    if not target.exists():
        return ""
    return f"?v={hashlib.sha256(target.read_bytes()).hexdigest()[:8]}"


def render_shell(ticker: str, slug: str) -> str:
    """Return the static shell used by the common browser renderer.

    Call this **after** the page's payload has been written: the script tags
    carry that file's content hash, so rendering the shell first would stamp the
    previous build's digest and defeat the point.
    """
    roster_v = fingerprint("data/roster.js")
    payload_v = fingerprint(f"data/{slug}.js")
    charts_v = fingerprint("assets/charts.js")
    page_v = fingerprint("assets/page.js")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ticker} Quarterly Results</title>
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<div class="wrap"><div class="inner">
<div id="head-slot"></div>
<main>
<div class="masthead"><span class="tracker" id="tracker">—</span><span class="meta" id="meta">—</span></div>
<h1 id="h1">—</h1>
<p class="subtitle" id="sub">—</p>
<p class="headline" id="headline">—</p>
<div class="brief" id="brief" hidden></div>
<div id="lead"></div>
<div id="guidance"></div>
<div id="sections"></div>
<details class="appendix-drawer">
  <summary>数据核对表与历史原值</summary>
  <div id="tables"></div>
</details>
<div class="source-drawer" id="sources"></div>
<div class="prose"><h2>口径与方法说明</h2><ol id="notes"></ol></div>
</main>
<footer id="foot"></footer>
</div></div>
<script src="../data/roster.js{roster_v}"></script>
<script src="../data/{slug}.js{payload_v}"></script>
<script src="../assets/charts.js{charts_v}"></script>
<script src="../assets/page.js{page_v}"></script>
</body>
</html>
"""
