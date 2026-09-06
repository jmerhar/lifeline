# The application as one image: the API, the scheduler, the built interface, and the browser
# an interactive login runs in. One image and one published port means a deployment is a
# single container with a single directory to persist.

FROM node:22-alpine AS frontend
WORKDIR /build
# A registry can be supplied for a network that proxies npm; unset, the default is used.
ARG NPM_REGISTRY=""
COPY frontend/package.json frontend/package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci --loglevel=error
COPY frontend/ ./
RUN npm run build


FROM python:3.14-slim AS app

# Xvfb gives the headful browser a screen, x11vnc serves that screen, and the API bridges it
# to the browser tab. Chromium's own libraries come from `playwright install --with-deps`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Outside any one user's home, so the browsers installed here as root stay readable to
    # the unprivileged user the container runs as.
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    HOME=/home/app

WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install . \
    && python -m playwright install --with-deps chromium \
    # Playwright installs a separate headless shell beside the full browser. An interactive
    # login needs the full build, and driver.py asks for it headlessly too, so the shell is a
    # third of a gigabyte for a second Chromium nothing here launches. ffmpeg is for recording
    # video, which this never does.
    && rm -rf "$PLAYWRIGHT_BROWSERS_PATH"/chromium_headless_shell-* \
              "$PLAYWRIGHT_BROWSERS_PATH"/ffmpeg-* \
    && rm -rf /var/lib/apt/lists/*

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /build/dist ./static
COPY bin/entrypoint.sh /usr/local/bin/entrypoint.sh

# Runs as an unprivileged user so that everything it writes into the mounted data directory
# is owned by a real account on the host rather than by root.
RUN mkdir -p /data /home/app && chown -R 1000:1000 /data /home/app
USER 1000:1000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "lifeline.healthcheck"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
