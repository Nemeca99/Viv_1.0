FROM aios-router-continuity-build:20261118 AS builder
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo test --locked --offline
RUN cargo build --release --locked --offline
FROM aios-router-mcp-v3-postal-candidate:0.3.0
COPY --from=builder --chown=10001:10001 /build/target/release/aios-router-mcp-v3-postal-candidate /usr/local/bin/aios-router-mcp
