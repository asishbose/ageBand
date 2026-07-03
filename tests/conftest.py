"""Root conftest — shared pytest fixtures and test configuration."""
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: fast, deterministic unit tests")
    config.addinivalue_line("markers", "integration: planner-driven integration tests (LLM mocked)")
    config.addinivalue_line("markers", "e2e: full end-to-end scenario tests")
    config.addinivalue_line("markers", "demo: demo replay marker")
