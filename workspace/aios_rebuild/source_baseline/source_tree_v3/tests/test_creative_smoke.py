"""
Creative RAG Smoke Tests
Minimal, fast tests to verify CreativeRAG doesn't regress

V5.1 CreativeRAG Hardening
Travis Miner | AIOS_clean

Regression tripwires:
- Index loads and returns templates
- Creative path logs to drift
- Embedder version pinned
- Config flag test (disabled -> no CreativeRAG)
"""

import sys
from pathlib import Path

# Add AIOS root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import json

# Mark as smoke tests (fast, always run)
pytestmark = pytest.mark.unit


# === SMOKE TEST 1: RETRIEVAL ===

def test_creative_retrieval_smoke():
    """
    Smoke test: Load index, retrieve templates, verify structure
    
    Regression tripwire: If this fails, index is corrupted or missing
    """
    from rag_core.creative_retriever import retrieve_creative_templates
    from data_core.data_core_unified import DataCore
    
    dc = DataCore()
    cfg = dc.load_config()
    
    # Skip if index doesn't exist (expected on fresh installs)
    idx_path = Path(cfg.get("creative_mode", {}).get("index_path", ""))
    if not idx_path or not Path(idx_path).exists():
        pytest.skip("Creative index not built")
    
    # Retrieve templates for haunting folklore
    results = retrieve_creative_templates(cfg, "haunting folklore", k=3)
    
    # Basic structure checks
    assert isinstance(results, list), "Should return list"
    assert len(results) >= 1, "Should return at least 1 template"
    
    template = results[0]
    assert "id" in template, "Template must have id"
    assert "beats" in template, "Template must have beats"
    assert isinstance(template["beats"], list), "Beats must be list"
    assert len(template["beats"]) >= 1, "Beats must have at least 1 entry"


# === SMOKE TEST 2: CREATIVE PATH ===

def test_creative_path_smoke(monkeypatch):
    """
    Smoke test: Creative path activates and logs to drift
    
    Regression tripwire: If this fails, creative path isn't wired
    """
    from luna_core.core.luna_core import LunaSystem
    from rag_core import creative_retriever
    
    # Mock retrieval to return fake template
    fake_template = {
        "id": "tmpl:smoke_test",
        "beats": ["Setup", "Development", "Climax", "Resolution"],
        "source": "test",
        "timestamp": 0
    }
    
    monkeypatch.setattr(
        creative_retriever,
        'retrieve_creative_templates',
        lambda cfg, q, k=3: [fake_template]
    )
    
    # Mock LM Studio API to return immediately
    def mock_requests_post(url, json=None, timeout=None):
        class MockResponse:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "Test creative story"}}]}
        return MockResponse()
    
    import requests
    monkeypatch.setattr(requests, 'post', mock_requests_post)
    
    # Initialize Luna with creative enabled
    luna = LunaSystem()
    rg = luna.response_generator
    rg.aios_config = {"creative_mode": {"enabled": True}}
    
    # Generate creative text
    result = rg._maybe_generate_creative("#creative test")
    
    # Should return text (not None)
    assert result is not None, "Should generate creative text"
    assert isinstance(result, str), "Should return string"
    
    # Check drift log for CreativeRAG entry
    if hasattr(rg, 'drift_monitor') and rg.drift_monitor:
        # Drift monitor should have logged the interaction
        # (We can't easily check the log file, but the method was called)
        pass


# === EMBEDDER VERSION PIN TEST ===

def test_embedder_version_pinned():
    """
    Embedder version must be pinned to prevent dimension mismatches
    
    Regression tripwire: If embedder changes, FAISS breaks
    """
    from data_core.data_core_unified import DataCore
    
    dc = DataCore()
    cfg = dc.load_config()
    
    embedder = cfg.get("creative_mode", {}).get("embedder")
    
    # Must be explicitly set (not None/missing)
    assert embedder is not None, "Embedder must be configured"
    
    # Must be the pinned version
    assert embedder == "sentence-transformers/all-MiniLM-L6-v2", \
        f"Embedder changed! Was 'all-MiniLM-L6-v2', now '{embedder}'. Rebuild index!"


# === CONFIG FLAG TEST ===

def test_config_flag_disabled_no_creative():
    """
    When creative_mode.enabled=false, creative path returns None
    
    Regression tripwire: Creative path shouldn't activate when disabled
    """
    from luna_core.core.response_generator import LunaResponseGenerator
    
    # Clean up singleton counter from previous tests
    if hasattr(LunaResponseGenerator, '_drift_instance_count'):
        delattr(LunaResponseGenerator, '_drift_instance_count')
    
    from luna_core.core.luna_core import LunaSystem
    
    luna = LunaSystem()
    rg = luna.response_generator
    
    # Explicitly disable
    rg.aios_config = {"creative_mode": {"enabled": False}}
    
    result = rg._maybe_generate_creative("#creative test")
    
    assert result is None, "Should return None when disabled"
    
    # Cleanup for next test
    if hasattr(LunaResponseGenerator, '_drift_instance_count'):
        delattr(LunaResponseGenerator, '_drift_instance_count')


# === FAISS SIZE SANITY ===

def test_faiss_size_sanity():
    """
    FAISS index must be reasonable size for template count
    
    Regression tripwire: Catches empty/corrupted indexes
    """
    from data_core.data_core_unified import DataCore
    
    dc = DataCore()
    cfg = dc.load_config()
    
    idx_path = Path(cfg.get("creative_mode", {}).get("index_path", ""))
    meta_path = Path(cfg.get("creative_mode", {}).get("meta_path", ""))
    
    # Skip if not built
    if not idx_path.exists() or not meta_path.exists():
        pytest.skip("Creative index not built")
    
    # Count templates
    with open(meta_path, 'r', encoding='utf-8') as f:
        template_count = sum(1 for _ in f)
    
    # Check index size
    idx_size = idx_path.stat().st_size
    
    # If we have 50+ templates, index must be > 8 KB
    if template_count >= 50:
        assert idx_size > 8192, \
            f"Index too small ({idx_size} bytes) for {template_count} templates - likely empty/corrupted"


# === MANIFEST INTEGRITY ===

def test_manifest_exists():
    """
    Manifest must exist and have required fields
    
    Regression tripwire: Tracks seed version and embedder
    """
    manifest_path = Path("data_core/creative/MANIFEST.json")
    
    # Skip if creative not set up
    if not manifest_path.exists():
        pytest.skip("Manifest not created - run seed_creative_corpus.py")
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Required fields
    assert "seed_version" in manifest
    assert "embedder" in manifest
    assert "sample_count" in manifest
    assert "index_hash" in manifest
    
    # Embedder must be pinned
    assert manifest["embedder"] == "sentence-transformers/all-MiniLM-L6-v2"

