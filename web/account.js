// Accounts: sign in / register, and keep the user's data on the server.
// Without an account everything still works and stays in this browser (localStorage);
// after signing in, CV skills, quiz results, roadmap ticks and saved jobs are stored via /users/me/*.
// Loaded after app.js and uses its helpers (api, t, esc, state, ...).

const TOKEN_KEY = "skilllens-token";

const Account = {
  user: null,
  saved: new Set(),   // ids of bookmarked jobs

  token() { return localStorage.getItem(TOKEN_KEY); },
  signedIn() { return !!this.user; },

  async init() {
    $("#auth-btn").addEventListener("click", () => (this.user ? this.toggleMenu() : this.open("login")));
    $("#auth-close").addEventListener("click", () => $("#auth-dialog").close());
    $$("#auth-dialog [data-auth-tab]").forEach((b) => b.addEventListener("click", () => this.open(b.dataset.authTab)));
    $("#auth-form").addEventListener("submit", (e) => { e.preventDefault(); this.submit(); });
    $("#auth-logout").addEventListener("click", () => this.signOut());
    document.addEventListener("click", (e) => {
      const star = e.target.closest("#job-save");
      if (star) this.toggleSaved(+star.dataset.id);
      if (!e.target.closest(".account")) $("#auth-menu").hidden = true;
    });
    document.addEventListener("langchange", () => this.paint());
    if (this.token()) {
      // wait until app.js has loaded the skill dictionary (needed to show saved CV skills)
      await new Promise((r) => { const tick = () => (state.dictionary?.skills?.length ? r() : setTimeout(tick, 50)); tick(); });
      try {
        this.user = await api("/users/me");
        await this.pull();
      } catch { this.forget(); }
    }
    this.paint();
  },

  open(mode) {
    const dlg = $("#auth-dialog");
    dlg.dataset.mode = mode;
    $$("[data-auth-tab]", dlg).forEach((b) => b.classList.toggle("active", b.dataset.authTab === mode));
    $("#auth-name-row").hidden = mode !== "register";
    $("#auth-name").required = mode === "register";
    $("#auth-submit").textContent = t(mode === "register" ? "acc.register" : "acc.login");
    $("#auth-password").autocomplete = mode === "register" ? "new-password" : "current-password";
    say($("#auth-msg"), "");
    if (!dlg.open) dlg.showModal();
    $("#auth-email").focus();
  },

  async submit() {
    const mode = $("#auth-dialog").dataset.mode;
    const email = $("#auth-email").value.trim(), password = $("#auth-password").value;
    const btn = $("#auth-submit");
    await busy(btn, async () => {
      try {
        if (mode === "register") {
          await api("/auth/register", { json: { email, password, name: $("#auth-name").value.trim() } });
        }
        const form = new URLSearchParams({ username: email, password });
        const res = await fetch("/auth/token", { method: "POST", body: form, headers: { "X-Lang": LANG } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
        localStorage.setItem(TOKEN_KEY, data.access_token);
        this.user = data.user;
        await this.pull(true);
        $("#auth-dialog").close();
        $("#auth-password").value = "";
        this.paint();
      } catch (err) {
        say($("#auth-msg"), err.message, "error");
      }
    });
  },

  forget() {
    localStorage.removeItem(TOKEN_KEY);
    this.user = null;
    this.saved = new Set();
  },

  signOut() {
    this.forget();
    $("#auth-menu").hidden = true;
    this.paint();
  },

  toggleMenu() { $("#auth-menu").hidden = !$("#auth-menu").hidden; },

  paint() {
    const btn = $("#auth-btn");
    btn.textContent = this.user ? this.user.name : t("acc.login");
    btn.classList.toggle("signed-in", !!this.user);
    $("#auth-who").textContent = this.user ? this.user.email : "";
    const star = $("#job-save");
    if (star) this.paintStar(star);
  },

  // ---- server <-> browser

  // After sign-in: take the server's data; local data the server does not have yet is sent up.
  async pull(pushLocal = false) {
    const [profile, results, roadmaps, saved] = await Promise.all([
      api("/users/me/profile"), api("/users/me/quiz-results"), api("/users/me/roadmaps"), api("/users/me/saved-jobs")]);
    this.saved = new Set(saved.map((s) => s.job_id));

    if (profile.cv_skills.length && !state.cvSkills.length) {
      state.cvSkills = profile.cv_skills;
      state.cvCandidates = profile.cv_skills.map((s) => ({ skill: s, evidence: [], topic: topicOf(s) }));
      renderChips();
      railState(1, "s1.rail", { n: state.cvSkills.length });
      state.ranking = null;
      renderJobList();
    } else if (pushLocal && state.cvSkills.length && !profile.cv_skills.length) {
      this.saveProfile();
    }

    if (results.length && !Object.keys(state.quizScores).length) {
      // the latest saved quiz counts as the quiz evidence for matching, as after taking it
      const last = results[results.length - 1];
      state.quizScores = Object.fromEntries(Object.entries(last.scores).map(([k, v]) => [k, { ...v, level: last.level }]));
      state.ranking = null;
    }
    if (results.length) {
      const list = results.map((r) => ({ date: r.taken_at, level: r.level, ratio: r.total ? r.correct / r.total : 0,
        topics: Object.fromEntries(Object.entries(r.scores).map(([k, v]) => [k, v.ratio])) }));
      localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(-30)));
      renderHistory();
    }

    let local = {};
    try { local = JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {}; } catch { /* none */ }
    for (const r of roadmaps) local[r.job_id] = [...new Set([...(local[r.job_id] || []), ...r.done])];
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(local));
    if (pushLocal) {
      for (const [jobId, done] of Object.entries(local)) {
        if (!roadmaps.some((r) => r.job_id === +jobId)) this.saveProgress(+jobId, done);
      }
    }
    renderProfile();
  },

  async saveProfile() {
    if (!this.user) return;
    try { await api("/users/me/profile", { method: "PUT", json: { cv_skills: state.cvSkills } }); } catch { /* kept locally */ }
  },

  async saveQuiz(res) {
    if (!this.user) return;
    const scores = Object.fromEntries(Object.entries(res.topics).map(([k, v]) => [k, { correct: v.correct, total: v.total, ratio: v.ratio }]));
    try {
      await api("/users/me/quiz-results", { json: { level: res.level, correct: res.correct, total: res.total, scores } });
    } catch { /* kept locally */ }
  },

  async saveProgress(jobId, done) {
    if (!this.user) return;
    try { await api(`/users/me/roadmaps/${jobId}`, { method: "PUT", json: { done: [...done] } }); } catch { /* kept locally */ }
  },

  // ---- saved jobs (star on the job view)

  starButton(jobId) {
    return `<button class="btn ghost star" id="job-save" data-id="${jobId}" aria-pressed="false"></button>`;
  },

  paintStar(btn) {
    const on = this.saved.has(+btn.dataset.id);
    btn.setAttribute("aria-pressed", String(on));
    btn.classList.toggle("on", on);
    btn.textContent = on ? `★ ${t("acc.saved")}` : `☆ ${t("acc.save")}`;
    btn.title = this.user ? "" : t("acc.save_hint");
  },

  async toggleSaved(jobId) {
    if (!this.user) { this.open("login"); return; }
    const on = this.saved.has(jobId);
    try {
      if (on) await api(`/users/me/saved-jobs/${jobId}`, { method: "DELETE" });
      else await api("/users/me/saved-jobs", { json: { job_id: jobId } });
      on ? this.saved.delete(jobId) : this.saved.add(jobId);
    } catch (err) {
      if (!on && /saved|kayıtlı/i.test(err.message)) this.saved.add(jobId);
    }
    this.paint();
    renderProfile();
  },
};

window.Account = Account;  // app.js calls it as window.Account (a top-level const is not a window property)
Account.init();
