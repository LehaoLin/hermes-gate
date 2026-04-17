"""tests/test_docs.py"""
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_guide_does_not_reference_missing_env_example():
    """GUIDE.md must not reference .env.example (it doesn't exist)."""
    guide = ROOT / "GUIDE.md"
    content = guide.read_text(encoding="utf-8")
    assert ".env.example" not in content


def test_guide_documents_interactive_server_input():
    """GUIDE.md should document the interactive user@host:port input."""
    guide = ROOT / "GUIDE.md"
    content = guide.read_text(encoding="utf-8")
    assert "Add Server" in content or "user@host" in content


def test_readme_matches_guide_startup():
    """README.md and GUIDE.md should agree on startup method."""
    readme = ROOT / "README.md"
    guide = ROOT / "GUIDE.md"
    readme_content = readme.read_text(encoding="utf-8")
    guide_content = guide.read_text(encoding="utf-8")
    assert "./start.sh" in readme_content
    assert "./start.sh" in guide_content


def test_readme_does_not_require_config_file():
    """README.md should state no config file is needed."""
    readme = ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    lines = content.split("\n")
    for line in lines:
        if ".env" in line.lower() and "example" in line.lower():
            assert "cp" not in line, "README should not instruct copying .env.example"
