from app.main import app

for route in app.routes:
    # We want APIRoute objects which have methods, path, and endpoint
    if hasattr(route, "methods") and hasattr(route, "path"):
        methods = ", ".join(route.methods)
        print(f"{methods:12} {route.path:40} -> {route.name}")
