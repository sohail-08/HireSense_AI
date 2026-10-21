from copy import deepcopy

from app.services.scoring_presentation import evidence_preview, present_breakdown, requirement_reason


def requirement(**overrides):
    return {"requirement_id": "experience:0", "name": "At least 3 years of relevant experience",
        "evaluation_criterion": "Relevant employment", "category": "experience", "status": "met", "evidence": [], **overrides}


def citation(text, key="pdf-page-1"):
    return {"block_id": key, "locator": "PDF page 1", "quote": text}


def assert_source_owned(preview, originals):
    for excerpt in preview:
        original = originals[excerpt["source_index"]]
        assert excerpt["quote"] == original["quote"][excerpt["quote_start"]:excerpt["quote_end"]]
        assert excerpt["locator"] == original["locator"]
        assert len(excerpt["quote"]) <= 320


def test_monolithic_overlapping_pdf_becomes_short_distinct_role_evidence():
    text = ("SYNTHETIC CANDIDATE | private@example.test\nPROFESSIONAL SUMMARY\n"
        "Machine learning engineer interested in building useful products.\nTECHNICAL SKILLS\nPython, Docker, SQL, MLflow, React.\n"
        "PROFESSIONAL EXPERIENCE\nSenior ML Engineer | Example Labs | Jan 2023 - Present\n"
        "• Built and deployed Python inference services with monitoring.\n"
        "ML Engineer | Example Systems | Jan 2021 - Dec 2022\n"
        "• Developed forecasting models and evaluated their quality.\n"
        "EDUCATION\nBachelor degree in Computer Science, 2020.")
    originals = [citation(text), citation(text[text.index("PROFESSIONAL EXPERIENCE"):], "pdf-page-1~overlap")]
    result = evidence_preview(requirement(evidence=originals))
    assert 1 <= len(result) <= 4
    assert_source_owned(result, originals)
    assert any("Jan 2023 - Present" in c["quote"] for c in result)
    assert any("Jan 2021 - Dec 2022" in c["quote"] for c in result)
    assert not any("private@example.test" in c["quote"] for c in result)
    assert not any("Bachelor degree" in c["quote"] for c in result)
    quotes = [c["quote"] for c in result]
    assert len(quotes) == len(set(quotes))
    assert sum(map(len, quotes)) < len(text) * 2


def test_short_docx_quotes_remain_exact_and_supported_skills_are_not_lost():
    originals = [citation("Built Python APIs.", "docx-paragraph-2"), citation("Python", "docx-paragraph-3")]
    result = evidence_preview(requirement(name="Python", category="technical", evidence=originals))
    assert_source_owned(result, originals)
    assert [c["quote"] for c in result] == ["Built Python APIs."]  # contained duplicate removed


def test_previews_do_not_cut_off_a_later_negation_or_separate_a_contrast():
    text = "Built React prototypes. However, I have not deployed them in production."
    originals = [citation(text)]
    result = evidence_preview(requirement(name="Production React", category="technical", evidence=originals))
    assert result[0]["quote"] == text
    long = "Built React " + "local prototypes " * 40 + "but not production services."
    assert evidence_preview(requirement(name="React", category="technical", evidence=[citation(long)])) == []


def test_long_sentence_preview_focuses_on_relevant_text_not_its_unrelated_prefix():
    text = "Background " * 50 + "Built Python inference APIs for forecasting services " + "with monitoring " * 30
    originals = [citation(text)]
    result = evidence_preview(requirement(name="Python", category="technical", evidence=originals))
    assert_source_owned(result, originals)
    assert "Python inference APIs" in result[0]["quote"]
    assert result[0]["omitted_before"] and result[0]["omitted_after"]


def test_experience_reason_uses_recorded_months_and_never_invents_years():
    met = requirement_reason(requirement(), {"months": 45})
    assert "3 years 9 months" in met and "3-year minimum" in met and "Overlapping jobs count once" in met
    partial = requirement_reason(requirement(status="partially_met"), {"months": 18})
    assert "1 year 6 months" in partial and "minimum is 3 years" in partial
    legacy = requirement_reason(requirement())
    assert "Relevant roles" in legacy and "3 years" not in legacy
    unmet = requirement_reason(requirement(status="unmet"), {"months": 60})
    assert "not provide enough evidence" in unmet and "5 years" not in unmet


def test_read_time_presentation_does_not_change_stored_scores_or_evidence():
    original = {"final_score": "85.25", "exact_final_score": {"numerator": "341", "denominator": "4"},
        "requirements": [requirement(evidence=[citation("Engineer | Example Labs | 2021 - 2024")])]}
    before = deepcopy(original)
    result = present_breakdown(original, {"experience:0": {"months": 36}})
    assert original == before
    assert result["final_score"] == original["final_score"]
    assert result["requirements"][0]["evidence"] == original["requirements"][0]["evidence"]
    assert result["requirements"][0]["reason"] and result["requirements"][0]["evidence_preview"]
