FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9 AS builder
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked

FROM aios-body-runtime:0.2.8-architect-runtime-permission@sha256:b1d7837fc4a78f60031bb5b0c3d68e639ecb786fa88b41776a5b64111f2a9634
USER root
RUN mkdir -p /var/lib/aios-router && chown 10001:10001 /var/lib/aios-router
COPY --from=builder --chown=10001:10001 /build/target/release/aios-router-mcp-v1-candidate /usr/local/bin/aios-router-mcp
ENV AIOS_ROUTER_DB=/var/lib/aios-router/router.sqlite3
ENV AIOS_BODY_RECEIPTS_DIR=/var/lib/aios-body-receipts
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/aios-router-mcp"]
