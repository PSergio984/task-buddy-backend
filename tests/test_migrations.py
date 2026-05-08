import os
import subprocess
import sys


def test_alembic_migrations():
    """
    Test that alembic migration can run against a clean database successfully.
    """
    db_file = "test_alembic.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = f"sqlite:///./{db_file}"
    env["ENV_STATE"] = "test"

    # Using sys.executable to ensure we use the same virtual environment
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15
        )
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"Alembic upgrade timed out after 15 seconds. Partial output: {e.output}") from e

    assert result.returncode == 0, f"Alembic upgrade failed: {result.stderr}"
    assert os.path.exists(db_file), "Database file was not created by alembic upgrade."
