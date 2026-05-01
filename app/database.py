import databases
import sqlalchemy

from app.config import config

metadata = sqlalchemy.MetaData()

tbl_task = sqlalchemy.Table(
    "tbl_tasks",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("completed", sqlalchemy.Boolean, default=False),
)

tbl_subtask = sqlalchemy.Table(
    "tbl_subtasks",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("task_id", sqlalchemy.ForeignKey("tbl_tasks.id"), nullable=False),
    sqlalchemy.Column("title", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("completed", sqlalchemy.Boolean, default=False),
)

engine = sqlalchemy.create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})

metadata.create_all(engine)

database = databases.Database(config.DATABASE_URL, force_rollback=config.DB_FORCE_ROLL_BACK)
