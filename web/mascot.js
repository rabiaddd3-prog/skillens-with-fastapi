// CVcik: a small walking CV page that follows the pointer and explains whatever the pointer is over.
// Tips are fixed texts written for each part of the page (no AI, works offline). The figure never
// takes clicks (pointer-events: none); it is switched on and off from the "Helper" button in the header,
// since a close button on a figure that follows the pointer could never be reached.
(() => {
  // Most specific first: the first selector that matches the hovered element wins. [selector, English, Turkish]
  const TIPS = [
    ["#lang-toggle", "Prefer Turkish? One click.", "İngilizce mi istersin? Tek tık yeter."],
    ["#theme-toggle", "Too bright? Try dark mode.", "Çok mu parlak? Koyu temayı dene."],
    ["#mascot-toggle", "You can switch me off here. I won't be offended. Much.", "Beni buradan kapatabilirsin. Alınmam. Pek."],
    [".tab[data-view='lab']", "See how BiLSTM and DistilBERT compare on the test set.", "BiLSTM ve DistilBERT'in test kümesinde nasıl karşılaştırıldığını gör."],
    [".rail-step", "You can jump between steps any time.", "Adımlar arasında istediğin zaman geçebilirsin."],
    ["#drop", "Drop a text-based PDF here. Scanned CVs are just pictures to me, so paste the text below instead.", "Metin tabanlı bir PDF bırak. Taranmış CV'ler benim için sadece resim, metni aşağıya yapıştır."],
    ["#cv-text", "Paste your CV text here, then press Analyse text.", "CV metnini buraya yapıştır, sonra Metni analiz et'e bas."],
    ["#cv-analyze", "I'll look for skills from the skill dictionary.", "Beceri sözlüğündeki becerileri arayacağım."],
    [".chip button", "Wrong skill? Click × and it's gone.", "Yanlış beceri mi? × işaretine tıkla, gitsin."],
    ["#cv-chips", "These are the skills I found. Hover one to see where it was in your CV.", "Bulduğum beceriler bunlar. CV'nde nerede geçtiğini görmek için üzerine gel."],
    ["#cv-add, #cv-add-btn", "Missing something? Type a skill like Docker and add it.", "Eksik bir şey mi var? Docker gibi bir beceri yazıp ekle."],
    ["#cv-confirm", "Happy with the list? Confirm and we'll look at jobs.", "Liste tamam mı? Onayla, ilanlara bakalım."],
    ["#job-filter", "Search by job title or company.", "İlan başlığına ya da şirkete göre ara."],
    [".add-job summary", "You can paste any English job ad, or import live listings.", "İstediğin İngilizce ilanı yapıştırabilir ya da canlı ilan çekebilirsin."],
    ["#live-board", "Type a company's board name, for example gitlab.", "Şirketin pano adını yaz, örneğin gitlab."],
    ["#job-list li[data-id]", "Pick a job and the model will read it for you.", "Bir ilan seç, model senin için okusun."],
    [".job-photo", "Demo photos are only representative; the companies are made up.", "Demo fotoğraflar sadece temsilidir; şirketler kurgusaldır."],
    [".highlight .sp.s", "Orange means a skill: something you do.", "Turuncu beceri demek: yaptığın bir iş."],
    [".highlight .sp.k", "Blue means knowledge: a tool or technology.", "Mavi bilgi demek: bir araç ya da teknoloji."],
    [".highlight .sp.d", "Dashed ones were found by the dictionary, not by the model.", "Kesikli olanları model değil, sözlük buldu."],
    [".highlight", "This is the ad as the model read it. Hover a highlight for details.", "Model ilanı böyle okudu. Ayrıntı için işaretli bir yerin üzerine gel."],
    [".req-table", "Every phrase the model found. 'Not matched' ones stay visible so nothing is hidden.", "Modelin bulduğu her ifade. 'Eşleşmedi' olanlar da görünür kalıyor, hiçbir şey gizlenmiyor."],
    ["#job-next", "Ready? Let's test those skills.", "Hazır mısın? Hadi şu becerileri test edelim."],
    ["#topic-pick", "Topics from the job are ticked for you. Add or remove any.", "İlandaki konular senin için işaretlendi. İstediğini ekle ya da çıkar."],
    ["#level-pick", "Junior is the basics, mid is everyday work, senior goes deep. Pick the job's level.", "Junior temeller, mid günlük iş, senior derinlemesine. İlanın seviyesini seç."],
    ["#q-total", "More questions give a more reliable score.", "Soru sayısı arttıkça puan daha güvenilir olur."],
    ["#quiz-skip", "Skipping is fine; matches will then use your CV only.", "Atlayabilirsin; eşleşmeler o zaman yalnızca CV'ni kullanır."],
    ["#quiz-start", "Answers are shuffled every time, so no peeking at patterns!", "Şıklar her seferinde karışıyor, kalıp yakalamaya çalışma!"],
    [".option", "Pick one answer. You'll see the right one after submitting.", "Bir cevap seç. Doğrusunu gönderdikten sonra göreceksin."],
    ["#q-submit", "Unanswered questions count as wrong.", "Cevaplanmayan sorular yanlış sayılır."],
    ["#quiz-result .bar-row", "Below the dotted 60% line a topic counts as weak.", "Noktalı %60 çizgisinin altındaki konu zayıf sayılır."],
    [".review", "Open a question to see the right answer and why.", "Doğru cevabı ve nedenini görmek için bir soruyu aç."],
    [".ring", "Overall match: half CV coverage, half quiz score.", "Genel eşleşme: yarısı CV kapsaması, yarısı quiz puanı."],
    [".mini", "CV coverage, quiz performance, and how many of the job's topics the quiz covered.", "CV kapsaması, quiz performansı ve quiz'in ilanın konularından kaçını kapsadığı."],
    [".status-chips, .status-legend", "Green: CV and quiz. Blue: one of them. Red: weak quiz. Dashed: missing.", "Yeşil: CV ve quiz. Mavi: biri. Kırmızı: zayıf quiz. Kesikli: eksik."],
    [".notes", "Notes tell you when a score rests on little evidence.", "Notlar, bir puan az kanıta dayanıyorsa bunu söyler."],
    [".match .btn", "Let's turn the gaps into a plan.", "Hadi eksikleri bir plana çevirelim."],
    [".courses", "Free courses from Patika, BTK Akademi and Udemy.", "Patika, BTK Akademi ve Udemy'den ücretsiz kurslar."],
    ["#pdf-download", "Take this plan with you as a PDF.", "Bu planı PDF olarak yanına al."],
    [".road-step.prerequisite", "Learn this one first; the next step builds on it.", "Önce bunu öğren; sonraki adım bunun üzerine kurulu."],
    [".road-step", "Do the steps in order. Each one says why it's there.", "Adımları sırayla yap. Her biri neden orada olduğunu söylüyor."],
    ["#lab-text", "Paste any job text and watch the model highlight it.", "Herhangi bir ilan metni yapıştır, modelin nasıl işaretlediğini izle."],
    ["#lab-scores, #lab-latency", "Measured on 3,569 test sentences. DistilBERT is more accurate, BiLSTM is faster.", "3.569 test cümlesinde ölçüldü. DistilBERT daha doğru, BiLSTM daha hızlı."],
  ];
  const HOME_TIP = ["Hi, I'm CVcik! Move around and I'll explain things.", "Merhaba, ben CVcik! İmleci gezdir, sana anlatayım."];
  const isTr = () => typeof LANG !== "undefined" && LANG === "tr";
  const pick = (pair) => (isTr() ? pair[1] : pair[0]);

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const el = document.createElement("div");
  el.id = "cvcik";
  el.setAttribute("aria-live", "polite");
  el.innerHTML = `
    <div class="cvcik-bubble" role="status"></div>
    <svg class="cvcik-body" viewBox="0 0 120 120" aria-hidden="true">
      <g class="cvcik-legs">
        <line class="leg-l" x1="46" y1="100" x2="42" y2="113" stroke="#14213d" stroke-width="4" stroke-linecap="round"/>
        <line class="leg-r" x1="76" y1="100" x2="80" y2="113" stroke="#14213d" stroke-width="4" stroke-linecap="round"/>
      </g>
      <path d="M30 14 H76 L92 30 V100 H30 Z" fill="#ffffff" stroke="#14213d" stroke-width="3" stroke-linejoin="round"/>
      <path d="M76 14 V30 H92" fill="#e8edf5" stroke="#14213d" stroke-width="3" stroke-linejoin="round"/>
      <line x1="40" y1="80" x2="82" y2="80" stroke="#c9d4e6" stroke-width="4" stroke-linecap="round"/>
      <line x1="40" y1="90" x2="70" y2="90" stroke="#c9d4e6" stroke-width="4" stroke-linecap="round"/>
      <g class="cvcik-eyes">
        <circle cx="50" cy="46" r="8" fill="#ffffff" stroke="#14213d" stroke-width="2"/>
        <circle cx="72" cy="46" r="8" fill="#ffffff" stroke="#14213d" stroke-width="2"/>
        <circle class="pupil" data-cx="50" data-cy="46" cx="50" cy="46" r="4" fill="#14213d"/>
        <circle class="pupil" data-cx="72" data-cy="46" cx="72" cy="46" r="4" fill="#14213d"/>
      </g>
      <path class="cvcik-smile" d="M53 62 Q61 68 69 62" fill="none" stroke="#14213d" stroke-width="3" stroke-linecap="round"/>
      <ellipse class="cvcik-mouth" cx="61" cy="64" rx="5" ry="4" fill="#14213d"/>
    </svg>`;
  document.body.append(el);
  const bubble = el.querySelector(".cvcik-bubble");
  const pupils = [...el.querySelectorAll(".pupil")];
  const svg = el.querySelector(".cvcik-body");

  const SIZE = 84;                       // rendered figure size in px
  const OFFSET = { x: 34, y: 26 };       // where the figure sits relative to the pointer
  const pos = { x: innerWidth - SIZE - 24, y: innerHeight - SIZE - 24 };
  const target = { ...pos };
  const mouse = { x: pos.x, y: pos.y };
  let tipKey = null, tipTimer = null, hideTimer = null, moving = false;

  function enabled() { return localStorage.getItem("skilllens-mascot") !== "off"; }
  function apply() {
    el.hidden = !enabled();
    const btn = document.getElementById("mascot-toggle");
    if (btn) btn.textContent = typeof t === "function" ? t(enabled() ? "helper.on" : "helper.off")
      : (enabled() ? "Helper: on" : "Helper: off");
  }

  function say(text) {
    bubble.textContent = text;
    el.classList.add("talking");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => el.classList.remove("talking"), Math.max(2500, text.length * 70));
  }

  function tipFor(node) {
    if (!(node instanceof Element) || el.contains(node)) return null;
    for (const [sel, en, tr] of TIPS) if (node.closest(sel)) return [sel, isTr() ? tr : en];
    return null;
  }

  addEventListener("mousemove", (e) => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    // keep the figure beside the pointer, flipping sides near the right/bottom edge
    const right = e.clientX + OFFSET.x + SIZE < innerWidth - 8;
    const below = e.clientY + OFFSET.y + SIZE < innerHeight - 8;
    target.x = right ? e.clientX + OFFSET.x : e.clientX - OFFSET.x - SIZE;
    target.y = below ? e.clientY + OFFSET.y : e.clientY - OFFSET.y - SIZE;

    const hit = tipFor(e.target);
    const key = hit ? hit[0] : null;
    if (key !== tipKey) {
      tipKey = key;
      clearTimeout(tipTimer);
      if (hit) tipTimer = setTimeout(() => say(hit[1]), 280);  // wait until the pointer settles
    }
  }, { passive: true });

  addEventListener("resize", () => {
    target.x = Math.min(target.x, innerWidth - SIZE - 8);
    target.y = Math.min(target.y, innerHeight - SIZE - 8);
  });

  function frame() {
    if (!el.hidden) {
      const k = reduce ? 1 : 0.12;               // reduced motion: jump, no gliding
      const dx = target.x - pos.x, dy = target.y - pos.y;
      pos.x += dx * k;
      pos.y += dy * k;
      const nowMoving = Math.hypot(dx, dy) > 2;
      if (nowMoving !== moving) { moving = nowMoving; el.classList.toggle("walking", moving && !reduce); }
      el.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
      // bubble goes on the side of the figure facing away from the pointer, if it fits
      const awayRight = pos.x >= mouse.x;
      const fitsRight = pos.x + SIZE + 270 < innerWidth, fitsLeft = pos.x - 270 > 0;
      el.classList.toggle("bubble-left", awayRight ? !fitsRight : fitsLeft);
      el.classList.toggle("bubble-up", pos.y + 130 > innerHeight);

      // pupils look at the pointer
      const r = svg.getBoundingClientRect(), s = r.width / 120;
      for (const p of pupils) {
        const cx = +p.dataset.cx, cy = +p.dataset.cy;
        const ex = mouse.x - (r.left + cx * s), ey = mouse.y - (r.top + cy * s);
        const d = Math.hypot(ex, ey) || 1, m = Math.min(3.5, d / 30);
        p.setAttribute("cx", cx + (ex / d) * m);
        p.setAttribute("cy", cy + (ey / d) * m);
      }
    }
    requestAnimationFrame(frame);
  }

  document.getElementById("mascot-toggle")?.addEventListener("click", () => {
    localStorage.setItem("skilllens-mascot", enabled() ? "off" : "on");
    apply();
    if (enabled()) say(pick(HOME_TIP));
  });
  document.addEventListener("langchange", () => { apply(); tipKey = null; });

  apply();
  requestAnimationFrame(frame);
  if (enabled()) setTimeout(() => say(pick(HOME_TIP)), 900);
})();
