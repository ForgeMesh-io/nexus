# NEXUS development image: base + test and lint tools for ForgeMesh itself.
# BASE must be a digest-pinned reference to the base image built from base.Dockerfile.
ARG BASE
FROM ${BASE}

USER root
ARG ACTIONLINT_VERSION=1.7.7
ARG ACTIONLINT_SHA256=023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757
RUN apt-get update \
 && apt-get install -y --no-install-recommends shellcheck curl \
 && curl -fsSL -o /tmp/al.tgz "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
 && echo "${ACTIONLINT_SHA256}  /tmp/al.tgz" | sha256sum -c - \
 && tar -xzf /tmp/al.tgz -C /usr/local/bin actionlint \
 && rm /tmp/al.tgz \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
USER 1000:1000
LABEL org.opencontainers.image.description="ForgeMesh NEXUS development environment"
