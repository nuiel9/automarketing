# Build from the REPO ROOT, not backend/ — strategy.yaml lives one level
# above backend/ (backend/app/config.py's default STRATEGY_PATH points at it
# via a relative "./strategy.yaml", resolved from the container's WORKDIR).
# A backend/-only context can't see it, so:
#
#   docker build -f backend/Dockerfile -t automarketing-backend .
#
# NOT `docker build backend` — that context lacks strategy.yaml and the
# COPY below will fail. cloudbuild.yaml (repo root) builds this the same way.
FROM python:3.12-slim
WORKDIR /app

# Install dependencies before copying source so this layer only rebuilds
# when pyproject.toml changes, not on every code edit.
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY strategy.yaml ./strategy.yaml

# Default strategy_path ("./strategy.yaml", resolved from process CWD) already
# matches where the file lands above; set explicitly so the image is correct
# even if config.py's default ever changes.
ENV STRATEGY_PATH=./strategy.yaml
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
