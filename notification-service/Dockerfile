ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1 HOME=/tmp
WORKDIR /app
COPY wheelhouse/linux-x86_64-cp312 /wheelhouse
COPY notification-service/pyproject.toml notification-service/alembic.ini ./
COPY notification-service/migrations ./migrations
COPY notification-service/src ./src
RUN python -m pip install --no-index --find-links=/wheelhouse setuptools alembic sqlalchemy psycopg psycopg-binary gunicorn \
    && python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir /tmp/service-wheel . \
    && SERVICE_WHEEL=$(python -c "from pathlib import Path; paths=list(Path('/tmp/service-wheel').glob('notification_service-*.whl')); assert len(paths) == 1, f'expected one service wheel, found {len(paths)}'; print(paths[0])") \
    && python -m pip install --no-index --find-links=/wheelhouse "$SERVICE_WHEEL" \
    && python -m compileall -q src migrations \
    && python -m pip check \
    && chown -R 10001:10001 /app
ENV APP_ENV=container
USER 10001:10001
EXPOSE 18170
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18170/ready', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:18170", "--workers=2", "--access-logfile=-", "notification_service.app:create_app()"]
