from pathlib import Path

# Make `import api.foo` load modules from the `app/` package directory.
# This shim keeps tests and external imports that expect a top-level
# `api` package working without changing existing code.
__path__ = [str(Path(__file__).resolve().parent.parent.joinpath("app"))]
