from autonomy.composition_progression import compose_paragraphs


def test_relation_linked_sentences_form_observation_paragraph_without_writeback():
    records = [
        {
            "sentence": "A bloom is part of a plant.",
            "type": "COMPOSED_FACT",
            "relation_path": [{"source": "bloom", "target": "plant"}],
        },
        {
            "sentence": "A plant is part of a garden.",
            "type": "COMPOSED_FACT",
            "relation_path": [{"source": "plant", "target": "garden"}],
        },
    ]
    report = compose_paragraphs(records, {"a", "bloom", "is", "part", "of", "plant", "garden"})
    assert report["valid_sentence_count"] == 2
    assert report["paragraph_count"] == 1
    assert report["paragraphs"][0]["ontology_writeback"] is False


def test_missing_provenance_is_held_closed():
    report = compose_paragraphs(
        [{"sentence": "A word is present.", "type": "UNKNOWN", "relation_path": []}],
        {"a", "word", "is", "present"},
    )
    assert report["valid_sentence_count"] == 0
    assert report["paragraph_count"] == 0

