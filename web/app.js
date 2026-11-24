// SkillLens frontend. Plain JS, talks to the FastAPI backend on the same origin.
// The CV text never leaves this page except for the analysis request; nothing is saved.
// All interface text comes from i18n.js via t(); the language is sent to the API as X-Lang.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Turkish writes the percent sign first (%20), English after (20%).
const fmtPct = (n) => (LANG === "tr" ? `%${n}` : `${n}%`);
const pct = (x) => (x === null || x === undefined ? "–" : fmtPct(Math.round(x * 100)));

const state = {
  dictionary: { topics: {}, skills: [] },
  cvCandidates: [],     // [{skill, evidence, topic, added?}]
  cvSkills: [],         // confirmed
  jobs: [],
  jobId: null,
  job: null,            // selected job with extraction
  quiz: null,           // running quiz {session_id, questions, answers, i}
  quizScores: {},       // {topic: {correct,total,ratio,level}}
  lastResult: null,     // last quiz result, re-rendered on language change
  roadmapJobId: null,
  lastCompare: null,    // last side-by-side model run {text, res}
  ranking: null,        // last /matches ranking (profile panel: best match)
  roadmap: null,        // {jobId, title, ids} of the roadmap on screen (profile panel: progress)
  comparison: null,     // /results/comparison (home page numbers)
  homeDemo: null,       // extraction of the home page sample sentence
  rail: {},             // step -> {key, vars, done}, re-rendered on language change
  health: null,
};

const STATUSES = ["cv_and_quiz", "cv_only", "quiz_only", "weak_quiz", "missing"];
const levelName = (level) => t(`lv.${level}`);

async function api(path, opts = {}) {
  const init = { ...opts, headers: { "X-Lang": LANG, ...(opts.headers || {}) } };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error(t("err.network"));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `HTTP ${res.status}`);
  }
  return data;
}

function say(el, text, kind = "") {
  el.textContent = text;
  el.className = `msg ${kind}`;
}

async function busy(btn, fn) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = t("busy");
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = label; }
}

// ------------------------------------------------------------ navigation

let currentStep = 1;

function go(step) {
  if (!$("#flow").classList.contains("active")) showView("flow");
  const forward = step >= currentStep;
  currentStep = step;
  $$(".rail-step").forEach((li) => li.classList.toggle("active", +li.dataset.step === step));
  $(".rail").style.setProperty("--progress", (step - 1) / 4);
  $$("#flow .panel").forEach((p) => {
    const on = p.id === `step-${step}`;
    p.classList.toggle("active", on);
    p.classList.remove("enter-right", "enter-left");
    if (on) { void p.offsetWidth; p.classList.add(forward ? "enter-right" : "enter-left"); }  // restart the animation
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (step === 3) { renderTopicPick(); renderHistory(); }
  if (step === 4) loadMatches();
  if (step === 5) loadRoadmap();
}

// Step-bar status texts are stored as a render function so they can be redrawn in another language.
function railState(step, key, vars = {}, done = true) {
  setRail(step, () => t(key, vars), done);
}
function setRail(step, render, done = true) {
  state.rail[step] = { render, done };
  drawRail(step);
}
function drawRail(step) {
  const r = state.rail[step];
  $(`#rail-${step}`).textContent = r.render();
  $(`.rail-step[data-step="${step}"]`).classList.toggle("done", r.done);
}

$$(".rail-step").forEach((li) => li.addEventListener("click", () => go(+li.dataset.step)));
function showView(view) {
  $$(".tab").forEach((x) => x.classList.toggle("active", x.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === view));
  if (view === "lab") loadLab();
  if (view === "home") renderHome();
  window.scrollTo({ top: 0 });
}
$$(".tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));

// ------------------------------------------------------------ theme and language
// The page sets data-theme before CSS loads (no flash). Light is the default; a choice of dark is
// remembered in localStorage. The language works the same way (i18n.js).

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

// Redraw everything that was built from JS; refetch what the server wrote (notes, roadmap, topic names).
document.addEventListener("langchange", () => {
  setThemeLabel();
  drawHealth();
  Object.keys(state.rail).forEach(drawRail);
  renderChips();
  renderJobList();
  if (state.job) renderJob();
  quizTopics = null;
  if (currentStep === 3) {
    if (!$("#quiz-setup").hidden) renderTopicPick();
    if (!$("#quiz-run").hidden && state.quiz) renderQuestion();
    if (!$("#quiz-result").hidden && state.lastResult) renderQuizResult(state.lastResult);
  }
  if (currentStep === 4) loadMatches();
  if (currentStep === 5) loadRoadmap();
  api("/skills/dictionary").then((d) => { state.dictionary = d; renderChips(); }).catch(() => {});
  labLoaded = false;
  if ($("#lab").classList.contains("active")) loadLab();
  if (state.lastCompare) renderCompare();
  renderProfile();
  if ($("#home").classList.contains("active")) renderHome();
  if (currentStep === 3) renderHistory();
});

// ------------------------------------------------------------ health + dictionary

function drawHealth() {
  const el = $("#health"), h = state.health;
  if (h === null) return;
  if (h === "offline") {
    el.className = "health bad";
    el.textContent = t("health.offline");
    return;
  }
  el.className = `health ${h.model_loaded ? "ok" : "bad"}`;
  el.textContent = h.model_loaded ? t("health.model", { name: h.model }) : t("health.no_model");
  el.title = h.model_error || t("health.jobs", { n: h.jobs });
}

async function boot() {
  applyI18n();
  setThemeLabel();
  try {
    state.health = await api("/health");
  } catch {
    state.health = "offline";
  }
  drawHealth();
  try {
    state.dictionary = await api("/skills/dictionary");
  } catch { /* topic names fall back to their ids */ }
  await loadJobs();
  renderProfile();
  renderHome();
}

const topicOf = (skill) => state.dictionary.skills.find((s) => s.name === skill)?.topic ?? null;
const topicName = (topic) => state.dictionary.topics[topic] || topic;

// ------------------------------------------------------------ step 1: CV

const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  if (e.dataTransfer.files[0]) analyzePdf(e.dataTransfer.files[0]);
});
$("#cv-file").addEventListener("change", (e) => e.target.files[0] && analyzePdf(e.target.files[0]));

async function analyzePdf(file) {
  const msg = $("#cv-msg");
  say(msg, t("s1.reading", { file: file.name }));
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api("/cv/analyze", { method: "POST", body: form });
    setCandidates(res.skills);
    say(msg, t("s1.found_pdf", { n: res.skills.length, chars: res.characters.toLocaleString() }), "ok");
  } catch (e) {
    say(msg, e.message, "error");
  }
  $("#cv-file").value = "";
}

async function analyzeText() {
  const msg = $("#cv-msg");
  const text = $("#cv-text").value;
  if (!text.trim()) return;
  try {
    const res = await api("/cv/analyze-text", { json: { text } });
    if ($("#cv-text").value !== text) return;  // the user kept typing; a newer scan follows
    setCandidates(res.skills);
    say(msg, t("s1.found", { n: res.skills.length }), "ok");
  } catch (err) {
    say(msg, err.message, "error");
  }
}
$("#cv-analyze").addEventListener("click", (e) => busy(e.target, analyzeText));
// Pasted or typed text is scanned automatically shortly after the user stops typing.
let cvTimer = null;
$("#cv-text").addEventListener("input", () => {
  clearTimeout(cvTimer);
  if ($("#cv-text").value.trim().length >= 30) {
    say($("#cv-msg"), t("s1.scanning"));
    cvTimer = setTimeout(analyzeText, 700);
  }
});

function setCandidates(skills) {
  state.cvCandidates = skills;
  renderChips();
}

// Dictionary categories, grouped into a few headings for the CV summary (order = display order).
const CV_GROUPS = [
  ["languages", ["language"]],
  ["frameworks", ["framework", "library", "web"]],
  ["databases", ["database"]],
  ["data", ["data"]],
  ["devops", ["devops", "cloud", "tool"]],
  ["concepts", ["concept", "practice", "architecture"]],
];
const categoryOf = (skill) => state.dictionary.skills.find((s) => s.name === skill)?.category ?? null;

// Mark the skill's words inside the CV snippet that triggered it.
function markEvidence(snippet, skill) {
  const words = [skill, ...((state.dictionary.skills.find((s) => s.name === skill) || {}).aliases || [])];
  const lower = snippet.toLowerCase();
  const hit = words.map((w) => [w, lower.indexOf(w.toLowerCase())]).find(([, i]) => i >= 0);
  if (!hit) return esc(snippet);
  const [w, i] = hit;
  return `${esc(snippet.slice(0, i))}<mark>${esc(snippet.slice(i, i + w.length))}</mark>${esc(snippet.slice(i + w.length))}`;
}

function renderChips() {
  const box = $("#cv-chips");
  const list = state.cvCandidates;
  $("#cv-count").textContent = list.length;
  $("#cv-confirm").disabled = list.length === 0;
  if (!list.length) {
    box.innerHTML = `<p class="empty">${esc(t("s1.none"))}</p>`;
    return;
  }
  const groups = CV_GROUPS.map(([key, cats]) => [key, list.filter((c) => cats.includes(categoryOf(c.skill)))]);
  const other = list.filter((c) => !CV_GROUPS.some(([, cats]) => cats.includes(categoryOf(c.skill))));
  if (other.length) groups.push(["other", other]);
  const quizTopics = [...new Set(list.map((c) => c.topic).filter(Boolean))];
  box.innerHTML = `
    <p class="cv-summary">${esc(t("s1.summary", { n: list.length, g: groups.filter(([, g]) => g.length).length }))}
      ${quizTopics.length ? ` ${esc(t("s1.quiz_topics"))} ${quizTopics.map((tp) => `<span class="st quiz_only">${esc(topicName(tp))}</span>`).join(" ")}` : ""}</p>
    ${groups.filter(([, g]) => g.length).map(([key, g]) => `
      <section class="cv-group">
        <h4>${esc(t(`s1.g_${key}`))} <span class="count">${g.length}</span></h4>
        <ul>${g.map((c) => `
          <li>
            <div class="cv-skill"><strong>${esc(c.skill)}</strong>${c.topic ? ` <span class="topic">${esc(topicName(c.topic))}</span>` : ""}
              <button class="cv-remove" aria-label="${esc(t("s1.remove", { skill: c.skill }))}" data-skill="${esc(c.skill)}">×</button></div>
            ${c.evidence.length ? `<p class="cv-evidence">“…${markEvidence(c.evidence[0], c.skill)}…”${c.evidence.length > 1 ? ` <span class="more">${esc(t("s1.more", { n: c.evidence.length - 1 }))}</span>` : ""}</p>` : ""}
          </li>`).join("")}</ul>
      </section>`).join("")}`;
  $$(".cv-remove", box).forEach((b) => b.addEventListener("click", () => {
    state.cvCandidates = state.cvCandidates.filter((c) => c.skill !== b.dataset.skill);
    renderChips();
  }));
}

$("#cv-confirm").addEventListener("click", () => {
  state.cvSkills = state.cvCandidates.map((c) => c.skill);
  railState(1, "s1.rail", { n: state.cvSkills.length });
  state.ranking = null;
  renderProfile();
  go(2);
});

// ------------------------------------------------------------ step 2: jobs

async function loadJobs() {
  try {
    state.jobs = await api("/jobs");
    renderJobList();
  } catch (e) {
    say($("#job-msg"), e.message, "error");
  }
}

function sourceBadge(j) {
  if (j.is_demo) return `<span class="badge demo">${esc(t("badge.demo"))}</span>`;
  return j.source !== "manual" ? `<span class="badge live">${esc(j.source)}</span>` : "";
}

// A job as a card: photo (or the company's initials), title, company, first skills the model found.
function jobCard(j) {
  const initials = (j.company || j.title).split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const skills = j.skills || [];
  return `<li data-id="${j.id}" class="job-card ${j.id === state.jobId ? "active" : ""}" tabindex="0">
      ${j.image ? `<img class="jc-photo" src="${esc(j.image.url)}" alt="" loading="lazy">` : `<span class="jc-photo jc-none" aria-hidden="true">${esc(initials)}</span>`}
      <span class="jc-body">
        <span class="title">${esc(j.title)}</span>
        <span class="meta">${esc(j.company || "—")} · ${esc(j.location || j.source)} ${sourceBadge(j)}</span>
        <span class="jc-skills">${skills.slice(0, 3).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}${skills.length > 3 ? `<span class="more">+${skills.length - 3}</span>` : ""}</span>
      </span>
    </li>`;
}

function bindJobCards(root, onPick) {
  $$("li[data-id]", root).forEach((li) => {
    li.addEventListener("click", () => onPick(+li.dataset.id));
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") onPick(+li.dataset.id); });
  });
}

function renderJobList() {
  const q = $("#job-filter").value.toLowerCase();
  const items = state.jobs.filter((j) => `${j.title} ${j.company} ${(j.skills || []).join(" ")}`.toLowerCase().includes(q));
  $("#job-list").innerHTML = items.map(jobCard).join("") || `<li class="empty">${esc(t("s2.no_match"))}</li>`;
  bindJobCards($("#job-list"), selectJob);
  if ($("#home").classList.contains("active")) renderHomeJobs();
}
$("#job-filter").addEventListener("input", renderJobList);

async function selectJob(id) {
  state.jobId = id;
  renderJobList();
  const box = $("#job-detail");
  box.innerHTML = readingSkeleton(t("s2.reading"));
  try {
    state.job = await api(`/jobs/${id}`);
    renderJob();
    renderProfile();
    const title = state.job.title.slice(0, 18);
    setRail(2, () => title);
  } catch (e) {
    box.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

const spanLabel = (m) => t(m.found_by === "dictionary" ? "label.dictionary" : `label.${m.type}`);

const spanKey = (m) => `${m.start}:${m.end}:${m.type}`;

function highlight(text, mentions, only = null) {
  // Overlapping spans (a word can be both skill and knowledge) are split at every boundary.
  const cuts = new Set([0, text.length]);
  mentions.forEach((m) => { cuts.add(m.start); cuts.add(m.end); });
  const points = [...cuts].sort((a, b) => a - b);
  let html = "", n = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const [a, b] = [points[i], points[i + 1]];
    const cover = mentions.filter((m) => m.start <= a && b <= m.end);
    const piece = esc(text.slice(a, b));
    if (!cover.length) { html += piece; continue; }
    const cls = new Set(cover.map((m) => (m.found_by === "dictionary" ? "d" : m.type === "skill" ? "s" : "k")));
    if (only && cover.some((m) => only.has(spanKey(m)))) cls.add("only");
    const tip = cover.map((m) => `${spanLabel(m)}: "${m.text}"${m.normalized.length ? " → " + m.normalized.join(", ") + (m.normalized_by === "embedding" ? ` (${t("s2.by_embedding", { s: m.norm_score.toFixed(2) })})` : "") : ""}`).join("\n");
    // Highlights light up in reading order; the delay is capped so long ads finish within ~2 s.
    const delay = Math.min(n++ * 60, 2000);
    html += `<span class="sp ${[...cls].join(" ")}" style="animation-delay:${delay}ms" title="${esc(tip)}">${piece}</span>`;
  }
  return html;
}

function readingSkeleton(label) {
  return `<div class="reading"><p class="hint">${esc(label)}</p>
    ${[92, 100, 76, 88, 64].map((w) => `<span class="sk-line" style="width:${w}%"></span>`).join("")}</div>`;
}

function requirementsTable(ex) {
  const rows = ex.requirements.map((r) => `
    <tr>
      <td><span class="dot ${r.found_by === "dictionary" ? "dictionary" : r.type}"></span>${esc(spanLabel(r))}</td>
      <td>${esc(r.text)}${r.mentions.length > 1 ? ` <span class="tag">×${r.mentions.length}</span>` : ""}</td>
      <td>${r.normalized.length ? esc(r.normalized.join(", ")) + (r.normalized_by === "embedding" ? ` <span class="tag" title="${esc(t("s2.embedding_tip"))}">${esc(t("s2.by_embedding", { s: r.norm_score.toFixed(2) }))}</span>` : "") : `<span class="none">${esc(t("s2.not_matched"))}</span>`}</td>
    </tr>`).join("");
  return `<table class="req-table"><thead><tr><th>${esc(t("s2.col_by"))}</th><th>${esc(t("s2.col_phrase"))}</th><th>${esc(t("s2.col_skill"))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// Small square photo for demo jobs; jobs without a photo get an empty placeholder of the same size.
function thumb(image) {
  return image
    ? `<img class="thumb" src="${esc(image.url)}" alt="" loading="lazy">`
    : '<span class="thumb thumb-none" aria-hidden="true"></span>';
}

const legend = () => `<div class="legend"><mark class="s">${esc(t("label.skill"))}</mark><mark class="k">${esc(t("label.knowledge"))}</mark><mark class="d">${esc(t("label.dictionary"))}</mark></div>`;

function renderJob() {
  const j = state.job;
  const ex = j.extraction;
  $("#job-detail").innerHTML = `
    ${j.image ? `<figure class="job-photo"><img src="${esc(j.image.url)}" alt="${esc(j.image.alt)}">
      <figcaption>${esc(t("s2.photo"))} <a href="${esc(j.image.page_url)}" target="_blank" rel="noopener">${esc(t("s2.photo_by", { name: j.image.photographer, source: j.image.source }))}</a></figcaption></figure>` : ""}
    <div class="head">
      <div>
        <h3>${esc(j.title)}</h3>
        <span class="meta">${esc(j.company || "")} · ${esc(j.location || "")} · ${esc(t("s2.source", { source: j.source }))}
          ${j.is_demo ? `<span class="badge demo">${esc(t("badge.demo"))}</span>` : ""}
          ${j.url ? `· <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(t("s2.original"))}</a>` : ""}</span>
      </div>
      <button class="btn primary" id="job-next">${esc(t("s2.take_quiz"))}</button>
    </div>
    ${legend()}
    <div class="highlight">${highlight(j.description, ex.mentions)}</div>
    <p class="hint">${esc(t("s2.recognised"))} <strong>${ex.skills.length ? esc(ex.skills.join(", ")) : esc(t("s2.none"))}</strong>
      ${ex.unmatched.length ? ` · ${esc(t("s2.unmatched", { n: ex.unmatched.length }))}` : ""}</p>
    ${requirementsTable(ex)}
    ${cvJobCard(ex.skills)}`;
  animate($("#job-detail"));
  $("#job-next").addEventListener("click", () => go(3));
}

// Each job skill next to the CV line that backs it; CV skills the job does not ask for are listed below.
function cvJobCard(jobSkills) {
  const confirmed = new Set(state.cvSkills);
  const cv = state.cvCandidates.filter((c) => confirmed.has(c.skill));
  if (!cv.length) return `<div class="cvjob"><h3>${esc(t("cvjob.title"))}</h3><p class="hint">${esc(t("cvjob.need_cv"))}</p></div>`;
  if (!jobSkills.length) return "";
  const bySkill = new Map(cv.map((c) => [c.skill, c]));
  const clip = (line) => (line.length > 110 ? line.slice(0, 107).trimEnd() + "…" : line);
  const rows = jobSkills.map((skill) => {
    const c = bySkill.get(skill);
    const cell = !c ? `<span class="cj-no">✗ ${esc(t("cvjob.no"))}</span>`
      : c.added ? `<span class="cj-yes">✓ ${esc(t("cvjob.yes"))}</span> <span class="hint">(${esc(t("cvjob.added"))})</span>`
        : `<span class="cj-yes">✓ ${esc(t("cvjob.yes"))}</span>${c.evidence?.length ? `<q>${esc(clip(c.evidence[0]))}</q>` : ""}`;
    return `<tr class="${c ? "have" : "gap"}"><td>${esc(skill)}</td><td>${cell}</td></tr>`;
  }).join("");
  const have = jobSkills.filter((s) => bySkill.has(s)).length;
  const asked = new Set(jobSkills);
  const extra = cv.filter((c) => !asked.has(c.skill));
  return `<div class="cvjob"><h3>${esc(t("cvjob.title"))}</h3>
    <p class="hint">${esc(t("cvjob.hint"))} <strong>${esc(t("cvjob.summary", { have, n: jobSkills.length }))}</strong></p>
    <div class="bar cj-bar"><div class="grow" data-w="${(have / jobSkills.length) * 100}" style="background:var(--good)"></div></div>
    <table class="req-table cj-table"><thead><tr><th>${esc(t("cvjob.col_req"))}</th><th>${esc(t("cvjob.col_cv"))}</th></tr></thead><tbody>${rows}</tbody></table>
    ${extra.length ? `<p class="hint">${esc(t("cvjob.extra"))} ${extra.map((c) => `<span class="st cv_only">${esc(c.skill)}</span>`).join(" ")}</p>` : ""}</div>`;
}

$("#job-add").addEventListener("click", (e) => busy(e.target, async () => {
  const msg = $("#job-msg");
  try {
    const res = await api("/jobs/import", { json: { source: "manual", title: $("#job-title").value || t("s2.untitled"), company: $("#job-company").value || null, description: $("#job-desc").value } });
    const r = res.imported[0];
    say(msg, t(r.status === "unchanged" ? "s2.already" : r.status === "updated" ? "s2.updated" : "s2.created"), "ok");
    await loadJobs();
    selectJob(r.id);
  } catch (err) {
    say(msg, err.message, "error");
  }
}));

$("#live-import").addEventListener("click", (e) => busy(e.target, async () => {
  const msg = $("#job-msg");
  say(msg, t("s2.contacting"));
  try {
    const res = await api("/jobs/import", { json: { source: $("#live-source").value, board: $("#live-board").value, limit: 20 } });
    const c = res.counts;
    say(msg, t("s2.imported", { source: res.source, created: c.created, updated: c.updated, unchanged: c.unchanged }), "ok");
    loadJobs();
  } catch (err) {
    say(msg, err.message, "error");
  }
}));

// ------------------------------------------------------------ step 3: quiz

let quizTopics = null;

async function renderTopicPick() {
  if (!quizTopics) {
    try { quizTopics = await api("/quiz/topics"); } catch (e) { say($("#quiz-msg"), e.message, "error"); return; }
  }
  const checked = new Set($$("#topic-pick input:checked").map((i) => i.value));
  const jobTopics = new Set((state.job?.extraction.skills || []).map(topicOf).filter(Boolean));
  const cvTopics = new Set(state.cvSkills.map(topicOf).filter(Boolean));
  $("#topic-pick").innerHTML = Object.entries(quizTopics.topics).map(([topic, n]) => {
    const fromJob = jobTopics.has(topic);
    const done = state.quizScores[topic];
    const on = checked.size ? checked.has(topic) : fromJob || (!jobTopics.size && cvTopics.has(topic));
    const last = done ? ` · ${t("s3.last", { pct: pct(done.ratio) })}${done.level ? " " + levelName(done.level) : ""}` : "";
    return `<label class="${fromJob ? "from-job" : ""}">
      <input type="checkbox" value="${esc(topic)}" ${on ? "checked" : ""}>
      ${esc(quizTopics.names[topic] || topic)} <small>${fromJob ? esc(t("s3.in_job")) : ""}${esc(last)}</small>
      <span class="tag">${esc(t("s3.q_short", { n }))}</span></label>`;
  }).join("");
}

$("#q-total").addEventListener("input", (e) => { $("#q-total-out").textContent = e.target.value; });

$("#quiz-start").addEventListener("click", (e) => busy(e.target, async () => {
  const topics = $$("#topic-pick input:checked").map((i) => i.value);
  try {
    const level = $("#level-pick input:checked")?.value || "mid";
    const q = await api("/quiz/start", { json: { topics, total: +$("#q-total").value, level } });
    state.quiz = { ...q, answers: {}, i: 0 };
    $("#quiz-setup").hidden = true;
    $("#quiz-result").hidden = true;
    $("#quiz-run").hidden = false;
    const notes = [];
    if (q.count < q.requested) notes.push(t("s3.bank_limit", { n: q.count }));
    if (q.from_other_levels) notes.push(t("s3.fallback", { n: q.from_other_levels, level: levelName(q.level) }));
    say($("#quiz-msg"), notes.join(" "));
    renderQuestion();
  } catch (err) {
    say($("#quiz-msg"), err.message, "error");
  }
}));

$("#quiz-skip").addEventListener("click", () => {
  railState(3, "s3.skipped", {}, false);
  go(4);
});

function renderQuestion() {
  const { questions, i, answers } = state.quiz;
  const q = questions[i];
  const answered = Object.keys(answers).length;
  $("#q-bar").style.width = `${(answered / questions.length) * 100}%`;
  $("#q-hp").textContent = t("s3.answered", { a: answered, n: questions.length });
  $("#q-index").textContent = t("s3.q_meta", { i: i + 1, n: questions.length, level: t("lv.tag", { level: levelName(q.level) }) });
  $("#q-topic").textContent = topicName(q.topic);
  $("#q-text").textContent = q.question;
  $("#q-options").innerHTML = q.options.map((o, k) => `
    <button class="option ${answers[q.id] === k ? "picked" : ""}" data-k="${k}"><span class="key">${"ABCD"[k]}</span><span>${esc(o)}</span></button>`).join("");
  $$("#q-options .option").forEach((b) => b.addEventListener("click", () => {
    answers[q.id] = +b.dataset.k;
    if (i < questions.length - 1) { state.quiz.i++; }
    renderQuestion();
  }));
  $("#q-prev").disabled = i === 0;
  $("#q-next").hidden = i === questions.length - 1;
  $("#q-submit").hidden = i !== questions.length - 1 && Object.keys(answers).length < questions.length;
}

$("#q-prev").addEventListener("click", () => { state.quiz.i--; renderQuestion(); });
$("#q-next").addEventListener("click", () => { state.quiz.i++; renderQuestion(); });
$("#q-submit").addEventListener("click", (e) => busy(e.target, async () => {
  const { questions, answers, session_id } = state.quiz;
  const open = questions.length - Object.keys(answers).length;
  if (open && !confirm(t("s3.unanswered", { n: open }))) return;
  try {
    const res = await api("/quiz/submit", { json: { session_id, answers } });
    Object.assign(state.quizScores, res.topics);
    state.lastResult = res;
    saveHistory(res);
    state.ranking = null;
    renderQuizResult(res);
    renderProfile();
    setRail(3, () => `${pct(res.ratio)} · ${levelName(res.level)}`);
  } catch (err) {
    say($("#quiz-msg"), err.message, "error");
  }
}));

function scoreBar(label, ratio, detail, threshold = 0.6) {
  // threshold = null: plain bar without the weak-evidence line (used in the model lab)
  const colour = threshold === null ? "var(--ink)" : ratio < threshold ? "var(--warn)" : "var(--good)";
  const mark = threshold === null ? "" : `<span class="mark" style="left:${threshold * 100}%"></span>`;
  return `<div class="bar-row"><span>${esc(label)}</span>
    <div class="bar"><div class="grow" data-w="${ratio * 100}" style="background:${colour}"></div>${mark}</div>
    <span>${countUp(ratio)} ${esc(detail)}</span></div>`;
}

// ------------------------------------------------------------ motion helpers
// Charts are rendered at zero and animated to their value; with reduced motion they jump straight there.

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function countUp(ratio) {
  return ratio === null || ratio === undefined ? "–" : `<span data-count="${Math.round(ratio * 100)}" data-pct="1">${fmtPct(0)}</span>`;
}

function animate(root = document) {
  const instant = reduceMotion();
  requestAnimationFrame(() => {
    $$("[data-w]", root).forEach((el) => { el.style.width = `${el.dataset.w}%`; });
    $$(".ring-arc", root).forEach((el) => { el.style.strokeDasharray = `${el.dataset.len} ${el.dataset.c}`; });
  });
  $$("[data-count]", root).forEach((el) => {
    const target = +el.dataset.count;
    const show = (n) => (el.dataset.pct ? fmtPct(n) : String(n));
    if (instant) { el.textContent = show(target); return; }
    const t0 = performance.now(), dur = 800;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / dur), eased = 1 - Math.pow(1 - k, 3);
      el.textContent = show(Math.round(target * eased));
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

function renderQuizResult(res) {
  $("#quiz-run").hidden = true;
  const box = $("#quiz-result");
  box.hidden = false;
  box.innerHTML = `
    <span class="level-tag">${esc(t("lv.tag", { level: levelName(res.level) }))}</span>
    <h3>${t("s3.result", { c: res.correct, n: res.total, pct: countUp(res.ratio) })}</h3>
    <p class="hint">${esc(t("s3.per_topic"))}</p>
    <div class="score-bars">${Object.entries(res.topics).map(([topic, s]) => scoreBar(topicName(topic), s.ratio, `${s.correct}/${s.total}`)).join("")}</div>
    <button class="btn primary" id="to-matches">${esc(t("s3.to_matches"))}</button>
    <button class="btn ghost" id="quiz-again">${esc(t("s3.again"))}</button>
    <div class="review">${res.review.map((r) => `
      <details><summary class="${r.correct ? "right" : "wrong"}">${r.correct ? "✓" : "✗"} ${esc(r.question.split("\n")[0])}</summary>
        <p>${esc(t("s3.your_answer"))} ${r.given === null || r.given === undefined ? esc(t("s3.none")) : esc(r.options[r.given])} · ${esc(t("s3.correct"))} <strong>${esc(r.options[r.answer])}</strong></p>
        <p>${esc(r.explanation)}</p></details>`).join("")}</div>`;
  animate(box);
  renderHistory();
  $("#to-matches").addEventListener("click", () => go(4));
  $("#quiz-again").addEventListener("click", () => {
    box.hidden = true;
    state.lastResult = null;
    $("#quiz-setup").hidden = false;
    renderTopicPick();
  });
}

// ------------------------------------------------------------ quiz history (this browser only)

const HISTORY_KEY = "skilllens-quiz-history";
// Colour follows the topic (fixed order), never its position in a given quiz. Slots 1-5 of the
// validated reference palette; light and dark steps are defined in styles.css as --series-N.
const TOPIC_ORDER = ["python", "csharp", "sql", "oop", "algorithms"];
const seriesVar = (topic) => `var(--series-${TOPIC_ORDER.indexOf(topic) + 1})`;

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; } catch { return []; }
}

function saveHistory(res) {
  const list = loadHistory();
  list.push({ date: new Date().toISOString(), level: res.level, ratio: res.ratio,
              topics: Object.fromEntries(Object.entries(res.topics).map(([k, v]) => [k, v.ratio])) });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-30)));
}

function historyChart(list) {
  const W = 640, H = 240, L = 44, R = 16, T = 14, B = 34;
  const x = (i) => L + (list.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (list.length - 1));
  const y = (v) => T + (1 - v) * (H - T - B);
  const topics = TOPIC_ORDER.filter((tp) => list.some((h) => tp in h.topics));
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/>
    <text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="axis">${esc(fmtPct(v * 100))}</text>`).join("");
  const ticks = list.map((h, i) => `<text x="${x(i)}" y="${H - 12}" text-anchor="middle" class="axis">${i + 1}</text>`).join("");
  const lines = topics.map((tp) => {
    const pts = list.map((h, i) => (tp in h.topics ? [x(i), y(h.topics[tp]), i] : null)).filter(Boolean);
    const path = pts.map(([px, py], k) => `${k ? "L" : "M"}${px},${py}`).join(" ");
    const dots = pts.map(([px, py, i]) => `<circle cx="${px}" cy="${py}" r="4.5" fill="${seriesVar(tp)}" class="dot"
      data-tip="${esc(`${t("hist.attempt", { n: i + 1 })} · ${levelName(list[i].level)}
${topicName(tp)}: ${pct(list[i].topics[tp])}`)}"/>`).join("");
    return `<path d="${path}" fill="none" stroke="${seriesVar(tp)}" stroke-width="2" stroke-linejoin="round"/>${dots}`;
  }).join("");
  return `<div class="hist-wrap"><svg class="hist" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("hist.title"))}">
    ${grid}<line x1="${L}" x2="${W - R}" y1="${y(0.6)}" y2="${y(0.6)}" class="ref"/>${ticks}${lines}</svg>
    <div class="hist-tip" hidden></div></div>
    <div class="legend hist-legend">${topics.map((tp) => `<span><i style="background:${seriesVar(tp)}"></i>${esc(topicName(tp))}</span>`).join("")}</div>`;
}

function renderHistory() {
  const box = $("#quiz-history");
  const list = loadHistory();
  box.hidden = !list.length;
  if (!list.length) return;
  const topics = TOPIC_ORDER.filter((tp) => list.some((h) => tp in h.topics));
  const date = (iso) => new Date(iso).toLocaleDateString(LANG === "tr" ? "tr-TR" : "en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  box.innerHTML = `<h3>${esc(t("hist.title"))}</h3><p class="hint">${esc(t("hist.hint"))}</p>
    ${historyChart(list)}
    ${list.length === 1 ? `<p class="hint">${esc(t("hist.one"))}</p>` : ""}
    <details><summary>${esc(t("hist.table"))}</summary>
      <table class="table"><thead><tr><th>${esc(t("hist.col_n"))}</th><th>${esc(t("hist.col_date"))}</th><th>${esc(t("hist.col_level"))}</th><th>${esc(t("hist.col_total"))}</th>${topics.map((tp) => `<th>${esc(topicName(tp))}</th>`).join("")}</tr></thead>
      <tbody>${list.map((h, i) => `<tr><td>${i + 1}</td><td>${esc(date(h.date))}</td><td>${esc(levelName(h.level))}</td><td>${pct(h.ratio)}</td>${topics.map((tp) => `<td>${tp in h.topics ? pct(h.topics[tp]) : "–"}</td>`).join("")}</tr>`).join("")}</tbody></table>
    </details>
    <div class="step-actions"><button class="btn ghost" id="hist-clear">${esc(t("hist.clear"))}</button></div>`;
  const tip = $(".hist-tip", box), wrap = $(".hist-wrap", box);
  $$(".dot", box).forEach((d) => {
    d.addEventListener("mouseenter", () => {
      tip.textContent = d.dataset.tip;
      tip.hidden = false;
      const r = d.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      tip.style.left = `${r.left - w.left + r.width / 2}px`;
      tip.style.top = `${r.top - w.top}px`;
    });
    d.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
  $("#hist-clear").addEventListener("click", () => {
    if (!confirm(t("hist.confirm"))) return;
    localStorage.removeItem(HISTORY_KEY);
    renderHistory();
  });
}

// ------------------------------------------------------------ step 4: matches

// How many jobs ask for each skill, coloured by the user's evidence for it (status is per skill).
function demandChart(ranking) {
  const counts = new Map();
  ranking.forEach((j) => j.match.skills.forEach((r) => {
    const e = counts.get(r.skill) || { skill: r.skill, n: 0, status: r.status };
    e.n++;
    counts.set(r.skill, e);
  }));
  const rows = [...counts.values()].sort((a, b) => b.n - a.n || a.skill.localeCompare(b.skill)).slice(0, 12);
  if (!rows.length) return "";
  const group = (st) => (st === "missing" ? "missing" : st === "weak_quiz" ? "weak" : "have");
  const max = rows[0].n;
  return `<h3>${esc(t("demand.title"))}</h3>
    <p class="hint">${esc(t("demand.hint", { n: ranking.length }))}</p>
    <div class="legend demand-legend">${["have", "weak", "missing"].map((g) => `<span><i class="dm ${g}"></i>${esc(t(`demand.${g}`))}</span>`).join("")}</div>
    <div class="demand">${rows.map((r) => `<div class="bar-row" title="${esc(`${r.skill}: ${t(`demand.${group(r.status)}`)}`)}">
      <span>${esc(r.skill)}</span>
      <div class="bar"><div class="grow dm ${group(r.status)}" data-w="${(r.n / max) * 100}"></div></div>
      <span>${esc(r.n === 1 ? t("demand.job") : t("demand.jobs", { n: r.n }))}</span></div>`).join("")}</div>`;
}

function ring(value) {
  const r = 42, c = 2 * Math.PI * r;
  const v = value ?? 0;
  const colour = value === null ? "var(--line)" : v >= 0.7 ? "var(--good)" : v >= 0.4 ? "var(--dict)" : "var(--warn)";
  return `<svg class="ring" viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--paper-2)" stroke-width="10"/>
    <circle class="ring-arc" cx="50" cy="50" r="${r}" fill="none" stroke="${colour}" stroke-width="10" stroke-dasharray="0 ${c}" data-len="${c * v}" data-c="${c}" transform="rotate(-90 50 50)"/>
    <text x="50" y="55" text-anchor="middle">${value === null ? esc(t("ring.na")) : `<tspan data-count="${Math.round(v * 100)}">0</tspan>`}</text>
    <text x="50" y="70" text-anchor="middle" class="sub">${esc(t("ring.match"))}</text></svg>`;
}

function chipTitle(r) {
  const extra = r.quiz
    ? ` · ${t("s4.quiz", { pct: pct(r.quiz.ratio) })}${r.quiz.level ? " (" + levelName(r.quiz.level) + ")" : ""}`
    : r.quiz_state === "not_evaluated" ? ` · ${t("s4.not_eval")}` : r.quiz_state === "no_quiz_for_skill" ? ` · ${t("s4.no_quiz")}` : "";
  return t(`st.${r.status}`) + extra;
}

async function loadMatches() {
  const list = $("#match-list");
  list.innerHTML = `<p class="empty">${esc(t("s4.scoring"))}</p>`;
  try {
    const { ranking } = await api("/matches", { json: { cv_skills: state.cvSkills, quiz_scores: state.quizScores } });
    state.ranking = ranking;
    renderProfile();
    const w = ranking[0]?.match.weights || { cv: 0.5, quiz: 0.5 };
    $("#match-formula").textContent = t("s4.formula", { cv: w.cv, quiz: w.quiz });
    list.innerHTML = `<div class="status-legend">${STATUSES.map((k) => `<span class="st ${k}">${esc(t(`st.${k}`))}</span>`).join("")}</div>` +
      ranking.map((j) => {
        const m = j.match, s = m.scores;
        return `<div class="card match">
          ${ring(s.combined)}
          <div>
            <div class="match-head">${thumb(j.image)}<div>
              <h3>${esc(j.title)}</h3>
              <span class="meta">${esc(j.company || "")} ${j.is_demo ? `<span class="badge demo">${esc(t("badge.demo"))}</span>` : ""}</span>
            </div></div>
            <div class="mini">
              <div>${esc(t("s4.cv_cov"))}<b>${countUp(s.cv_coverage)}</b><i><span class="grow" data-w="${(s.cv_coverage ?? 0) * 100}"></span></i></div>
              <div>${esc(t("s4.quiz_perf"))}<b>${countUp(s.quiz_performance)}</b><i><span class="grow" data-w="${(s.quiz_performance ?? 0) * 100}"></span></i></div>
              <div>${esc(t("s4.quiz_cov"))}<b>${countUp(s.quiz_coverage)}</b><i><span class="grow" data-w="${(s.quiz_coverage ?? 0) * 100}"></span></i></div>
            </div>
            <div class="status-chips">${m.skills.map((r) => `<span class="st ${r.status}" title="${esc(chipTitle(r))}">${esc(r.skill)}</span>`).join("")}</div>
            ${m.notes.length ? `<ul class="notes">${m.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
            <button class="btn" data-id="${j.id}">${esc(t("s4.show_roadmap"))}</button>
          </div></div>`;
      }).join("");
    const demand = $("#demand");
    demand.innerHTML = demandChart(ranking);
    demand.hidden = !demand.innerHTML;
    animate(list);
    animate(demand);
    $$("#match-list .btn[data-id]").forEach((b) => b.addEventListener("click", () => {
      state.roadmapJobId = +b.dataset.id;
      go(5);
    }));
    railState(4, "s4.ranked", { n: ranking.length });
  } catch (e) {
    list.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

// ------------------------------------------------------------ step 5: roadmap

async function loadRoadmap() {
  const box = $("#roadmap");
  const id = state.roadmapJobId ?? state.jobId;
  if (!id) {
    box.innerHTML = `<p class="empty">${esc(t("s5.pick"))}</p>`;
    return;
  }
  box.innerHTML = `<p class="empty">${esc(t("s5.building"))}</p>`;
  try {
    const res = await api("/roadmap", { json: { job_id: id, cv_skills: state.cvSkills, quiz_scores: state.quizScores } });
    const rm = res.roadmap;
    const have = res.match.skills.filter((r) => ["cv_only", "cv_and_quiz", "quiz_only"].includes(r.status));
    const done = getProgress(id);
    box.innerHTML = `
      <div class="card"><h3>${esc(res.job.title)} <span class="meta">${esc(res.job.company || "")}</span></h3>
        <p class="hint">${esc(t("s5.backed"))} ${have.length ? have.map((r) => `<span class="st ${r.status}">${esc(r.skill)}</span>`).join(" ") : esc(t("s5.none"))}</p>
        <div class="step-actions"><button class="btn" id="pdf-view" aria-expanded="false">${esc(t("s5.pdf_view"))}</button><button class="btn primary" id="pdf-download">${esc(t("s5.pdf"))}</button></div>
        <p class="msg" id="pdf-msg" role="status"></p>
        <div class="pdf-viewer" id="pdf-viewer" hidden></div>
        ${rm.steps.length ? `<div class="road-progress"><span id="road-count"></span><div class="bar"><div class="grow" id="road-bar" style="background:var(--good)"></div></div></div>` : ""}</div>
      ${rm.message ? `<div class="card road-clear"><span class="road-clear-icon" aria-hidden="true">✓</span><p>${esc(rm.message)}</p></div>`
        : `${roadOverview(rm.steps, done)}<ol class="road">${rm.steps.map((s) => roadStep(s, done, rm.steps)).join("")}</ol>`}`;
    state.roadmap = { jobId: id, title: res.job.title, ids: rm.steps.map((s) => s.id) };
    drawRoadProgress();
    $$(".done-check input", box).forEach((cb) => cb.addEventListener("change", () => {
      const set = getProgress(id);
      cb.checked ? set.add(cb.dataset.stepId) : set.delete(cb.dataset.stepId);
      saveProgress(id, set);
      cb.closest(".road-step").classList.toggle("done", cb.checked);
      $$(`.rm-node[data-step-id="${CSS.escape(cb.dataset.stepId)}"]`, box).forEach((n) => n.classList.toggle("done", cb.checked));
      drawRoadProgress();
    }));
    $$(".rm-node, .req-link", box).forEach((n) => n.addEventListener("click", (e) => {
      e.preventDefault();
      const target = $(`#road-${CSS.escape(n.dataset.stepId)}`);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.classList.remove("flash");
      void target?.offsetWidth;
      target?.classList.add("flash");
    }));
    if (rm.steps.length) railState(5, "s5.steps", { n: rm.steps.length });
    else railState(5, "s5.no_gaps");
    $("#pdf-download").addEventListener("click", (e) => busy(e.target, () => downloadPdf(id)));
    $("#pdf-view").addEventListener("click", () => togglePdfView(id));
  } catch (e) {
    box.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

// Route overview: every step as a node in reading order, then summary numbers.
function roadOverview(steps, done) {
  const gaps = steps.filter((s) => s.kind === "gap").length;
  const courses = steps.reduce((n, s) => n + s.courses.length, 0);
  const nodes = steps.map((s, i) => `
    ${i ? '<span class="rm-arrow" aria-hidden="true"></span>' : ""}
    <a href="#road-${esc(s.id)}" class="rm-node ${s.kind} ${done.has(s.id) ? "done" : ""}" data-step-id="${esc(s.id)}" title="${esc(s.title)}">
      <span class="rm-dot">${s.order}</span><span class="rm-label">${esc(s.title)}</span></a>`).join("");
  return `<div class="card road-overview">
    <div class="rm-stats">
      <div><b>${steps.length}</b><span>${esc(t("road.st_steps"))}</span></div>
      <div><b>${gaps}</b><span>${esc(t("road.st_gaps"))}</span></div>
      <div><b>${steps.length - gaps}</b><span>${esc(t("road.st_prereqs"))}</span></div>
      <div><b>${courses}</b><span>${esc(t("road.st_courses"))}</span></div>
    </div>
    <div class="rm-track" role="list">${nodes}</div>
    <div class="rm-legend"><span class="lg gap">${esc(t("s5.gap"))}</span><span class="lg prerequisite">${esc(t("s5.prereq"))}</span><span class="lg done">${esc(t("road.done"))}</span></div>
  </div>`;
}

function roadStep(s, done, steps) {
  const byId = Object.fromEntries(steps.map((x) => [x.id, x]));
  const needs = (s.prereqs || []).filter((p) => byId[p]);
  return `<li class="card road-step ${s.kind} ${done.has(s.id) ? "done" : ""}" id="road-${esc(s.id)}" data-n="${s.order}">
    <div class="rs-head">
      <span class="kind">${esc(t(s.kind === "prerequisite" ? "s5.prereq" : "s5.gap"))}</span>
      <label class="done-check"><input type="checkbox" data-step-id="${esc(s.id)}" ${done.has(s.id) ? "checked" : ""}><span>${esc(t("road.done"))}</span></label>
    </div>
    <h3>${esc(s.title)}</h3>
    ${s.for_skills.length ? `<p class="rs-for">${esc(t("road.for"))} ${s.for_skills.map((k) => `<span class="chip">${esc(k)}</span>`).join(" ")}</p>` : ""}
    <p class="rs-reason">${esc(s.reason)}</p>
    ${needs.length ? `<p class="rs-needs">${esc(t("road.needs"))} ${needs.map((p) => `<a href="#road-${esc(p)}" class="req-link" data-step-id="${esc(p)}">${byId[p].order}. ${esc(byId[p].title)}</a>`).join(" ")}</p>` : ""}
    <div class="goal"><span class="goal-label">${esc(t("road.goal"))}</span>${esc(s.goal)}</div>
    ${s.courses.length ? `<div class="course-grid">${s.courses.map((c) => `
      <a class="course" href="${esc(c.url)}" target="_blank" rel="noopener">
        <span class="course-title">${esc(c.title)}</span>
        <span class="prov">${esc(c.provider)}${c.language ? " · " + esc(c.language) : ""}</span>
        <span class="course-go" aria-hidden="true">↗</span></a>`).join("")}</div>` : `<p class="hint">${esc(t("s5.no_course"))}</p>`}
  </li>`;
}

// Ticked roadmap steps, per job, kept in this browser only.
const PROGRESS_KEY = "skilllens-roadmap-progress";
function getProgress(jobId) {
  try { return new Set((JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {})[jobId] || []); } catch { return new Set(); }
}
function saveProgress(jobId, set) {
  let all = {};
  try { all = JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {}; } catch { /* start over */ }
  all[jobId] = [...set];
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(all));
}
function roadDone() {
  const r = state.roadmap;
  if (!r || !r.ids.length) return null;
  const set = getProgress(r.jobId);
  return { done: r.ids.filter((x) => set.has(x)).length, total: r.ids.length };
}
function drawRoadProgress() {
  const p = roadDone();
  if (p && $("#road-count")) {
    $("#road-count").textContent = t("road.progress", { done: p.done, n: p.total });
    $("#road-bar").style.width = `${(p.done / p.total) * 100}%`;
  }
  renderProfile();
}

async function fetchPdf(jobId) {
  const res = await fetch("/roadmap/pdf", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Lang": LANG },
    body: JSON.stringify({ job_id: jobId, cv_skills: state.cvSkills, quiz_scores: state.quizScores }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
  return res.blob();
}

// Show the same PDF summary inside the page (the browser's own PDF viewer), without downloading it.
let pdfViewUrl = null;
async function togglePdfView(jobId) {
  const box = $("#pdf-viewer"), btn = $("#pdf-view"), msg = $("#pdf-msg");
  if (!box.hidden) {
    box.hidden = true;
    box.innerHTML = "";
    btn.textContent = t("s5.pdf_view");
    btn.setAttribute("aria-expanded", "false");
    return;
  }
  btn.disabled = true;
  btn.textContent = t("busy");
  try {
    if (pdfViewUrl) URL.revokeObjectURL(pdfViewUrl);
    pdfViewUrl = URL.createObjectURL(await fetchPdf(jobId));
    box.innerHTML = `<iframe src="${pdfViewUrl}" title="${esc(t("s5.pdf_title"))}"></iframe>`;
    box.hidden = false;
    btn.textContent = t("s5.pdf_hide");
    btn.setAttribute("aria-expanded", "true");
    say(msg, "", "ok");
  } catch (err) {
    btn.textContent = t("s5.pdf_view");
    say(msg, err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function downloadPdf(jobId) {
  const msg = $("#pdf-msg");
  try {
    const url = URL.createObjectURL(await fetchPdf(jobId));
    const a = Object.assign(document.createElement("a"), { href: url, download: `skilllens_job${jobId}.pdf` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    say(msg, t("s5.pdf_done"), "ok");
  } catch (err) {
    say(msg, err.message, "error");
  }
}

// ------------------------------------------------------------ model lab

let labLoaded = false;
async function loadLab() {
  if (labLoaded) return;
  try {
    const r = await api("/results/comparison");
    labLoaded = true;
    const names = Object.keys(r.models);
    const best = (scope, key) => Math.max(...names.map((n) => r.models[n].scores[scope][key]));
    const rows = [];
    for (const scope of ["overall", "skill", "knowledge"]) {
      for (const n of names) {
        const s = r.models[n].scores[scope];
        const cell = (k) => `<td class="${s[k] === best(scope, k) ? "best" : ""}">${s[k].toFixed(3)}</td>`;
        rows.push(`<tr><td>${esc(t(`scope.${scope}`))} · ${esc(n)}</td>${cell("precision")}${cell("recall")}${cell("f1")}<td>${s.tp}/${s.n_gold}</td></tr>`);
      }
    }
    $("#lab-setup").textContent = t("lab.setup", { n: r.test_sentences.toLocaleString(), device: r.device });
    $("#lab-scores").innerHTML = `<h3>${esc(t("lab.accuracy"))}</h3><table class="table"><thead><tr><th>${esc(t("lab.col_scope"))}</th><th>P</th><th>R</th><th>F1</th><th>TP / gold</th></tr></thead><tbody>${rows.join("")}</tbody></table>
      <div class="score-bars">${names.map((n) => scoreBar(`${n} F1`, r.models[n].scores.overall.f1, "", null)).join("")}</div>`;
    const maxMs = Math.max(...names.map((n) => r.models[n].latency.p90_ms));
    $("#lab-latency").innerHTML = `<h3>${esc(t("lab.speed"))}</h3>
      <p class="hint">${esc(t("lab.speed_hint", { n: r.latency_setup.latency_sentences, w: r.latency_setup.warmup }))}</p>
      <table class="table"><thead><tr><th>${esc(t("lab.col_model"))}</th><th>${esc(t("lab.col_median"))}</th><th>${esc(t("lab.col_p90"))}</th><th>${esc(t("lab.col_params"))}</th><th>${esc(t("lab.col_epoch"))}</th></tr></thead><tbody>
      ${names.map((n) => { const m = r.models[n]; return `<tr><td>${esc(n)}</td><td>${m.latency.median_ms.toFixed(2)}</td><td>${m.latency.p90_ms.toFixed(2)}</td><td>${(m.parameters / 1e6).toFixed(1)}M</td><td>${m.best_val_epoch}</td></tr>`; }).join("")}
      </tbody></table>
      <div class="score-bars">${names.map((n) => `<div class="bar-row"><span>${esc(n)}</span><div class="bar"><div class="grow" data-w="${(r.models[n].latency.median_ms / maxMs) * 100}" style="background:var(--ink)"></div></div><span>${r.models[n].latency.median_ms.toFixed(1)} ms</span></div>`).join("")}</div>
      <h3>${esc(t("lab.errors"))}</h3>
      <table class="table"><thead><tr><th>${esc(t("lab.col_model"))}</th><th>${esc(t("lab.col_boundary"))}</th><th>${esc(t("lab.col_fp"))}</th><th>${esc(t("lab.col_fn"))}</th></tr></thead><tbody>
      ${names.map((n) => { const e = r.models[n].error_counts; const sum = (k) => (e[`skill_${k}`] || 0) + (e[`knowledge_${k}`] || 0); return `<tr><td>${esc(n)}</td><td>${sum("boundary")}</td><td>${sum("fp")}</td><td>${sum("fn")}</td></tr>`; }).join("")}
      </tbody></table>`;
    animate($("#lab"));
  } catch (e) {
    $("#lab-scores").innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

$("#lab-run").addEventListener("click", (e) => busy(e.target, async () => {
  const text = $("#lab-text").value;
  try {
    $("#lab-out").innerHTML = readingSkeleton(t("lab.reading"));
    const t0 = performance.now();
    const ex = await api("/skills/extract", { json: { text } });
    const ms = performance.now() - t0;
    $("#lab-out").innerHTML = highlight(text, ex.mentions) +
      `\n\n<span class="hint">${esc(t("lab.result", { n: ex.mentions.length, skills: ex.skills.join(", ") || t("s2.none"), ms: ms.toFixed(0) }))}</span>`;
  } catch (err) {
    $("#lab-out").innerHTML = `<span class="msg error">${esc(err.message)}</span>`;
  }
}));

// ------------------------------------------------------------ home page

const HOME_SAMPLE = "You will design scalable REST APIs in Python, write unit tests and work with PostgreSQL and Docker.";

async function renderHome() {
  renderHomeStats();
  renderHomeJobs();
  const demo = $("#home-demo");
  if (state.homeDemo === null) {
    demo.textContent = HOME_SAMPLE;
    try {
      state.homeDemo = await api("/skills/extract", { json: { text: HOME_SAMPLE } });
    } catch { state.homeDemo = false; }  // no model: the sentence stays plain
  }
  if (state.homeDemo) {
    demo.innerHTML = highlight(HOME_SAMPLE, state.homeDemo.mentions.filter((m) => m.found_by === "model"));
  }
  if (!state.comparison) {
    try { state.comparison = await api("/results/comparison"); } catch { state.comparison = false; }
    renderHomeStats();
  }
  if (!quizTopics) {
    try { quizTopics = await api("/quiz/topics"); renderHomeStats(); } catch { /* tile shows a dash */ }
  }
}

function renderHomeStats() {
  const c = state.comparison, h = state.health;
  const m = c ? c.models : null;
  const num = (x, d = 0) => (x === undefined || x === null ? "–" : Number(x).toLocaleString(LANG === "tr" ? "tr-TR" : "en-GB", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const questions = quizTopics ? Object.values(quizTopics.topics).reduce((a, b) => a + b, 0) : null;
  const tiles = [
    [num(h && h !== "offline" ? h.jobs : null), t("home.st_jobs")],
    [num(questions), t("home.st_questions")],
    [m?.DistilBERT ? num(m.DistilBERT.scores.overall.f1, 3) : "–", t("home.st_f1", { other: m?.BiLSTM ? num(m.BiLSTM.scores.overall.f1, 3) : "–" })],
    [m?.DistilBERT ? `${num(m.DistilBERT.latency.median_ms, 1)} ms` : "–", t("home.st_ms", { other: m?.BiLSTM ? num(m.BiLSTM.latency.median_ms, 1) : "–" })],
  ];
  $("#home-stats").innerHTML = tiles.map(([v, label]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(label)}</span></div>`).join("");
}

function renderHomeJobs() {
  const picks = state.jobs.filter((j) => j.image).slice(0, 8);
  $("#home-jobs").innerHTML = picks.map(jobCard).join("");
  bindJobCards($("#home-jobs"), (id) => { go(2); selectJob(id); });
}

$("#home-start").addEventListener("click", () => go(1));
$("#home-lab").addEventListener("click", () => showView("lab"));
$("#home-all-jobs").addEventListener("click", () => go(2));
$$(".how-steps li").forEach((li) => li.addEventListener("click", () => go(+li.dataset.step)));

// ------------------------------------------------------------ profile panel (beside the steps)

function renderProfile() {
  const box = $("#profile");
  const sec = (step, title, body) => `<section class="pf-sec" data-step="${step}"><h4>${esc(title)}</h4>${body}</section>`;
  const none = (key) => `<p class="pf-empty">${esc(t(key))}</p>`;
  const skills = state.cvSkills;
  const cv = skills.length
    ? `<p class="pf-big">${esc(t("prof.skills_n", { n: skills.length }))}</p><div class="pf-chips">${skills.slice(0, 10).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}${skills.length > 10 ? `<span class="more">+${skills.length - 10}</span>` : ""}</div>`
    : none("prof.no_cv");
  const job = state.job ? `<p class="pf-big">${esc(state.job.title)}</p><p class="pf-sub">${esc(state.job.company || "")} · ${esc(t("prof.job_skills", { n: state.job.extraction.skills.length }))}</p>` : none("prof.no_job");
  const topics = Object.entries(state.quizScores);
  const quiz = topics.length
    ? `<div class="pf-bars">${topics.map(([tp, s]) => `<div class="pf-bar"><span>${esc(topicName(tp))}</span><i><b style="width:${s.ratio * 100}%;background:${s.ratio < 0.6 ? "var(--warn)" : "var(--good)"}"></b></i><em>${pct(s.ratio)}</em></div>`).join("")}</div>`
    : none("prof.no_quiz");
  const best = state.ranking?.find((r) => r.match.scores.combined !== null);
  const match = best
    ? `<p class="pf-big">${esc(best.title)}</p><p class="pf-sub">${esc(t("prof.best", { pct: pct(best.match.scores.combined) }))}</p>`
    : none("prof.no_match");
  const p = roadDone();
  const road = p
    ? `<p class="pf-sub">${esc(state.roadmap.title)}</p><div class="pf-bar"><span>${esc(t("road.progress", { done: p.done, n: p.total }))}</span><i><b style="width:${(p.done / p.total) * 100}%;background:var(--good)"></b></i></div>`
    : none("prof.no_road");
  box.innerHTML = `<h3>${esc(t("prof.title"))}</h3>` +
    sec(1, t("rail.cv"), cv) + sec(2, t("rail.job"), job) + sec(3, t("rail.quiz"), quiz) +
    sec(4, t("prof.best_title"), match) + sec(5, t("rail.roadmap"), road);
  $$(".pf-sec", box).forEach((el) => el.addEventListener("click", () => go(+el.dataset.step)));
}

function renderCompare() {
  const { text, res } = state.lastCompare;
  const names = { bilstm: "BiLSTM", distilbert: "DistilBERT" };
  const col = (n) => {
    const r = res[n];
    return `<div class="cmp-col"><h4>${esc(names[n])}</h4>
      <p class="meta">${esc(t("lab.cmp_meta", { n: r.mentions.length, ms: r.ms.toFixed(1) }))}</p>
      <div class="highlight">${highlight(text, r.mentions, new Set(r.only_here.map(spanKey)))}</div></div>`;
  };
  const diff = (n) => `<li><strong>${esc(t("lab.cmp_only", { model: names[n] }))}</strong> ${res[n].only_here.length
    ? res[n].only_here.map((m) => `<span class="tag ${m.type === "skill" ? "s" : "k"}">${esc(m.text)} · ${esc(t(`label.${m.type}`))}</span>`).join(" ")
    : esc(t("lab.cmp_none"))}</li>`;
  $("#lab-compare-out").innerHTML = `<h3>${esc(t("lab.cmp_title"))}</h3>
    <p class="hint">${esc(t("lab.cmp_hint"))}</p>
    <div class="legend">${legend().replace(/^<div class="legend">|<\/div>$/g, "")}<mark class="only">${esc(t("lab.cmp_only_mark"))}</mark></div>
    <div class="cmp-grid">${col("bilstm")}${col("distilbert")}</div>
    <p>${esc(t("lab.cmp_agree", { n: res.agree }))}</p>
    <ul class="cmp-diff">${diff("bilstm")}${diff("distilbert")}</ul>`;
}

$("#lab-compare").addEventListener("click", (e) => busy(e.target, async () => {
  const text = $("#lab-text").value;
  const out = $("#lab-compare-out");
  try {
    out.innerHTML = readingSkeleton(t("lab.cmp_reading"));
    const res = await api("/skills/compare", { json: { text } });
    state.lastCompare = { text, res };
    renderCompare();
  } catch (err) {
    out.innerHTML = `<p class="msg error">${esc(err.message)}</p>`;
  }
}));

boot();
