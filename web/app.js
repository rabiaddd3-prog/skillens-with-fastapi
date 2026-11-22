// SkillLens frontend. Plain JS, talks to the FastAPI backend on the same origin.
// The CV text never leaves this page except for the analysis request; nothing is saved.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => (x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`);

const state = {
  dictionary: { topics: {}, skills: [] },
  cvCandidates: [],     // [{skill, evidence, topic, added?}]
  cvSkills: [],         // confirmed
  jobs: [],
  jobId: null,
  job: null,            // selected job with extraction
  quiz: null,           // running quiz {session_id, questions, answers, i}
  quizScores: {},       // {topic: {correct,total,ratio}}
  roadmapJobId: null,
};

const STATUS_TEXT = {
  cv_and_quiz: "CV and quiz",
  cv_only: "CV only",
  quiz_only: "quiz only",
  weak_quiz: "weak quiz result",
  missing: "missing",
};

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Cannot reach the SkillLens API. Is the server running?");
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
  btn.textContent = "Working…";
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = label; }
}

// ------------------------------------------------------------ navigation

let currentStep = 1;

function go(step) {
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
  if (step === 3) renderTopicPick();
  if (step === 4) loadMatches();
  if (step === 5) loadRoadmap();
}

function railState(step, text, done = true) {
  $(`#rail-${step}`).textContent = text;
  $(`.rail-step[data-step="${step}"]`).classList.toggle("done", done);
}

$$(".rail-step").forEach((li) => li.addEventListener("click", () => go(+li.dataset.step)));
$$(".tab").forEach((t) => t.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === t.dataset.view));
  if (t.dataset.view === "lab") loadLab();
}));

// ------------------------------------------------------------ theme
// The page sets data-theme before CSS loads (no flash). Light is the default; a choice of dark is
// remembered in localStorage.

function setThemeLabel() {
  $("#theme-toggle").textContent = document.documentElement.dataset.theme === "dark" ? "Light mode" : "Dark mode";
}
$("#theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("skilllens-theme", next);
  setThemeLabel();
});
setThemeLabel();

// ------------------------------------------------------------ health + dictionary

async function boot() {
  try {
    const h = await api("/health");
    const el = $("#health");
    el.className = `health ${h.model_loaded ? "ok" : "bad"}`;
    el.textContent = h.model_loaded ? `model: ${h.model}` : "model not loaded";
    el.title = h.model_error || `${h.jobs} jobs in catalog`;
  } catch (e) {
    $("#health").className = "health bad";
    $("#health").textContent = "API offline";
  }
  try {
    state.dictionary = await api("/skills/dictionary");
    $("#skill-list").innerHTML = state.dictionary.skills.map((s) => `<option value="${esc(s.name)}">`).join("");
  } catch { /* the add box simply has no suggestions */ }
  loadJobs();
}

const topicOf = (skill) => state.dictionary.skills.find((s) => s.name === skill)?.topic ?? null;
const topicName = (t) => state.dictionary.topics[t] || t;

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
  say(msg, `Reading ${file.name}…`);
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await api("/cv/analyze", { method: "POST", body: form });
    setCandidates(res.skills);
    say(msg, `Found ${res.skills.length} skills in ${res.characters.toLocaleString()} characters.`, "ok");
  } catch (e) {
    say(msg, e.message, "error");
  }
  $("#cv-file").value = "";
}

$("#cv-analyze").addEventListener("click", (e) => busy(e.target, async () => {
  const msg = $("#cv-msg");
  try {
    const res = await api("/cv/analyze-text", { json: { text: $("#cv-text").value } });
    setCandidates(res.skills);
    say(msg, `Found ${res.skills.length} skills.`, "ok");
  } catch (err) {
    say(msg, err.message, "error");
  }
}));

function setCandidates(skills) {
  state.cvCandidates = skills;
  renderChips();
}

function renderChips() {
  const box = $("#cv-chips");
  $("#cv-count").textContent = state.cvCandidates.length;
  $("#cv-confirm").disabled = state.cvCandidates.length === 0;
  if (!state.cvCandidates.length) {
    box.innerHTML = '<p class="empty">Nothing yet.</p>';
    return;
  }
  box.innerHTML = state.cvCandidates.map((c, i) => `
    <span class="chip ${c.added ? "added" : ""}" title="${esc(c.added ? "Added by you" : c.evidence.join("\n…\n"))}">
      ${esc(c.skill)}${c.topic ? ` <span class="topic">${esc(topicName(c.topic))}</span>` : ""}
      <button aria-label="Remove ${esc(c.skill)}" data-i="${i}">×</button>
    </span>`).join("");
  $$("button", box).forEach((b) => b.addEventListener("click", () => {
    state.cvCandidates.splice(+b.dataset.i, 1);
    renderChips();
  }));
}

function addSkill() {
  const input = $("#cv-add");
  const raw = input.value.trim();
  if (!raw) return;
  const known = state.dictionary.skills.find((s) => s.name.toLowerCase() === raw.toLowerCase());
  const name = known ? known.name : raw;
  if (!state.cvCandidates.some((c) => c.skill.toLowerCase() === name.toLowerCase())) {
    state.cvCandidates.push({ skill: name, evidence: [], topic: known?.topic ?? null, added: true });
  }
  input.value = "";
  renderChips();
}
$("#cv-add-btn").addEventListener("click", addSkill);
$("#cv-add").addEventListener("keydown", (e) => e.key === "Enter" && addSkill());

$("#cv-confirm").addEventListener("click", () => {
  state.cvSkills = state.cvCandidates.map((c) => c.skill);
  railState(1, `${state.cvSkills.length} skills`);
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

function renderJobList() {
  const q = $("#job-filter").value.toLowerCase();
  const items = state.jobs.filter((j) => `${j.title} ${j.company}`.toLowerCase().includes(q));
  $("#job-list").innerHTML = items.map((j) => `
    <li data-id="${j.id}" class="${j.id === state.jobId ? "active" : ""}">
      ${thumb(j.image)}
      <span class="job-text">
        <span class="title">${esc(j.title)}</span>
        <span class="meta">${esc(j.company || "—")} · ${esc(j.location || j.source)}
          ${j.is_demo ? '<span class="badge demo">demo</span>' : j.source !== "manual" ? `<span class="badge live">${esc(j.source)}</span>` : ""}</span>
      </span>
    </li>`).join("") || '<li class="empty">No jobs match.</li>';
  $$("#job-list li[data-id]").forEach((li) => li.addEventListener("click", () => selectJob(+li.dataset.id)));
}
$("#job-filter").addEventListener("input", renderJobList);

async function selectJob(id) {
  state.jobId = id;
  renderJobList();
  const box = $("#job-detail");
  box.innerHTML = readingSkeleton("The model is reading this job…");
  try {
    state.job = await api(`/jobs/${id}`);
    renderJob();
    railState(2, state.job.title.slice(0, 18));
  } catch (e) {
    box.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

function highlight(text, mentions) {
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
    const tip = cover.map((m) => `${m.found_by === "dictionary" ? "dictionary" : m.type}: "${m.text}"${m.normalized.length ? " → " + m.normalized.join(", ") : ""}`).join("\n");
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
      <td><span class="dot ${r.found_by === "dictionary" ? "dictionary" : r.type}"></span>${esc(r.found_by === "dictionary" ? "dictionary" : r.type)}</td>
      <td>${esc(r.text)}${r.mentions.length > 1 ? ` <span class="tag">×${r.mentions.length}</span>` : ""}</td>
      <td>${r.normalized.length ? esc(r.normalized.join(", ")) : '<span class="none">not matched</span>'}</td>
    </tr>`).join("");
  return `<table class="req-table"><thead><tr><th>Found by</th><th>Phrase in the ad</th><th>Normalised skill</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// Small square photo for demo jobs; jobs without a photo get an empty placeholder of the same size.
function thumb(image) {
  return image
    ? `<img class="thumb" src="${esc(image.url)}" alt="" loading="lazy">`
    : '<span class="thumb thumb-none" aria-hidden="true"></span>';
}

function renderJob() {
  const j = state.job;
  const ex = j.extraction;
  $("#job-detail").innerHTML = `
    ${j.image ? `<figure class="job-photo"><img src="${esc(j.image.url)}" alt="${esc(j.image.alt)}">
      <figcaption>Representative photo: <a href="${esc(j.image.page_url)}" target="_blank" rel="noopener">${esc(j.image.photographer)} on ${esc(j.image.source)}</a></figcaption></figure>` : ""}
    <div class="head">
      <div>
        <h3>${esc(j.title)}</h3>
        <span class="meta">${esc(j.company || "")} · ${esc(j.location || "")} · source: ${esc(j.source)}
          ${j.is_demo ? '<span class="badge demo">demo</span>' : ""}
          ${j.url ? `· <a href="${esc(j.url)}" target="_blank" rel="noopener">original posting</a>` : ""}</span>
      </div>
      <button class="btn primary" id="job-next">Take the quiz for this job</button>
    </div>
    <div class="legend"><mark class="s">skill</mark><mark class="k">knowledge</mark><mark class="d">dictionary</mark></div>
    <div class="highlight">${highlight(j.description, ex.mentions)}</div>
    <p class="hint">Recognised skills: <strong>${ex.skills.length ? esc(ex.skills.join(", ")) : "none"}</strong>
      ${ex.unmatched.length ? ` · ${ex.unmatched.length} phrases not in the dictionary (kept visible below)` : ""}</p>
    ${requirementsTable(ex)}`;
  $("#job-next").addEventListener("click", () => go(3));
}

$("#job-add").addEventListener("click", (e) => busy(e.target, async () => {
  const msg = $("#job-msg");
  try {
    const res = await api("/jobs/import", { json: { source: "manual", title: $("#job-title").value || "Untitled job", company: $("#job-company").value || null, description: $("#job-desc").value } });
    const r = res.imported[0];
    say(msg, r.status === "unchanged" ? "This job is already in the catalog." : `Job ${r.status}.`, "ok");
    await loadJobs();
    selectJob(r.id);
  } catch (err) {
    say(msg, err.message, "error");
  }
}));

$("#live-import").addEventListener("click", (e) => busy(e.target, async () => {
  const msg = $("#job-msg");
  say(msg, "Contacting the job source…");
  try {
    const res = await api("/jobs/import", { json: { source: $("#live-source").value, board: $("#live-board").value, limit: 20 } });
    const c = res.counts;
    say(msg, `Imported from ${res.source}: ${c.created} new, ${c.updated} updated, ${c.unchanged} unchanged.`, "ok");
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
  const jobTopics = new Set((state.job?.extraction.skills || []).map(topicOf).filter(Boolean));
  const cvTopics = new Set(state.cvSkills.map(topicOf).filter(Boolean));
  $("#topic-pick").innerHTML = Object.entries(quizTopics.topics).map(([t, n]) => {
    const fromJob = jobTopics.has(t);
    const done = state.quizScores[t];
    return `<label class="${fromJob ? "from-job" : ""}">
      <input type="checkbox" value="${esc(t)}" ${fromJob || (!jobTopics.size && cvTopics.has(t)) ? "checked" : ""}>
      ${esc(quizTopics.names[t] || t)} <small>${fromJob ? "in job" : ""}${done ? ` · last ${pct(done.ratio)}` : ""}</small>
      <span class="tag">${n} q</span></label>`;
  }).join("");
}

$("#q-total").addEventListener("input", (e) => { $("#q-total-out").textContent = e.target.value; });

$("#quiz-start").addEventListener("click", (e) => busy(e.target, async () => {
  const topics = $$("#topic-pick input:checked").map((i) => i.value);
  try {
    const q = await api("/quiz/start", { json: { topics, total: +$("#q-total").value } });
    state.quiz = { ...q, answers: {}, i: 0 };
    $("#quiz-setup").hidden = true;
    $("#quiz-result").hidden = true;
    $("#quiz-run").hidden = false;
    say($("#quiz-msg"), q.count < q.requested ? `The bank holds ${q.count} questions for these topics.` : "");
    renderQuestion();
  } catch (err) {
    say($("#quiz-msg"), err.message, "error");
  }
}));

$("#quiz-skip").addEventListener("click", () => {
  railState(3, "skipped", false);
  go(4);
});

function renderQuestion() {
  const { questions, i, answers } = state.quiz;
  const q = questions[i];
 const answered = Object.keys(answers).length;
  $("#q-bar").style.width = `${(answered / questions.length) * 100}%`;
  $("#q-hp").textContent = `${answered} of ${questions.length} answered`;
  $("#q-index").textContent = `Question ${i + 1} / ${questions.length} · ${q.difficulty}`;
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
  if (open && !confirm(`${open} questions are unanswered and will count as wrong. Submit anyway?`)) return;
  try {
    const res = await api("/quiz/submit", { json: { session_id, answers } });
    Object.assign(state.quizScores, res.topics);
    renderQuizResult(res);
    railState(3, `${pct(res.ratio)} overall`);
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
  return ratio === null || ratio === undefined ? "–" : `<span data-count="${Math.round(ratio * 100)}" data-suffix="%">0%</span>`;
}

function animate(root = document) {
  const instant = reduceMotion();
  requestAnimationFrame(() => {
    $$("[data-w]", root).forEach((el) => { el.style.width = `${el.dataset.w}%`; });
    $$(".ring-arc", root).forEach((el) => { el.style.strokeDasharray = `${el.dataset.len} ${el.dataset.c}`; });
  });
  $$("[data-count]", root).forEach((el) => {
    const target = +el.dataset.count, suffix = el.dataset.suffix || "";
    if (instant) { el.textContent = target + suffix; return; }
    const t0 = performance.now(), dur = 800;
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / dur), eased = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(target * eased) + suffix;
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
    <h3>${res.correct} / ${res.total} correct (${countUp(res.ratio)})</h3>
    <p class="hint">Per topic. The dotted line marks 60%: below it a topic counts as weak evidence.</p>
    <div class="score-bars">${Object.entries(res.topics).map(([t, s]) => scoreBar(topicName(t), s.ratio, `${s.correct}/${s.total}`)).join("")}</div>
    <button class="btn primary" id="to-matches">See job matches</button>
    <button class="btn ghost" id="quiz-again">Take another quiz</button>
    <div class="review">${res.review.map((r) => `
      <details><summary class="${r.correct ? "right" : "wrong"}">${r.correct ? "✓" : "✗"} ${esc(r.question.split("\n")[0])}</summary>
        <p>Your answer: ${r.given === null || r.given === undefined ? "none" : esc(r.options[r.given])} · Correct: <strong>${esc(r.options[r.answer])}</strong></p>
        <p>${esc(r.explanation)}</p></details>`).join("")}</div>`;
  animate(box);
  $("#to-matches").addEventListener("click", () => go(4));
  $("#quiz-again").addEventListener("click", () => {
    box.hidden = true;
    $("#quiz-setup").hidden = false;
    renderTopicPick();
  });
}

// ------------------------------------------------------------ step 4: matches

function ring(value) {
  const r = 42, c = 2 * Math.PI * r;
  const v = value ?? 0;
  const colour = value === null ? "var(--line)" : v >= 0.7 ? "var(--good)" : v >= 0.4 ? "var(--dict)" : "var(--warn)";
  return `<svg class="ring" viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--paper-2)" stroke-width="10"/>
    <circle class="ring-arc" cx="50" cy="50" r="${r}" fill="none" stroke="${colour}" stroke-width="10" stroke-dasharray="0 ${c}" data-len="${c * v}" data-c="${c}" transform="rotate(-90 50 50)"/>
    <text x="50" y="55" text-anchor="middle">${value === null ? "n/a" : `<tspan data-count="${Math.round(v * 100)}">0</tspan>`}</text>
    <text x="50" y="70" text-anchor="middle" class="sub">match</text></svg>`;
}

async function loadMatches() {
  const list = $("#match-list");
  list.innerHTML = '<p class="empty">Scoring every job in the catalog…</p>';
  try {
    const { ranking } = await api("/matches", { json: { cv_skills: state.cvSkills, quiz_scores: state.quizScores } });
    const w = ranking[0]?.match.weights || { cv: 0.5, quiz: 0.5 };
    $("#match-formula").innerHTML = `combined = ${w.cv} × CV coverage + ${w.quiz} × quiz performance. If no quiz result covers a job's topics, combined = CV coverage. Jobs with no recognised skills cannot be scored.`;
    list.innerHTML = `<div class="status-legend">${Object.entries(STATUS_TEXT).map(([k, v]) => `<span class="st ${k}">${v}</span>`).join("")}</div>` +
      ranking.map((j) => {
        const m = j.match, s = m.scores;
        return `<div class="card match">
          ${ring(s.combined)}
          <div>
            <div class="match-head">${thumb(j.image)}<div>
              <h3>${esc(j.title)}</h3>
              <span class="meta">${esc(j.company || "")} ${j.is_demo ? '<span class="badge demo">demo</span>' : ""}</span>
            </div></div>
            <div class="mini">
              <div>CV coverage<b>${countUp(s.cv_coverage)}</b><i><span class="grow" data-w="${(s.cv_coverage ?? 0) * 100}"></span></i></div>
              <div>Quiz performance<b>${countUp(s.quiz_performance)}</b><i><span class="grow" data-w="${(s.quiz_performance ?? 0) * 100}"></span></i></div>
              <div>Quiz coverage<b>${countUp(s.quiz_coverage)}</b><i><span class="grow" data-w="${(s.quiz_coverage ?? 0) * 100}"></span></i></div>
            </div>
            <div class="status-chips">${m.skills.map((r) => `<span class="st ${r.status}" title="${esc(STATUS_TEXT[r.status])}${r.quiz ? ` · quiz ${pct(r.quiz.ratio)}` : r.quiz_state === "not_evaluated" ? " · not evaluated by quiz" : r.quiz_state === "no_quiz_for_skill" ? " · no quiz for this skill" : ""}">${esc(r.skill)}</span>`).join("")}</div>
            ${m.notes.length ? `<ul class="notes">${m.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
            <button class="btn" data-id="${j.id}">Show roadmap</button>
          </div></div>`;
      }).join("");
    animate(list);
    $$("#match-list .btn[data-id]").forEach((b) => b.addEventListener("click", () => {
      state.roadmapJobId = +b.dataset.id;
      go(5);
    }));
    railState(4, `${ranking.length} ranked`);
  } catch (e) {
    list.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

// ------------------------------------------------------------ step 5: roadmap

async function loadRoadmap() {
  const box = $("#roadmap");
  const id = state.roadmapJobId ?? state.jobId;
  if (!id) {
    box.innerHTML = '<p class="empty">Pick a job in step 2 or step 4 first.</p>';
    return;
  }
  box.innerHTML = '<p class="empty">Building your plan…</p>';
  try {
    const res = await api("/roadmap", { json: { job_id: id, cv_skills: state.cvSkills, quiz_scores: state.quizScores } });
    const rm = res.roadmap;
    const have = res.match.skills.filter((r) => ["cv_only", "cv_and_quiz", "quiz_only"].includes(r.status));
    box.innerHTML = `
      <div class="card"><h3>${esc(res.job.title)} <span class="meta">${esc(res.job.company || "")}</span></h3>
        <p class="hint">Already backed by evidence: ${have.length ? have.map((r) => `<span class="st ${r.status}">${esc(r.skill)}</span>`).join(" ") : "none"}</p>
        <div class="step-actions"><button class="btn primary" id="pdf-download">Download PDF summary</button></div>
        <p class="msg" id="pdf-msg" role="status"></p></div>
      ${rm.message ? `<div class="card"><p>${esc(rm.message)}</p></div>` : `<div class="road">${rm.steps.map((s) => `
        <div class="card road-step ${s.kind}" data-n="${s.order}">
          <span class="kind">${s.kind === "prerequisite" ? "prerequisite" : "gap"}</span>
          <h3>${esc(s.title)}</h3>
          <p>${esc(s.reason)}</p>
          <div class="goal">${esc(s.goal)}</div>
          ${s.courses.length ? `<ul class="courses">${s.courses.map((c) => `<li><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a><span class="prov">${esc(c.provider)}${c.language ? " · " + esc(c.language) : ""}</span></li>`).join("")}</ul>` : '<p class="hint">No course linked for this topic yet.</p>'}
        </div>`).join("")}</div>`}`;
    railState(5, rm.steps.length ? `${rm.steps.length} steps` : "no gaps");
    $("#pdf-download").addEventListener("click", (e) => busy(e.target, () => downloadPdf(id)));
  } catch (e) {
    box.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

async function downloadPdf(jobId) {
  const msg = $("#pdf-msg");
  try {
    const res = await fetch("/roadmap/pdf", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, cv_skills: state.cvSkills, quiz_scores: state.quizScores }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `skilllens_job${jobId}.pdf` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    say(msg, "PDF downloaded.", "ok");
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
        rows.push(`<tr><td>${esc(scope)} · ${esc(n)}</td>${cell("precision")}${cell("recall")}${cell("f1")}<td>${s.tp}/${s.n_gold}</td></tr>`);
      }
    }
    $("#lab-setup").textContent = `Measured on the SkillSpan test split (${r.test_sentences.toLocaleString()} sentences) on ${r.device}. Entity-level: a span counts only if boundaries and type match exactly.`;
    $("#lab-scores").innerHTML = `<h3>Accuracy</h3><table class="table"><thead><tr><th>Scope · model</th><th>P</th><th>R</th><th>F1</th><th>TP / gold</th></tr></thead><tbody>${rows.join("")}</tbody></table>
      <div class="score-bars">${names.map((n) => scoreBar(`${n} F1`, r.models[n].scores.overall.f1, "", null)).join("")}</div>`;
    const maxMs = Math.max(...names.map((n) => r.models[n].latency.p90_ms));
    $("#lab-latency").innerHTML = `<h3>Speed</h3>
      <p class="hint">Per sentence, batch size 1, ${r.latency_setup.latency_sentences} test sentences after ${r.latency_setup.warmup} warm-up runs; includes tokenisation and decoding.</p>
      <table class="table"><thead><tr><th>Model</th><th>Median ms</th><th>p90 ms</th><th>Params</th><th>Best val epoch</th></tr></thead><tbody>
      ${names.map((n) => { const m = r.models[n]; return `<tr><td>${esc(n)}</td><td>${m.latency.median_ms.toFixed(2)}</td><td>${m.latency.p90_ms.toFixed(2)}</td><td>${(m.parameters / 1e6).toFixed(1)}M</td><td>${m.best_val_epoch}</td></tr>`; }).join("")}
      </tbody></table>
      <div class="score-bars">${names.map((n) => `<div class="bar-row"><span>${esc(n)}</span><div class="bar"><div class="grow" data-w="${(r.models[n].latency.median_ms / maxMs) * 100}" style="background:var(--ink)"></div></div><span>${r.models[n].latency.median_ms.toFixed(1)} ms</span></div>`).join("")}</div>
      <h3>Error types</h3>
      <table class="table"><thead><tr><th>Model</th><th>Boundary</th><th>False pos.</th><th>False neg.</th></tr></thead><tbody>
      ${names.map((n) => { const e = r.models[n].error_counts; const sum = (t) => (e[`skill_${t}`] || 0) + (e[`knowledge_${t}`] || 0); return `<tr><td>${esc(n)}</td><td>${sum("boundary")}</td><td>${sum("fp")}</td><td>${sum("fn")}</td></tr>`; }).join("")}
      </tbody></table>`;
    animate($("#lab"));
  } catch (e) {
    $("#lab-scores").innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

$("#lab-run").addEventListener("click", (e) => busy(e.target, async () => {
  const text = $("#lab-text").value;
  try {
    $("#lab-out").innerHTML = readingSkeleton("The model is reading…");
    const t0 = performance.now();
    const ex = await api("/skills/extract", { json: { text } });
    const ms = performance.now() - t0;
    $("#lab-out").innerHTML = highlight(text, ex.mentions) +
      `\n\n<span class="hint">${ex.mentions.length} spans · skills: ${esc(ex.skills.join(", ") || "none")} · round trip ${ms.toFixed(0)} ms (includes HTTP)</span>`;
  } catch (err) {
    $("#lab-out").innerHTML = `<span class="msg error">${esc(err.message)}</span>`;
  }
}));

boot();
