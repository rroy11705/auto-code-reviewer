import pytest
from app.services.openhands_client import OpenHandsClient
from app.models.review_models import ReviewResult

MOCK_RAW_RESPONSE = """```json
{
  "summary": "This PR adds user payment authentication and input sanitization.",
  "mermaid_diagram": "flowchart TD\\n  Client --> AuthAPI\\n  AuthAPI --> DB",
  "breaking_changes": [
    {
      "file_path": "app/auth.py",
      "symbol_name": "validate_token",
      "description": "Added required parameter without default value",
      "affected_callers": ["app/views.py:45"]
    }
  ],
  "comments": [
    {
      "file_path": "app/payment.py",
      "line_number": 88,
      "issue_title": "Uncaught Exception in Payment Processing",
      "description": "The Stripe charge call can raise StripeError which is not caught.",
      "suggested_replacement": "try:\\n    charge = stripe.Charge.create()\\nexcept stripe.StripeError as e:\\n    raise PaymentFailed(e)"
    }
  ]
}
```"""


def test_parse_model_response():
    client = OpenHandsClient()
    result = client._parse_model_response(MOCK_RAW_RESPONSE)

    assert isinstance(result, ReviewResult)
    assert "user payment authentication" in result.summary
    assert "flowchart TD" in result.mermaid_diagram

    # Breaking changes check
    assert len(result.breaking_changes) == 1
    alert = result.breaking_changes[0]
    assert alert.symbol_name == "validate_token"
    assert "app/views.py:45" in alert.affected_callers

    # Comments check
    assert len(result.comments) == 1
    comment = result.comments[0]
    assert comment.file_path == "app/payment.py"
    assert comment.line_number == 88
    assert "Uncaught Exception" in comment.issue_title
    assert "try:" in comment.suggested_replacement
