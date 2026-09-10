import pytest
from app.services.context_builder import ContextBuilder

SAMPLE_PYTHON_FILE = """import os
import sys
from typing import Optional

def helper_function(x: int) -> int:
    return x * 2

def process_order(order_id: int, user_id: str) -> dict:
    \"\"\"Process an order with nested validator.\"\"\"
    def validate_payment():
        if order_id < 0:
            raise ValueError("Invalid order")
        return True

    validate_payment()
    return {"order_id": order_id, "processed": True}

class OrderManager:
    def cancel_order(self, order_id: int):
        print(f"Cancelling {order_id}")
"""

SAMPLE_PATCH = """@@ -9,4 +9,6 @@ def helper_function(x: int) -> int:
 def process_order(order_id: int, user_id: str) -> dict:
+    # New log line
+    print("Starting order")
     def validate_payment():
"""

SAMPLE_CALLER_FILE = """from app.orders import process_order

def checkout_view(request):
    user = request.user
    result = process_order(123, "user_456")
    return result
"""


def test_parse_patch_changed_lines():
    changed_lines = ContextBuilder.parse_patch_changed_lines(SAMPLE_PATCH)
    assert len(changed_lines) == 2
    assert 10 in changed_lines
    assert 11 in changed_lines


def test_extract_enclosing_python_scope():
    # Lines 10 and 11 fall inside process_order
    snippets = ContextBuilder.extract_enclosing_python_scope(
        SAMPLE_PYTHON_FILE, [10, 11]
    )

    assert len(snippets) == 1
    scope = snippets[0]
    assert scope["symbol"] == "def process_order"
    assert "def validate_payment" in scope["code"]
    assert "return {\"order_id\": order_id" in scope["code"]


def test_extract_file_header():
    header = ContextBuilder.extract_file_header(SAMPLE_PYTHON_FILE)
    assert "import os" in header
    assert "from typing import Optional" in header
    assert "def helper_function" not in header


def test_find_caller_snippets():
    repo_files = {
        "views.py": SAMPLE_CALLER_FILE,
    }
    callers = ContextBuilder.find_caller_snippets(
        repo_files=repo_files,
        modified_symbols=["process_order"],
        current_file="orders.py",
    )

    assert len(callers) >= 1
    caller = callers[0]
    assert caller["file_path"] == "views.py"
    assert caller["callee_symbol"] == "process_order"
    assert "checkout_view" in caller["caller_symbol"]
