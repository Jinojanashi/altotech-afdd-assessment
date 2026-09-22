FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY apps/simulator ./apps/simulator
COPY data/candidate-starter-pack ./data/candidate-starter-pack
CMD ["python", "-m", "apps.simulator.main"]

