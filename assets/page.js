/* Quarterly dashboard renderer.  All calculations and formatting stay in Python. */
(function () {
  'use strict';

  var D = window.DASH;
  if (!D) {
    document.body.innerHTML = '<p style="padding:40px">缺少 data/*.js</p>';
    return;
  }

  function el(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function set(id, value) { var node = el(id); if (node) node.textContent = value || ''; }
  function statusLabel(status) {
    return status === 'history_ready' ? '历史趋势已接入' : '最新季已接入 · 历史待补';
  }

  function navigation() {
    var R = window.ROSTER;
    if (!R) return '<nav class="nav" aria-label="公司导航"><a class="home" href="../">总览</a></nav>';
    var byGroup = {};
    R.items.forEach(function (item) {
      (byGroup[item.group] || (byGroup[item.group] = [])).push(item);
    });
    var html = '<nav class="quarter-nav" aria-label="公司导航"><a class="back" href="../">← 全部公司</a>' +
      '<label>切换公司 <select id="ticker-select" aria-label="切换公司">';
    R.groups.forEach(function (group) {
      html += '<optgroup label="' + esc(group.label) + '">';
      (byGroup[group.key] || []).forEach(function (item) {
        html += '<option value="' + esc(item.slug) + '"' +
          (item.slug === D.page.slug ? ' selected' : '') + '>' +
          esc(item.ticker + ' · ' + item.name) + '</option>';
      });
      html += '</optgroup>';
    });
    return html + '</select></label></nav>';
  }

  var head = el('head-slot');
  if (head) {
    head.innerHTML = navigation();
    var select = el('ticker-select');
    if (select) select.addEventListener('change', function () {
      window.location.href = '../' + select.value + '/';
    });
  }

  document.title = D.company.ticker + ' Quarterly Results';
  set('tracker', D.tracker);
  var meta = [
    D.latest.disclosed_period_label,
    D.latest.release_date ? '发布 ' + D.latest.release_date : '',
    statusLabel(D.latest.status)
  ].filter(Boolean).join(' · ');
  set('meta', meta);
  set('h1', D.title);
  set('sub', D.subtitle);
  set('headline', D.headline);
  if (D.brief) {
    el('brief').innerHTML = D.brief;
    el('brief').hidden = false;
  }

  function markScrollable(wrap, columns) {
    if (!wrap) return;
    window.requestAnimationFrame(function () {
      if (wrap.scrollWidth > wrap.clientWidth + 1) {
        wrap.classList.add('scrollable');
        wrap.setAttribute('data-cols', String(columns));
      }
    });
  }

  function tableHTML(title, headers, rows, extraClass) {
    var html = '<section class="card table-card ' + (extraClass || '') + '"><header><h3>' +
      esc(title) + '</h3></header><div class="tblwrap"><table><thead><tr>';
    headers.forEach(function (header) { html += '<th scope="col">' + esc(header) + '</th>'; });
    html += '</tr></thead><tbody>';
    rows.forEach(function (row) {
      html += '<tr>';
      headers.forEach(function (_, index) {
        var value = row[index];
        html += '<td>' + esc(value == null || value === '' ? '—' : value) + '</td>';
      });
      html += '</tr>';
    });
    return html + '</tbody></table></div></section>';
  }

  function summaryHTML(block, index) {
    var html = '<section class="card summary-card' + (block.id ? ' block-' + esc(block.id) : '') +
      '"><header><h3>Exhibit ' + (index + 1) + ': ' +
      esc(block.title) + '</h3><span class="frequency-chip">' +
      (block.frequency === 'semiannual' ? '半年频' : '季度') + '</span></header>' +
      '<div class="tblwrap"><table class="sum"><thead><tr><th scope="col">指标</th>';
    block.heads.forEach(function (header, headIndex) {
      html += '<th scope="col"' + (headIndex === block.sep ? ' class="sep"' : '') + '>' + esc(header) + '</th>';
    });
    html += '</tr></thead><tbody>';
    block.rows.forEach(function (row) {
      html += '<tr><td>' + esc(row.label) + '</td>';
      row.cells.forEach(function (cell, cellIndex) {
        html += '<td class="' + esc((cell.cls || '') + (cellIndex === block.sep ? ' sep' : '')) + '">' +
          esc(cell.v || '—') + (cell.status === 'derived' ? '<sup class="derived-mark">D</sup>' : '') + '</td>';
      });
      html += '</tr>';
    });
    return html + '</tbody></table></div><p class="src">' + D.source +
      (block.note ? '<br><b>Note:</b> ' + esc(block.note) : '') + '</p></section>';
  }

  var blocks = (D.summary && D.summary.blocks) || [];
  el('lead').innerHTML = blocks.map(summaryHTML).join('');
  Array.prototype.forEach.call(el('lead').querySelectorAll('.tblwrap'), function (wrap, index) {
    markScrollable(wrap, (blocks[index] ? blocks[index].heads.length + 1 : 0));
  });

  /* Layer 1: the fixed operating panel.  Groups are collapsible because the
     panel is deliberately exhaustive -- it answers "what did the last eight
     quarters look like", which is a scan, not a read. */
  function panelGroupHTML(group) {
    var html = '<details class="card panel-group"' + (group.open ? ' open' : '') +
      '><summary><h3>' + esc(group.title) + '</h3></summary>' +
      '<div class="tblwrap"><table class="sum"><thead><tr><th scope="col">指标</th>';
    group.heads.forEach(function (header, headIndex) {
      html += '<th scope="col"' + (headIndex === group.sep ? ' class="sep"' : '') + '>' +
        esc(header) + '</th>';
    });
    html += '</tr></thead><tbody>';
    group.rows.forEach(function (row) {
      html += '<tr><td>' + esc(row.label) + '</td>';
      row.cells.forEach(function (cell, cellIndex) {
        html += '<td class="' + esc((cell.cls || '') + (cellIndex === group.sep ? ' sep' : '')) + '">' +
          esc(cell.v || '—') + (cell.status === 'derived' ? '<sup class="derived-mark">D</sup>' : '') + '</td>';
      });
      html += '</tr>';
    });
    return html + '</tbody></table></div>' +
      (group.note ? '<p class="src"><b>Note:</b> ' + esc(group.note) + '</p>' : '') +
      '</details>';
  }

  if (D.panel) {
    el('panel').innerHTML = '<div class="section-head"><h2>' + esc(D.panel.title) + '</h2>' +
      (D.panel.description ? '<p>' + esc(D.panel.description) + '</p>' : '') + '</div>' +
      (D.panel.groups || []).map(panelGroupHTML).join('');
    Array.prototype.forEach.call(el('panel').querySelectorAll('.panel-group'), function (node, index) {
      var group = (D.panel.groups || [])[index] || {heads: []};
      var wrap = node.querySelector('.tblwrap');
      markScrollable(wrap, group.heads.length + 1);
      // A collapsed <details> measures zero width, so re-check on first open.
      node.addEventListener('toggle', function () {
        if (node.open) markScrollable(wrap, group.heads.length + 1);
      });
    });
  }

  if (D.guidance) {
    el('guidance').innerHTML = '<h2 class="section">Guidance / Outlook</h2>' +
      tableHTML(D.guidance.title, D.guidance.headers, D.guidance.rows, 'guidance-card') +
      '<p class="src">' + D.source + '<br><b>Note:</b> ' + esc(D.guidance.note || '') + '</p>';
    markScrollable(el('guidance').querySelector('.tblwrap'), D.guidance.headers.length);
  }

  var sectionsHost = el('sections');
  (D.sections || []).forEach(function (section) {
    var sectionNode = document.createElement('section');
    sectionNode.className = 'data-section';
    sectionNode.innerHTML = '<div class="section-head"><h2>' + esc(section.title) + '</h2>' +
      (section.description ? '<p>' + esc(section.description) + '</p>' : '') + '</div>' +
      '<div class="grid"></div>';
    sectionsHost.appendChild(sectionNode);
    var grid = sectionNode.querySelector('.grid');
    (section.exhibits || []).forEach(function (exhibit) {
      window.Exhibits.card(grid, exhibit, {
        source: D.source,
        xlabels: exhibit.xlabels || [],
        height: exhibit.height
      });
      if (exhibit.full) grid.lastElementChild.classList.add('wide');
    });
  });

  var tablesHost = el('tables');
  (D.tables || []).forEach(function (table) {
    var wrapper = document.createElement('div');
    wrapper.innerHTML = tableHTML('Exhibit ' + table.n + ': ' + table.title, table.headers, table.rows, 'appendix-card');
    var card = wrapper.firstElementChild;
    tablesHost.appendChild(card);
    markScrollable(card.querySelector('.tblwrap'), table.headers.length);
  });

  var sourceLinks = (D.source_links || []).map(function (item) {
    return '<li><a href="' + esc(item.url) + '" rel="noopener">' + esc(item.label) + '</a></li>';
  }).join('');
  el('sources').innerHTML = '<details><summary>来源与版本线索</summary>' +
    '<p><a href="' + esc(D.source_url) + '" rel="noopener">公司官方 IR / Quarterly Results</a></p>' +
    (sourceLinks ? '<p>本页图表使用的公开原件：</p><ul>' + sourceLinks + '</ul>' : '') +
    '<p>公开仓只保存重画后的数据图、简单派生值和官方链接，不复制本地 PDF、PPT 或 transcript。</p></details>';

  el('notes').innerHTML = (D.notes || []).map(function (note) {
    return '<li>' + esc(note) + '</li>';
  }).join('');
  el('foot').innerHTML = D.footer || '';
})();
