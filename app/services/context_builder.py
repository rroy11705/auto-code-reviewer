import ast
import re
from typing import List, Dict, Any, Optional, Tuple, Set


class ContextBuilder:
    """Builds semantic context by extracting enclosing functions, nested helpers,

    and caller snippets instead of entire multi-thousand line files.
    """

    @staticmethod
    def parse_patch_changed_lines(patch: str) -> List[int]:
        """Parses a unified diff patch string and returns the line numbers

        in the new file that were added or modified.
        """
        changed_lines = []
        if not patch:
            return changed_lines

        lines = patch.splitlines()
        current_new_line = 0

        hunk_header_regex = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

        for line in lines:
            match = hunk_header_regex.match(line)
            if match:
                current_new_line = int(match.group(1))
                continue

            if line.startswith("+") and not line.startswith("+++"):
                changed_lines.append(current_new_line)
                current_new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                # Deleted line in old file, doesn't increment new file line counter
                pass
            else:
                # Context line
                current_new_line += 1

        return changed_lines

    @classmethod
    def extract_enclosing_python_scope(
        cls, file_content: str, target_lines: List[int]
    ) -> List[Dict[str, Any]]:
        """Uses Python AST to find enclosing functions or methods for the target lines.

        Returns snippets covering the complete enclosing function(s), including
        nested functions, decorators, and signatures.
        """
        snippets = []
        if not target_lines:
            return snippets

        lines = file_content.splitlines()

        try:
            tree = ast.parse(file_content)
        except SyntaxError:
            # Fallback to indentation-based extraction
            return cls.extract_indentation_block(file_content, target_lines)

        nodes_found: List[Tuple[ast.AST, str, int, int]] = []

        class ScopeVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef):
                self._check_node(node, f"def {node.name}")
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                self._check_node(node, f"async def {node.name}")
                self.generic_visit(node)

            def _check_node(self, node: Any, symbol_label: str):
                start = getattr(node, "lineno", 1)
                end = getattr(node, "end_lineno", len(lines))
                # Check if any target line falls within this node
                if any(start <= line <= end for line in target_lines):
                    nodes_found.append((node, symbol_label, start, end))

        ScopeVisitor().visit(tree)

        # De-duplicate nodes: If both outer function and nested function match,
        # we can prioritize the outermost enclosing function to capture all nested helpers.
        if nodes_found:
            # Sort by span size descending (outermost first)
            nodes_found.sort(key=lambda x: (x[3] - x[2]), reverse=True)
            chosen_nodes = []
            covered_spans: Set[Tuple[int, int]] = set()

            for node, symbol, start, end in nodes_found:
                # If this span is already covered by a wider chosen span, skip
                already_covered = any(
                    c_start <= start and end <= c_end for c_start, c_end in covered_spans
                )
                if not already_covered:
                    chosen_nodes.append((node, symbol, start, end))
                    covered_spans.add((start, end))

            for _, symbol, start, end in chosen_nodes:
                snippet_text = "\n".join(lines[start - 1 : end])
                snippets.append(
                    {
                        "symbol": symbol,
                        "start_line": start,
                        "end_line": end,
                        "code": snippet_text,
                    }
                )

        # If no function enclosed the lines (e.g. top-level statements), extract surrounding lines
        if not snippets:
            return cls.extract_surrounding_window(lines, target_lines)

        return snippets

    @classmethod
    def extract_indentation_block(
        cls, file_content: str, target_lines: List[int]
    ) -> List[Dict[str, Any]]:
        """Fallback block extractor for languages other than Python (or syntax errors).

        Walks backwards to find function definition, then forward to scope end.
        """
        lines = file_content.splitlines()
        snippets = []
        if not lines or not target_lines:
            return snippets

        def_pattern = re.compile(
            r"^\s*(def |async def |function |func |public |private |protected |const [a-zA-Z0-9_]+\s*=\s*(?:async\s*)?\()"
        )

        min_line = max(1, min(target_lines))
        max_line = min(len(lines), max(target_lines))

        # Scan backwards to locate start of function
        start_idx = min_line - 1
        found_def = False
        while start_idx >= 0:
            if def_pattern.match(lines[start_idx]):
                found_def = True
                break
            start_idx -= 1

        if not found_def:
            start_idx = max(0, min_line - 10)

        # Scan forward for reasonable scope or indentation drop
        end_idx = min(len(lines), max_line + 15)

        snippet_code = "\n".join(lines[start_idx:end_idx])
        snippets.append(
            {
                "symbol": lines[start_idx].strip() if found_def else "block",
                "start_line": start_idx + 1,
                "end_line": end_idx,
                "code": snippet_code,
            }
        )

        return snippets

    @staticmethod
    def extract_surrounding_window(
        lines: List[str], target_lines: List[int], window: int = 15
    ) -> List[Dict[str, Any]]:
        """Extracts a bounded window around target lines."""
        if not target_lines:
            return []
        min_line = max(1, min(target_lines) - window)
        max_line = min(len(lines), max(target_lines) + window)

        snippet_text = "\n".join(lines[min_line - 1 : max_line])
        return [
            {
                "symbol": "top-level",
                "start_line": min_line,
                "end_line": max_line,
                "code": snippet_text,
            }
        ]

    @staticmethod
    def extract_file_header(file_content: str, max_lines: int = 25) -> str:
        """Extracts imports and header lines from top of file."""
        lines = file_content.splitlines()
        header_lines = []
        for line in lines[:max_lines]:
            # Keep imports, package statements, or module docstrings
            if any(
                keyword in line
                for keyword in ["import ", "from ", "package ", "require(", "using "]
            ):
                header_lines.append(line)
        return "\n".join(header_lines)

    @classmethod
    def find_caller_snippets(
        cls,
        repo_files: Dict[str, str],
        modified_symbols: List[str],
        current_file: str,
    ) -> List[Dict[str, Any]]:
        """Finds snippets in other repo files that invoke the modified symbols

        to detect breaking changes.
        """
        caller_snippets = []
        if not modified_symbols:
            return caller_snippets

        for file_path, content in repo_files.items():
            if file_path == current_file:
                continue

            for symbol in modified_symbols:
                # Look for calls like symbol(...)
                pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(")
                lines = content.splitlines()

                matching_lines = [
                    idx + 1
                    for idx, line in enumerate(lines)
                    if pattern.search(line)
                ]

                if matching_lines:
                    if file_path.endswith(".py"):
                        extracted = cls.extract_enclosing_python_scope(
                            content, matching_lines
                        )
                    else:
                        extracted = cls.extract_indentation_block(
                            content, matching_lines
                        )

                    for item in extracted:
                        caller_snippets.append(
                            {
                                "file_path": file_path,
                                "callee_symbol": symbol,
                                "caller_symbol": item.get("symbol", "unknown"),
                                "start_line": item.get("start_line"),
                                "end_line": item.get("end_line"),
                                "code": item.get("code"),
                            }
                        )

        return caller_snippets
