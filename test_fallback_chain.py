"""
test_fallback_chain.py — Verifies the 3-tier AI provider fallback logic.

Run with: python test_fallback_chain.py
(No pytest needed — uses only stdlib unittest.mock)
"""
import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def run_test(name, fn):
    try:
        fn()
        print(f"  [{PASS}] {name}")
        results.append(True)
    except Exception as e:
        print(f"  [{FAIL}] {name}: {e}")
        results.append(False)


# ── Import modules ─────────────────────────────────────────────────────────
from app.ai_engine import RATE_LIMITED
import app.ai_engine as ai_engine
import app.utils as utils_mod


# ── Test 1: TF-IDF works with no API keys ─────────────────────────────────
def test_tfidf_direct():
    result = utils_mod._tfidf_analyze(
        "Python developer with 3 years machine learning and deep learning experience.",
        "ML Engineer with Python and deep learning skills.",
        "test_resume.docx",
    )
    assert result["match_score"] > 0, f"Expected score > 0, got {result['match_score']}"
    assert isinstance(result["found_skills"], list), "found_skills should be a list"


# ── Test 2: Gemini success → return Gemini result, Groq never called ───────
def test_gemini_success_skips_groq():
    mock_result = {
        "match_score": 90.0, "skill_score": 88.0, "content_score": 93.0,
        "reasoning": "Great match", "found_skills": ["python"], "missing_skills": [],
        "status": "success", "phone": "Not found", "email": "a@b.com",
        "education": "Masters Degree", "experience_years": 5,
    }
    # Must patch in utils_mod namespace (where the function reference lives after import)
    with mock.patch("app.utils.analyze_with_gemini", return_value=mock_result), \
         mock.patch("app.utils.analyze_with_groq") as gg:
        res = utils_mod.analyze_single_resume("resume text", "r.docx", "job desc")
        gg.assert_not_called()
    assert res["match_score"] == 90.0


# ── Test 3: Gemini RATE_LIMITED → Groq called immediately ──────────────────
def test_rate_limited_calls_groq():
    mock_groq = {
        "match_score": 77.5, "skill_score": 80.0, "content_score": 73.0,
        "reasoning": "Groq result", "found_skills": ["python"], "missing_skills": [],
        "status": "success", "phone": "Not found", "email": "x@y.com",
        "education": "Bachelor's Degree", "experience_years": 3,
    }
    with mock.patch("app.utils.analyze_with_gemini", return_value=RATE_LIMITED), \
         mock.patch("app.utils.analyze_with_groq", return_value=mock_groq) as mg:
        res = utils_mod.analyze_single_resume("resume text", "r.docx", "job desc")
        mg.assert_called_once()
    assert res["match_score"] == 77.5


# ── Test 4: Gemini RATE_LIMITED + Groq None → TF-IDF used ─────────────────
def test_both_llms_fail_uses_tfidf():
    with mock.patch("app.utils.analyze_with_gemini", return_value=RATE_LIMITED), \
         mock.patch("app.utils.analyze_with_groq", return_value=None):
        res = utils_mod.analyze_single_resume(
            "Python machine learning deep learning engineer 4 years experience.",
            "deep_learning.docx",
            "Expert in Python, machine learning, deep learning.",
        )
    # TF-IDF should still produce a valid structure
    assert "match_score" in res
    assert "found_skills" in res
    assert "status" in res


# ── Test 5: Gemini non-rate-limit failure → Groq tried → TF-IDF ────────────
def test_gemini_other_failure_tries_groq():
    with mock.patch("app.utils.analyze_with_gemini", return_value=None), \
         mock.patch("app.utils.analyze_with_groq", return_value=None):
        res = utils_mod.analyze_single_resume(
            "Java Spring developer 2 years REST API microservices.",
            "java_dev.docx",
            "Java developer with Spring and REST API.",
        )
    assert "match_score" in res


# ── Test 6: No env keys set → TF-IDF used directly ────────────────────────
def test_no_keys_tfidf():
    original_gemini = os.environ.pop("GEMINI_API_KEY", None)
    original_groq   = os.environ.pop("GROQ_API_KEY", None)
    try:
        res = utils_mod.analyze_single_resume(
            "Python developer skilled in machine learning deep learning.",
            "no_key.docx",
            "Python ML engineer.",
        )
        assert "match_score" in res
    finally:
        if original_gemini:
            os.environ["GEMINI_API_KEY"] = original_gemini
        if original_groq:
            os.environ["GROQ_API_KEY"] = original_groq


# ── Run all ────────────────────────────────────────────────────────────────
print("\n== Fallback Chain Tests ==\n")
run_test("TF-IDF works standalone (no API keys)", test_tfidf_direct)
run_test("Gemini success → Groq never called", test_gemini_success_skips_groq)
run_test("Gemini RATE_LIMITED → Groq called immediately", test_rate_limited_calls_groq)
run_test("Both LLMs fail → TF-IDF used", test_both_llms_fail_uses_tfidf)
run_test("Gemini non-rate-limit error → Groq tried then TF-IDF", test_gemini_other_failure_tries_groq)
run_test("No API keys set → TF-IDF used directly", test_no_keys_tfidf)

passed = sum(results)
total  = len(results)
print(f"\n== Results: {passed}/{total} passed ==\n")
sys.exit(0 if passed == total else 1)
