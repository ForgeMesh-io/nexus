# VIE research image: base + Rust toolchain + Vulkan/SPIR-V tools. No game data, SDKs or keys.
ARG BASE
FROM docker.io/library/rust:1-slim-bookworm@sha256:bb875b0f8ce726053e259034848c471840e96bfe591fd52556178ae9a05e6126 AS rust

FROM ${BASE}
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config cmake ninja-build \
      vulkan-tools spirv-tools mesa-vulkan-drivers libvulkan-dev \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/home/forge/.cargo PATH=/usr/local/cargo/bin:$PATH
USER 1000:1000
LABEL org.opencontainers.image.description="ForgeMesh VIE research environment"
