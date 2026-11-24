"""English/Turkish messages for everything the backend shows to users.

Core code raises LocalizedError(key, **values); str(error) is English (logs, tests), and the API
returns error.localized(lang) in the language the page asked for (X-Lang header). Developer-only
errors (bad checkpoints, malformed data files) stay plain English.
"""
from __future__ import annotations

LANGS = ("en", "tr")

MESSAGES: dict[str, dict[str, str]] = {
    "admin.unauthorized": {"en": "Admin token missing or wrong.", "tr": "Yönetici anahtarı eksik ya da yanlış."},
    "auth.required": {"en": "Please sign in.", "tr": "Lütfen giriş yapın."},
    "auth.bad_login": {"en": "E-mail or password is wrong.", "tr": "E-posta ya da şifre yanlış."},
    "auth.email_taken": {"en": "An account with this e-mail already exists.", "tr": "Bu e-postayla bir hesap zaten var."},
    "job.not_owner": {"en": "Only the user who created this job can change it.", "tr": "Bu ilanı yalnızca oluşturan kullanıcı değiştirebilir."},
    "profile.unknown_skills": {"en": "Unknown skills: {skills}.", "tr": "Bilinmeyen beceriler: {skills}."},
    "quiz.bad_result": {"en": "Correct answers cannot exceed the number of questions.", "tr": "Doğru sayısı soru sayısını aşamaz."},
    "saved.exists": {"en": "This job is already saved.", "tr": "Bu ilan zaten kayıtlı."},
    "not_found": {"en": "Not found.", "tr": "Bulunamadı."},
    "model.light": {"en": "Light mode: the model is not loaded, so only saved results are available. Start the server in full mode to read new text.",
                    "tr": "Hafif mod: model yüklü değil, yalnızca kayıtlı sonuçlar kullanılabilir. Yeni metin okutmak için sunucuyu tam modda başlatın."},
    # CV
    "cv.empty_file": {"en": "The file is empty.", "tr": "Dosya boş."},
    "cv.too_large": {"en": "The file is larger than {mb} MB.", "tr": "Dosya {mb} MB'tan büyük."},
    "cv.not_pdf": {"en": "This is not a PDF file.", "tr": "Bu bir PDF dosyası değil."},
    "cv.damaged": {"en": "The PDF could not be read; it may be damaged.",
                   "tr": "PDF okunamadı; dosya bozuk olabilir."},
    "cv.no_text": {"en": "No text found in the PDF. It may be a scanned image; paste the CV text instead.",
                   "tr": "PDF'te metin bulunamadı. Taranmış bir görüntü olabilir; CV metnini yapıştırın."},
    "cv.empty_text": {"en": "The CV text is empty.", "tr": "CV metni boş."},
    # jobs
    "job.field_required": {"en": "Job field '{field}' is required.", "tr": "İlan alanı '{field}' zorunlu."},
    "job.too_short": {"en": "The job description is empty or too short.", "tr": "İlan metni boş ya da çok kısa."},
    "job.network": {"en": "Network error while contacting the job source: {error}",
                    "tr": "İlan kaynağına bağlanırken ağ hatası: {error}"},
    "job.board_not_found": {"en": "Job board not found. Check the board / company name.",
                            "tr": "İlan panosu bulunamadı. Pano / şirket adını kontrol edin."},
    "job.http_status": {"en": "Job source answered with HTTP {status}.", "tr": "İlan kaynağı HTTP {status} döndürdü."},
    "job.bad_board": {"en": "Board name may only contain letters, digits, '-' and '_'.",
                      "tr": "Pano adı yalnızca harf, rakam, '-' ve '_' içerebilir."},
    "job.bad_company": {"en": "Company name may only contain letters, digits, '-' and '_'.",
                        "tr": "Şirket adı yalnızca harf, rakam, '-' ve '_' içerebilir."},
    "job.board_empty": {"en": "The board returned no open jobs.", "tr": "Pano açık ilan döndürmedi."},
    "job.company_empty": {"en": "The company returned no open jobs.", "tr": "Şirket açık ilan döndürmedi."},
    "job.board_required": {"en": "A board / company name is required for this source.",
                           "tr": "Bu kaynak için pano / şirket adı gerekli."},
    "job.not_found": {"en": "Job not found.", "tr": "İlan bulunamadı."},
    "job.not_found_id": {"en": "Job {id} not found.", "tr": "{id} numaralı ilan bulunamadı."},
    # quiz
    "quiz.unknown_topics": {"en": "No questions for topic(s): {topics}.", "tr": "Şu konular için soru yok: {topics}."},
    "quiz.no_topics": {"en": "Choose at least one quiz topic.", "tr": "En az bir quiz konusu seçin."},
    "quiz.no_questions": {"en": "The quiz needs at least one question.", "tr": "Quiz en az bir soru içermeli."},
    "quiz.unknown_level": {"en": "Unknown level {level}; use junior, mid or senior.",
                           "tr": "Bilinmeyen seviye: {level}; junior, mid ya da senior kullanın."},
    "quiz.session_missing": {"en": "Quiz session not found or expired. Start a new quiz.",
                             "tr": "Quiz oturumu bulunamadı ya da süresi doldu. Yeni bir quiz başlatın."},
    "quiz.already_submitted": {"en": "This quiz was already submitted.", "tr": "Bu quiz zaten gönderildi."},
    "quiz.job_no_topics": {"en": "This job has no skills covered by the quiz bank. Choose topics manually.",
                           "tr": "Bu ilandaki beceriler soru bankasında yok. Konuları elle seçin."},
    # model / results
    "model.not_loaded": {"en": "Skill extraction model is not loaded: {reason}",
                         "tr": "Beceri çıkarma modeli yüklenmedi: {reason}"},
    "results.missing": {"en": "No evaluation results yet. Run scripts/evaluate.py first.",
                        "tr": "Henüz değerlendirme sonucu yok. Önce scripts/evaluate.py çalıştırın."},
    # matching notes
    "match.no_quiz": {"en": "No quiz result covers this job's topics; combined score = CV coverage only.",
                      "tr": "Bu ilanın konularını kapsayan quiz sonucu yok; birleşik skor = yalnızca CV kapsaması."},
    "match.few_skills": {"en": "Only {n} recognised skill(s) in this job; the score rests on very little evidence.",
                         "tr": "Bu ilanda yalnızca {n} tanınan beceri var; skor çok az kanıta dayanıyor."},
    "match.not_evaluated": {"en": "Not evaluated by quiz: {skills}.", "tr": "Quiz ile ölçülmedi: {skills}."},
    "match.not_calculated": {"en": "No skills were extracted from this job, so the score could not be calculated.",
                             "tr": "Bu ilandan beceri çıkarılamadı, bu yüzden skor hesaplanamadı."},
    # roadmap
    "road.no_gaps": {"en": "No gaps found for this job: every required skill has CV or quiz evidence.",
                     "tr": "Bu ilan için eksik yok: istenen her becerinin CV ya da quiz kanıtı var."},
    "road.weak": {"en": "The job asks for {skill}; your {topic} quiz score{level} is {pct} ({correct}/{total}).",
                  "tr": "İlan {skill} istiyor; {topic} quiz puanınız{level} %{pct_num} ({correct}/{total})."},
    "road.level": {"en": " ({level} level)", "tr": " ({level} seviye)"},
    "road.missing": {"en": "The job asks for {skill}; it was not found in your CV or quiz results.",
                     "tr": "İlan {skill} istiyor; CV'nizde ya da quiz sonuçlarınızda bulunamadı."},
    "road.prereq": {"en": "Prerequisite for {title}.", "tr": "{title} için ön koşul."},
    "road.generic_title": {"en": "Learn {skill}", "tr": "{skill} öğren"},
    "road.generic_goal": {"en": "Complete an introductory {skill} tutorial and build one small project.",
                          "tr": "Giriş seviyesinde bir {skill} eğitimini bitirin ve küçük bir proje yapın."},
    # quiz topic names
    "topic.python": {"en": "Python", "tr": "Python"},
    "topic.csharp": {"en": "C#", "tr": "C#"},
    "topic.sql": {"en": "SQL", "tr": "SQL"},
    "topic.oop": {"en": "OOP", "tr": "Nesne Yönelimli Programlama"},
    "topic.algorithms": {"en": "Algorithms & Data Structures", "tr": "Algoritmalar ve Veri Yapıları"},
}


def norm_lang(lang: str | None) -> str:
    """'tr', 'tr-TR', 'TR' -> 'tr'; anything unknown -> 'en'."""
    code = (lang or "en").split(",")[0].split("-")[0].strip().lower()
    return code if code in LANGS else "en"


def msg(key: str, lang: str = "en", **values) -> str:
    entry = MESSAGES[key]
    return entry.get(norm_lang(lang), entry["en"]).format(**values)


class LocalizedError(ValueError):
    """A user-facing error whose text can be produced in any supported language."""

    def __init__(self, key: str, **values):
        self.key, self.values = key, values
        super().__init__(msg(key, "en", **values))

    def localized(self, lang: str) -> str:
        return msg(self.key, lang, **self.values)
