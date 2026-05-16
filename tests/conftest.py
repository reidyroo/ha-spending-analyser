"""Pytest configuration for HA Spending Analyser tests."""
import pytest

@pytest.fixture
def mock_config_entry_data():
    return {
        "ollama_host": "localhost",
        "ollama_port": 11434,
        "ollama_model": "phi3:mini",
    }
