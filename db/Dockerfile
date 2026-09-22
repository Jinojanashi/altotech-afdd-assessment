FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY alembic.ini ./
COPY db/migrations ./db/migrations
COPY data/candidate-starter-pack/building-and-equipment ./data/candidate-starter-pack/building-and-equipment
CMD ["alembic", "upgrade", "head"]
