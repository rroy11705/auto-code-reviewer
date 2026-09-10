import logging
from typing import Dict, Any, List
from app.services.context_builder import ContextBuilder
from app.services.openhands_client import OpenHandsClient
from app.services.github_service import GitHubService
from app.services.ses_service import SESService
from app.models.github_models import GitHubWebhookEvent

logger = logging.getLogger(__name__)


class ReviewOrchestrator:
    """Orchestrates the entire review lifecycle from webhook event to final comments and email."""

    def __init__(
        self,
        github_service: GitHubService = None,
        openhands_client: OpenHandsClient = None,
        ses_service: SESService = None,
    ):
        self.github_service = github_service or GitHubService()
        self.openhands_client = openhands_client or OpenHandsClient()
        self.ses_service = ses_service or SESService()

    async def process_pull_request_event(self, event_data: Dict[str, Any]) -> None:
        """Entrypoint called by FastAPI BackgroundTasks."""
        action = event_data.get("action")
        pr_data = event_data.get("pull_request")
        repo_data = event_data.get("repository", {})

        if not pr_data or not repo_data:
            logger.warning("Event missing pull_request or repository data. Skipping.")
            return

        repo_full_name = repo_data.get("full_name")
        pr_number = pr_data.get("number")
        pr_title = pr_data.get("title", "")
        pr_url = pr_data.get("html_url", "")

        logger.info(
            f"Starting review orchestration for {repo_full_name} PR #{pr_number} (action: {action})"
        )

        try:
            # 1. If this is a subsequent commit (synchronize), auto-resolve fixed threads
            if action == "synchronize":
                logger.info("Synchronize event detected. Checking for resolvable comment threads...")
                resolved = await self.github_service.auto_resolve_threads(
                    repo_full_name, pr_number
                )
                logger.info(f"Auto-resolved {resolved} outdated threads.")

            # 2. Fetch PR diff, file contents, lint configs, and repo documentation
            pr_context = self.github_service.fetch_pr_context(
                repo_full_name, pr_number
            )

            # 3. ContextBuilder: Extract targeted enclosing function snippets (not full files)
            targeted_snippets = []
            modified_symbols = []

            for changed_file in pr_context["changed_files"]:
                filename = changed_file["filename"]
                patch = changed_file["patch"]
                content = changed_file["content"]

                if not content or not patch:
                    continue

                # Parse changed line numbers from the patch
                changed_lines = ContextBuilder.parse_patch_changed_lines(patch)

                if filename.endswith(".py"):
                    extracted = ContextBuilder.extract_enclosing_python_scope(
                        content, changed_lines
                    )
                else:
                    extracted = ContextBuilder.extract_indentation_block(
                        content, changed_lines
                    )

                for item in extracted:
                    item["file_path"] = filename
                    targeted_snippets.append(item)
                    # Extract function name from symbol label e.g. "def calculate_total"
                    symbol_str = item.get("symbol", "")
                    if " " in symbol_str:
                        clean_name = symbol_str.split()[-1].split("(")[0]
                        modified_symbols.append(clean_name)

            # Extract caller snippets across other repository files to detect breaking changes
            caller_snippets = ContextBuilder.find_caller_snippets(
                repo_files=pr_context.get("repo_files_sample", {}),
                modified_symbols=modified_symbols,
                current_file="",
            )

            logger.info(
                f"Extracted {len(targeted_snippets)} enclosing snippets and "
                f"{len(caller_snippets)} caller snippets for OpenHands analysis."
            )

            # 4. OpenHands: Code understanding, criticism, Mermaid diagram, and fixes
            review_result = await self.openhands_client.analyze_and_review(
                pr_title=pr_context["pr_title"],
                pr_body=pr_context["pr_body"],
                snippets=targeted_snippets,
                caller_snippets=caller_snippets,
                lint_configs=pr_context["lint_configs"],
                doc_context=pr_context["doc_context"],
            )

            # 5. Update PR description with AI summary and Mermaid.js diagram
            self.github_service.update_pr_description_with_mermaid(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                summary=review_result.summary,
                mermaid_diagram=review_result.mermaid_diagram,
                breaking_changes=review_result.breaking_changes,
            )

            # 6. Post inline review comments with GitHub suggestion blocks & multi-tool buttons
            posted_comments = self.github_service.post_inline_comments(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=pr_context["head_sha"],
                proposals=review_result.comments,
            )
            logger.info(f"Posted {posted_comments} inline review comments on PR #{pr_number}.")

            # 7. Send AWS SES notification email to reviewers
            reviewer_emails = []  # Can be populated from PR requested reviewers or team default
            self.ses_service.send_review_notification(
                repo_name=repo_full_name,
                pr_number=pr_number,
                pr_title=pr_title,
                pr_url=pr_url,
                review_result=review_result,
                recipients=reviewer_emails,
            )

            logger.info(f"Review orchestration completed successfully for PR #{pr_number}.")

        except Exception as e:
            logger.exception(f"Error during review orchestration for PR #{pr_number}: {e}")
