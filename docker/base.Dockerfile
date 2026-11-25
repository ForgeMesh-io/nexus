# ForgeMesh base image: git, Rust tooling and the legacy Python client.
# Base pinned by digest; Python dependencies pinned by hash. Runs as a non-root user.
FROM docker.io/library/rust:1.96-slim-bookworm@sha256:e18a79fc84dfcfc3ab5ba72290398a644c135c97eaa881447fddc354ee4701a3 AS build
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY forgemesh/schemas ./forgemesh/schemas
RUN cargo build --locked --release

FROM docker.io/library/python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64

ARG SOURCE_DATE_EPOCH=0
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates jq \
 && rm -rf /var/lib/apt/lists/*

COPY docker/requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements.lock && rm /tmp/requirements.lock

COPY forgemesh /opt/forgemesh/forgemesh
COPY --from=build /build/target/release/forgemesh /usr/local/bin/forgemesh
ENV PYTHONPATH=/opt/forgemesh

RUN useradd --uid 1000 --create-home --home-dir /home/forge forge
USER 1000:1000
WORKDIR /work
LABEL org.opencontainers.image.source="https://github.com/ForgeMesh-io/nexus" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="ForgeMesh base environment"
CMD ["python", "-m", "forgemesh", "--help"]
