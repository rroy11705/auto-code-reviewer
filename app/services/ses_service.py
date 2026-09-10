import logging
from typing import List, Optional
import boto3
from botocore.exceptions import ClientError

from app.config import settings
from app.models.review_models import ReviewResult

logger = logging.getLogger(__name__)


class SESService:
    """Service to send review summary notifications via AWS SES using boto3."""

    def __init__(self):
        self.region = settings.AWS_REGION
        self.sender_email = settings.SES_SENDER_EMAIL
        self.default_recipient = settings.SES_DEFAULT_RECIPIENT
        self.dry_run = settings.SES_DRY_RUN

        # Initialize boto3 SES client if credentials available and not dry run
        self.client = None
        if not self.dry_run and (settings.AWS_ACCESS_KEY_ID or settings.AWS_REGION):
            try:
                session = boto3.Session(
                    region_name=self.region,
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                )
                self.client = session.client("ses")
            except Exception as e:
                logger.warning(f"Could not initialize AWS SES client: {e}. Falling back to dry-run mode.")
                self.dry_run = True
        else:
            self.dry_run = True

    def send_review_notification(
        self,
        repo_name: str,
        pr_number: int,
        pr_title: str,
        pr_url: str,
        review_result: ReviewResult,
        recipients: Optional[List[str]] = None,
    ) -> bool:
        """Sends an HTML and plaintext summary email to PR reviewers."""
        to_addresses = recipients if recipients else [self.default_recipient]

        subject = f"[auto-code-reviewer] Review Finished: #{pr_number} {pr_title}"

        # Count metrics
        issue_count = len(review_result.comments)
        breaking_count = len(review_result.breaking_changes)

        # Plaintext body
        text_body = (
            f"AI PR Review Completed for {repo_name} #{pr_number}\n\n"
            f"Title: {pr_title}\n"
            f"PR Link: {pr_url}\n\n"
            f"Summary:\n{review_result.summary}\n\n"
            f"Issues Flagged: {issue_count}\n"
            f"Breaking Changes: {breaking_count}\n\n"
            f"View the complete review and one-click fixes in GitHub: {pr_url}\n"
        )

        # HTML body
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e1e4e8; border-radius: 6px; }}
                .header {{ background-color: #24292e; color: #fff; padding: 15px; border-radius: 4px 4px 0 0; }}
                .badge {{ display: inline-block; padding: 4px 8px; border-radius: 12px; font-weight: bold; font-size: 12px; }}
                .badge-warning {{ background-color: #fff5b1; color: #735c0f; }}
                .badge-danger {{ background-color: #ffdce0; color: #cb2431; }}
                .btn {{ display: inline-block; background-color: #2ea44f; color: white; padding: 10px 18px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🤖 auto-code-reviewer Notification</h2>
                </div>
                <div style="padding: 20px 0;">
                    <h3><a href="{pr_url}">#{pr_number}: {pr_title}</a></h3>
                    <p><strong>Repository:</strong> {repo_name}</p>
                    <p>{review_result.summary}</p>
                    
                    <div style="margin: 20px 0;">
                        <span class="badge badge-warning">⚠️ {issue_count} Issues Detected</span>
                        {f'<span class="badge badge-danger">🚨 {breaking_count} Breaking Changes</span>' if breaking_count else ''}
                    </div>

                    <a href="{pr_url}" class="btn">View Review on GitHub</a>
                </div>
                <hr style="border: none; border-top: 1px solid #e1e4e8;" />
                <small style="color: #586069;">Powered by OpenHands & auto-code-reviewer</small>
            </div>
        </body>
        </html>
        """

        if self.dry_run or not self.client:
            logger.info(
                f"[SES DRY-RUN] Would send notification to {to_addresses} for PR #{pr_number}:\n"
                f"Subject: {subject}\n{text_body}"
            )
            return True

        try:
            response = self.client.send_email(
                Source=self.sender_email,
                Destination={"ToAddresses": to_addresses},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )
            logger.info(f"SES email sent successfully. MessageId: {response.get('MessageId')}")
            return True
        except ClientError as e:
            logger.error(f"Failed to send AWS SES email: {e.response['Error']['Message']}")
            return False
