from pathlib import Path

ROOT = Path(__file__).parents[2] / "src/coding_harness/web"


def test_webui_assets_expose_operations_and_safe_api_only_surface() -> None:
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    script = (ROOT / "static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static/styles.css").read_text(encoding="utf-8")

    for label in ("Submit task", "Supervisor", "Timeline", "Approvals", "Changed files", "Validation evidence", "Stop reason"):
        assert label in html
    assert "api/runs" in script
    assert "approve" in script and "reject" in script
    assert "API_KEY" not in html and "password" not in html.lower()
    assert "@media" in styles


def test_webui_has_accessible_approval_controls_and_state_regions() -> None:
    html = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    assert 'aria-label="Approve approval"' in html
    assert 'aria-label="Reject approval"' in html
    assert 'aria-live="polite"' in html
    assert 'id="error"' in html
