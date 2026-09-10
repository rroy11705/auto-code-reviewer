from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class GitUser(BaseModel):
    login: str
    id: Optional[int] = None
    avatar_url: Optional[str] = None
    html_url: Optional[str] = None


class GitCommitRef(BaseModel):
    label: Optional[str] = None
    ref: str
    sha: str


class RepositoryInfo(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool = False
    html_url: str
    description: Optional[str] = None
    default_branch: str = "main"


class PullRequestInfo(BaseModel):
    id: int
    number: int
    title: str
    body: Optional[str] = ""
    state: str = "open"
    html_url: str
    diff_url: Optional[str] = None
    patch_url: Optional[str] = None
    user: GitUser
    head: GitCommitRef
    base: GitCommitRef
    requested_reviewers: List[GitUser] = Field(default_factory=list)


class GitHubWebhookEvent(BaseModel):
    """Payload sent by GitHub for pull_request events."""
    action: str
    number: Optional[int] = None
    pull_request: Optional[PullRequestInfo] = None
    repository: RepositoryInfo
    sender: GitUser
