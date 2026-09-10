from typing import List, Optional
from pydantic import BaseModel, Field


class InlineCommentProposal(BaseModel):
    """An issue identified on a specific line of code with multiple fix mechanisms."""
    file_path: str
    line_number: int
    issue_title: str
    description: str
    suggested_replacement: Optional[str] = None
    
    # Pre-calculated CLI commands and preloaded prompts
    claude_code_command: Optional[str] = None
    agy_command: Optional[str] = None
    codex_prompt: Optional[str] = None
    
    # Clickable web deep links
    deep_link_claude: Optional[str] = None
    deep_link_codex: Optional[str] = None


class BreakingChangeAlert(BaseModel):
    """Alert for cross-file regressions or signature breakages."""
    file_path: str
    symbol_name: str
    description: str
    affected_callers: List[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """Overall review outcome produced by OpenHands."""
    summary: str
    mermaid_diagram: str
    breaking_changes: List[BreakingChangeAlert] = Field(default_factory=list)
    comments: List[InlineCommentProposal] = Field(default_factory=list)
