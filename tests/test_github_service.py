import pytest
from app.models.review_models import InlineCommentProposal, BreakingChangeAlert
from app.services.prompt_builder import MultiToolFixBuilder


def test_enrich_comment_proposal():
    proposal = InlineCommentProposal(
        file_path="app/auth.py",
        line_number=42,
        issue_title="Missing null check",
        description="user object can be None if not found in db",
        suggested_replacement="if user is None:\n    return None",
    )

    enriched = MultiToolFixBuilder.enrich_comment_proposal(
        proposal, repo_name="org/repo", pr_number=10
    )

    assert "agy " in enriched.agy_command
    assert "app/auth.py" in enriched.agy_command
    assert "claude " in enriched.claude_code_command
    assert "claude.ai" in enriched.deep_link_claude
    assert "chatgpt.com" in enriched.deep_link_codex


def test_format_github_review_comment():
    proposal = InlineCommentProposal(
        file_path="app/auth.py",
        line_number=42,
        issue_title="Missing null check",
        description="user object can be None",
        suggested_replacement="if not user:\n    return None",
    )
    enriched = MultiToolFixBuilder.enrich_comment_proposal(
        proposal, repo_name="org/repo", pr_number=10
    )
    formatted = MultiToolFixBuilder.format_github_review_comment(enriched)

    # Check for GitHub Suggestion block
    assert "```suggestion" in formatted
    assert "if not user:" in formatted

    # Check for Claude / Codex badges
    assert "Fix in Claude Code" in formatted
    assert "Fix in Codex" in formatted

    # Check for CLI commands
    assert "Antigravity CLI (`agy`)" in formatted
    assert "Claude Code CLI (`claude`)" in formatted


def test_format_breaking_change_section():
    alerts = [
        BreakingChangeAlert(
            file_path="app/services/db.py",
            symbol_name="query_users",
            description="Signature changed from query_users(id) to query_users(id, tenant_id)",
            affected_callers=["app/views.py:12"],
        )
    ]
    formatted = MultiToolFixBuilder.format_breaking_change_section(alerts)

    assert "Cross-File Breaking Change Warnings" in formatted
    assert "`query_users` in `app/services/db.py`" in formatted
    assert "app/views.py:12" in formatted
