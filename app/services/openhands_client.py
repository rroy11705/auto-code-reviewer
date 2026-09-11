import json
import logging
import re
from typing import Dict, Any, List, Optional
import httpx

from app.config import settings
from app.models.review_models import (
    ReviewResult,
    InlineCommentProposal,
    BreakingChangeAlert,
)

logger = logging.getLogger(__name__)


class OpenHandsClient:
    """Client for the user-downloaded OpenHands model (or OpenAI-compatible local model)

    with fallback to Anthropic Claude.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.endpoint = endpoint or settings.OPENHANDS_ENDPOINT
        self.model_name = model_name or settings.OPENHANDS_MODEL_NAME
        self.api_key = api_key or settings.OPENHANDS_API_KEY

    async def analyze_and_review(
        self,
        pr_title: str,
        pr_body: str,
        snippets: List[Dict[str, Any]],
        caller_snippets: List[Dict[str, Any]],
        lint_configs: Dict[str, Any],
        doc_context: str,
    ) -> ReviewResult:
        """Sends the semantic snippets, caller context, and lint configs

        to OpenHands to analyze, criticize, generate a Mermaid architecture diagram,
        detect breaking changes, and propose code fixes.
        """
        system_prompt = (
            "You are an expert Staff Software Engineer and AI Code Reviewer using OpenHands. "
            "Your task is to thoroughly analyze, criticize, and review a GitHub Pull Request.\n\n"
            "Key Requirements:\n"
            "1. Deep Code Criticism: Detect bugs, security vulnerabilities, edge-case failures, "
            "and linting/formatting issues according to the repository's configs.\n"
            "2. Cross-Function & Cross-File Impact: Analyze the provided caller snippets to verify if "
            "any changes (signature changes, return types, renamed fields) will break callers across the repo.\n"
            "3. Architecture Diagram: Generate a clean, valid Mermaid.js diagram (e.g. flowchart TD or sequenceDiagram) "
            "illustrating how the new feature or changes interact with the system architecture.\n"
            "4. Actionable Fixes: For each issue, provide a precise 1-to-few line code replacement "
            "compatible with GitHub suggestion blocks.\n\n"
            "You must respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            '  "summary": "Detailed summary of PR changes and impact",\n'
            '  "mermaid_diagram": "flowchart TD\\n  A[Client] --> B[Endpoint]\\n  ...",\n'
            '  "breaking_changes": [\n'
            '    {\n'
            '      "file_path": "path/to/file.py",\n'
            '      "symbol_name": "function_name",\n'
            '      "description": "Explanation of how this breaks dependent modules",\n'
            '      "affected_callers": ["caller_file.py:line_num"]\n'
            '    }\n'
            '  ],\n'
            '  "comments": [\n'
            '    {\n'
            '      "file_path": "path/to/file.py",\n'
            '      "line_number": 42,\n'
            '      "issue_title": "Concise issue summary",\n'
            '      "description": "Thorough explanation of the bug or lint issue",\n'
            '      "suggested_replacement": "corrected line(s) of code"\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        user_prompt = self._build_user_prompt(
            pr_title=pr_title,
            pr_body=pr_body,
            snippets=snippets,
            caller_snippets=caller_snippets,
            lint_configs=lint_configs,
            doc_context=doc_context,
        )

        try:
            # 1. Primary: Attempt query to OpenHands model
            response_json = await self._call_openhands_endpoint(system_prompt, user_prompt)
            return self._parse_model_response(response_json)
        except Exception as e:
            logger.warning(
                f"OpenHands model endpoint failed ({e}). Checking Anthropic Claude fallback..."
            )
            # 2. Secondary: Fallback to Anthropic Claude if configured
            if settings.ANTHROPIC_API_KEY:
                return await self._call_anthropic_fallback(system_prompt, user_prompt)
            raise e

    def _build_user_prompt(
        self,
        pr_title: str,
        pr_body: str,
        snippets: List[Dict[str, Any]],
        caller_snippets: List[Dict[str, Any]],
        lint_configs: Dict[str, Any],
        doc_context: str,
    ) -> str:
        parts = [
            f"# Pull Request: {pr_title}",
            f"## Description:\n{pr_body or 'No description provided.'}\n",
        ]

        if lint_configs:
            parts.append("## Project Linting & Formatting Configurations:")
            for cfg_name, cfg_content in lint_configs.items():
                parts.append(f"### {cfg_name}\n```\n{cfg_content}\n```\n")

        if doc_context:
            parts.append(f"## Documentation Context:\n{doc_context}\n")

        parts.append("## Modified Code Snippets (Enclosing Functions & Nested Helpers):")
        for snip in snippets:
            parts.append(
                f"### File: {snip.get('file_path')} (Lines {snip.get('start_line')}-{snip.get('end_line')})\n"
                f"Scope: `{snip.get('symbol')}`\n"
                f"```\n{snip.get('code')}\n```\n"
            )

        if caller_snippets:
            parts.append("## Cross-File Callers & Supporting Dependencies:")
            for c_snip in caller_snippets:
                parts.append(
                    f"### Caller File: {c_snip.get('file_path')} (Calling `{c_snip.get('callee_symbol')}`)\n"
                    f"Caller Scope: `{c_snip.get('caller_symbol')}`\n"
                    f"```\n{c_snip.get('code')}\n```\n"
                )

        return "\n".join(parts)

    async def _call_openhands_endpoint(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        """Invokes the OpenHands server / local OpenAI-compatible inference endpoint."""
        url = self.endpoint.rstrip("/")
        # If pointing to base or /api or /v1, determine chat completions URL
        if not url.endswith("/chat/completions"):
            if url.endswith("/v1"):
                url = f"{url}/chat/completions"
            else:
                url = f"{url}/v1/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_anthropic_fallback(
        self, system_prompt: str, user_prompt: str
    ) -> ReviewResult:
        """Fallback to Anthropic Claude SDK if OpenHands local model is not running."""
        import anthropic

        logger.info("Executing review using Anthropic Claude SDK fallback.")
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=4096,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        return self._parse_model_response(content_text)

    def _parse_model_response(self, raw_text: str) -> ReviewResult:
        """Extracts and parses JSON object from model output."""
        # Find json block if fenced
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        clean_json = json_match.group(1) if json_match else raw_text.strip()

        try:
            data = json.loads(clean_json)
        except json.JSONDecodeError:
            # Attempt to extract outermost { ... }
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1:
                data = json.loads(raw_text[start : end + 1])
            else:
                raise ValueError(f"Could not parse valid JSON from model response: {raw_text[:200]}")

        # Construct Pydantic models
        breaking_alerts = [
            BreakingChangeAlert(
                file_path=b.get("file_path", ""),
                symbol_name=b.get("symbol_name", ""),
                description=b.get("description", ""),
                affected_callers=b.get("affected_callers", []),
            )
            for b in data.get("breaking_changes", [])
        ]

        comments = [
            InlineCommentProposal(
                file_path=c.get("file_path", ""),
                line_number=c.get("line_number", 1),
                issue_title=c.get("issue_title", "Code Quality Issue"),
                description=c.get("description", ""),
                suggested_replacement=c.get("suggested_replacement"),
            )
            for c in data.get("comments", [])
        ]

        return ReviewResult(
            summary=data.get("summary", "PR review completed."),
            mermaid_diagram=data.get("mermaid_diagram", "graph TD;\n  A[PR Changes] --> B[Components];"),
            breaking_changes=breaking_alerts,
            comments=comments,
        )
