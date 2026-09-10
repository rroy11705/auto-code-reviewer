import hmac
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.services.reviewer import ReviewOrchestrator

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auto-code-reviewer")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Starting up auto-code-reviewer service...")
    logger.info(f"OpenHands Endpoint: {settings.OPENHANDS_ENDPOINT}")
    logger.info(f"AWS SES Region: {settings.AWS_REGION} (Dry-Run: {settings.SES_DRY_RUN})")
    yield
    logger.info("Shutting down auto-code-reviewer service...")


app = FastAPI(
    title="auto-code-reviewer",
    description="AI-powered GitHub PR reviewer using OpenHands, FastAPI, and PyGithub.",
    version="0.1.0",
    lifespan=lifespan,
)

orchestrator = ReviewOrchestrator()


def verify_github_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Verifies HMAC SHA-256 signature from GitHub webhook header."""
    if not settings.GITHUB_WEBHOOK_SECRET:
        # If secret is not configured, warn and bypass for development
        logger.warning("GITHUB_WEBHOOK_SECRET is not configured; skipping signature check.")
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header[7:]
    mac = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    )
    return hmac.compare_digest(mac.hexdigest(), expected_sig)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Uptime healthcheck endpoint."""
    return {
        "status": "ok",
        "service": "auto-code-reviewer",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    """Service metadata and links."""
    return {
        "name": "auto-code-reviewer",
        "description": "AI-powered GitHub PR reviewer leveraging OpenHands, PyGithub, and AWS SES.",
        "endpoints": {
            "health": "/health",
            "webhook": "/webhook/github",
        },
    }


@app.post("/webhook/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
):
    """Receives and verifies GitHub webhook payloads.

    Dispatches review orchestration asynchronously on pull_request events.
    """
    raw_body = await request.body()

    # 1. Verify HMAC SHA-256 Signature
    if settings.GITHUB_WEBHOOK_SECRET and not verify_github_signature(
        raw_body, x_hub_signature_256
    ):
        logger.error("Invalid GitHub webhook signature.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature",
        )

    # 2. Filter for Pull Request Events
    if x_github_event != "pull_request":
        logger.debug(f"Ignoring non-pull_request event: {x_github_event}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": f"Event '{x_github_event}' ignored."},
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON payload.")

    action = payload.get("action")

    # 3. Only handle 'opened', 'synchronize', and 'reopened'
    if action not in ["opened", "synchronize", "reopened"]:
        logger.info(f"Ignoring pull_request action: {action}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": f"Pull request action '{action}' ignored."},
        )

    # 4. Enqueue review orchestrator in background task to respond promptly to GitHub
    pr_number = payload.get("pull_request", {}).get("number")
    repo_name = payload.get("repository", {}).get("full_name")
    logger.info(
        f"Queued background review for PR #{pr_number} in {repo_name} (action: {action})"
    )

    background_tasks.add_task(orchestrator.process_pull_request_event, payload)

    return {
        "status": "accepted",
        "message": f"Review process initiated for PR #{pr_number}.",
        "action": action,
    }
