# ForgeMesh base image: git, Python and the ForgeMesh tooling. Shared by every swarm image.
# Base pinned by digest; Python dependencies pinned by hash. Runs as a non-root user.
FROM docker.io/library/python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64

ARG SOURCE_DATE_EPOCH=0
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates jq \
 && rm -rf /var/lib/apt/lists/*

COPY docker/requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements.lock && rm /tmp/requirements.lock

COPY forgemesh /opt/forgemesh/forgemesh
ENV PYTHONPATH=/opt/forgemesh

RUN useradd --uid 1000 --create-home --home-dir /home/forge forge
USER 1000:1000
WORKDIR /work
LABEL org.opencontainers.image.source="https://github.com/ForgeMesh-io/nexus" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="ForgeMesh base environment"
CMD ["python", "-m", "forgemesh", "--help"]
