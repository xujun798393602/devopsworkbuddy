# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ARG PYTHON_IMPLEMENTATION=cp312
ARG PYTHON_VERSION_EXPECTED=3.12
ARG WHEELHOUSE_DIR=wheelhouse/linux-x86_64-cp312
ARG LOCK_FILE=constraints/cp312-linux-x86_64.txt
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INDEX=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY ${WHEELHOUSE_DIR} /wheelhouse
COPY ${LOCK_FILE} /constraints/locked.txt
COPY scripts/verify-wheelhouse.py /opt/wkdevops/verify-wheelhouse.py
# Filename scan runs before pip executes; detailed packaging tag/hash validation follows.
RUN python -c "from pathlib import Path; implementation='${PYTHON_IMPLEMENTATION}'; forbidden=('win','macosx','aarch64','arm64','i686','i386','ppc','s390x'); wheels=[path.name.lower() for path in Path('/wheelhouse').glob('*.whl')]; invalid=[name for name in wheels if any(part in name for part in forbidden) or ('cp312' in name and implementation != 'cp312') or ('cp313' in name and implementation != 'cp313')]; assert wheels, 'wheelhouse is empty'; assert not invalid, invalid" \
    && python -c "import platform,sys; expected='${PYTHON_VERSION_EXPECTED}'; actual=platform.python_version(); assert actual.startswith(expected + '.') or actual == expected, (expected, actual); assert sys.implementation.cache_tag == 'cpython-' + '${PYTHON_IMPLEMENTATION}'.removeprefix('cp')" \
    && python -m pip install --no-index --find-links=/wheelhouse packaging \
    && python /opt/wkdevops/verify-wheelhouse.py /wheelhouse --implementation "${PYTHON_IMPLEMENTATION}" --sha256sums /wheelhouse/SHA256SUMS >/dev/null \
    && python -m pip install --no-index --find-links=/wheelhouse -r /constraints/locked.txt \
    && python -m pip check
COPY project-service/pyproject.toml project-service/alembic.ini ./
COPY project-service/migrations ./migrations
COPY project-service/src ./src
RUN python -m pip install --no-index --no-deps --no-build-isolation . \
    && python -m compileall -q /app/src /app/migrations \
    && python -m pip check
USER app
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=2", "--access-logfile=-", "project_service.app:create_app()"]
