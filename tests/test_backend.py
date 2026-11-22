"""Backend logic: dictionary, extractor plumbing, CV, jobs, quiz, matching, roadmap and the brief's demo scenario."""
import pytest

from core.cv import CVError, detect_skills, pdf_to_text
from core.extractor import SkillExtractor, split_sentences, tokenize_words
from core.jobs import JobStore, demo_jobs, html_to_text, manual_job
from core.matching import match_job, rank_jobs
from core.quiz import QuizEngine, QuizError, load_bank
from core.roadmap import build_roadmap, load_topics
from core.skills import default_dictionary

D = default_dictionary()


# ---------------------------------------------------------------- dictionary

def test_js_and_javascript_merge_but_java_stays_separate():
    assert D.normalize("JS, JavaScript and Java") == ["JavaScript", "Java"]


def test_special_tokens_and_longest_alias_win():
    assert D.normalize("C#, C++, .NET Core, Node.js, CI/CD, SQL Server") == \
        ["C#", "C++", ".NET", "Node.js", "CI/CD", "SQL Server"]


def test_common_words_are_not_skills():
    assert D.normalize("the rest of the team works in spring on a go-to node") == []


def test_company_name_gitlab_is_not_git_skill():
    assert D.normalize("Join GitLab, the DevSecOps platform") == []
    assert D.normalize("Experience with Git and GitHub") == ["Git"]


def test_few_skills_warning():
    m = match_job(["Git"], ["Git"], {})
    assert any("very little evidence" in n for n in m["notes"])
    assert not any("very little evidence" in n for n in match_job(["Python", "SQL", "Git"], [], {})["notes"])


def test_canonical_lookup():
    assert D.canonical("python") == "Python" and D.canonical("js") == "JavaScript" and D.canonical("xyz") is None


# ---------------------------------------------------------------- extractor plumbing

def test_tokenize_keeps_offsets_and_technical_tokens():
    s = "We use C#, Node.js and CI/CD."
    words = tokenize_words(s)
    assert [w for w, _, _ in words] == ["We", "use", "C#", ",", "Node.js", "and", "CI/CD", "."]
    assert all(s[a:b] == w for w, a, b in words)


def test_split_sentences_on_bullets_and_periods():
    text = "Intro line. Second sentence.\n- bullet one\n- bullet two"
    parts = [s for s, _ in split_sentences(text)]
    assert parts == ["Intro line.", "Second sentence.", "bullet one", "bullet two"]


def fake_tagger(sentences):
    """Tags 'Python' and 'SQL' as knowledge; 'write tests' as a skill."""
    out = {"skill": [], "knowledge": []}
    for words in sentences:
        k = ["B" if w in ("Python", "SQL") else "O" for w in words]
        s = ["O"] * len(words)
        for i in range(len(words) - 1):
            if words[i] == "write" and words[i + 1] == "tests":
                s[i], s[i + 1] = "B", "I"
        out["knowledge"].append(k)
        out["skill"].append(s)
    return out


def test_extract_offsets_dedup_and_dictionary_fallback():
    text = "You know Python and SQL. You write tests in Python. Git is a plus."
    result = SkillExtractor(fake_tagger, model_name="fake").extract(text)
    for m in result["mentions"]:
        assert text[m["start"]:m["end"]] == m["text"]
    reqs = {(r["type"], r["text"]): r for r in result["requirements"]}
    assert len(reqs[("knowledge", "Python")]["mentions"]) == 2  # repeated span merged
    assert reqs[("knowledge", "Git")]["found_by"] == "dictionary"
    assert "write tests" in result["unmatched"]  # visible, not silently dropped
    assert result["skills"] == ["Python", "SQL", "Git"]


def test_span_edges_drop_punctuation():
    def tag_all(sentences):  # model tags every token, including the final period
        return {"skill": [["B"] + ["I"] * (len(s) - 1) for s in sentences], "knowledge": [["O"] * len(s) for s in sentences]}
    result = SkillExtractor(tag_all, model_name="fake").extract("Design REST APIs.", use_dictionary=False)
    assert [m["text"] for m in result["mentions"]] == ["Design REST APIs"]
    assert SkillExtractor(tag_all).extract("...", use_dictionary=False)["mentions"] == []


def test_extract_empty_text():
    assert SkillExtractor(fake_tagger).extract("   ")["skills"] == []


# ---------------------------------------------------------------- CV

def test_cv_errors_are_clear():
    with pytest.raises(CVError, match="empty"):
        pdf_to_text(b"")
    with pytest.raises(CVError, match="not a PDF"):
        pdf_to_text(b"hello world")
    with pytest.raises(CVError, match="larger"):
        pdf_to_text(b"%PDF" + b"0" * 100, max_bytes=50)
    with pytest.raises(CVError, match="damaged"):
        pdf_to_text(b"%PDF-1.4 broken")


def test_cv_pdf_roundtrip():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Skills: Python, Git, PostgreSQL and React development")
    skills = [s["skill"] for s in detect_skills(pdf_to_text(doc.tobytes()))]
    assert skills == ["Python", "Git", "PostgreSQL", "React"]


def test_scanned_pdf_without_text():
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(CVError, match="scanned"):
        pdf_to_text(doc.tobytes())


# ---------------------------------------------------------------- jobs

def test_job_upsert_updates_instead_of_duplicating():
    store = JobStore(":memory:")
    job = {"source": "greenhouse", "source_id": "acme:1", "title": "Dev", "description": "Python and SQL work."}
    jid, status = store.upsert(job)
    assert status == "created"
    assert store.upsert(job) == (jid, "unchanged")
    store.set_extraction(jid, {"skills": ["Python"]})
    assert store.upsert({**job, "description": "Now Java."}) == (jid, "updated")
    assert len(store.list()) == 1 and store.get(jid)["extraction"] is None


def test_manual_job_rejects_empty_and_demo_flagged():
    with pytest.raises(ValueError):
        manual_job("x", "   ")
    jobs = demo_jobs()
    assert len(jobs) >= 10 and all(j["is_demo"] and "(demo)" in j["company"] for j in jobs)


def test_html_to_text():
    assert html_to_text("&lt;p&gt;Use &lt;b&gt;Python&lt;/b&gt;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;") == \
        "Use Python\n- SQL"


# ---------------------------------------------------------------- quiz

def test_bank_is_valid_and_covers_topics():
    bank = load_bank()
    assert len(bank) >= 60
    assert {q["topic"] for q in bank} == set(D.topics)


def test_quiz_hides_answers_and_scores_per_topic():
    engine = QuizEngine(seed=1)
    started = engine.start(["python", "sql"], total=10)
    assert started["count"] == 10
    assert all("answer" not in q and "explanation" not in q for q in started["questions"])
    key = {q["id"]: q["answer"] for q in engine.sessions[started["session_id"]].questions}
    answers = {qid: (a if qid.startswith("py") else (a + 1) % 4) for qid, a in key.items()}
    result = engine.submit(started["session_id"], answers)
    assert result["topics"]["python"]["ratio"] == 1.0 and result["topics"]["sql"]["ratio"] == 0.0
    with pytest.raises(QuizError, match="already"):
        engine.submit(started["session_id"], answers)


def test_quiz_options_shuffled_and_key_follows():
    bank = load_bank()
    by_id = {q["id"]: q for q in bank}
    engine = QuizEngine(seed=3)
    positions = []
    for _ in range(5):
        started = engine.start(list(D.topics), total=25)
        for q in engine.sessions[started["session_id"]].questions:
            original = by_id[q["id"]]
            assert sorted(q["options"]) == sorted(original["options"])
            assert q["options"][q["answer"]] == original["options"][original["answer"]]
            positions.append(q["answer"])
    # Always picking one letter must not pass: no position holds a majority of answers.
    assert max(positions.count(k) for k in range(4)) / len(positions) < 0.4


def test_bank_has_15_per_topic_and_level():
    import collections

    c = collections.Counter((q["topic"], q["difficulty"]) for q in load_bank())
    assert all(c[(t, d)] >= 15 for t in D.topics for d in ("easy", "medium", "hard"))


def test_quiz_level_picks_matching_difficulty():
    engine = QuizEngine(seed=5)
    for level, difficulty in (("junior", "easy"), ("mid", "medium"), ("senior", "hard")):
        started = engine.start(["python", "sql"], total=20, level=level)
        assert started["level"] == level and started["from_other_levels"] == 0
        assert {q["difficulty"] for q in started["questions"]} == {difficulty}
        assert {q["level"] for q in started["questions"]} == {level}


def test_quiz_level_falls_back_to_nearest_level_and_reports_it():
    bank = [q for q in load_bank() if q["topic"] == "sql"]
    hard = [q for q in bank if q["difficulty"] == "hard"][:2]
    others = [q for q in bank if q["difficulty"] != "hard"]
    engine = QuizEngine(bank=hard + others, seed=1)
    started = engine.start(["sql"], total=6, level="senior")
    diffs = [q["difficulty"] for q in started["questions"]]
    assert diffs.count("hard") == 2 and diffs.count("medium") == 4  # medium is the nearest level to senior
    assert started["from_other_levels"] == 4


def test_quiz_result_carries_level_and_rejects_unknown_level():
    engine = QuizEngine(seed=2)
    started = engine.start(["oop"], total=3, level="senior")
    result = engine.submit(started["session_id"], {})
    assert result["level"] == "senior" and result["topics"]["oop"]["level"] == "senior"
    with pytest.raises(QuizError, match="Unknown level"):
        engine.start(["oop"], level="expert")


def test_roadmap_reason_mentions_quiz_level():
    quiz = {"sql": {"correct": 1, "total": 5, "ratio": 0.2, "level": "senior"}}
    steps = build_roadmap(match_job(["SQL"], [], quiz), quiz_scores=quiz, courses={})["steps"]
    assert "(senior level)" in steps[0]["reason"]


def test_quiz_errors():
    engine = QuizEngine(seed=1)
    with pytest.raises(QuizError):
        engine.start(["cobol"])
    with pytest.raises(QuizError):
        engine.submit("nope", {})


# ---------------------------------------------------------------- matching + roadmap (brief demo)

def test_brief_demo_scenario():
    """CV: Python, Git. Job: Python, SQL, Git. Quiz: Python strong, SQL weak, Git untested."""
    quiz = {"python": {"correct": 9, "total": 10, "ratio": 0.9}, "sql": {"correct": 3, "total": 10, "ratio": 0.3}}
    m = match_job(["Python", "SQL", "Git"], ["Python", "Git"], quiz)
    status = {r["skill"]: r for r in m["skills"]}
    assert status["Python"]["status"] == "cv_and_quiz"
    assert status["SQL"]["status"] == "weak_quiz"
    assert status["Git"]["status"] == "cv_only" and status["Git"]["quiz_state"] == "no_quiz_for_skill"
    assert m["scores"]["cv_coverage"] == pytest.approx(2 / 3)
    assert m["scores"]["quiz_performance"] == pytest.approx(0.6)
    assert m["scores"]["quiz_coverage"] == 1.0
    steps = build_roadmap(m, courses={})["steps"]
    assert [s["id"] for s in steps] == ["sql_fundamentals"]
    assert "30%" in steps[0]["reason"]


def test_no_skills_means_not_calculated():
    m = match_job([], ["Python"], {})
    assert m["scores"]["combined"] is None and "could not be calculated" in m["notes"][0]


def test_missing_quiz_falls_back_to_cv_coverage_and_says_so():
    m = match_job(["Python", "Docker"], ["Python"], {})
    assert m["scores"]["combined"] == 0.5 and m["scores"]["quiz_performance"] is None
    assert any("CV coverage only" in n for n in m["notes"])
    assert any("Not evaluated" in n and "Python" in n for n in m["notes"])


def test_roadmap_prerequisites_first_and_deduplicated():
    m = match_job(["Kubernetes", "Docker", "Rust"], [], {})
    ids = [s["id"] for s in build_roadmap(m, courses={})["steps"]]
    assert ids == ["linux_basics", "docker", "kubernetes", "generic:Rust"]
    docker = next(s for s in build_roadmap(m, courses={})["steps"] if s["id"] == "docker")
    assert docker["kind"] == "gap"  # direct gap, not just a prerequisite


def test_roadmap_skips_known_prerequisite():
    m = match_job(["Kubernetes"], ["Docker"], {})
    assert [s["id"] for s in build_roadmap(m, cv_skills=["Docker"], courses={})["steps"]] == ["kubernetes"]


def test_roadmap_topics_acyclic_and_skills_exist():
    topics = load_topics()
    for t in topics.values():
        assert all(s in D.skills for s in t["skills"]), t["id"]


def test_rank_jobs_orders_by_combined_and_unscored_last():
    jobs = [{"id": 1, "skills": []}, {"id": 2, "skills": ["Python"]}, {"id": 3, "skills": ["Java"]}]
    assert [j["id"] for j in rank_jobs(jobs, ["Python"], {})] == [2, 3, 1]
