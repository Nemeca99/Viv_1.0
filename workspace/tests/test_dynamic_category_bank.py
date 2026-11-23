"""Unit tests for DynamicCategoryBank."""

import pytest
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.dynamic_category_bank import DynamicCategoryBank, get_category_bank


class TestPrivacy:
    def authorize_file_write(self, path):
        return {"allowed": True, "reason": "test_scope"}


def test_dynamic_category_bank_initialization(tmp_path):
    storage = tmp_path / "test_categories.json"
    bank = DynamicCategoryBank(storage_path=storage, privacy_core=TestPrivacy())
    summary = bank.manifest_summary()

    assert summary["agents"] >= 20
    assert summary["objects"] >= 25
    assert summary["botanical"] >= 25
    assert summary["motion_verbs"] >= 25
    assert summary["sensory_adjectives"] >= 25


def test_dynamic_word_categorization(tmp_path):
    storage = tmp_path / "test_categories.json"
    bank = DynamicCategoryBank(storage_path=storage, privacy_core=TestPrivacy())

    # 1. Test categorization with concept domain hint
    cats_thaw = bank.categorize_word("thaw", domain_hint="sensory_thermal")
    assert "sensory_adjectives" in cats_thaw
    assert "thaw" in bank.categories["sensory_adjectives"]

    cats_stride = bank.categorize_word("stride", domain_hint="kinematic_motion")
    assert "motion_verbs" in cats_stride
    assert "stride" in bank.categories["motion_verbs"]

    cats_fern = bank.categorize_word("fern", domain_hint="botanical_living")
    assert "botanical" in cats_fern
    assert "fern" in bank.categories["botanical"]

    # 2. Test pool retrieval
    pool = bank.get_pool("botanical", limit=5)
    assert len(pool) == 5
    assert all(isinstance(w, str) for w in pool)

    # 3. Test persistence
    assert storage.exists()
    reloaded_bank = DynamicCategoryBank(storage_path=storage, privacy_core=TestPrivacy())
    assert "fern" in reloaded_bank.categories["botanical"]


def test_four_writers_merge_without_shared_temp_collision(tmp_path):
    storage = tmp_path / "dynamic_categories.json"
    banks = [DynamicCategoryBank(storage_path=storage, privacy_core=TestPrivacy()) for _ in range(4)]
    for index, bank in enumerate(banks):
        bank.categories["objects"].add(f"probe_{index}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda bank: bank.save(), banks))
    merged = DynamicCategoryBank(storage_path=storage, privacy_core=TestPrivacy())
    assert all(f"probe_{index}" in merged.categories["objects"] for index in range(4))
    assert not list(tmp_path.glob("*.tmp"))
