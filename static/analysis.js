// Analysis tab: hawkishness gauge, next-meeting tally, member table, 6-month path.
// Uses $, esc, fmtDate, shortDate, fmtDuration and store from index.html.
window.Analysis = (() => {
  let A = null, model = store.get("model"), open = null, tick = null, started = false;
  const f1 = x => x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(1);
  const CALL = {hike: "Hike", hold: "Hold", cut: "Cut"};
  const monthName = m => new Date(m + "-15T12:00:00").toLocaleDateString("en-US", {month: "short"});

  // diverging fill for a stance (-5 dove .. +5 hawk); text stays in ink
  const fill = s => s == null ? "transparent"
    : `color-mix(in oklab, var(${s >= 0 ? "--hawk" : "--dove"}) ${Math.round(Math.min(Math.abs(s) / 5, 1) * 70)}%, var(--mid))`;

  async function load() {
    A = await (await fetch("/api/analysis?model=" + encodeURIComponent(model || ""))).json();
    if (A.error) { $("#ana").innerHTML = `<div class="banner">${esc(A.error)}</div>`; return; }
    model = A.model;
    $("#model").innerHTML = A.models.map(m => `<option ${m === model ? "selected" : ""}>${esc(m)}</option>`).join("");
    render();
    if (A.run.running && !tick) poll();
    else if (!A.run.running) $("#alog").textContent = A.run.log.join("\n");
    status();
  }

  function status() {
    if (tick) return;
    const r = A.last_run, t = $("#atimer");
    t.className = "muted";
    t.textContent = (r ? `Last run ${r.finished_at.replace("T", " ").slice(0, 16)} · ${A.prompt_version} · ${r.calls} call${r.calls === 1 ? "" : "s"} · took ${fmtDuration(r.duration_s)}`
                       : "Not run yet with this model") + (A.daily_limit ? ` · ${A.calls_today}/${A.daily_limit} calls today` : " · needs your OK for paid credits")
                     + (A.fallback ? ` (+ ${A.fallback.model}: ${A.fallback.calls_today}/${A.fallback.daily_limit})` : "");
  }

  function gaugeBar(g) {
    const pct = Math.max(0, Math.min(100, g * 10));
    return `<div class="gbar"><div class="gtrack"></div><div class="gmid"></div><div class="gpin" style="left:${pct}%"></div></div>
      <div class="gends muted"><span>0 dovish</span><span>5 hold</span><span>10 hawkish</span></div>`;
  }

  function render() {
    const R = A.reading;
    if (!R) {
      $("#ana").innerHTML = `<div class="empty">No analysis with ${esc(model)} yet. Press <b>Run analysis</b>.</div>`;
      return;
    }
    const ctx = R.context, nm = ctx.next_meeting;
    const nmLabel = nm ? new Date(nm + "T12:00:00").toLocaleDateString("en-US", {month: "short"}) : "Next";
    const t = R.tally;
    const chg = R.gauge_change;
    const pending = R.pending_docs ? `<div class="banner">${R.pending_docs} document${R.pending_docs === 1 ? "" : "s"} in this window ${R.pending_docs === 1 ? "is" : "are"} not scored yet${A.calls_today >= A.daily_limit ? " (today's call limit is used up; run again after midnight Pacific)" : ""}. Members without a scored document use their earlier scores until then.</div>` : "";
    const snap = A.snapshot ? `<div class="snap muted">Going into the ${fmtDate(A.snapshot.context.next_meeting)} meeting (blackout from ${fmtDate(A.snapshot.as_of)}): <b>${A.snapshot.gauge?.toFixed(1) ?? "—"}/10</b>, ${A.snapshot.tally.hold} hold / ${A.snapshot.tally.hike} hike / ${A.snapshot.tally.cut} cut</div>` : "";
    $("#ana").innerHTML = `${pending}
      <div class="atop">
        <div class="panel gauge">
          <div class="label muted">Fed gauge · ${fmtDate(R.window_start)} – ${fmtDate(R.window_end)}</div>
          <div class="big">${R.gauge == null ? "—" : R.gauge.toFixed(1)}<span>/10</span></div>
          <div class="muted">${chg == null ? "no previous window" : `${f1(chg)} vs previous window (${R.gauge_prev.toFixed(1)})`}</div>
          ${R.gauge == null ? "" : gaugeBar(R.gauge)}
        </div>
        <div class="panel tally">
          <div class="label muted">${esc(nmLabel)} meeting · members' calls</div>
          <div class="big2">${t.hold} hold / ${t.hike} hike / ${t.cut} cut</div>
          ${t.none ? `<div class="muted">${t.none} without a call</div>` : ""}
          <div class="muted" style="margin-top:8px">Spread (std dev of stances): <b>${R.spread == null ? "—" : R.spread.toFixed(2)}</b></div>
          <div class="muted">Rate ${esc(ctx.target_range)} · last decision ${esc(ctx.last_decision)} ${fmtDate(ctx.last_decision_date)}</div>
        </div>
      </div>
      ${snap}
      <div class="panel summary">${R.summary_text ? esc(R.summary_text) : `<span class="muted">No summary yet${A.calls_today >= A.daily_limit ? " (daily call limit reached)" : ""}.</span>`}</div>
      <h2>Members <span class="sub muted">stance −5 (wants big cuts) … +5 (wants big hikes), relative to the current rate</span></h2>
      <div class="gridwrap"><table class="grid mtable">
        <thead><tr><th>Member</th><th>Stance</th><th>Change</th><th>${esc(nmLabel)} call</th><th>Docs</th><th style="text-align:left">Latest quote</th></tr></thead>
        <tbody>${R.members.map(row).join("")}</tbody></table></div>
      <div id="adetail"></div>
      <h2>Path <span class="sub muted">month by month, all documents</span></h2>
      ${pathChart(R.path)}
      ${pathTable(R.path, R.members)}`;
    document.querySelectorAll(".mtable tbody tr").forEach(tr => tr.onclick = () => toggleMember(tr.dataset.id));
    if (open) showMember(open, false);
  }

  function row(m) {
    const lab = m.call_label;
    const q = m.latest_quote;
    return `<tr data-id="${m.id}" class="${open === m.id ? "sel" : ""}">
      <td>${esc(m.name)}${m.carried_over ? ` <span class="badge warn" title="Nothing new on policy this window; score carried over from ${esc(m.carried_from || "")}">carried over</span>` : ""}</td>
      <td class="num" style="background:${fill(m.stance)}">${f1(m.stance)}</td>
      <td class="num muted">${f1(m.change)}</td>
      <td><span class="${lab}">${CALL[lab]}</span> ${callTag(m)}</td>
      <td class="num">${m.n_docs}${m.n_earlier ? ` <span class="muted" title="scored documents from the two earlier windows, at reduced weight">+${m.n_earlier} earlier</span>` : ""}${m.pending ? ` <span class="muted">(${m.pending} unscored)</span>` : ""}</td>
      <td class="quote">${q ? `“${esc(q.quote)}” <a href="${esc(q.url)}" target="_blank" rel="noopener" class="muted">${shortDate(q.date)}</a>` : `<span class="muted">—</span>`}</td></tr>`;
  }

  function callTag(m) {
    if (m.call_prob != null) return Math.round(m.call_prob * 100) + "%";
    const n = m.call_note || "";
    const [cls, txt] = n.startsWith("from their dissent") ? ["dis", "from dissent"] : n.startsWith("no call") ? ["warn", "no call"] : ["warn", "out of date"];
    return `<span class="badge ${cls}" title="${esc(n)}">${txt}</span>`;
  }

  function toggleMember(id) {
    if (open === id) { open = null; $("#adetail").innerHTML = ""; document.querySelectorAll(".mtable tr.sel").forEach(r => r.classList.remove("sel")); return; }
    showMember(id, true);
  }

  async function showMember(id, scroll) {
    open = id;
    document.querySelectorAll(".mtable tbody tr").forEach(r => r.classList.toggle("sel", r.dataset.id === id));
    const m = A.reading.members.find(x => x.id === id);
    const d = await (await fetch(`/api/analysis/member/${id}?model=${encodeURIComponent(model)}`)).json();
    const items = d.docs.map(x => {
      const inWin = x.date >= d.window_start;
      if (x.pending) return `<div class="speech"><div class="meta"><span class="date">${shortDate(x.date)}</span><span>${esc(x.title)}</span><span class="badge warn">not scored yet</span></div></div>`;
      const w = x.weight;
      return `<div class="speech ${inWin ? "" : "older"}">
        <div class="meta"><span class="date">${shortDate(x.date)}</span>
          <span class="stance" style="background:${fill(x.stance)}">${f1(x.stance)}</span>
          ${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>` : esc(x.title)}
          <span class="badge">${esc(x.doc_type)}</span>
          ${x.model && x.model !== model ? `<span class="badge warn" title="Scored by the fallback model">${esc(x.model)}</span>` : ""}
          ${inWin ? "" : `<span class="muted">earlier window</span>`}</div>
        <div class="muted small">weight ${w.toFixed(2)}${x.doc_type === "vote" ? "" : ` = source × relevance ${x.policy_relevance.toFixed(2)} × confidence ${x.confidence.toFixed(2)}`}${x.recency != null && x.recency < 1 ? ` × recency ${x.recency}` : ""}${x.recency == null ? " (outside the lookback: path only)" : ""}${x.call ? ` · next meeting: hike ${pc(x.call.hike)} / hold ${pc(x.call.hold)} / cut ${pc(x.call.cut)}` : ""}${x.mandate_balance != null ? ` · mandate balance ${f1(x.mandate_balance)}` : ""}</div>
        ${x.summary ? `<div>${esc(x.summary)}</div>` : ""}
        ${x.mandate_reason ? `<div class="muted small">${esc(x.mandate_reason)}</div>` : ""}
        ${(x.evidence || []).length ? `<ul class="ev">${x.evidence.map(e => `<li>“${esc(e.quote)}” <span class="muted">${esc(e.timestamp || e.date)}</span></li>`).join("")}</ul>` : ""}
        ${x.sub_views ? `<details><summary>Views</summary><div class="small">${Object.entries(x.sub_views).map(([k, v]) => `<div><b>${esc(k.replace("_", " "))}:</b> ${esc(v)}</div>`).join("")}</div></details>` : ""}
        ${x.notes ? `<div class="small" style="color:var(--warn)">${esc(x.notes)}</div>` : ""}
      </div>`;
    }).join("");
    $("#adetail").innerHTML = `<div class="panel" style="margin-top:14px">
      <div class="head" style="display:flex;gap:12px"><div style="flex:1"><h3 style="margin:0">${esc(m.name)}</h3>
        <div class="muted">Stance ${f1(m.stance)} this window${m.carried_over ? " (carried over)" : ""} · documents since ${fmtDate(d.docs.length ? d.docs[d.docs.length - 1].date : d.window_start)}</div></div>
        <button id="closeA">Close ✕</button></div>
      ${items || `<div class="muted">No documents.</div>`}</div>`;
    $("#closeA").onclick = () => toggleMember(id);
    if (scroll) $("#adetail").scrollIntoView({behavior: "smooth", block: "nearest"});
  }
  const pc = x => x == null ? "—" : Math.round(x * 100) + "%";

  // single-series line: Fed gauge (0-10) by month, with crosshair tooltip
  function pathChart(P) {
    const W = 720, H = 200, L = 34, Rr = 12, T = 12, B = 26;
    const xs = i => L + (W - L - Rr) * (P.length === 1 ? 0.5 : i / (P.length - 1));
    const ys = v => T + (H - T - B) * (1 - v / 10);
    const pts = P.map((p, i) => p.gauge == null ? null : [xs(i), ys(p.gauge), p]).filter(Boolean);
    const grid = [0, 5, 10].map(v => `<line x1="${L}" x2="${W - Rr}" y1="${ys(v)}" y2="${ys(v)}" class="${v === 5 ? "gmidline" : "gline"}"/><text x="${L - 6}" y="${ys(v) + 4}" text-anchor="end">${v}</text>`).join("");
    const xl = P.map((p, i) => `<text x="${xs(i)}" y="${H - 6}" text-anchor="middle">${monthName(p.month)}</text>`).join("");
    const line = pts.length > 1 ? `<path d="M${pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join("L")}" class="pline"/>` : "";
    const dots = pts.map(([x, y, p]) => `<circle cx="${x}" cy="${y}" r="4" class="pdot"/><circle cx="${x}" cy="${y}" r="16" class="hit" data-tip="${esc(monthName(p.month))}: gauge ${p.gauge.toFixed(1)} (${p.n_members} members with documents)"/>`).join("");
    setTimeout(() => document.querySelectorAll(".pathsvg .hit").forEach(c => {
      c.onmouseenter = e => { const t = $("#ptip"); t.textContent = c.dataset.tip; t.hidden = false; };
      c.onmouseleave = () => $("#ptip").hidden = true;
    }));
    return `<div class="panel"><div class="label muted">Fed gauge by month (0 dovish – 10 hawkish)</div>
      <svg class="pathsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Fed gauge by month">${grid}${xl}${line}${dots}</svg>
      <div id="ptip" class="muted small" hidden></div></div>`;
  }

  function pathTable(P, members) {
    return `<div class="gridwrap" style="margin-top:10px"><table class="grid ptable">
      <thead><tr><th>Member</th>${P.map(p => `<th>${monthName(p.month)}</th>`).join("")}</tr></thead>
      <tbody>${members.map(m => `<tr><td>${esc(m.name)}</td>${P.map(p => { const v = p.members[m.id]; return `<td class="num" style="background:${fill(v)}">${v == null ? `<span class="muted">·</span>` : f1(v)}</td>`; }).join("")}</tr>`).join("")}
      <tr class="fedrow"><td><b>Fed (average)</b></td>${P.map(p => `<td class="num"><b>${f1(p.fed_stance)}</b></td>`).join("")}</tr></tbody></table>
      <div class="muted small" style="margin-top:4px">Blank: no documents or votes that month.</div></div>`;
  }

  async function poll() {
    const btn = $("#analyse"), t = $("#atimer");
    btn.disabled = true; btn.textContent = "Analysing…";
    $("#alogwrap").hidden = false;
    const st = await (await fetch("/api/analyse?model=" + encodeURIComponent(model))).json();
    $("#alog").textContent = st.log.join("\n");
    $("#alog").scrollTop = $("#alog").scrollHeight;
    if (st.running) {
      if (!tick) {
        const base = Date.now() - (st.elapsed || 0) * 1000;
        tick = setInterval(() => { t.textContent = `⏱ ${fmtDuration((Date.now() - base) / 1000)} · ${st.model}`; }, 250);
      }
      t.className = "running";
      return setTimeout(poll, 1500);
    }
    clearInterval(tick); tick = null;
    btn.disabled = false; btn.textContent = "Run analysis";
    await load();
  }

  function wire() {
    $("#model").onchange = e => { model = e.target.value; store.set("model", model); open = null; load(); };
    $("#analyse").onclick = async () => { await fetch("/api/analyse?model=" + encodeURIComponent(model), {method: "POST"}); poll(); };
    $("#alogbtn").onclick = () => { $("#alogwrap").hidden = !$("#alogwrap").hidden; };
  }

  const css = document.createElement("style");
  css.textContent = `
    .atop { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin-top: 12px; }
    .label { font-size: 12.5px; }
    .gauge .big { font-size: 44px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
    .gauge .big span { font-size: 18px; color: var(--muted); font-weight: 500; }
    .big2 { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .gbar { position: relative; height: 14px; margin-top: 12px; }
    .gtrack { position: absolute; inset: 4px 0; border-radius: 4px; background: linear-gradient(90deg, var(--dove), var(--mid), var(--hawk)); }
    .gmid { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--muted); }
    .gpin { position: absolute; top: -2px; width: 4px; height: 18px; margin-left: -2px; border-radius: 2px; background: var(--ink); box-shadow: 0 0 0 2px var(--panel); }
    .gends { display: flex; justify-content: space-between; font-size: 11.5px; margin-top: 2px; }
    .summary { margin-top: 10px; font-size: 14.5px; line-height: 1.55; }
    .snap { margin-top: 8px; font-size: 13px; }
    .mtable tbody tr { cursor: pointer; }
    .mtable tbody tr:hover td, .mtable tr.sel td { box-shadow: inset 0 0 0 9999px var(--accent-soft); }
    .mtable td.num, .ptable td.num { font-variant-numeric: tabular-nums; text-align: center; }
    .mtable td.quote { text-align: left; white-space: normal; min-width: 280px; font-size: 12.5px; }
    .mtable .hike { color: var(--hike); font-weight: 600; } .mtable .cut { color: var(--cut); font-weight: 600; } .mtable .hold { color: var(--hold); font-weight: 600; }
    .stance { padding: 0 6px; border-radius: 4px; font-variant-numeric: tabular-nums; font-weight: 600; }
    .small { font-size: 12.5px; }
    .speech.older { opacity: .75; }
    ul.ev { margin: 4px 0; padding-left: 18px; font-size: 13px; }
    .pathsvg { width: 100%; height: auto; display: block; margin-top: 6px; }
    .pathsvg text { fill: var(--muted); font-size: 11px; }
    .pathsvg .gline { stroke: var(--line); } .pathsvg .gmidline { stroke: var(--muted); stroke-dasharray: 3 3; }
    .pathsvg .pline { fill: none; stroke: var(--accent); stroke-width: 2; }
    .pathsvg .pdot { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }
    .pathsvg .hit { fill: transparent; cursor: default; }
    .ptable .fedrow td { border-top: 2px solid var(--line); }`;
  document.head.appendChild(css);

  return {
    show() { if (!started) { started = true; wire(); } load(); },
  };
})();
