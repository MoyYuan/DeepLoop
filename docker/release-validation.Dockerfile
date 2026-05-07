# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.11-slim

FROM ${PYTHON_IMAGE} AS source
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/deeploop
COPY . /opt/deeploop

FROM source AS artifact-builder
RUN python -m pip install --upgrade pip build \
    && python -m build

FROM ${PYTHON_IMAGE} AS runtime-base
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/deeploop \
    PATH=/home/deeploop/.local/bin:${PATH} \
    DEEPLOOP_WORKSPACE_ROOT=/home/deeploop/Workspaces
RUN useradd --create-home --home-dir /home/deeploop --shell /bin/bash deeploop
COPY --from=artifact-builder /opt/deeploop /opt/deeploop
RUN mkdir -p /home/deeploop/Workspaces \
    && chown -R deeploop:deeploop /home/deeploop /opt/deeploop
WORKDIR /home/deeploop
USER deeploop
RUN python -m pip install --upgrade pip

FROM runtime-base AS artifact-validation
RUN python -m pip install /opt/deeploop/dist/*.whl \
    && python /opt/deeploop/scripts/release/in_container_smoke.py \
        --repo-root /opt/deeploop \
        --install-source wheel

FROM runtime-base AS pypi-validation
ARG DEEPLOOP_INSTALL_SPEC=deeploop
RUN python -m pip install "${DEEPLOOP_INSTALL_SPEC}" \
    && python /opt/deeploop/scripts/release/in_container_smoke.py \
        --repo-root /opt/deeploop \
        --install-source pypi \
        --install-spec "${DEEPLOOP_INSTALL_SPEC}"
