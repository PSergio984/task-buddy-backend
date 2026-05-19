import os
import sys

backend_dir = os.environ.get("BACKEND_DIR", os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(backend_dir):
    raise RuntimeError(f"Backend directory does not exist: {backend_dir}")
sys.path.insert(0, backend_dir)

try:
    from app.main import app
    for route in app.routes:
        methods = getattr(route, 'methods', set())
        path = getattr(route, 'path', getattr(route, 'name', str(route)))
        print(f"{list(methods)} {path}")
except Exception:
    import traceback
    traceback.print_exc()
