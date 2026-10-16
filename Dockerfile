# One image for every Lattice role (KTD12). Compose and Render choose the role by command:
#   lattice api | lattice mcp | lattice worker <role> | lattice seed --if-empty | lattice check
# There is no ENTRYPOINT, so a platform's start or pre-deploy command is the whole command.

# --- build: resolve dependencies into a venv --------------------------------------------------
FROM python:3.11-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so code edits don't invalidate the dependency layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- runtime: the venv, the replay recordings, and an unprivileged user ----------------------
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LATTICE_RECORDINGS_DIR=/app/recordings

RUN useradd --create-home --uid 10001 lattice
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY recordings ./recordings
USER lattice

EXPOSE 8080 8000
CMD ["lattice", "check"]
