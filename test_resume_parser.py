"""
test_resume_parser.py — Regression tests for Unicode resume parsing.

Tests the exact Alex Carter ML Engineer resume that previously scored 9.5%
despite ~93% actual fit due to Unicode bullets & box-drawing dividers.

Run:
    python test_resume_parser.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "✅"
FAIL = "❌"
results = []


def run_test(name, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append(True)
    except AssertionError as e:
        print(f"  {FAIL} {name}: {e}")
        results.append(False)
    except Exception as e:
        print(f"  {FAIL} {name}: UNEXPECTED ERROR — {e}")
        results.append(False)


# ── Alex Carter resume (the exact failing case) ─────────────────────────────
ALEX_CARTER_RESUME = """\
alex.carter@gmail.com | +1-415-555-0192 | Mountain View, CA
────────────────────────────────────────────────────────────
Results-driven ML Engineer with 7+ years of experience building and deploying
production ML systems at scale. Expert in designing end-to-end pipelines from
data ingestion through model serving.

SKILLS
────────────────────────────────────────────────────────────
• Languages: Python, C++, Go, Java
• ML Frameworks: TensorFlow, PyTorch, JAX, Keras
• MLOps: MLflow, Kubeflow, SageMaker, Vertex AI
• Infrastructure: Docker, Kubernetes, AWS, GCP
• Data: Spark, Kafka, Airflow, dbt
• Databases: PostgreSQL, MongoDB, Redis

EXPERIENCE
────────────────────────────────────────────────────────────
Senior ML Engineer — TechCorp (2021–present)
• Led a team of 6 engineers building a real-time recommendation engine
  serving 50M+ users with <10ms P99 latency.
• Designed distributed training pipeline (PyTorch + Kubernetes) cutting
  training time by 70%.
• Implemented CI/CD for ML models using GitHub Actions and MLflow.

ML Engineer — DataStartup (2018–2021)
• Built NLP text classification system (BERT fine-tuning) achieving 94% F1.
• Deployed computer vision model (TensorFlow + CUDA) to edge devices.

EDUCATION
────────────────────────────────────────────────────────────
M.S. Computer Science, Stanford University, 2018
B.S. Electrical Engineering, UC Berkeley, 2016
"""

SENIOR_ML_JD = """\
We are looking for a Senior ML Engineer with:
- 5+ years of experience in machine learning and deep learning
- Strong Python and C++ skills
- Experience with TensorFlow, PyTorch, or JAX
- MLOps expertise: MLflow, Kubeflow, or SageMaker
- Knowledge of distributed systems and Kubernetes
- Experience with data pipelines: Airflow, Spark, or Kafka
- AWS or GCP cloud experience
- Familiarity with NLP and computer vision
"""


# ── Test 1: Unicode normalization doesn't mangle skill tokens ───────────────
def test_unicode_normalization():
    from resume_screener_api import TextProcessor

    raw = "• Python, C++, Go\n────────────\n• TensorFlow — PyTorch"
    cleaned = TextProcessor.clean(raw)

    assert "python" in cleaned, f"'python' missing after clean(): {cleaned!r}"
    assert "c++" in cleaned, f"'c++' missing after clean(): {cleaned!r}"
    assert "go" in cleaned, f"'go' missing after clean(): {cleaned!r}"
    assert "tensorflow" in cleaned, f"'tensorflow' missing after clean(): {cleaned!r}"
    assert "pytorch" in cleaned, f"'pytorch' missing after clean(): {cleaned!r}"
    # Box-drawing chars should be gone (replaced by space/pipe, not letters)
    assert "\u2500" not in cleaned, "Box-drawing characters survived clean()"
    # Unicode bullets should be gone
    assert "\u2022" not in cleaned, "Unicode bullet survived clean()"


# ── Test 2: Skills extracted from Alex Carter's Unicode-heavy Skills section ─
def test_skill_extraction_with_bullets_and_dividers():
    from resume_screener_api import TextProcessor

    found = TextProcessor.extract_explicit_skills(ALEX_CARTER_RESUME)
    skill_names = {s.lower() for s in found}

    expected = ["python", "c++", "go", "java", "tensorflow", "pytorch",
                "jax", "keras", "mlflow", "docker", "kubernetes", "aws",
                "gcp", "spark", "kafka", "airflow", "postgresql", "mongodb",
                "redis"]
    missing = [s for s in expected if s not in skill_names]
    assert not missing, (
        f"Skills NOT extracted: {missing}\n"
        f"  (found: {sorted(skill_names)})"
    )


# ── Test 3: Evidence snippets include Skills/Experience sections ─────────────
def test_evidence_snippets_include_skills_section():
    from resume_screener_api import MatchingEngine

    engine = MatchingEngine(jd_text=SENIOR_ML_JD, resume_text=ALEX_CARTER_RESUME)
    snippets = engine._extract_resume_snippets()
    combined = "\n".join(snippets).lower()

    # At least one snippet should be from Skills or Experience — not just header
    skill_keywords_in_evidence = any(
        kw in combined for kw in ["python", "tensorflow", "pytorch", "mlflow",
                                  "kubernetes", "recommendation", "nlp", "bert"]
    )
    assert skill_keywords_in_evidence, (
        f"Evidence snippets don't contain any skills/experience content!\n"
        f"  snippets: {snippets}"
    )
    # Should have more than 1 snippet
    assert len(snippets) >= 2, f"Expected >=2 evidence snippets, got {len(snippets)}"


# ── Test 4: TF-IDF score for Alex Carter is reasonable (>30%) ────────────────
def test_tfidf_score_reasonable_for_strong_candidate():
    from resume_screener_api import MatchingEngine

    engine = MatchingEngine(jd_text=SENIOR_ML_JD, resume_text=ALEX_CARTER_RESUME)
    result = engine.analyze(filename="alex_carter.pdf")

    assert result.match_score > 30, (
        f"Alex Carter should score >30% but got {result.match_score}%\n"
        f"  skill_score={result.skill_score}% content_score={result.content_score}%\n"
        f"  found_skills={result.found_skills}\n"
        f"  missing_skills={result.missing_skills}"
    )
    assert result.skill_score > 20, (
        f"Skill score should be >20% but got {result.skill_score}%\n"
        f"  found_skills={result.found_skills}"
    )
    # Should find at least 5 skills
    assert len(result.found_skills) >= 5, (
        f"Expected >=5 found_skills, got {len(result.found_skills)}: {result.found_skills}"
    )
    print(f"\n      match={result.match_score}%  skill={result.skill_score}%  "
          f"content={result.content_score}%")
    print(f"      found_skills ({len(result.found_skills)}): {result.found_skills}")


# ── Test 5: _preprocess_for_llm normalizes Unicode ──────────────────────────
def test_preprocess_for_llm():
    from app.ai_engine import _preprocess_for_llm

    raw = "SKILLS\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\u2022 Python, C++\n\u2022 TensorFlow"
    processed = _preprocess_for_llm(raw)

    assert "\u2500" not in processed, "Box-drawing chars survived _preprocess_for_llm()"
    assert "\u2022" not in processed, "Unicode bullets survived _preprocess_for_llm()"
    assert "Python" in processed, "Case-sensitive skill name 'Python' was lost"
    assert "TensorFlow" in processed, "'TensorFlow' was lost"
    # Should still have content — not be blank
    assert len(processed.strip()) > 10, "Preprocessed text is empty!"


# ── Test 6: SKILL_DB expanded with ML tools ──────────────────────────────────
def test_skill_db_has_ml_tools():
    from resume_screener_api import SKILL_DB

    all_skills = set()
    for category in SKILL_DB.values():
        all_skills.update(category)

    required_new = ["jax", "mlflow", "kubeflow", "cuda", "onnx",
                    "xgboost", "lightgbm", "langchain", "scikit-learn",
                    "wandb", "databricks"]
    missing = [s for s in required_new if s not in all_skills]
    assert not missing, f"New ML skills missing from SKILL_DB: {missing}"


# ── Run all ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n== Resume Parser Tests (Unicode / Alex Carter Case) ==\n")
    run_test("Unicode normalization preserves skill tokens", test_unicode_normalization)
    run_test("Skill extraction through bullets + dividers", test_skill_extraction_with_bullets_and_dividers)
    run_test("Evidence snippets include Skills/Experience sections", test_evidence_snippets_include_skills_section)
    run_test("TF-IDF score >30% for well-matched ML candidate", test_tfidf_score_reasonable_for_strong_candidate)
    run_test("_preprocess_for_llm() normalizes Unicode for LLM", test_preprocess_for_llm)
    run_test("SKILL_DB expanded with modern ML tools", test_skill_db_has_ml_tools)

    passed = sum(results)
    total = len(results)
    print(f"\n== Results: {passed}/{total} passed ==\n")
    sys.exit(0 if passed == total else 1)
