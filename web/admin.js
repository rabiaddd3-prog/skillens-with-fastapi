// SkillLens admin page: overview, job catalog, import log and question bank.
// The token is kept in sessionStorage (cleared when the tab closes) and sent as X-Admin-Token.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const locale = () => (LANG === "tr" ? "tr-TR" : "en-GB");
const num = (x, d = 0) => Number(x).toLocaleString(locale(), { minimumFractionDigits: d, maximumFractionDigits: d });
const when = (iso) => new Date(iso).toLocaleString(locale(), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const LEVELS = ["junior", "mid", "senior"];
const TOKEN_KEY = "skilllens-admin-token";

const adm = { view: "overview", stats: null, jobs: null, topicNames: {}, quizTopic: "python", quizLevel: "junior", jobFilter: "" };

async function api(path, opts = {}) {
  const headers = { "X-Lang": LANG, "X-Admin-Token": sessionStorage.getItem(TOKEN_KEY) || "" };
  if (opts.json) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method: opts.method || (opts.json ? "POST" : "GET"), headers, body: opts.json ? JSON.stringify(opts.json) : undefined });
  } catch {
    throw new Error(t("err.network"));
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    signOut(data.detail);
    throw new Error(data.detail);
  }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ------------------------------------------------------------ sign-in

function signedIn() {
  const on = !!sessionStorage.getItem(TOKEN_KEY);
  $("#adm-login").hidden = on;
  $("#adm-tabs").hidden = !on;
  $("#adm-logout").hidden = !on;
  return on;
}

function signOut(message) {
  sessionStorage.removeItem(TOKEN_KEY);
  signedIn();
  $$(".adm-view").forEach((v) => { v.hidden = true; });
  if (message) say(message, "error");
}

function say(text, kind = "") {
  const el = $("#adm-msg");
  el.className = `msg ${kind}`;
  el.textContent = text;
}

$("#adm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  sessionStorage.setItem(TOKEN_KEY, $("#adm-token").value.trim());
  $("#adm-token").value = "";
  try {
    await api("/admin/api/stats");
    say("");
    signedIn();
    show(adm.view);
  } catch { /* api() already signed out and showed the message */ }
});
$("#adm-logout").addEventListener("click", () => signOut());

// ------------------------------------------------------------ views

function show(view) {
  adm.view = view;
  $$("#adm-tabs .tab").forEach((x) => x.classList.toggle("active", x.dataset.view === view));
  $$(".adm-view").forEach((v) => { v.hidden = v.id !== `adm-${view}`; });
  ({ overview: loadOverview, jobs: loadJobs, imports: loadImports, quiz: loadQuiz })[view]();
}
$$("#adm-tabs .tab").forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.view)));

function fail(box, err) {
  box.innerHTML = `<div class="card"><p class="msg error">${esc(err.message)}</p></div>`;
}

const topicName = (tp) => adm.topicNames[tp] || tp;

async function loadOverview() {
  const box = $("#adm-overview");
  try {
    const [s, topics] = await Promise.all([api("/admin/api/stats"), api("/quiz/topics")]);
    adm.stats = s;
    adm.topicNames = topics.names;
    const up = Math.floor(s.uptime_s / 60);
    const tiles = [
      [s.model || t("adm.none"), t("adm.st_model", { models: s.models.join(", ") || t("adm.none") })],
      [`${num(s.extracted)} / ${num(s.jobs)}`, t("adm.st_jobs")],
      [num(s.quiz_sessions), t("adm.st_sessions")],
      [t("adm.uptime_v", { h: Math.floor(up / 60), m: up % 60 }), t("adm.st_uptime")],
    ];
    const bankTotal = (lv) => Object.values(s.quiz_bank).reduce((a, r) => a + r[lv], 0);
    box.innerHTML = `
      <div class="panel-head"><h2>${esc(t("adm.tab_overview"))}</h2>${s.model_error ? `<p class="msg error">${esc(s.model_error)}</p>` : ""}</div>
      <section class="stats">${tiles.map(([v, l]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}</section>
      <div class="adm-cols">
        <div class="card"><h3>${esc(t("adm.by_source"))}</h3>
          <table class="table"><thead><tr><th>${esc(t("adm.col_source"))}</th><th class="n">${esc(t("adm.col_count"))}</th></tr></thead>
          <tbody>${Object.entries(s.by_source).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${num(v)}</td></tr>`).join("")}</tbody></table></div>
        <div class="card"><h3>${esc(t("adm.bank"))}</h3>
          <table class="table"><thead><tr><th>${esc(t("adm.col_topic"))}</th>${LEVELS.map((lv) => `<th class="n">${esc(t(`lv.${lv}`))}</th>`).join("")}</tr></thead>
          <tbody>${Object.entries(s.quiz_bank).map(([tp, r]) => `<tr><td>${esc(topicName(tp))}</td>${LEVELS.map((lv) => `<td class="n">${r[lv]}</td>`).join("")}</tr>`).join("")}
          <tr class="total"><td>${esc(t("adm.total"))}</td>${LEVELS.map((lv) => `<td class="n">${bankTotal(lv)}</td>`).join("")}</tr></tbody></table></div>
      </div>
      <div class="card"><h3>${esc(t("adm.usage"))}</h3><p class="hint">${esc(t("adm.usage_hint"))}</p>
        ${s.usage.length ? `<table class="table"><thead><tr><th>${esc(t("adm.col_route"))}</th><th class="n">${esc(t("adm.col_calls"))}</th><th class="n">${esc(t("adm.col_errors"))}</th><th class="n">${esc(t("adm.col_avg"))}</th></tr></thead>
        <tbody>${s.usage.map((u) => `<tr><td><code>${esc(u.route)}</code></td><td class="n">${num(u.count)}</td><td class="n ${u.errors ? "bad" : ""}">${num(u.errors)}</td><td class="n">${num(u.avg_ms, 1)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="empty">${esc(t("adm.no_usage"))}</p>`}</div>`;
  } catch (e) { fail(box, e); }
}

async function loadJobs() {
  const box = $("#adm-jobs");
  try {
    adm.jobs = await api("/admin/api/jobs");
    drawJobs();
  } catch (e) { fail(box, e); }
}

function drawJobs() {
  const box = $("#adm-jobs");
  const q = adm.jobFilter.toLowerCase();
  const rows = adm.jobs.filter((j) => `${j.id} ${j.title} ${j.company} ${j.source}`.toLowerCase().includes(q));
  box.innerHTML = `
    <div class="panel-head"><h2>${esc(t("adm.tab_jobs"))}</h2><p>${esc(t("adm.jobs_hint"))}</p></div>
    <div class="card">
      <input id="adm-job-filter" value="${esc(adm.jobFilter)}" placeholder="${esc(t("adm.filter"))}">
      <p class="msg" id="adm-job-msg" role="status"></p>
      <div class="table-wrap"><table class="table adm-jobs"><thead><tr><th>ID</th><th>${esc(t("adm.col_title"))}</th><th>${esc(t("adm.col_source"))}</th><th class="n">${esc(t("adm.col_skills"))}</th><th>${esc(t("adm.col_model"))}</th><th>${esc(t("adm.col_imported"))}</th><th></th></tr></thead>
      <tbody>${rows.map((j) => `<tr data-id="${j.id}">
        <td>${j.id}</td>
        <td><strong>${j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>` : esc(j.title)}</strong><br><span class="meta">${esc(j.company || "—")}</span></td>
        <td>${j.is_demo ? `<span class="badge demo">${esc(t("badge.demo"))}</span>` : `<span class="badge live">${esc(j.source)}</span>`}</td>
        <td class="n" title="${esc(j.skills.join(", "))}">${j.skills.length}</td>
        <td>${esc(j.extracted_by || "—")}</td>
        <td>${esc(when(j.imported_at))}</td>
        <td class="actions"><button class="btn ghost small" data-act="reextract">${esc(t("adm.reextract"))}</button><button class="btn ghost small danger" data-act="delete">${esc(t("adm.delete"))}</button></td>
      </tr>`).join("") || `<tr><td colspan="7" class="empty">${esc(t("adm.no_rows"))}</td></tr>`}</tbody></table></div>
    </div>`;
  const filter = $("#adm-job-filter");
  filter.addEventListener("input", () => {
    adm.jobFilter = filter.value;
    const pos = filter.selectionStart;
    drawJobs();
    const f = $("#adm-job-filter");
    f.focus();
    f.setSelectionRange(pos, pos);
  });
  $$("button[data-act]", box).forEach((b) => b.addEventListener("click", () => jobAction(b)));
}

async function jobAction(button) {
  const id = +button.closest("tr").dataset.id;
  const job = adm.jobs.find((j) => j.id === id);
  const msg = $("#adm-job-msg");
  if (button.dataset.act === "delete" && !confirm(t("adm.confirm_delete", { title: job.title }))) return;
  button.disabled = true;
  try {
    if (button.dataset.act === "delete") {
      await api(`/admin/api/jobs/${id}`, { method: "DELETE" });
      adm.jobs = adm.jobs.filter((j) => j.id !== id);
      drawJobs();
      $("#adm-job-msg").className = "msg ok";
      $("#adm-job-msg").textContent = t("adm.deleted", { title: job.title });
    } else {
      const r = await api(`/admin/api/jobs/${id}/reextract`, { method: "POST" });
      job.skills = r.skills;
      job.extracted_by = adm.stats?.model || job.extracted_by;
      drawJobs();
      $("#adm-job-msg").className = "msg ok";
      $("#adm-job-msg").textContent = t("adm.reextracted", { title: job.title, n: r.skills.length, ms: num(r.ms, 0) });
    }
  } catch (e) {
    msg.className = "msg error";
    msg.textContent = e.message;
    button.disabled = false;
  }
}

async function loadImports() {
  const box = $("#adm-imports");
  try {
    const log = await api("/admin/api/imports");
    box.innerHTML = `
      <div class="panel-head"><h2>${esc(t("adm.tab_imports"))}</h2><p>${esc(t("adm.imports_hint"))}</p></div>
      <div class="card">${log.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>${esc(t("adm.col_time"))}</th><th>${esc(t("adm.col_source"))}</th><th>${esc(t("adm.col_board"))}</th><th>${esc(t("adm.col_status"))}</th><th class="n">${esc(t("adm.col_new"))}</th><th class="n">${esc(t("adm.col_updated"))}</th><th class="n">${esc(t("adm.col_same"))}</th></tr></thead>
        <tbody>${log.map((e) => `<tr><td>${esc(when(e.at))}</td><td>${esc(e.source)}</td><td>${esc(e.board || "—")}</td>
          <td>${e.status === "ok" ? `<span class="st cv_and_quiz">${esc(t("adm.ok"))}</span>` : `<span class="st weak_quiz" title="${esc(e.message || "")}">${esc(t("adm.error"))}</span><br><span class="meta">${esc(e.message || "")}</span>`}</td>
          <td class="n">${e.created}</td><td class="n">${e.updated}</td><td class="n">${e.unchanged}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="empty">${esc(t("adm.no_imports"))}</p>`}</div>`;
  } catch (e) { fail(box, e); }
}

async function loadQuiz() {
  const box = $("#adm-quiz");
  try {
    if (!Object.keys(adm.topicNames).length) adm.topicNames = (await api("/quiz/topics")).names;
    const qs = await api(`/admin/api/quiz?topic=${encodeURIComponent(adm.quizTopic)}&level=${adm.quizLevel}`);
    const letters = "ABCD";
    box.innerHTML = `
      <div class="panel-head"><h2>${esc(t("adm.tab_quiz"))}</h2><p>${esc(t("adm.quiz_hint"))}</p></div>
      <div class="card adm-quiz-filter">
        <label>${esc(t("adm.col_topic"))} <select id="adm-topic">${Object.entries(adm.topicNames).map(([k, v]) => `<option value="${esc(k)}" ${k === adm.quizTopic ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <label>${esc(t("adm.col_level"))} <select id="adm-level">${LEVELS.map((lv) => `<option value="${lv}" ${lv === adm.quizLevel ? "selected" : ""}>${esc(t(`lv.${lv}`))}</option>`).join("")}</select></label>
        <span class="meta">${esc(t("adm.n_questions", { n: qs.length }))}</span>
      </div>
      ${qs.map((q, i) => `<div class="card adm-q">
        <div class="q-meta"><span>${i + 1}. <code>${esc(q.id)}</code></span><span class="tag">${esc(topicName(q.topic))} · ${esc(t(`lv.${q.level}`))}</span></div>
        <pre class="q-text">${esc(q.question)}</pre>
        <ol class="adm-options">${q.options.map((o, k) => `<li class="${k === q.answer ? "right" : ""}"><b>${letters[k]}</b> ${esc(o)}${k === q.answer ? ` <span class="cj-yes">✓ ${esc(t("adm.correct"))}</span>` : ""}</li>`).join("")}</ol>
        <p class="hint">${esc(q.explanation)}</p></div>`).join("")}`;
    $("#adm-topic").addEventListener("change", (e) => { adm.quizTopic = e.target.value; loadQuiz(); });
    $("#adm-level").addEventListener("change", (e) => { adm.quizLevel = e.target.value; loadQuiz(); });
  } catch (e) { fail(box, e); }
}

// ------------------------------------------------------------ theme and language

function setThemeLabel() {
  $("#theme-toggle").textContent = t(document.documentElement.dataset.theme === "dark" ? "theme.light" : "theme.dark");
}
$("#theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("skilllens-theme", next);
  setThemeLabel();
});
$("#lang-toggle").addEventListener("click", () => setLang(LANG === "en" ? "tr" : "en"));
document.addEventListener("langchange", () => {
  document.title = t("adm.page_title");
  setThemeLabel();
  adm.topicNames = {};
  if (signedIn()) show(adm.view);
});

applyI18n();
document.title = t("adm.page_title");
setThemeLabel();
if (signedIn()) show("overview");
