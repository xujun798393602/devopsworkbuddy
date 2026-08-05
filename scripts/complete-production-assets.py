"""Generate consistent service migration and container production assets."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {
    "requirement-service": ("requirement_service", "migrations", "DATABASE_URL", 18110),
    "tp-service": ("tp_service", "alembic", "DATABASE_URL", 18120),
    "td-service": ("td_service", "migrations", "DATABASE_URL", 18130),
    "iam-service": ("iam_service", "migrations", "DATABASE_URL", 18140),
    "workflow-service": ("workflow_service", "migrations", "DATABASE_URL", 18150),
    "audit-service": ("audit_service", "migrations", "DATABASE_URL", 18160),
    "notification-service": ("notification_service", "migrations", "DATABASE_URL", 18170),
}

INI = """[alembic]
script_location = {location}
prepend_sys_path = src
sqlalchemy.url = postgresql+psycopg://unused:unused@localhost/unused

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

ENV = '''"""Alembic environment for this service private database."""
from logging.config import fileConfig
from os import environ

from alembic import context
from sqlalchemy import engine_from_config, pool

from {package}.persistence import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
database_url = environ.get("{database_env}", "").strip()
if not database_url:
    raise RuntimeError("{database_env} is required for migrations")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {{}}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
'''

TEMPLATE = '''"""${message}"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "return None"}


def downgrade() -> None:
    ${downgrades if downgrades else "return None"}
'''

DOCKERFILE = """ARG PYTHON_IMAGE=devops-debug-backend:latest
FROM ${{PYTHON_IMAGE}}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1
WORKDIR /app
COPY wheelhouse /wheelhouse
COPY service/pyproject.toml service/alembic.ini ./
COPY service/{migration_dir} ./{migration_dir}
COPY service/src ./src
RUN python -m pip install --no-index --find-links=/wheelhouse alembic sqlalchemy psycopg psycopg-binary gunicorn \\
    && python -m pip install --no-index --no-deps . \\
    && python -m compileall -q src {migration_dir} \\
    && python -m pip check \\
    && addgroup --system wkdevops \\
    && adduser --system --uid 10001 --ingroup wkdevops wkdevops \\
    && chown -R wkdevops:wkdevops /app
USER 10001:10001
EXPOSE {port}
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:{port}", "--workers=2", "--access-logfile=-", "{package}.app:create_app()"]
"""

for service, (package, migration_dir, database_env, port) in SERVICES.items():
    service_root = ROOT / service
    migration_root = service_root / migration_dir
    migration_root.mkdir(parents=True, exist_ok=True)
    (service_root / "alembic.ini").write_text(INI.format(location=migration_dir), encoding="utf-8")
    (migration_root / "env.py").write_text(
        ENV.format(package=package, database_env=database_env), encoding="utf-8"
    )
    (migration_root / "script.py.mako").write_text(TEMPLATE, encoding="utf-8")
    (service_root / "Dockerfile").write_text(
        DOCKERFILE.format(package=package, migration_dir=migration_dir, port=port), encoding="utf-8"
    )
