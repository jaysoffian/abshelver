FROM alpine:edge AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/usr/local/share/uv-python \
    UV_PYTHON_BIN_DIR=/usr/local/bin
WORKDIR /app
RUN uv python install 3.14
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM alpine:edge
RUN apk add --no-cache ffmpeg
WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app/.venv /app/.venv
COPY abshelver/ abshelver/
RUN printf '#!/bin/sh\nexec python -m abshelver.cli "$@"\n' > /usr/local/bin/abshelver \
    && chmod +x /usr/local/bin/abshelver
ENV PATH="/app/.venv/bin:$PATH" \
    ABSHELVER_IMPORT_DIR=/downloads \
    ABSHELVER_LIBRARY_DIR=/audiobooks
EXPOSE 8556
CMD ["uvicorn", "abshelver.app:app", "--host", "0.0.0.0", "--port", "8556"]

ARG GIT_COMMIT=unknown
RUN printf '%s' "$GIT_COMMIT" > /app/VERSION
LABEL org.opencontainers.image.revision="$GIT_COMMIT" \
      org.opencontainers.image.title="abshelver"
