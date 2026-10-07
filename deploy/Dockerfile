# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

FROM base AS build
WORKDIR /app
RUN pip install --upgrade pip build
COPY pyproject.toml ./
COPY src ./src
RUN pip wheel --no-deps --wheel-dir /wheels . && pip wheel --wheel-dir /wheels .

FROM base AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links /wheels writing-assistant && rm -rf /wheels
USER app
ENTRYPOINT ["python", "-m", "writing_assistant"]
