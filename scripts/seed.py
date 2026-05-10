"""
Standalone seed script — no app imports required.
Uses SQLAlchemy to support both SQLite (local/test) and PostgreSQL (prod).
"""

import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# Load .env if it exists
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Must match security.py exactly so seed passwords pass verify_password()
pwd_context = CryptContext(schemes=["argon2", "pbkdf2_sha256"], deprecated="auto")


def get_database_url():
    """Matches the logic in app/config.py for environment-prefixed variables."""
    state = os.environ.get("ENV_STATE", "DEV").upper()

    # 1. State-specific (e.g., DEV_DATABASE_URL, TEST_DATABASE_URL)
    if url := os.environ.get(f"{state}_DATABASE_URL"):
        return url

    # 2. Production prefix (standard for Render if not state-prefixed)
    if url := os.environ.get("PROD_DATABASE_URL"):
        return url

    # 3. Direct DATABASE_URL
    if url := os.environ.get("DATABASE_URL"):
        return url

    # 4. Fallback for TEST state matching app/config.py
    if state == "TEST":
        return "sqlite:///./test.db"

    return None


DATABASE_URL = get_database_url()
if not DATABASE_URL:
    logger.error("Missing DATABASE_URL. Please set DATABASE_URL, DEV_DATABASE_URL, or PROD_DATABASE_URL.")
    sys.exit(1)

# Handle postgres:// vs postgresql:// for SQLAlchemy
CONN_STR = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def seed():  # noqa: C901
    env = os.environ.get("APP_ENV", os.environ.get("ENV_STATE", "development")).lower()
    seed_allowed = os.environ.get("SEED_ALLOWED", "").lower()

    if env == "production" and seed_allowed != "true":
        logger.error(
            "Seed script blocked in production. "
            "Set SEED_ALLOWED=true to override (destructive — wipes demo user data)."
        )
        sys.exit(1)

    engine = create_engine(CONN_STR)
    is_pg = "postgresql" in str(engine.url)

    # Parameter marker and type cast differences
    # PG uses :param, SQLite also supports :param via SQLAlchemy text()
    # But PG enums need casting
    priority_type = "::taskpriority" if is_pg else ""

    with engine.begin() as conn:
        try:
            # ── Demo user ──────────────────────────────────────────────
            res = conn.execute(text("SELECT id FROM tbl_users WHERE email = :email"), {"email": "demo@example.com"})
            row = res.mappings().fetchone()

            if not row:
                logger.info("Creating demo user...")
                hashed = pwd_context.hash("password123")
                res = conn.execute(
                    text("""
                    INSERT INTO tbl_users (username, email, password, confirmed)
                    VALUES (:username, :email, :password, :confirmed)
                    RETURNING id
                    """),
                    {"username": "demouser", "email": "demo@example.com", "password": hashed, "confirmed": True}
                )
                row2 = res.mappings().fetchone()
                if row2 is None:
                    raise RuntimeError("INSERT tbl_users RETURNING id returned nothing")
                user_id = row2["id"]
            else:
                user_id = row["id"]
                logger.info(f"Demo user found (ID: {user_id}). Purging existing seed data...")

                # SQLite doesn't support complex subqueries in DELETE as easily, but this is standard SQL
                conn.execute(
                    text("DELETE FROM tbl_task_tags WHERE task_id IN (SELECT id FROM tbl_tasks WHERE user_id = :uid)"),
                    {"uid": user_id}
                )
                conn.execute(text("DELETE FROM tbl_subtasks WHERE user_id = :uid"), {"uid": user_id})
                conn.execute(text("DELETE FROM tbl_tasks WHERE user_id = :uid"), {"uid": user_id})
                conn.execute(text("DELETE FROM tbl_tags WHERE user_id = :uid"), {"uid": user_id})
                conn.execute(text("DELETE FROM tbl_projects WHERE user_id = :uid"), {"uid": user_id})

            # ── Projects ───────────────────────────────────────────────
            logger.info("Creating projects...")
            project_data = [
                ("Strategic Ops",     "#2563eb"),
                ("Product Design",    "#8b5cf6"),
                ("Growth & Marketing","#10b981"),
                ("Personal Mastery",  "#f59e0b"),
            ]
            project_ids = []
            for name, color in project_data:
                res = conn.execute(
                    text("INSERT INTO tbl_projects (name, color, user_id) VALUES (:name, :color, :user_id) RETURNING id"),
                    {"name": name, "color": color, "user_id": user_id}
                )
                p_row = res.mappings().fetchone()
                if p_row:
                    project_ids.append(p_row["id"])

            # ── Tags ───────────────────────────────────────────────────
            logger.info("Creating tags...")
            tag_names = ["Critical", "Research", "Review", "Development", "Outreach", "Wellness"]
            tag_ids = []
            for name in tag_names:
                res = conn.execute(
                    text("INSERT INTO tbl_tags (name, user_id) VALUES (:name, :user_id) RETURNING id"),
                    {"name": name, "user_id": user_id}
                )
                t_row = res.mappings().fetchone()
                if t_row:
                    tag_ids.append(t_row["id"])

            # ── Tasks ──────────────────────────────────────────────────
            logger.info("Creating 24 tasks...")
            now = datetime.now(timezone.utc)

            task_templates = [
                ("Finalize Q3 Infrastructure Audit",  "Deep dive into cloud costs and performance bottlenecks.", 0, "HIGH",   2),
                ("Review Q4 Roadmap with Stakeholders","Alignment session for upcoming features.",                0, "MEDIUM", 5),
                ("Compliance Certification Renewal",   "Annual SOC2 compliance documentation review.",            0, "HIGH",   10),
                ("Quarterly Financial Recap",          "Prepare charts for the board meeting.",                   0, "MEDIUM", 3),
                ("Legacy API Deprecation Plan",        "Phase out v1 endpoints safely.",                          0, "LOW",    15),
                ("Update Onboarding Documentation",    "Refresh the engineering wiki.",                           0, "LOW",    7),
                ("UI Brand System Refresh",            "Consolidate design tokens for v2.0.",                     1, "HIGH",   1),
                ("User Interview Synthesis",           "Extract key pain points from the last 10 sessions.",      1, "MEDIUM", 4),
                ("Accessibility Audit - Main Flow",    "Ensure WCAG 2.1 compliance on Dashboard.",                1, "HIGH",   6),
                ("High-Fidelity Mobile Mockups",       "Finalize layouts for iOS/Android apps.",                  1, "MEDIUM", 8),
                ("Prototyping Interaction Hooks",      "Implement micro-interactions for sidebar.",               1, "LOW",    2),
                ("Design Critique: Dark Mode",         "Gather feedback on new palette.",                         1, "LOW",    3),
                ("Launch Early Access Campaign",       "Email sequence for top 500 users.",                       2, "HIGH",   0),
                ("SEO Content Strategy Audit",         "Keyword research for upcoming blog series.",              2, "MEDIUM", 12),
                ("A/B Test Landing Page Hero",         "Compare 'Effortless' vs 'Strategic' messaging.",          2, "HIGH",   2),
                ("Affiliate Program Outreach",         "Identify 20 key influencers in productivity space.",      2, "MEDIUM", 9),
                ("Social Media Visual Assets",         "Graphics for Twitter/LinkedIn launch.",                   2, "LOW",    5),
                ("Analyze Conversion Funnel",          "Identify drop-off points in registration.",               2, "MEDIUM", 1),
                ("Advanced React Patterns Study",      "Deep dive into Server Components and Actions.",           3, "HIGH",   4),
                ("Weekly Retrospective",               "Reflect on wins and alignment with core goals.",          3, "MEDIUM", 0),
                ("Curate Professional Portfolio",      "Update project case studies.",                            3, "MEDIUM", 20),
                ("Daily Deep Work Session",            "2 hours of focused output without distractions.",         3, "HIGH",   0),
                ("Read: 'Building a Second Brain'",    "Apply PARA method to current notes.",                     3, "LOW",    30),
                ("Setup Automated Backup Logic",       "Secure local environment data.",                          3, "LOW",    10),
            ]

            task_ids = []
            for title, desc, p_idx, priority, due_days in task_templates:
                due = now + timedelta(days=due_days) if due_days >= 0 else None
                completed = random.random() < 0.2

                insert_sql = f"""
                INSERT INTO tbl_tasks
                    (title, description, user_id, project_id, priority, due_date, completed)
                VALUES (:title, :desc, :user_id, :project_id, :priority{priority_type}, :due_date, :completed)
                RETURNING id
                """

                res = conn.execute(
                    text(insert_sql),
                    {
                        "title": title, "desc": desc, "user_id": user_id,
                        "project_id": project_ids[p_idx], "priority": priority,
                        "due_date": due, "completed": completed
                    }
                )
                task_row = res.mappings().fetchone()
                if task_row:
                    task_ids.append(task_row["id"])

            # Assign random tags
            for task_id in task_ids:
                n = random.randint(0, 2)
                for tag_id in random.sample(tag_ids, n):
                    try:
                        conn.execute(
                            text("INSERT INTO tbl_task_tags (task_id, tag_id) VALUES (:t_id, :tg_id)"),
                            {"t_id": task_id, "tg_id": tag_id}
                        )
                    except IntegrityError:
                        pass # Duplicate tag

            # ── Subtasks ───────────────────────────────────────────────
            logger.info("Creating subtasks...")
            subtask_data = [
                (task_ids[0],  ["Review AWS billing", "Identify idle EC2 instances", "Draft cost-saving proposal"]),
                (task_ids[6],  ["Audit color palette", "Update typography scale", "Export SVG assets"]),
                (task_ids[12], ["Draft email templates", "Segment user list", "Configure tracking links"]),
                (task_ids[18], ["Watch conference talks", "Implement demo project", "Write summary notes"]),
            ]
            for t_id, titles in subtask_data:
                for st_title in titles:
                    conn.execute(
                        text("""
                        INSERT INTO tbl_subtasks (title, task_id, user_id, completed)
                        VALUES (:title, :t_id, :u_id, :completed)
                        """),
                        {"title": st_title, "t_id": t_id, "u_id": user_id, "completed": random.random() < 0.4}
                    )

            logger.info(f"Seeding complete. {len(task_ids)} tasks, {len(project_ids)} projects.")

        except Exception:
            logger.exception("Seeding failed")
            raise


if __name__ == "__main__":
    seed()

