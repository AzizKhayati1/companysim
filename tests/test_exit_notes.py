import numpy as np

from companysim.ml.exit_notes import (
    NotesAnalysis,
    analyze_notes,
    augment_explanation_with_notes,
    generate_note,
    score_sentiment,
)


def test_note_grounded_in_worst_driver_mentions_it():
    rng = np.random.default_rng(1)
    profile = {"workload_perceived": 0.95, "manager_support_score": 0.7, "mood": 0.6}
    note = generate_note(profile, rng)
    assert "workload" in note.lower()


def test_neutral_profile_produces_neutral_note():
    rng = np.random.default_rng(2)
    profile = {"workload_perceived": 0.45, "manager_support_score": 0.55, "mood": 0.5}
    note = generate_note(profile, rng)
    assert "personal opportunity" in note.lower()


def test_bad_notes_score_negative_and_good_notes_do_not():
    rng = np.random.default_rng(3)
    bad_profile = {"workload_perceived": 0.9, "manager_support_score": 0.15}
    bad_notes = [generate_note(bad_profile, rng) for _ in range(10)]
    mean_bad = float(np.mean([score_sentiment(n) for n in bad_notes]))
    assert mean_bad < -0.1

    neutral_profile = {"workload_perceived": 0.45, "manager_support_score": 0.6}
    neutral_note = generate_note(neutral_profile, rng)
    assert score_sentiment(neutral_note) >= 0.0


def test_theme_detection_matches_grounding_driver():
    rng = np.random.default_rng(4)
    profile = {"manager_support_score": 0.1}
    notes = {i: generate_note(profile, rng) for i in range(5)}
    analysis = analyze_notes(notes)
    assert "manager_support" in analysis.theme_counts
    assert analysis.theme_counts["manager_support"] == 5


def test_analyze_notes_empty_input_degrades_gracefully():
    analysis = analyze_notes({})
    assert analysis.n_notes == 0
    assert analysis.mean_sentiment == 0.0
    assert analysis.theme_counts == {}
    assert analysis.top_terms == []
    assert analysis.sample_quotes == []


def test_analyze_notes_single_note_does_not_crash():
    analysis = analyze_notes({1: "The workload was overwhelming and unmanageable."})
    assert analysis.n_notes == 1
    assert len(analysis.top_terms) > 0


def test_augment_explanation_without_notes_is_honest_about_no_exits():
    text = augment_explanation_with_notes("Base explanation.", None)
    assert "Base explanation." in text
    assert "no employees" in text.lower() or "structural risk factors" in text.lower()


def test_augment_explanation_with_notes_includes_theme_and_quote():
    analysis = NotesAnalysis(
        n_notes=3, mean_sentiment=-0.5,
        theme_counts={"workload": 3, "manager_support": 2},
        top_terms=["workload", "unsupported"],
        sample_quotes=["The workload was overwhelming."],
    )
    text = augment_explanation_with_notes("Base explanation.", analysis)
    assert "3 employee(s)" in text
    assert "workload" in text
    assert "The workload was overwhelming." in text
