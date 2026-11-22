// Analysis tab: hawkishness gauge, next-meeting tally, member table, 6-month path.
// Uses $, esc, fmtDate, shortDate, fmtDuration and store from index.html.
window.Analysis = (() => {
  let A = null, model = store.get("model"), open = null, tick = null, started = false;
  const f1 = x => x == null ? "—" : (x > 0 ? "+" : "") + x.toFixed(1);
  const pct = g => g == null ? "—" : Math.round(g * 10) + "%";   // gauge is stored 0-10, shown 0-100%
  const CALL = {hike: "Hike", hold: "Hold", cut: "Cut"};
  const monthName = m => new Date(m + "-15T12:00:00").toLocaleDateString("en-US", {month: "short"});

  // diverging fill for a stance (-5 dove .. +5 hawk); text stays in ink
  const fill = s => s == null ? "transparent"
    : `color-mix(in oklab, var(${s >= 0 ? "--hawk" : "--dove"}) ${Math.round(Math.min(Math.abs(s) / 5, 1) * 70)}%, var(--mid))`;

  async function load() {
    A = await (await fetch("/api/analysis?model=" + encodeURIComponent(model || ""))).json();
    if (A.error) { $("#ana").innerHTML = `<div class="banner">${esc(A.error)}</div>`; return; }
    model = A.model;
    $("#model").innerHTML = A.models.map(m => `<option value="${esc(m)}" ${m === model ? "selected" : ""}>${esc(m)}${A.paid_models.includes(m) ? " (paid)" : ""}</option>`).join("");
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
                       : "Not run yet with this model") + (A.free_daily ? ` · ${A.calls_today}/${A.free_daily} free calls today` : " · paid model")
                     + (A.needs_password ? " · 🔒 password needed to run" : "")
                     + (A.fallback ? ` (+ ${A.fallback.model}: ${A.fallback.calls_today}/${A.fallback.daily_limit})` : "");
  }

  // "Dec 8–9, 2026" from the context's first and last meeting days
  function meetingDates(ctx) {
    const a = new Date(ctx.next_meeting_start + "T12:00:00"), b = new Date(ctx.next_meeting + "T12:00:00");
    const m = d => d.toLocaleDateString("en-US", {month: "short"});
    return a.getMonth() === b.getMonth() ? `${m(a)} ${a.getDate()}–${b.getDate()}, ${b.getFullYear()}`
                                         : `${m(a)} ${a.getDate()} – ${m(b)} ${b.getDate()}, ${b.getFullYear()}`;
  }

  // implied move, Bloomberg-style: +100% = a 25bp hike fully expected, -100% = a 25bp cut, 0 = hold
  const mv = x => x == null ? "—" : `${x > 0.5 ? "+" : x < -0.5 ? "−" : ""}${Math.abs(Math.round(x))}%`;
  const mvBps = x => x == null ? "" : `≈ ${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x / 100 * 25).toFixed(1)}bp`;

  function moveBar(x) {
    const pos = Math.max(0, Math.min(100, (x + 100) / 2));
    return `<div class="gbar"><div class="gtrack"></div><div class="gmid"></div><div class="gpin" style="left:${pos}%"></div></div>
      <div class="gends muted"><span>−100% · 25bp cut</span><span>0 · hold</span><span>+100% · 25bp hike</span></div>`;
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
    const pending = R.pending_docs ? `<div class="banner">${R.pending_docs} document${R.pending_docs === 1 ? "" : "s"} in this window ${R.pending_docs === 1 ? "is" : "are"} not scored yet${A.needs_password ? (A.free_daily ? " (today's free calls are used up: Run analysis asks for the paid password, or wait until midnight Pacific)" : " (paid model: Run analysis asks for the paid password)") : ""}. Members without a scored document use their earlier scores until then.</div>` : "";
    const snap = A.snapshot ? `<div class="snap muted">Going into the ${fmtDate(A.snapshot.context.next_meeting)} meeting (latest run in the blackout, ${fmtDate(A.snapshot.as_of)}): <b>${mv(A.snapshot.implied)}</b> implied move</div>` : "";
    $("#ana").innerHTML = `${pending}
      <div class="atop">
        <div class="panel gauge">
          <div class="label"><b>Implied move at the ${nm ? meetingDates(ctx) : "next"} meeting</b></div>
          <div class="label muted">Since the ${fmtDate(R.window_start)} decision · speeches up to ${fmtDate(R.window_end)}${ctx.blackout_start ? ` · ${R.window_end >= ctx.blackout_start ? "blackout started" : "blackout starts"} ${fmtDate(ctx.blackout_start)}` : ""}</div>
          <div class="big">${mv(R.implied)} <span>${mvBps(R.implied)}</span></div>
          ${R.committee ? `<div class="probs"><span class="hike">Hike ${Math.round(R.committee.hike * 100)}%</span> · <span class="hold">Hold ${Math.round(R.committee.hold * 100)}%</span> · <span class="cut">Cut ${Math.round(R.committee.cut * 100)}%</span></div>` : ""}
          ${prevLine(R)}
          ${R.implied == null ? "" : moveBar(R.implied)}
        </div>
        <div class="panel tally">
          <div class="label"><b>How the members line up</b></div>
          <div class="big2">${R.tally_own ? `${R.tally_own.hike} hike · ${R.tally_own.hold} hold${R.tally_own.cut ? ` · ${R.tally_own.cut} cut` : ""}` : `${t.hike} hike · ${t.hold} hold`}</div>
          <div class="muted small">members with a current view of their own: a policy speech since ${fmtDate(R.window_start)}, a data condition, or a dissent</div>
          ${R.no_view ? `<div class="muted" style="margin-top:6px">${R.no_view} with no current view, assumed to vote with the committee (${CALL[R.committee?.predicted || "hold"].toLowerCase()})</div>` : ""}
          <div class="muted" style="margin-top:8px">Spread of stances (std dev): <b>${R.spread == null ? "—" : R.spread.toFixed(2)}</b></div>
          <div class="muted">Rate ${esc(ctx.target_range)} · last decision ${esc(ctx.last_decision)} ${fmtDate(ctx.last_decision_date)}</div>
        </div>
      </div>
      ${method()}
      ${snap}
      <div class="panel summary">${R.summary_text ? esc(R.summary_text) : `<span class="muted">No summary yet${A.needs_password ? " (needs a run: free calls used up or paid model)" : ""}.</span>`}${R.rebuilt && R.summary_text ? `<div class="muted small" style="margin-top:6px">Numbers above were recalculated with the current rules; this summary is from the ${esc(R.created_at.slice(0, 10))} run.</div>` : ""}</div>
      <h2>Members <span class="sub muted">implied move per member: +100% = sure to back a 25bp hike, 0 = hold, −100% = a 25bp cut</span></h2>
      <div class="gridwrap"><table class="grid mtable">
        <thead><tr><th>Member</th><th title="this member's hike odds minus cut odds for the next meeting">Implied move</th><th title="points vs going into the previous meeting">Change</th><th>${esc(nmLabel)} call</th><th title="since the last decision (on policy) + from the two earlier windows">Docs</th><th style="text-align:left">Latest quote</th></tr></thead>
        <tbody>${R.members.map(row).join("")}</tbody></table></div>
      <div id="adetail"></div>
      <h2>Path <span class="sub muted">meeting by meeting</span></h2>
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
      <td class="num" style="background:${fill(m.implied == null ? null : m.implied / 20)}" title="hawkishness score ${f1(m.stance)} on −5…+5">${mv(m.implied)}</td>
      <td class="num muted">${(() => { const prev = (A.reading.path || []).filter(p => !p.upcoming).at(-1); const pv = prev?.member_implied?.[m.id]; return pv == null || m.implied == null ? "—" : (Math.round(m.implied - pv) === 0 ? "0" : `${m.implied > pv ? "+" : "−"}${Math.abs(Math.round(m.implied - pv))}`); })()}</td>
      <td class="call"><span class="${lab}">${CALL[lab]}</span> ${callTag(m)}</td>
      <td class="docs"><div title="documents since the last decision; 'on policy' = mainly about monetary policy (relevance ≥ 0.5), the only ones that give a call"><b>${m.n_docs}</b> <span class="${m.n_policy ? "" : "muted"}">· ${m.n_policy} on policy</span></div>${m.n_earlier ? `<div class="muted small" title="scored documents from the two earlier windows, at reduced weight">+${m.n_earlier} earlier</div>` : ""}${m.pending ? `<div class="muted small">${m.pending} unscored</div>` : ""}</td>
      <td class="quote">${q ? `“${esc(q.quote)}” <a href="${esc(q.url)}" target="_blank" rel="noopener" class="muted">${shortDate(q.date)}</a>` : `<span class="muted">—</span>`}</td></tr>`;
  }

  // change vs the reading going into the previous meeting, and what actually happened there
  function prevLine(R) {
    const prev = (R.path || []).filter(p => !p.upcoming).at(-1);
    if (!prev || prev.implied == null || R.implied == null) return "";
    const d = Math.round(R.implied - prev.implied);
    return `<div class="muted small">${d === 0 ? "No change" : `${d > 0 ? "+" : "−"}${Math.abs(d)} pts`} vs ${mv(prev.implied)} going into ${esc(mLabel(prev))} (actual: ${actualText(prev.actual)})</div>`;
  }

  // the committee view: averaged odds of members with a current view of their own
  function decision(c) {
    if (!c) return `<div class="big2">—</div>`;
    const lab = c.predicted, p = Math.round(c[lab] * 100);
    return `<div class="big2"><span class="${lab}">${CALL[lab]}</span> <span class="muted" style="font-size:16px;font-weight:500">${p}% likely</span></div>
      <div class="muted small">hike ${Math.round(c.hike * 100)}% · hold ${Math.round(c.hold * 100)}% · cut ${Math.round(c.cut * 100)}% — average of ${c.n_views} members with a current view</div>`;
  }

  function condLine(m) {
    const c = m.condition;
    if (!c) return "";
    const st = {met: "condition met", not_met: "condition not met", pending: "conditional, waiting for data"}[c.status] || c.status;
    return `<div class="small cond ${c.status}" title="“${esc(c.quote)}” (${esc(c.date)})\n${esc(c.detail)}">${st}: ${CALL[c.then]} if ${c.status === "pending" ? esc(c.detail.replace(/^waiting for /, "")) : "data " + (c.status === "met" ? "came in as stated" : "did not")}</div>`;
  }

  function callTag(m) {
    if (m.call_basis === "condition") return `<span class="badge ${m.condition.status === "met" ? "dis" : "warn"}" title="${esc(m.call_note)}">${m.condition.status === "met" ? "condition met" : "condition not met"}</span><div class="muted small">${esc((m.condition.detail.split(";")[0] || "").replace(/ \(.*$/, ""))}${m.condition.status === "met" ? "" : ` → otherwise ${esc(m.call_label)}`}</div>`;
    if (m.call_basis === "committee") return `<span class="badge" title="${esc(m.call_note)}">follows committee</span><div class="muted small">no current view of their own</div>` + condLine(m);
    if (m.call_prob != null) return Math.round(m.call_prob * 100) + "%" + condLine(m);
    const n = m.call_note || "";
    const [cls, txt, sub] = n.startsWith("from their dissent") ? ["dis", "from dissent", `no policy speech since ${shortDate(A.reading.window_start)}`]
      : n.startsWith("no call") ? ["warn", "no call", "no recent policy speech"]
      : ["warn", "out of date", `last policy speech ${m.call?.date ? shortDate(m.call.date) : "?"}`];
    return `<span class="badge ${cls}" title="${esc(n)}">${txt}</span><div class="muted small">${sub}</div>`;
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
          <span class="stance" style="background:${fill(x.call ? (x.call.hike - x.call.cut) * 5 : x.stance)}" title="raw hawkishness score ${f1(x.stance)} on −5…+5">${x.call ? mv((x.call.hike - x.call.cut) * 100) : f1(x.stance)}</span>
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
        <div class="muted">Implied move ${mv(m.implied)} (${esc(CALL[m.call_label])}) · hawkishness score ${f1(m.stance)} on −5…+5${m.carried_over ? " (carried over)" : ""} · documents since ${fmtDate(d.docs.length ? d.docs[d.docs.length - 1].date : d.window_start)}</div></div>
        <button id="closeA">Close ✕</button></div>
      ${items || `<div class="muted">No documents.</div>`}</div>`;
    $("#closeA").onclick = () => toggleMember(id);
    if (scroll) $("#adetail").scrollIntoView({behavior: "smooth", block: "nearest"});
  }
  const pc = x => x == null ? "—" : Math.round(x * 100) + "%";

  // the methodology behind the headline numbers, collapsed by default; values come from config
  function method() {
    const M = A.method, sw = M.source_weights, d = M.window_decay.map(x => Math.round(x * 100) + "%");
    return `<details class="panel method"><summary>How the score is worked out</summary><ul>
      <li>The AI (${esc(model)}, prompt ${esc(A.prompt_version)}) reads every speech, essay and dissent statement from the 12 voters and scores it from −5 (wants big cuts) to +5 (wants big hikes), relative to the current rate. Worry about inflation counts as hawkish, worry about jobs as dovish (the dual mandate). Speeches with no monetary-policy content are skipped.</li>
      <li>Votes are scored by rule: voting with the majority 0, a dissent on the rate ±${M.vote_scores.dissent_tighter_rate}, a dissent on the statement's wording only ±${M.vote_scores.dissent_tighter_wording}.</li>
      <li>Each document's weight = source × how much it is about policy × how clear the stance is × how recent it is. Sources: dissent statement and essay ${sw.statement}, speech ${sw.speech}, Q&amp;A ${sw.qa}, panel ${sw.panel}, dissent vote ${sw.vote}, agreeing vote ${sw.vote_agree}.</li>
      <li>Recency: since the last decision ${d[0]}, the window before ${d[1]}, the one before that ${d[2]}.</li>
      <li>Member stance = the weighted average of their documents. A member with nothing in those windows keeps their older score ("carried over").</li>
      <li><b>Implied move</b> = hike probability − cut probability, read like a Bloomberg WIRP figure: +100% means a 25bp hike is fully expected, −100% a 25bp cut, 0 a hold. +59% means a hike is more likely than not (≈ +15bp expected on average).</li>
      <li><b>Calls</b> come from each member's latest policy speech. If they made a data-dependent statement ("if August inflation is hot, I'd hike in September"), the released CPI, PCE and jobs data decide it: hotter or cooler than the Cleveland Fed nowcast (inflation) or the recent trend (jobs). A rate dissent at the last meeting counts in its direction until they speak again.</li>
      <li><b>Expected decision</b> = the average hike / hold / cut odds of the members with a current view of their own. Members with no current view (silent since the last decision) are assumed to vote with the committee, as members almost always do.</li>
      <li><b>Spread</b> = how far apart the 12 stances are (standard deviation, in stance points).</li>
      <li>The written summary only explains these numbers; it cannot change them.</li>
    </ul></details>`;
  }

  const mLabel = p => p.meeting_start ? meetingDates({next_meeting_start: p.meeting_start, next_meeting: p.meeting}).replace(/, \d{4}$/, "") : "next";
  const actualText = a => a.decision === "hold" ? "Hold" : `${a.decision === "hike" ? "Hike" : "Cut"} ${a.bps}bps`;
  const tallyText = t => `${t.hold} hold / ${t.hike} hike / ${t.cut} cut`;

  // single-series line: the gauge going into each meeting (past: rebuilt as of the day before its
  // blackout; last point: the upcoming meeting, from the latest run), with the actual decision under each
  function pathChart(P) {
    const W = 720, H = 230, L = 40, Rr = 40, T = 22, B = 46;
    const xs = i => L + (W - L - Rr) * (P.length === 1 ? 0.5 : i / (P.length - 1));
    const ys = v => T + (H - T - B) * (1 - (v + 100) / 200);
    const pts = P.map((p, i) => p.implied == null ? null : [xs(i), ys(p.implied), p]).filter(Boolean);
    const grid = [-100, 0, 100].map(v => `<line x1="${L}" x2="${W - Rr}" y1="${ys(v)}" y2="${ys(v)}" class="${v === 0 ? "gmidline" : "gline"}"/><text x="${L - 6}" y="${ys(v) + 4}" text-anchor="end">${mv(v)}</text>`).join("");
    const acts = P.filter(p => !p.upcoming).map(p => { const i = P.indexOf(p), x = xs(i), y = ys(p.actual.implied);
      return `<path d="M${x},${y - 6}L${x + 6},${y}L${x},${y + 6}L${x - 6},${y}Z" class="adot ${p.actual.decision}"/>`; }).join("");
    const xl = P.map((p, i) => `<text x="${xs(i)}" y="${H - 26}" text-anchor="middle">${esc(mLabel(p))}</text>
      <text x="${xs(i)}" y="${H - 10}" text-anchor="middle" class="${p.upcoming ? "nextlbl" : "actual " + p.actual.decision}">${p.upcoming ? "next meeting" : "actual: " + actualText(p.actual)}</text>`).join("");
    const past = pts.filter(q => !q[2].upcoming), nxt = pts.find(q => q[2].upcoming);
    const line = past.length > 1 ? `<path d="M${past.map(q => q[0].toFixed(1) + "," + q[1].toFixed(1)).join("L")}" class="pline"/>` : "";
    const dash = nxt && past.length ? `<path d="M${past.at(-1)[0]},${past.at(-1)[1]}L${nxt[0]},${nxt[1]}" class="pline next"/>` : "";
    const dots = pts.map(([x, y, p]) => {
      const tip = p.upcoming
        ? `${mLabel(p)} (next): implied move ${mv(p.implied)} from the latest run (speeches to ${p.as_of})${p.committee ? `; hike ${Math.round(p.committee.hike * 100)}% / hold ${Math.round(p.committee.hold * 100)}% / cut ${Math.round(p.committee.cut * 100)}%` : ""}`
        : `${mLabel(p)}: implied move ${mv(p.implied)} going in (as of ${p.as_of})${p.committee ? `; hike ${Math.round(p.committee.hike * 100)}% / hold ${Math.round(p.committee.hold * 100)}% / cut ${Math.round(p.committee.cut * 100)}%` : ""}; actual ${actualText(p.actual)} ${p.actual.for}-${p.actual.against}${p.actual.dissents.length ? " (" + p.actual.dissents.map(d => d[0].split(" ").pop() + " wanted " + d[1]).join(", ") + ")" : ""}; ${p.calls_right}/${p.calls_compared} member calls right`;
      return `<circle cx="${x}" cy="${y}" r="5" class="${p.upcoming ? "pdot hollow" : "pdot"}"/>
        <text x="${P.indexOf(p) === 0 ? x + 8 : x}" y="${!p.upcoming && p.actual.implied > p.implied ? y + 18 : y - 10}" text-anchor="${P.indexOf(p) === 0 ? "start" : "middle"}" class="plbl">${mv(p.implied)}</text>
        <circle cx="${x}" cy="${y}" r="18" class="hit" data-tip="${esc(tip)}"/>`;
    }).join("");
    setTimeout(() => document.querySelectorAll(".pathsvg .hit").forEach(c => {
      c.onmouseenter = () => { const t = $("#ptip"); t.textContent = c.dataset.tip; t.hidden = false; };
      c.onmouseleave = () => $("#ptip").hidden = true;
    }));
    return `<div class="panel"><div class="label muted">Implied move going into each meeting (line) against what the FOMC actually did (◆: +100% = 25bp hike, 0 = hold, −100% = 25bp cut). Past meetings: what this board would have shown the day before the meeting. Last point: the upcoming meeting, from your latest run.</div>
      <svg class="pathsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Implied move going into each meeting vs the actual decision">${grid}${line}${dash}${acts}${xl}${dots}</svg>
      <div id="ptip" class="muted small" hidden></div></div>`;
  }

  function pathTable(P, members) {
    const callMark = c => c === "hike" ? "▲" : c === "cut" ? "▼" : "";
    const head = P.map(p => `<th>${esc(mLabel(p))}${p.upcoming ? "<br><span class='muted small'>next</span>" : ""}</th>`).join("");
    const rows = members.map(m => `<tr><td>${esc(m.name)}</td>${P.map(p => {
      const v = p.member_implied ? p.member_implied[m.id] : null, c = p.calls[m.id], a = p.actual?.votes?.[m.id];
      const miss = a && c && a !== c;
      return `<td class="num" style="background:${fill(v == null ? null : v / 20)}" title="${v == null ? "not a voter / no data" : `implied move ${mv(v)}; expected ${c || "—"}${a ? `; voted ${a}` : ""}`}">${v == null ? `<span class="muted">·</span>` : mv(v)}${callMark(c) ? ` <span class="small">${callMark(c)}</span>` : ""}${miss ? ` <span class="small" style="color:var(--dissent)">✗</span>` : ""}</td>`;
    }).join("")}</tr>`).join("");
    return `<div class="gridwrap" style="margin-top:10px"><table class="grid ptable">
      <thead><tr><th>Member</th>${head}</tr></thead>
      <tbody>${rows}
      <tr class="fedrow"><td><b>Implied move</b></td>${P.map(p => `<td class="num"><b>${mv(p.implied)}</b></td>`).join("")}</tr>
      <tr><td>Expected decision</td>${P.map(p => `<td class="num small">${p.committee ? `<b>${CALL[p.committee.predicted]}</b> ${Math.round(p.committee[p.committee.predicted] * 100)}%` : "—"}</td>`).join("")}</tr>
      <tr><td>Expected votes</td>${P.map(p => `<td class="num small">${tallyText(p.tally)}</td>`).join("")}</tr>
      <tr><td>Actual</td>${P.map(p => `<td class="num small">${p.upcoming ? `<span class="muted">—</span>` : `${actualText(p.actual)} ${p.actual.for}–${p.actual.against}`}</td>`).join("")}</tr>
      <tr><td>Member calls right</td>${P.map(p => `<td class="num small">${p.upcoming ? `<span class="muted">—</span>` : `${p.calls_right}/${p.calls_compared}`}</td>`).join("")}</tr>
      </tbody></table>
      <div class="muted small" style="margin-top:4px">Cells: each member's implied move going into that meeting (+100% = sure to back a 25bp hike, −100% = a 25bp cut). ▲ expected to back a hike, ▼ a cut; ✗ the call was wrong. Current voters only.</div></div>`;
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

  // spending past a free limit, or using a paid-only model, needs the paid password
  function askPassword() {
    const why = A.free_daily ? `Today's ${A.free_daily} free calls for ${model} are used up, so this run would be billed.`
                             : `${model} is a paid model, so this run would be billed.`;
    $("#pwwhy").textContent = why + ` Runs stop at ${A.daily_limit_paid ?? 150} calls a day.`;
    $("#pwhint").textContent = A.hint;
    $("#pwerr").textContent = "";
    $("#pw").value = "";
    $("#pwdlg").showModal();
    $("#pw").focus();
  }

  async function start(password) {
    const r = await fetch("/api/analyse?model=" + encodeURIComponent(model), {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(password == null ? {} : {password})});
    const j = await r.json();
    if (!j.started) {
      if (!$("#pwdlg").open) askPassword();
      $("#pwerr").textContent = j.error === "wrong password" ? "Wrong password." : "";
      return false;
    }
    poll();
    return true;
  }

  function wire() {
    document.body.insertAdjacentHTML("beforeend", `<dialog id="pwdlg"><form id="pwform">
      <h3>Paid run</h3>
      <p id="pwwhy" class="muted small"></p>
      <label>Password <input id="pw" type="password" autocomplete="off"></label>
      <p class="muted small">Hint: <span id="pwhint"></span></p>
      <p id="pwerr" class="pwerr"></p>
      <div class="pwbtns"><button type="button" id="pwcancel">Cancel</button><button type="submit" class="primary">Run (paid)</button></div>
    </form></dialog>`);
    $("#model").onchange = e => { model = e.target.value; store.set("model", model); open = null; load(); };
    $("#analyse").onclick = () => A.needs_password ? askPassword() : start();
    $("#pwform").onsubmit = async e => {
      e.preventDefault();
      if (await start($("#pw").value)) $("#pwdlg").close();
    };
    $("#pwcancel").onclick = () => $("#pwdlg").close();
    $("#alogbtn").onclick = () => { $("#alogwrap").hidden = !$("#alogwrap").hidden; };
  }

  const css = document.createElement("style");
  css.textContent = `
    .atop { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin-top: 12px; }
    .label { font-size: 12.5px; }
    .gauge .big { font-size: 44px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
    .gauge .big span { font-size: 18px; color: var(--muted); font-weight: 500; }
    .probs { font-size: 15px; font-weight: 600; margin-top: 2px; }
    .probs .hike { color: var(--hike); } .probs .hold { color: var(--hold); } .probs .cut { color: var(--cut); }
    .big2 { font-size: 24px; font-weight: 700; margin-top: 6px; }
    .big2 .hike { color: var(--hike); } .big2 .cut { color: var(--cut); } .big2 .hold { color: var(--hold); }
    .cond { margin-top: 2px; white-space: normal; max-width: 220px; } .cond.met { color: var(--dissent); } .cond.pending { color: var(--warn); }
    .gbar { position: relative; height: 14px; margin-top: 12px; }
    .gtrack { position: absolute; inset: 4px 0; border-radius: 4px; background: linear-gradient(90deg, var(--dove), var(--mid), var(--hawk)); }
    .gmid { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--muted); }
    .gpin { position: absolute; top: -2px; width: 4px; height: 18px; margin-left: -2px; border-radius: 2px; background: var(--ink); box-shadow: 0 0 0 2px var(--panel); }
    .gends { display: flex; justify-content: space-between; font-size: 11.5px; margin-top: 2px; }
    #pwdlg { border: 1px solid var(--line); border-radius: 10px; background: var(--panel); color: var(--ink); padding: 18px 20px; max-width: 380px; }
    #pwdlg::backdrop { background: rgba(0,0,0,.35); }
    #pwdlg h3 { margin: 0 0 6px; }
    #pwdlg input { font: inherit; margin-left: 6px; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--line); background: var(--bg); color: var(--ink); }
    .pwerr { color: var(--dissent); min-height: 1em; margin: 4px 0; font-size: 13px; }
    .pwbtns { display: flex; justify-content: flex-end; gap: 8px; }
    .method { margin-top: 10px; padding: 10px 18px; }
    .method summary { color: var(--muted); font-size: 13px; }
    .method ul { margin: 8px 0 2px; padding-left: 18px; font-size: 13px; line-height: 1.5; }
    .method li { margin: 3px 0; }
    .summary { margin-top: 10px; font-size: 14.5px; line-height: 1.55; }
    .snap { margin-top: 8px; font-size: 13px; }
    .mtable tbody tr { cursor: pointer; }
    .mtable tbody tr:hover td, .mtable tr.sel td { box-shadow: inset 0 0 0 9999px var(--accent-soft); }
    .mtable td.num, .ptable td.num { font-variant-numeric: tabular-nums; text-align: center; }
    .mtable td.call { white-space: nowrap; text-align: left; }
    .mtable td.docs { white-space: nowrap; text-align: left; font-variant-numeric: tabular-nums; }
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
    .pathsvg .adot { fill: var(--panel); stroke-width: 2; } .pathsvg .adot.hike { stroke: var(--hike); } .pathsvg .adot.hold { stroke: var(--hold); } .pathsvg .adot.cut { stroke: var(--cut); }
    .pathsvg .pdot.hollow { fill: var(--panel); stroke: var(--accent); stroke-width: 2; }
    .pathsvg .pline.next { stroke-dasharray: 4 4; }
    .pathsvg .plbl { fill: var(--ink); font-size: 11.5px; font-weight: 600; }
    .pathsvg .actual.hike { fill: var(--hike); } .pathsvg .actual.cut { fill: var(--cut); } .pathsvg .nextlbl { fill: var(--accent); }
    .pathsvg .hit { fill: transparent; cursor: default; }
    .ptable .fedrow td { border-top: 2px solid var(--line); }`;
  document.head.appendChild(css);

  return {
    show() { if (!started) { started = true; wire(); } load(); },
  };
})();
