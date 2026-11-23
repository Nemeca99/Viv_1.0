"""Steel Brain package boundary with compatibility-preserving lazy exports."""

from __future__ import annotations

from importlib import import_module


_LAZY_EXPORTS = {
    "ENGINE_VERSION": (".config", "ENGINE_VERSION"),
    "append_command_log": (".audit", "append_command_log"),
    "train_dictionary_batch": (".dictionary", "train_dictionary_batch"),
    "persist_resolution": (".hierarchy_persistence", "persist_resolution"),
    "LexiconEntry": (".models", "LexiconEntry"),
    "WordMemory": (".models", "WordMemory"),
    "apply_lexical_observation": (".lexicon_training", "apply_lexical_observation"),
    "teach_lexicon": (".lexicon_training", "teach_lexicon"),
    "verify_lexicon": (".lexicon_verify", "verify_lexicon"),
    "verify_frozen_vocabulary": (".recall", "verify_frozen_vocabulary"),
    "build_sentence_model_rows": (".sentence_model", "build_sentence_model_rows"),
    "teach_sentence_model": (".sentence_model", "teach_sentence_model"),
    "LocalState": (".storage", "LocalState"),
    "LearningControls": (".word_engine", "LearningControls"),
    "WordEngine": (".word_engine", "WordEngine"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value

__all__ = [
    "ENGINE_VERSION",
    "LearningControls",
    "LexiconEntry",
    "LocalState",
    "WordEngine",
    "WordMemory",
    "apply_lexical_observation",
    "build_sentence_model_rows",
    "teach_lexicon",
    "teach_sentence_model",
    "train_dictionary_batch",
    "verify_lexicon",
    "verify_frozen_vocabulary",
    "persist_resolution",
    "append_command_log",
]
