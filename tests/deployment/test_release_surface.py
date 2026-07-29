from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]


def test_public_release_has_required_governance_and_operator_documents() -> None:
    expected = (
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "docs/architecture.md",
        "docs/operations.md",
        "docs/strategy-plugin.md",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
    )

    assert all((PROJECT_ROOT / relative).is_file() for relative in expected)


def test_readme_quick_start_is_honest_about_alpha_boundaries() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docker compose up -d --build" in readme
    assert "当前边界" in readme
    assert "不构成投资建议" in readme
    assert "实盘交易" in readme
    assert "时点基本面同步" in readme
    assert "本机无 Docker时" not in readme
