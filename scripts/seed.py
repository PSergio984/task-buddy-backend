"""
Standalone seed script — no app imports required.
Uses DATABASE_URL env var + psycopg2 directly.
"""

import logging
import os
import random
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

# psycopg2 wants postgresql://, not postgres://
CONN_STR = DATABASE_URL.replace("postgres://", "postgresql://", 1)


def seed():  # noqa: C901
    env = os.environ.get("APP_ENV", "development").lower()
    seed_allowed = os.environ.get("SEED_ALLOWED", "").lower()
    if env == "production" and seed_allowed != "true":
        logger.error(
            "Seed script blocked in production. "
            "Set SEED_ALLOWED=true to override (destructive — wipes demo user data)."
        )
        raise SystemExit(1)

    conn = psycopg2.connect(CONN_STR)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # ── Demo user ──────────────────────────────────────────────
        cur.execute("SELECT id FROM tbl_users WHERE email = %s", ("demo@example.com",))
        row = cur.fetchone()

        if not row:
            logger.info("Creating demo user...")
            hashed = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
            cur.execute(
                """
                INSERT INTO tbl_users (username, email, password, confirmed)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                ("demouser", "demo@example.com", hashed, True),
            )
            row2 = cur.fetchone()
            if row2 is None:
                raise RuntimeError("INSERT tbl_users RETURNING id returned nothing — check schema")
            user_id = row2["id"]
        else:
            user_id = row["id"]
            logger.info("Demo user found. Purging existing seed data...")
            cur.execute(
                """
                DELETE FROM tbl_task_tags
                WHERE task_id IN (SELECT id FROM tbl_tasks WHERE user_id = %s)
                """,
                (user_id,),
            )
            cur.execute("DELETE FROM tbl_subtasks WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM tbl_tasks WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM tbl_tags WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM tbl_projects WHERE user_id = %s", (user_id,))

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
            cur.execute(
                "INSERT INTO tbl_projects (name, color, user_id) VALUES (%s, %s, %s) RETURNING id",
                (name, color, user_id),
            )
            proj_row = cur.fetchone()
            if proj_row is None:
                raise RuntimeError(f"INSERT tbl_projects RETURNING id returned nothing for '{name}'")
            project_ids.append(proj_row["id"])

        # ── Tags ───────────────────────────────────────────────────
        logger.info("Creating tags...")
        tag_names = ["Critical", "Research", "Review", "Development", "Outreach", "Wellness"]
        tag_ids = []
        for name in tag_names:
            cur.execute(
                "INSERT INTO tbl_tags (name, user_id) VALUES (%s, %s) RETURNING id",
                (name, user_id),
            )
            tag_row = cur.fetchone()
            if tag_row is None:
                raise RuntimeError(f"INSERT tbl_tags RETURNING id returned nothing for '{name}'")
            tag_ids.append(tag_row["id"])

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
            cur.execute(
                """
                INSERT INTO tbl_tasks
                    (title, description, user_id, project_id, priority, due_date, completed)
                VALUES (%s, %s, %s, %s, %s::taskpriority, %s, %s)
                RETURNING id
                """,
                (title, desc, user_id, project_ids[p_idx], priority, due, completed),
            )
            task_row = cur.fetchone()
            if task_row is None:
                raise RuntimeError(f"INSERT tbl_tasks RETURNING id returned nothing for '{title}' — check schema and enum values")
            task_ids.append(task_row["id"])

        # Assign 0-2 random tags per task
        for task_id in task_ids:
            n = random.randint(0, 2)
            for tag_id in random.sample(tag_ids, n):
                cur.execute(
                    "INSERT INTO tbl_task_tags (task_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (task_id, tag_id),
                )

        # ── Subtasks ───────────────────────────────────────────────
        logger.info("Creating subtasks...")
        subtask_data = [
            (task_ids[0],  ["Review AWS billing", "Identify idle EC2 instances", "Draft cost-saving proposal"]),
            (task_ids[6],  ["Audit color palette", "Update typography scale", "Export SVG assets"]),
            (task_ids[12], ["Draft email templates", "Segment user list", "Configure tracking links"]),
            (task_ids[18], ["Watch conference talks", "Implement demo project", "Write summary notes"]),
        ]
        for t_id, titles in subtask_data:
            for title in titles:
                cur.execute(
                    """
                    INSERT INTO tbl_subtasks (title, task_id, user_id, completed)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (title, t_id, user_id, random.random() < 0.4),
                )

        conn.commit()
        logger.info(f"Seeding complete. {len(task_ids)} tasks, {len(project_ids)} projects.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    seed()
