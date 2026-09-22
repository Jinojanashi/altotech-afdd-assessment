FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/src
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir '.[dev]'
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY tests ./tests
COPY data/candidate-starter-pack/building-and-equipment ./data/candidate-starter-pack/building-and-equipment
CMD ["pytest", "-q"]
