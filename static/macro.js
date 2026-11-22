// Economic data panel for the Votes & speeches tab: actual vs expected for each monthly release.
// Bars = actual; the dark tick = expected (Cleveland Fed nowcast for inflation, recent trend for jobs).
// Bar colour = surprise direction: hawkish (hotter inflation, stronger jobs) vs dovish.
window.Macro = (() => {
  const SERIES = [
    ["core_cpi", "Core CPI", "% m/m", 2], ["cpi", "CPI", "% m/m", 2], ["core_pce", "Core PCE", "% m/m", 2],
    ["payrolls", "Payrolls", "k jobs", 0], ["unemployment", "Unemployment rate", "%", 1], ["wages", "Hourly earnings", "% m/m", 2],
  ];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const mon = p => MON[+p.slice(5) - 1] + (p.slice(5) === "01" ? " " + p.slice(2, 4) : "");
  const TOL = {payrolls: 15, unemployment: 0.05};  // smaller surprises count as "in line"

  // +1 hawkish surprise, -1 dovish, 0 in line / unknown
  function surprise(id, r) {
    if (r.actual == null || r.expected == null) return 0;
    const d = r.actual - r.expected, tol = TOL[id] ?? 0.03;
    if (Math.abs(d) <= tol) return 0;
    return (id === "unemployment" ? -d : d) > 0 ? 1 : -1;
  }

  function chart(id, label, unit, dp, rows) {
    const W = 340, H = 150, L = 38, R = 8, T = 10, B = 22;
    const vals = rows.flatMap(r => [r.actual, r.expected]).filter(v => v != null);
    if (!vals.length) return "";
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (id === "unemployment") { lo = Math.min(...vals) - 0.2; hi = Math.max(...vals) + 0.2; }
    const pad = (hi - lo) * 0.08 || 0.1; hi += pad; if (lo < 0) lo -= pad;
    const ys = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
    const bw = (W - L - R) / rows.length, base = id === "unemployment" ? lo : 0;
    const ticks = [lo, (lo + hi) / 2, hi].map(v => +v.toFixed(dp));
    const axis = ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${ys(v)}" y2="${ys(v)}" class="gl"/><text x="${L - 4}" y="${ys(v) + 3}" text-anchor="end">${v}</text>`).join("")
      + (lo < 0 ? `<line x1="${L}" x2="${W - R}" y1="${ys(0)}" y2="${ys(0)}" class="zero"/>` : "");
    const marks = rows.map((r, i) => {
      const x = L + i * bw, cx = x + bw / 2, s = surprise(id, r);
      const tip = `${label} ${mon(r.period)} ${r.period.slice(0, 4)}: ` + (r.actual != null ? `actual ${r.actual.toFixed(dp)}` : "not released yet")
        + (r.expected != null ? `, expected ${r.expected.toFixed(dp)} (${r.expected_kind === "nowcast" ? "Cleveland Fed nowcast" : id === "unemployment" ? "previous month" : "3-month trend"})` : "")
        + (s ? ` — ${s > 0 ? "hawkish" : "dovish"} surprise` : "") + (r.release_date ? `; released ${r.release_date}` : "");
      const bar = r.actual == null ? "" : (() => {
        const y0 = ys(base), y1 = ys(r.actual), top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
        return `<rect x="${x + bw * 0.18}" y="${top}" width="${bw * 0.64}" height="${h}" rx="2" class="bar ${s > 0 ? "hawk" : s < 0 ? "dove" : "flat"}"/>`;
      })();
      const exp = r.expected == null ? "" : `<line x1="${x + bw * 0.08}" x2="${x + bw * 0.92}" y1="${ys(r.expected)}" y2="${ys(r.expected)}" class="exp${r.actual == null ? " pending" : ""}"/>`;
      return `${bar}${exp}<text x="${cx}" y="${H - 6}" text-anchor="middle">${mon(r.period)}</text>
        <rect x="${x}" y="${T}" width="${bw}" height="${H - T - B}" class="hit" data-tip="${esc(tip)}"/>`;
    }).join("");
    const last = [...rows].reverse().find(r => r.actual != null);
    const head = last ? `${last.actual.toFixed(dp)}${unit.startsWith("%") ? "%" : unit === "k jobs" ? "k" : ""} <span class="muted">${mon(last.period)}${last.expected != null ? `, exp. ${last.expected.toFixed(dp)}` : ""}</span>` : "";
    return `<div class="mchart"><div class="mhead"><b>${esc(label)}</b> <span class="muted small">${esc(unit)}</span><span class="mlast">${head}</span></div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)} actual vs expected">${axis}${marks}</svg></div>`;
  }

  function section(S) {
    const rows = S.macro || [];
    if (!rows.length) return `<div class="panel muted">No economic data yet. Press <b>Load</b> to fetch it.</div>`;
    const by = {};
    rows.forEach(r => (by[r.series] ||= []).push(r));
    const charts = SERIES.map(([id, label, unit, dp]) => by[id] ? chart(id, label, unit, dp, by[id].sort((a, b) => a.period < b.period ? -1 : 1)) : "").join("");
    setTimeout(() => document.querySelectorAll(".mcharts .hit").forEach(h => {
      h.onmouseenter = () => { const t = $("#mtip"); t.textContent = h.dataset.tip; t.hidden = false; };
      h.onmouseleave = () => $("#mtip").hidden = true;
    }));
    return `<div class="mlegend small"><span><i class="sw hawk"></i>hotter / stronger than expected (hawkish)</span>
      <span><i class="sw dove"></i>cooler / weaker (dovish)</span><span><i class="sw flat"></i>in line</span>
      <span><i class="tick"></i>expected</span></div>
      <div class="mcharts">${charts}</div>
      <div id="mtip" class="muted small" hidden></div>
      <div class="muted small" style="margin-top:6px">Expected: for CPI and PCE, the Cleveland Fed's inflation nowcast just before release; for jobs there is no free consensus, so it is the 3-month trend (unemployment: previous month). Jobs figures are as revised today.</div>`;
  }

  const css = document.createElement("style");
  css.textContent = `
    .mcharts { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
    .mchart { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px 4px; }
    .mhead { display: flex; gap: 8px; align-items: baseline; font-size: 13.5px; }
    .mlast { margin-left: auto; font-variant-numeric: tabular-nums; font-size: 13px; }
    .mchart svg { width: 100%; height: auto; display: block; }
    .mchart text { fill: var(--muted); font-size: 10px; }
    .mchart .gl { stroke: var(--line); } .mchart .zero { stroke: var(--muted); }
    .mchart .bar.hawk, .sw.hawk { fill: var(--hawk); background: var(--hawk); }
    .mchart .bar.dove, .sw.dove { fill: var(--dove); background: var(--dove); }
    .mchart .bar.flat, .sw.flat { fill: var(--hold); background: var(--hold); }
    .mchart .exp { stroke: var(--ink); stroke-width: 2; } .mchart .exp.pending { stroke-dasharray: 3 2; }
    .mchart .hit { fill: transparent; }
    .mlegend { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; color: var(--muted); }
    .mlegend .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
    .mlegend .tick { display: inline-block; width: 14px; height: 2px; background: var(--ink); margin-right: 5px; vertical-align: 3px; }`;
  document.head.appendChild(css);
  return {section};
})();
