import os
import re
from pathlib import Path

frontend_dir = str(Path(os.environ.get("FRONTEND_DIR", Path.home() / "OneDrive" / "Documents" / "GitHub" / "task-buddy-frontend")))
test_pattern = re.compile(r'(?:it|test)\s*\(\s*["\'`](.*?)["\'`]')

print("Frontend tests:")
for root, _, files in os.walk(frontend_dir):
    if "node_modules" in root or ".next" in root or "dist" in root:
        continue
    for file in files:
        if file.endswith((".test.tsx", ".test.ts", ".spec.tsx", ".spec.ts")):
            filepath = os.path.join(root, file)
            rel = os.path.relpath(filepath, frontend_dir).replace("\\", "/")
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
                matches = test_pattern.findall(content)
                if matches:
                    print(f"\n{rel}:")
                    for m in matches:
                        print(f"  - {m}")
                else:
                    print(f"\n{rel} (no matches):")
            except Exception as e:
                print(f"Error reading {rel}: {e}")
