from __future__ import annotations

from app.ui import dashboard_core


def test_configure_page_renders_hidden_frontend_runtime_identity(monkeypatch) -> None:
    rendered_markdown: list[str] = []

    monkeypatch.setattr(
        dashboard_core,
        "runtime_identity_status",
        lambda: {
            "git_commit": "commit-main-test",
            "git_commit_short": "commit-main-",
            "git_dirty": False,
            "source": "git",
        },
    )
    monkeypatch.setattr(dashboard_core.st, "set_page_config", lambda **_kwargs: None)
    monkeypatch.setattr(dashboard_core, "load_dashboard_css", lambda: None)
    monkeypatch.setattr(
        dashboard_core.st,
        "markdown",
        lambda body, **_kwargs: rendered_markdown.append(str(body)),
    )

    dashboard_core.configure_page("測試頁")

    marker = "\n".join(rendered_markdown)
    assert 'data-stock-frontend-runtime="true"' in marker
    assert 'data-git-commit="commit-main-test"' in marker
    assert 'data-git-dirty="false"' in marker
    assert 'aria-hidden="true"' in marker
