"""Shared HTML shell for quarterly-results company pages."""

from __future__ import annotations


def render_shell(ticker: str, slug: str) -> str:
    """Return the static shell used by the common browser renderer."""
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
<script src="../data/roster.js"></script>
<script src="../data/{slug}.js"></script>
<script src="../assets/charts.js"></script>
<script src="../assets/page.js"></script>
</body>
</html>
"""
