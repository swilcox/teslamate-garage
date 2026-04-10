FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ARG APP_VERSION=0.0.0+unknown
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG REPO_URL=https://github.com/swilcox/teslamate-garage

LABEL org.opencontainers.image.version=$APP_VERSION \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.source=$REPO_URL \
      org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY garage_door.py .

ENV APP_VERSION=$APP_VERSION

CMD ["uv", "run", "--no-sync", "python", "garage_door.py"]
