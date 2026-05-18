import os
import ast
from pathlib import Path

backend_dir = str(Path(os.environ.get("BACKEND_DIR", Path.home() / "OneDrive" / "Documents" / "GitHub" / "task-buddy-backend")))
tests_dir = os.path.join(backend_dir, "tests")

print("Backend tests:")
for root, _, files in os.walk(tests_dir):
    for file in files:
        if file.endswith(".py") and not file.startswith("__"):
            filepath = os.path.join(root, file)
            rel = os.path.relpath(filepath, backend_dir).replace("\\", "/")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=filepath)
                funcs = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                        funcs.append(node.name)
                if funcs:
                    print(f"\n{rel}:")
                    for fn in sorted(funcs):
                        print(f"  - {fn}")
            except Exception as e:
                print(f"Error parsing {rel}: {e}")
