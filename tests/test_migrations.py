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

    # 1. Upgrade to head
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"Alembic upgrade timed out. Partial output: {e.output}") from e

    assert result.returncode == 0, f"Alembic upgrade failed: {result.stderr}"
    assert os.path.exists(db_file), "Database file was not created by alembic upgrade."

    # 2. Downgrade to base
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"Alembic downgrade timed out. Partial output: {e.output}") from e

    assert result.returncode == 0, f"Alembic downgrade failed: {result.stderr}"

    # 3. Upgrade to head again to ensure everything is still consistent
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"Alembic secondary upgrade timed out. Partial output: {e.output}") from e

    assert result.returncode == 0, f"Alembic secondary upgrade failed: {result.stderr}"

    # Cleanup
    if os.path.exists(db_file):
        os.remove(db_file)
