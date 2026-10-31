/* AdhikarVani front end: vanilla JS, no build step. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers --
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const main = $("#main");
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  let LANGS = { hi: { name: "Hindi", native: "हिन्दी" }, en: { name: "English", native: "English" } };
  let uiLang = store.get("av-lang", "hi");

  async function api(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, opts);
    } catch {
      throw new Error("Can't reach the server. Check your connection and try again.");
    }
    let body = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) throw new Error((body && (body.detail || body.error)) || `Request failed (${res.status})`);
    return body;
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  }

  function langOptions(selected) {
    return Object.entries(LANGS).map(([k, v]) =>
      `<option value="${k}" ${k === selected ? "selected" : ""}>${esc(v.native)}${v.native !== v.name ? ` (${esc(v.name)})` : ""}</option>`).join("");
  }

  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
  const MIC_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  const STOP_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>';

  // ------------------------------------------------------------- health --
  async function loadHealth() {
    const el = $("#health");
    try {
      const h = await api("/api/health");
      if (h.languages) LANGS = h.languages;
      if (!LANGS[uiLang]) uiLang = "hi";
      const names = { gemini: "Gemini", groq: "Groq", cerebras: "Cerebras", mistral: "Mistral", openrouter: "OpenRouter" };
      const live = (h.llm.configured || []).map((p) => names[p] || p);
      el.className = "health " + (live.length ? "ok" : "bad");
      el.innerHTML = `<span class="dot"></span><span>${live.length ? "Live AI: " + esc(live.join(", ")) : "No AI key configured"}</span>`;
      el.title = (h.llm.active.heavy || []).join("\n");
    } catch {
      el.className = "health bad";
      el.innerHTML = '<span class="dot"></span><span>Server unreachable</span>';
    }
  }

  // ------------------------------------------------------------- router --
  const routes = [
    [/^#?\/?$/, renderHome, "home"],
    [/^#\/policy\/([a-z0-9-]+)$/, renderPolicy, null],
    [/^#\/radar$/, renderRadar, "radar"],
    [/^#\/how$/, renderHow, "how"],
  ];
  async function route() {
    const h = location.hash || "#/";
    for (const [rx, fn, nav] of routes) {
      const m = h.match(rx);
      if (m) {
        $$(".nav a").forEach((a) => a.toggleAttribute("aria-current", false));
        if (nav) $(`.nav a[data-nav="${nav}"]`)?.setAttribute("aria-current", "page");
        stopAudio();
        await fn(...m.slice(1));
        main.focus({ preventScroll: true });
        return;
      }
    }
    location.hash = "#/";
  }
  window.addEventListener("hashchange", route);

  const mount = (id) => { main.replaceChildren($(`#${id}`).content.cloneNode(true)); };
  let currentAudio = null;
  function stopAudio() { if (currentAudio) { currentAudio.pause(); currentAudio = null; } }
  function play(url) {
    stopAudio();
    if (!url) return;
    currentAudio = new Audio(url);
    currentAudio.play().catch(() => { /* autoplay blocked; the user can press play */ });
  }

  // =============================================================== HOME ==
  const STEPS = [
    ["fetch", "Fetch source"], ["parse", "Read & OCR"], ["segment", "Split into clauses"],
    ["retrieve", "Rank evidence (BM25)"], ["extract", "Extract claims (LLM)"], ["verify", "Verify quotes + entailment"],
    ["finalize_claims", "Hallucination firewall"], ["compile_rules", "Compile rules (LLM)"],
    ["validate_rules", "Type-check rules"], ["explain", "Write explainer"], ["speak", "Synthesize voice"], ["store", "Store card"],
  ];

  async function renderHome() {
    mount("tpl-home");
    $("#lang").innerHTML = langOptions(uiLang);
    $("#lang").addEventListener("change", (e) => { uiLang = e.target.value; store.set("av-lang", uiLang); });
    const fileInput = $("#file");
    fileInput.addEventListener("change", () => {
      $("#file-name").textContent = fileInput.files[0] ? fileInput.files[0].name : "Upload a file";
      if (fileInput.files[0]) $("#url").value = "";
    });
    $("#compile-form").addEventListener("submit", (e) => { e.preventDefault(); startCompile(); });
    $$("[data-pulse]").forEach((b) => b.addEventListener("click", () => {
      $$("[data-pulse]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      loadPulse(b.dataset.pulse);
    }));
    loadPulse("en");
    loadRegister();
  }

  async function loadPulse(lang) {
    const list = $("#pulse-list");
    if (!list) return;
    list.innerHTML = '<li class="muted">Loading the live feed…</li>';
    try {
      const feed = await api(`/api/pulse?lang=${lang}`);
      $("#pulse-sub").textContent = `Live from pib.gov.in, fetched ${timeAgo(feed.fetched_at)}${feed.stale ? " (PIB is slow, showing the last copy)" : ""}.${feed.note ? " " + feed.note + "." : ""}`;
      list.innerHTML = feed.items.map((it, i) => `
        <li>
          <a class="pulse-title" href="${esc(safeUrl(it.link) || "#")}" target="_blank" rel="noopener" lang="${it.lang === "hi" ? "hi" : "en"}">${esc(it.title)}</a>
          <div class="pulse-meta"><span>${esc(timeAgo(it.published))}</span>
          <button class="link-btn" type="button" data-explain="${i}">Explain this release</button></div>
        </li>`).join("");
      $$("[data-explain]", list).forEach((b) => b.addEventListener("click", () => {
        const it = feed.items[+b.dataset.explain];
        $("#url").value = it.link;
        $("#file").value = "";
        $("#file-name").textContent = "Upload a file";
        startCompile();
        $("#compile-form").scrollIntoView({ behavior: "smooth", block: "start" });
      }));
    } catch (err) {
      list.innerHTML = `<li class="muted">${esc(err.message)} <button class="link-btn" type="button" id="pulse-retry">Try again</button></li>`;
      $("#pulse-retry")?.addEventListener("click", () => loadPulse(lang));
    }
  }

  async function loadRegister() {
    const el = $("#register");
    if (!el) return;
    try {
      const { policies } = await api("/api/policies");
      if (!policies.length) {
        el.innerHTML = '<div class="empty">Nothing compiled yet. Paste a link above, upload a PDF, or pick a release from today\'s PIB feed.</div>';
        return;
      }
      el.innerHTML = `<table class="reg-table">
        <thead><tr><th scope="col">Document</th><th scope="col">Verified facts</th><th scope="col">Rules</th><th scope="col">Voice</th><th scope="col">Compiled</th></tr></thead>
        <tbody>${policies.map((p) => `<tr data-id="${esc(p.id)}">
          <td><a class="reg-title" href="#/policy/${esc(p.id)}">${esc(p.title)}</a>
              <span class="reg-sub">${esc([p.issuing_authority, p.jurisdiction].filter(Boolean).join(", ") || p.domain || "")}</span></td>
          <td><span class="num-ok">${p.verified}</span>${p.rejected ? ` <span class="small">(${p.rejected} rejected)</span>` : ""}</td>
          <td>${p.rules || "None"}</td>
          <td>${esc((p.languages || []).map((l) => (LANGS[l] || {}).native || l).join(", ") || "None")}</td>
          <td class="small">${esc(timeAgo(p.created_at))}</td></tr>`).join("")}</tbody></table>`;
      $$("tbody tr", el).forEach((tr) => tr.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        location.hash = `#/policy/${tr.dataset.id}`;
      }));
    } catch (err) {
      el.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  }

  async function startCompile() {
    const url = $("#url").value.trim();
    const file = $("#file").files[0];
    const errEl = $("#compile-error");
    errEl.hidden = true;
    if (!url && !file) {
      errEl.textContent = "Paste a link to a government document or upload a file.";
      errEl.hidden = false;
      $("#url").focus();
      return;
    }
    const fd = new FormData();
    if (file) fd.append("file", file); else fd.append("url", url);
    fd.append("lang", $("#lang").value);
    const btn = $("#compile-btn");
    btn.disabled = true;
    btn.textContent = "Compiling…";
    $("#compile-form").classList.add("untied");
    try {
      const { job_id } = await api("/api/compile", { method: "POST", body: fd });
      followJob(job_id);
    } catch (err) {
      errEl.textContent = err.message;
      errEl.hidden = false;
      resetCompileButton();
    }
  }

  function resetCompileButton(retie = true) {
    const btn = $("#compile-btn");
    if (!btn) return;
    btn.disabled = false;
    btn.textContent = "Compile document";
    if (retie) $("#compile-form")?.classList.remove("untied");
  }

  function followJob(jobId) {
    const box = $("#trace");
    box.hidden = false;
    box.innerHTML = `<div class="trace-head"><h2>Agent at work</h2><span class="small" id="trace-clock">0 s</span></div>
      <ol class="steps" id="steps">${STEPS.map(([k, label]) => `<li class="step pending" data-node="${k}"><span class="step-title">${esc(label)}</span><span class="step-ms"></span><div class="step-detail"></div><div class="step-evs"></div></li>`).join("")}</ol>
      <div class="trace-actions" id="trace-actions"></div>`;
    const steps = $("#steps");
    let current = null;
    let lastSeq = 0;
    let finished = false;
    const t0 = Date.now();
    const clock = setInterval(() => { const c = $("#trace-clock"); if (c && !finished) c.textContent = `${Math.round((Date.now() - t0) / 1000)} s`; }, 500);

    function rowFor(node, label) {
      let row = $$(`[data-node="${node}"]`, steps).pop();
      if (row && !row.classList.contains("pending")) {
        const again = row.cloneNode(true);
        again.className = "step pending";
        $(".step-title", again).textContent = `${label} (again)`;
        $(".step-ms", again).textContent = "";
        $(".step-detail", again).textContent = "";
        $(".step-evs", again).innerHTML = "";
        (current || row).after(again);
        row = again;
      } else if (!row) {
        row = document.createElement("li");
        row.className = "step pending";
        row.dataset.node = node;
        row.innerHTML = `<span class="step-title">${esc(label)}</span><span class="step-ms"></span><div class="step-detail"></div><div class="step-evs"></div>`;
        (current || steps.lastElementChild).after(row);
      }
      return row;
    }

    function handle(ev) {
      if (ev.seq) lastSeq = Math.max(lastSeq, ev.seq);
      if (ev.type === "node") {
        if (ev.status === "start") {
          current = rowFor(ev.node, ev.label);
          current.className = "step running";
        } else {
          const row = current && current.dataset.node === ev.node ? current : rowFor(ev.node, ev.label);
          row.className = `step ${ev.status === "error" ? "error" : "done"}`;
          $(".step-ms", row).textContent = ev.ms != null ? `${(ev.ms / 1000).toFixed(1)} s` : "";
          $(".step-detail", row).textContent = ev.detail || "";
        }
      } else if (["llm", "tool", "guard", "info"].includes(ev.type) && current) {
        if (ev.type === "llm" && ev.status === "ok" && !ev.detail) {
          addEv(`${ev.task}: ${ev.provider} ${ev.model}, ${(ev.ms / 1000).toFixed(1)} s`, "llm");
        } else if (ev.type === "llm") {
          addEv(`${ev.task}: ${ev.provider} ${ev.model} ${ev.status === "repair" ? "" : "unavailable, switching"} (${ev.detail || ev.status})`, ev.status === "repair" ? "llm" : "failover");
        } else {
          addEv(ev.detail || "", ev.type === "info" ? "" : ev.type);
        }
      } else if (ev.type === "end") {
        finish(ev);
      }
    }
    function addEv(text, cls) {
      const d = document.createElement("div");
      d.className = `ev ${cls}`;
      d.textContent = text;
      $(".step-evs", current).append(d);
    }
    function finish(ev) {
      if (finished) return;
      finished = true;
      clearInterval(clock);
      resetCompileButton(ev.status !== "done");
      $$(".step.pending", steps).forEach((r) => { if (ev.status === "done") r.remove(); });
      const act = $("#trace-actions");
      if (ev.status === "done" && ev.result) {
        act.innerHTML = `<a class="btn btn-primary" href="#/policy/${esc(ev.result.policy_id)}">Open the Rights Card</a>`;
        $("a", act).focus();
        loadRegister();
      } else {
        act.innerHTML = `<p class="form-error">${esc(ev.error || "Compilation failed.")}</p>`;
      }
    }

    // Live stream with a polling fallback if the connection drops.
    let es;
    try { es = new EventSource(`/api/jobs/${jobId}/events`); } catch { es = null; }
    if (!es) return poll();
    es.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch { /* ignore malformed */ } if (finished) es.close(); };
    es.onerror = () => { if (!finished) { es.close(); poll(); } };

    async function poll() {
      while (!finished) {
        try {
          const snap = await api(`/api/jobs/${jobId}?after=${lastSeq}`);
          snap.events.forEach(handle);
          if (snap.status === "done" || snap.status === "error") { finish({ status: snap.status, result: snap.result, error: snap.error }); }
        } catch (err) {
          finish({ status: "error", error: err.message });
        }
        await new Promise((r) => setTimeout(r, 1200));
      }
    }
  }

  // ============================================================= POLICY ==
  const GROUPS = [
    ["benefit", "What you get"], ["right", "Your rights"], ["eligibility", "Who can apply"],
    ["exclusion", "Who cannot apply"], ["document", "Papers you need"], ["process", "How to apply"],
    ["deadline", "Dates and time limits"], ["obligation", "Duties"], ["penalty", "Penalties"],
    ["impact", "Other effects"], ["other", "Other facts"],
  ];
  const METHOD = { exact: "exact quote", fuzzy: "close match", relocated: "found in another clause", normalised: "matched after fixing the PDF's Hindi text order" };
  const OPS = { "==": "=", "!=": "≠", ">=": "≥", "<=": "≤", ">": ">", "<": "<", in: "is one of", not_in: "is not one of" };

  function condText(c) {
    if (!c || typeof c !== "object") return "";
    if (c.all) return c.all.map(condText).join(" and ");
    if (c.any) return "(" + c.any.map(condText).join(" or ") + ")";
    if (c.not) return "not (" + condText(c.not) + ")";
    const v = Array.isArray(c.value) ? c.value.join(", ") : String(c.value);
    return `${c.var} ${OPS[c.op] || c.op} ${v}`;
  }

  async function renderPolicy(id) {
    mount("tpl-policy");
    const cardEl = $("#card");
    cardEl.innerHTML = '<p class="muted">Opening the Rights Card…</p>';
    let card;
    try { card = await api(`/api/policies/${id}`); } catch (err) {
      cardEl.innerHTML = `<a class="back" href="#/">Back to the register</a><p class="form-error">${esc(err.message)}</p>`;
      return;
    }
    const clauses = Object.fromEntries((card.clauses || []).map((c) => [c.id, c]));
    const src = card.source || {};
    const srcLang = src.language && src.language !== "en" ? ` lang="${esc(src.language)}"` : "";
    const st = card.stats || {};
    const badges = [
      src.official ? `<span class="badge ok">Official source: ${esc(src.domain)}</span>` : src.domain ? `<span class="badge warn">Not a government domain: ${esc(src.domain)}</span>` : `<span class="badge">Uploaded file</span>`,
      src.ocr_used ? `<span class="badge">Read with OCR (${src.ocr_pages} page${src.ocr_pages === 1 ? "" : "s"})</span>` : "",
      src.tls_verified === false ? `<span class="badge warn">Site certificate incomplete</span>` : "",
      card.is_policy_document === false ? `<span class="badge warn">May not be a policy document</span>` : "",
    ].join("");
    const groups = GROUPS.map(([kind, label]) => {
      const items = (card.claims || []).filter((c) => c.kind === kind);
      if (!items.length) return "";
      return `<section class="group"><h2>${label}</h2><ul class="facts">${items.map((c) => {
        const cl = clauses[c.clause_id] || {};
        const v = c.verification || {};
        const how = v.corrected ? '<span class="fixed">Repaired by the agent, then verified</span>' : `Verified: ${METHOD[v.method] || "quote found"}`;
        return `<li class="fact"><p class="fact-text">${esc(c.text)}</p>
          <blockquote class="proof"${srcLang}>${esc(c.quote)}
          <span class="proof-ref">Page ${esc(cl.page ?? "?")}, clause ${esc(c.clause_id)}${cl.section ? ` (${esc(cl.section)})` : ""}. ${how}.</span></blockquote></li>`;
      }).join("")}</ul></section>`;
    }).join("");
    const vars = Object.fromEntries((card.variables || []).map((v) => [v.name, v]));
    const rules = (card.rules || []).map((r) => `<div class="rule"><strong>${esc(r.id)}</strong> ${r.kind === "exclusion" ? "Excluded if" : "Requires"}: ${esc(r.description)}
        <div><code class="code">${esc(condText(r.condition))}</code></div>
        <div class="small">From fact ${esc(r.claim_id)}, clause ${esc(r.clause_id)}${Object.keys(vars).length ? "" : ""}</div></div>`).join("");
    const newVars = (card.variables || []).map((v) => `<li><code class="code">${esc(v.name)}</code> ${esc(v.question)}</li>`).join("");
    const rejected = (card.rejected || []).map((r) => `<div class="rejected-item"><s>${esc(r.text)}</s><span class="why">${esc(r.reason)}</span></div>`).join("");
    const srcLink = safeUrl(src.final_url || src.url);

    cardEl.innerHTML = `
      <a class="back" href="#/">Back to the register</a>
      <h1>${esc(card.title)}</h1>
      <p class="card-meta">${esc([card.issuing_authority, card.jurisdiction && `applies to ${card.jurisdiction}`, card.effective_date && `effective ${card.effective_date}`].filter(Boolean).join(", "))}</p>
      <div class="badges">${badges}</div>
      <div class="stamp" role="group" aria-label="Verification result">
        <div class="v"><strong>${st.verified ?? (card.claims || []).length}</strong><span>facts verified</span></div>
        <div class="c"><strong>${st.corrected ?? 0}</strong><span>repaired by the agent</span></div>
        <div class="r"><strong>${st.rejected ?? (card.rejected || []).length}</strong><span>rejected, not shown</span></div>
      </div>
      <p class="stamp-caption">Every fact below is shown with the exact words from the document that prove it.</p>
      ${card.summary ? `<p class="summary">${esc(card.summary)}</p>` : ""}
      ${(card.audience || []).length ? `<p class="small">Affects: ${esc(card.audience.join("; "))}</p>` : ""}
      ${(card.warnings || []).map((w) => `<p class="msg sys">${esc(w)}</p>`).join("")}
      ${groups}
      ${rules ? `<details class="more" open><summary>Eligibility as code (${card.rules.length} rules)</summary>
        <p class="small">These typed rules are what the assistant evaluates. No AI is involved in the verdict.</p>${rules}
        ${newVars ? `<p class="small">Extra facts this document needs:</p><ul class="small">${newVars}</ul>` : ""}</details>` : ""}
      ${rejected ? `<details class="more"><summary>Rejected by the verifier (${card.rejected.length})</summary>
        <p class="small">The AI proposed these, but the document does not say them, so they are not shown above.</p>${rejected}</details>` : ""}
      <p class="src">Source: ${srcLink ? `<a href="${esc(srcLink)}" target="_blank" rel="noopener">${esc(srcLink)}</a>` : esc(src.filename || "uploaded file")}.
        ${src.followed_from ? `Reached from ${esc(src.followed_from)}. ` : ""}Read ${esc(src.pages)} page(s) on ${esc(new Date(src.fetched_at).toLocaleString("en-IN"))}.
        Document fingerprint (SHA-256) ${esc((src.sha256 || "").slice(0, 16))}…
        Compiled in ${esc(st.seconds)} s with ${esc(st.llm_calls)} AI calls${(card.models_used || []).length ? ` (${esc(card.models_used.join(", "))})` : ""}.</p>`;

    renderVoicePanel(card);
  }

  function renderVoicePanel(card) {
    const el = $("#voice");
    const have = Object.keys(card.explainers || {});
    let lang = have.includes(uiLang) ? uiLang : (have[0] || uiLang);
    el.innerHTML = `
      <p class="voice-title">${esc(card.title)}</p>
      <section class="panel listen">
        <h2>Listen</h2>
        <div class="panel-row"><select id="ex-lang" aria-label="Explainer language">${langOptions(lang)}</select>
          <button class="btn btn-small btn-primary" id="ex-go" type="button">Play explainer</button></div>
        <audio id="ex-audio" controls hidden></audio>
        <p class="small" id="ex-status"></p>
        <div class="explainer-text" id="ex-text"></div>
      </section>
      <section class="panel" id="agent"></section>`;
    const show = (ex) => {
      $("#ex-text").innerHTML = ex ? `<strong>${esc(ex.title)}</strong><p>${esc(ex.script)}</p>${(ex.warnings || []).map((w) => `<p class="small">${esc(w)}</p>`).join("")}` : "";
      const a = $("#ex-audio");
      if (ex && ex.audio) { a.src = `/audio/${ex.audio}`; a.hidden = false; } else { a.hidden = true; a.removeAttribute("src"); }
      $("#ex-go").hidden = Boolean(ex && ex.audio);
      $("#ex-go").textContent = ex ? "Try the voice again" : `Make the ${LANGS[lang]?.name || ""} explainer`;
    };
    show(card.explainers?.[lang]);
    $("#ex-lang").addEventListener("change", (e) => { lang = e.target.value; show(card.explainers?.[lang]); $("#ex-status").textContent = ""; });
    $("#ex-go").addEventListener("click", async () => {
      const btn = $("#ex-go");
      btn.disabled = true;
      $("#ex-status").textContent = `Writing and checking the ${LANGS[lang]?.name} explainer…`;
      try {
        const fd = new FormData();
        fd.append("lang", lang);
        const res = await api(`/api/policies/${card.id}/explain`, { method: "POST", body: fd });
        card.explainers = card.explainers || {};
        card.explainers[lang] = res.explainer;
        show(res.explainer);
        const guard = (res.events || []).find((e) => e.type === "guard");
        $("#ex-status").textContent = guard ? guard.detail : "";
        if (res.explainer.audio) $("#ex-audio").play().catch(() => {});
      } catch (err) {
        $("#ex-status").textContent = err.message;
      } finally { btn.disabled = false; }
    });
    mountAgent($("#agent"), { mode: "policy", policyId: card.id, hasRules: (card.rules || []).length > 0 });
  }

  // ============================================================== AGENT ==
  function mountAgent(el, { mode, policyId, hasRules = true, onTurn }) {
    el.classList.add("panel");
    el.innerHTML = `
      <h2>${mode === "radar" ? "Tell the assistant about yourself" : "Check if you qualify"}</h2>
      <p class="small">${hasRules ? "Speak in your language or type. It asks only what it needs and never stores your answers." : "This document has no eligibility rules, but you can still ask questions about it."}</p>
      <div class="panel-row"><label class="small">Language <select class="agent-lang">${langOptions(uiLang)}</select></label>
        <button class="btn btn-small agent-start" type="button">${mode === "radar" ? "Start" : "Start the check"}</button></div>
      <div class="chat" aria-live="polite"></div>
      <div class="composer">
        <button class="mic" type="button" aria-label="Record your answer">${MIC_SVG}</button>
        <input type="text" class="agent-text" placeholder="Or type here" aria-label="Type your answer">
        <button class="btn btn-small agent-send" type="button">Send</button>
      </div>
      <div class="verdict-box"></div>
      <ul class="checklist"></ul>`;
    const chat = $(".chat", el);
    let state = {};
    let busy = false;
    let lang = uiLang;
    $(".agent-lang", el).addEventListener("change", (e) => { lang = e.target.value; });

    const add = (cls, html) => {
      const d = document.createElement("div");
      d.className = `msg ${cls}`;
      d.innerHTML = html;
      chat.append(d);
      chat.scrollTop = chat.scrollHeight;
      return d;
    };

    async function turn({ text = "", blob = null }) {
      if (busy) return;
      busy = true;
      setBusy(true);
      const mine = text ? add("me", esc(text)) : blob ? add("me", "<em>Listening to your recording…</em>") : null;
      const fd = new FormData();
      fd.append("mode", mode);
      if (policyId) fd.append("policy_id", policyId);
      fd.append("lang", lang);
      fd.append("text", text);
      fd.append("state", JSON.stringify(state));
      if (blob) fd.append("audio", blob, blob.type.includes("mp4") ? "speech.m4a" : blob.type.includes("ogg") ? "speech.ogg" : "speech.webm");
      const thinking = add("bot", "<em>Thinking…</em>");
      try {
        const res = await api("/api/agent/turn", { method: "POST", body: fd });
        state = res.state;
        if (mine && blob) mine.innerHTML = esc(res.transcript || "(nothing heard)");
        const chips = (res.facts || []).map((f) => `<span class="chip">${esc(f.var.replace(/_/g, " "))}: ${esc(fmt(f.value))}</span>`)
          .concat((res.rejected_facts || []).map((f) => `<span class="chip no" title="${esc(f.reason)}">ignored: ${esc(f.var.replace(/_/g, " "))}</span>`)).join("");
        if (chips && mine) mine.insertAdjacentHTML("beforeend", `<div class="facts-chips">${chips}</div>`);
        thinking.innerHTML = esc(res.say);
        if (res.say_lang && res.say_lang !== "en") thinking.lang = res.say_lang;
        play(res.audio_url);
        if (mode === "policy") renderEval(res.evaluations[0]);
        if (onTurn) onTurn(res);
      } catch (err) {
        thinking.remove();
        add("sys", esc(err.message));
        if (mine && blob) mine.remove();
      } finally {
        busy = false;
        setBusy(false);
      }
    }

    function fmt(v) { return v === true ? "yes" : v === false ? "no" : typeof v === "number" ? v.toLocaleString("en-IN") : String(v); }

    function renderEval(ev) {
      if (!ev) return;
      const label = { eligible: "You meet every condition we checked.", not_eligible: "You do not meet at least one condition.",
        needs_info: "Still checking: a few answers are needed.", no_rules: "No eligibility rules in this document." }[ev.status];
      $(".verdict-box", el).innerHTML = `<div class="verdict ${ev.status}">${label}</div>`;
      $(".checklist", el).innerHTML = ev.rules.map((r) => {
        const m = r.passes === true ? ["yes", "✓", "met"] : r.passes === false ? ["no", "✗", "not met"] : ["unk", "?", "unknown"];
        return `<li><span class="mark ${m[0]}" aria-label="${m[2]}">${m[1]}</span><span>${esc(r.description)} <span class="small">(${esc(r.clause_id)})</span></span></li>`;
      }).join("");
    }

    function setBusy(b) {
      $$(".agent-send, .agent-start, .mic", el).forEach((x) => { if (!(x.classList.contains("mic") && rec)) x.disabled = b; });
    }

    $(".agent-start", el).addEventListener("click", () => { state = {}; chat.innerHTML = ""; turn({}); });
    const send = () => { const t = $(".agent-text", el).value.trim(); if (!t) return; $(".agent-text", el).value = ""; turn({ text: t }); };
    $(".agent-send", el).addEventListener("click", send);
    $(".agent-text", el).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); send(); } });

    // --- microphone: tap to start, tap again to send (auto-stops at 30 s)
    let rec = null, chunks = [], stopTimer = null;
    const mic = $(".mic", el);
    mic.addEventListener("click", async () => {
      if (rec) { rec.stop(); return; }
      if (busy) return;
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        add("sys", "This browser can't record audio. Please type instead.");
        return;
      }
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch {
        add("sys", "Microphone permission was blocked. Allow it in the address bar, or type instead.");
        return;
      }
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported?.(t));
      rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = () => {
        clearTimeout(stopTimer);
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        rec = null;
        mic.classList.remove("rec");
        mic.innerHTML = MIC_SVG;
        mic.setAttribute("aria-label", "Record your answer");
        if (blob.size < 1200) { add("sys", "That recording was too short. Tap the microphone, speak, then tap again."); return; }
        turn({ blob });
      };
      stopAudio();
      rec.start();
      mic.classList.add("rec");
      mic.innerHTML = STOP_SVG;
      mic.setAttribute("aria-label", "Stop and send");
      stopTimer = setTimeout(() => rec && rec.stop(), 30000);
    });
    return { turn };
  }

  // ============================================================== RADAR ==
  async function renderRadar() {
    mount("tpl-radar");
    const results = $("#radar-results");
    let policies = [];
    try { policies = (await api("/api/policies")).policies.filter((p) => p.rules > 0); } catch (err) {
      results.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
    if (!policies.length) {
      results.innerHTML = '<div class="empty">No compiled scheme has eligibility rules yet. Compile a scheme\'s guidelines on the Compile page first, then come back.</div>';
      $("#radar-voice").innerHTML = "";
      return;
    }
    const draw = (evals) => {
      const byId = Object.fromEntries((evals || []).map((e) => [e.policy_id, e]));
      const order = { eligible: 0, needs_info: 1, not_eligible: 2, no_rules: 3 };
      const rows = policies.map((p) => ({ p, e: byId[p.id] })).sort((a, b) => (order[a.e?.status] ?? 1) - (order[b.e?.status] ?? 1));
      results.innerHTML = `<h2>${policies.length} scheme${policies.length === 1 ? "" : "s"} checked at once</h2>` + rows.map(({ p, e }) => {
        const status = e?.status || "needs_info";
        const label = { eligible: "Looks eligible", not_eligible: "Not eligible", needs_info: e ? `Needs ${e.missing.length} more answer${e.missing.length === 1 ? "" : "s"}` : "Not checked yet" }[status] || status;
        const why = e && status === "not_eligible" ? e.rules.filter((r) => r.passes === false).map((r) => esc(r.description)).join("; ") : "";
        return `<div class="radar-item ${status}"><a href="#/policy/${esc(p.id)}">${esc(p.title)}</a>
          <div class="radar-status">${label}</div>${why ? `<div class="small">${why}</div>` : ""}</div>`;
      }).join("");
    };
    draw([]);
    mountAgent($("#radar-voice"), { mode: "radar", onTurn: (res) => draw(res.evaluations) });
  }

  // ================================================================ HOW ==
  async function renderHow() {
    mount("tpl-how");
    try {
      const { mermaid: src } = await api("/api/graph");
      if (!window.mermaid) {
        await new Promise((ok, fail) => {
          const s = document.createElement("script");
          s.src = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js";
          s.onload = ok; s.onerror = fail;
          document.head.append(s);
        });
        window.mermaid.initialize({ startOnLoad: false, theme: "base", themeVariables: {
          primaryColor: "#E6E5F3", primaryTextColor: "#2B2A6E", primaryBorderColor: "#2B2A6E", lineColor: "#59616B", fontFamily: "Mukta" } });
      }
      const { svg } = await window.mermaid.render("pipeline-graph", src);
      $("#graph").innerHTML = svg;
    } catch {
      $("#graph").innerHTML = '<p class="muted">The diagram could not be drawn here. The pipeline is also described below.</p>';
    }
  }

  // ---------------------------------------------------------------- boot --
  loadHealth().then(route);
})();
