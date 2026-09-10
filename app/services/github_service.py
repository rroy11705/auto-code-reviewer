import logging
import httpx
from typing import Dict, Any, List, Optional, Tuple
from github import Github, GithubException
from github.PullRequest import PullRequest

from app.config import settings
from app.models.review_models import InlineCommentProposal, BreakingChangeAlert
from app.services.prompt_builder import MultiToolFixBuilder

logger = logging.getLogger(__name__)

LINT_FILENAMES = [
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    ".prettierrc",
    ".prettierrc.json",
    "ruff.toml",
    "pyproject.toml",
    "tsconfig.json",
]

DOC_FILENAMES = ["README.md", "CONTRIBUTING.md"]


class GitHubService:
    """Service wrapping PyGithub and GitHub GraphQL API."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        self.gh = Github(self.token) if self.token else None

    def _get_repo_and_pr(self, repo_full_name: str, pr_number: int) -> Tuple[Any, PullRequest]:
        if not self.gh:
            raise ValueError("GITHUB_TOKEN is not configured.")
        repo = self.gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        return repo, pr

    def fetch_pr_context(self, repo_full_name: str, pr_number: int) -> Dict[str, Any]:
        """Fetches PR diff, full contents of changed files, lint configs, and docs."""
        repo, pr = self._get_repo_and_pr(repo_full_name, pr_number)

        changed_files_data = []
        repo_files_sample = {}

        # 1. Fetch changed files & patches
        for f in pr.get_files():
            file_content = ""
            try:
                content_file = repo.get_contents(f.filename, ref=pr.head.sha)
                if not isinstance(content_file, list) and content_file.decoded_content:
                    file_content = content_file.decoded_content.decode("utf-8", errors="replace")
            except Exception as e:
                logger.debug(f"Could not load full content for {f.filename}: {e}")

            changed_files_data.append(
                {
                    "filename": f.filename,
                    "patch": f.patch or "",
                    "content": file_content,
                    "status": f.status,
                }
            )

        # 2. Extract lint configs from repo
        lint_configs = {}
        for lint_file in LINT_FILENAMES:
            try:
                c = repo.get_contents(lint_file, ref=pr.head.sha)
                if not isinstance(c, list) and c.decoded_content:
                    lint_configs[lint_file] = c.decoded_content.decode("utf-8", errors="replace")
            except GithubException:
                pass  # File does not exist

        # 3. Extract documentation context
        doc_context_parts = []
        for doc_file in DOC_FILENAMES:
            try:
                d = repo.get_contents(doc_file, ref=pr.head.sha)
                if not isinstance(d, list) and d.decoded_content:
                    doc_context_parts.append(
                        f"### {doc_file}:\n"
                        + d.decoded_content.decode("utf-8", errors="replace")[:2000]
                    )
            except GithubException:
                pass

        # 4. Fetch repo tree sample to find callers
        try:
            tree = repo.get_git_tree(pr.head.sha, recursive=True)
            for element in tree.tree:
                # Target code files
                if element.path.endswith((".py", ".js", ".ts", ".go")):
                    # Fetch first 30 relevant files for caller scanning
                    if len(repo_files_sample) < 30 and element.path not in [
                        cf["filename"] for cf in changed_files_data
                    ]:
                        try:
                            cf = repo.get_contents(element.path, ref=pr.head.sha)
                            if not isinstance(cf, list) and cf.decoded_content:
                                repo_files_sample[element.path] = (
                                    cf.decoded_content.decode("utf-8", errors="replace")
                                )
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Could not fetch git tree for caller scanning: {e}")

        return {
            "pr_title": pr.title,
            "pr_body": pr.body or "",
            "head_sha": pr.head.sha,
            "changed_files": changed_files_data,
            "lint_configs": lint_configs,
            "doc_context": "\n".join(doc_context_parts),
            "repo_files_sample": repo_files_sample,
        }

    def update_pr_description_with_mermaid(
        self,
        repo_full_name: str,
        pr_number: int,
        summary: str,
        mermaid_diagram: str,
        breaking_changes: List[BreakingChangeAlert],
    ) -> None:
        """Injects or updates the AI Review section in the PR description,

        preserving existing author description.
        """
        _, pr = self._get_repo_and_pr(repo_full_name, pr_number)
        current_body = pr.body or ""

        marker_start = "<!-- AUTO-CODE-REVIEWER-START -->"
        marker_end = "<!-- AUTO-CODE-REVIEWER-END -->"

        breaking_md = MultiToolFixBuilder.format_breaking_change_section(breaking_changes)

        ai_section = (
            f"{marker_start}\n"
            f"## 🤖 AI Architectural Review (OpenHands)\n\n"
            f"### 📋 Summary\n{summary}\n\n"
            f"### 🏗️ Architecture & Component Flow\n"
            f"```mermaid\n{mermaid_diagram}\n```\n\n"
            f"{breaking_md}"
            f"---\n"
            f"*Auto-generated by [auto-code-reviewer](https://github.com/your-org/auto-code-reviewer)*\n"
            f"{marker_end}"
        )

        if marker_start in current_body and marker_end in current_body:
            # Replace existing section
            start_idx = current_body.find(marker_start)
            end_idx = current_body.find(marker_end) + len(marker_end)
            new_body = current_body[:start_idx] + ai_section + current_body[end_idx:]
        else:
            # Append to bottom
            new_body = (
                f"{current_body}\n\n{ai_section}" if current_body else ai_section
            )

        pr.edit(body=new_body)
        logger.info(f"Updated PR #{pr_number} description with Mermaid diagram.")

    def post_inline_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        proposals: List[InlineCommentProposal],
    ) -> int:
        """Publishes inline review comments with GitHub suggestions and tool commands."""
        repo, pr = self._get_repo_and_pr(repo_full_name, pr_number)
        posted_count = 0

        # Retrieve commit object
        commit = repo.get_commit(head_sha)

        for p in proposals:
            enriched = MultiToolFixBuilder.enrich_comment_proposal(
                p, repo_name=repo_full_name, pr_number=pr_number
            )
            comment_body = MultiToolFixBuilder.format_github_review_comment(enriched)

            try:
                pr.create_review_comment(
                    body=comment_body,
                    commit=commit,
                    path=enriched.file_path,
                    line=enriched.line_number,
                )
                posted_count += 1
                logger.info(
                    f"Posted inline comment on {enriched.file_path}:{enriched.line_number}"
                )
            except GithubException as e:
                # Sometimes line is not part of diff hunk, post fallback general comment
                logger.warning(
                    f"Could not post review comment on line {enriched.line_number} of {enriched.file_path}: {e}"
                )
                try:
                    pr.create_issue_comment(
                        f"**Line {enriched.line_number} in `{enriched.file_path}`:**\n{comment_body}"
                    )
                    posted_count += 1
                except Exception as ex:
                    logger.error(f"Failed to post fallback PR comment: {ex}")

        return posted_count

    async def auto_resolve_threads(
        self, repo_full_name: str, pr_number: int
    ) -> int:
        """Uses GitHub's GraphQL API to resolve review threads that have been fixed."""
        if not self.token:
            return 0

        owner, repo_name = repo_full_name.split("/")
        graphql_query = """
        query GetPRThreads($owner: String!, $name: String!, $pr: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $pr) {
              reviewThreads(first: 50) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  comments(first: 1) {
                    nodes {
                      body
                      author {
                        login
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        mutation = """
        mutation ResolveThread($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread {
              id
              isResolved
            }
          }
        }
        """

        resolved_count = 0
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.github.com/graphql",
                headers=headers,
                json={
                    "query": graphql_query,
                    "variables": {"owner": owner, "name": repo_name, "pr": pr_number},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"GraphQL query failed with status {resp.status_code}")
                return 0

            data = resp.json()
            threads = (
                data.get("data", {})
                .get("repository", {})
                .get("pullRequest", {})
                .get("reviewThreads", {})
                .get("nodes", [])
            )

            for thread in threads:
                thread_id = thread.get("id")
                is_resolved = thread.get("isResolved", False)
                is_outdated = thread.get("isOutdated", False)

                # Check if it was an auto-code-reviewer thread
                first_comment = (
                    thread.get("comments", {}).get("nodes", [{}])[0]
                    if thread.get("comments", {}).get("nodes")
                    else {}
                )
                comment_body = first_comment.get("body", "")

                is_bot_comment = "auto-code-reviewer" in comment_body

                # If thread was outdated (new commit pushed fixing lines) or flagged as resolved
                if not is_resolved and is_bot_comment and is_outdated:
                    resolve_resp = await client.post(
                        "https://api.github.com/graphql",
                        headers=headers,
                        json={"query": mutation, "variables": {"threadId": thread_id}},
                    )
                    if resolve_resp.status_code == 200:
                        logger.info(f"Auto-resolved thread {thread_id} on PR #{pr_number}")
                        resolved_count += 1

        return resolved_count
