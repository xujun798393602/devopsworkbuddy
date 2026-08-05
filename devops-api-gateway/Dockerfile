ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
USER root
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1 HOME=/tmp
WORKDIR /app
COPY wheelhouse/linux-x86_64-cp312 /wheelhouse
COPY devops-api-gateway/pyproject.toml ./
COPY devops-api-gateway/src ./src
RUN python -m pip install --no-index --find-links=/wheelhouse setuptools gunicorn flask \
    && python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir /tmp/gateway-wheel . \
    && GATEWAY_WHEEL=$(python -c "from pathlib import Path; paths=list(Path('/tmp/gateway-wheel').glob('devops_api_gateway-*.whl')); assert len(paths) == 1, f'expected one gateway wheel, found {len(paths)}'; print(paths[0])") \
    && python -m pip install --no-index --find-links=/wheelhouse "$GATEWAY_WHEEL" \
    && python -m compileall -q src \
    && python -m pip check \
    && chown -R 10001:10001 /app
ENV APP_ENV=container
USER 10001:10001
EXPOSE 18180
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18180/health', timeout=2)"]
CMD ["gunicorn", "--bind=0.0.0.0:18180", "--workers=2", "--access-logfile=-", "gateway.wsgi:application"]
