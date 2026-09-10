# Contributing to auto-code-reviewer

Thank you for your interest in contributing to **auto-code-reviewer**! We welcome bug reports, feature suggestions, architecture enhancements, and pull requests.

---

## 🛠️ Development Setup

### 1. Prerequisites
- Python 3.11+
- Docker & Docker Compose (optional, for containerized run)
- Git

### 2. Local Environment
```bash
# Clone the repository
git clone https://github.com/your-username/auto-code-reviewer.git
cd auto-code-reviewer

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure your environment
cp .env.example .env
```

### 3. Running the Service
```bash
# Run locally with Uvicorn
uvicorn app.main:app --reload --port 8000

# Or run via Docker Compose
docker compose up --build
```

---

## 🧪 Testing

We use `pytest` for unit and integration testing.

```bash
# Run the test suite
pytest -v

# Run with coverage
pytest --cov=app tests/
```

---

## 📐 Project Architecture

- **`app/main.py`**: Webhook endpoint listening for GitHub `pull_request` events.
- **`app/services/context_builder.py`**: AST-aware enclosing function/method and nested helper extractor, plus cross-file caller resolution.
- **`app/services/openhands_client.py`**: Model client for code comprehension, criticism, Mermaid.js synthesis, and fix proposals.
- **`app/services/prompt_builder.py`**: Formats inline review comments with GitHub suggestions, deep-link badges, and copyable prompts for Claude Code, Codex, and AGY.
- **`app/services/github_service.py`**: PyGithub and GraphQL interactions (PR descriptions, review comments, and auto-resolving threads).
- **`app/services/ses_service.py`**: AWS SES review summary notifications.
- **`deploy/`**: Automated scripts and configs for Vultr VPS and reverse proxy setup.

---

## 🤝 Contribution Guidelines

1. **Fork & Branch**: Create a descriptive feature branch (e.g., `git checkout -b feature/support-custom-llm`).
2. **Code Standards**:
   - Write type hints for all function arguments and returns.
   - Follow PEP 8 standards.
   - Keep functions focused and well-documented.
3. **Tests**: Add unit tests in `tests/` for any new service, parser, or model.
4. **Pull Request**: Open a PR against `main` with a clear description of the changes, test results, and any relevant context.
