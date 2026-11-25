# ORBIS build image for the AnyPS5 fork (Ubuntu 24.04, GCC, CMake, Ninja, lavapipe).
# Package list from upstream docs/dev/BUILD.md and release.yml (see FORGEMESH.md in the fork).
FROM docker.io/library/ubuntu:24.04@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates build-essential git cmake ninja-build ccache python3 \
      libx11-dev libxext-dev libxrandr-dev libwayland-dev libxkbcommon-dev libegl-dev libdecor-0-dev \
      libpipewire-0.3-dev libpulse-dev libasound2-dev libvulkan1 mesa-vulkan-drivers vulkan-tools locales \
 && locale-gen en_US.UTF-8 \
 && rm -rf /var/lib/apt/lists/*
# Ubuntu images already ship user 'ubuntu' with uid 1000.
ENV HOME=/home/ubuntu CCACHE_DIR=/tmp/ccache
USER 1000:1000
WORKDIR /work
LABEL org.opencontainers.image.source="https://github.com/ForgeMesh-io/nexus" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.description="ForgeMesh ORBIS build environment for AnyPS5"
