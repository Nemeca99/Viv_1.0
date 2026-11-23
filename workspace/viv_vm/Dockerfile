# Viv's workshop: Rust toolchain (pinned) plus Python 3.12 (pinned). Built from local images only; no network at build time.
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS py
FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9
COPY --from=py /usr/local/bin/python3.12 /usr/local/bin/python3.12
COPY --from=py /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=py /usr/local/lib/libpython3.12.so.1.0 /usr/local/lib/libpython3.12.so.1.0
RUN ln -s /usr/local/bin/python3.12 /usr/local/bin/python3 && ln -s /usr/local/bin/python3.12 /usr/local/bin/python && ldconfig
RUN useradd --create-home --uid 10001 viv
ENV HOME=/home/viv CARGO_HOME=/home/viv/.cargo RUSTUP_HOME=/usr/local/rustup PATH=/usr/local/cargo/bin:/usr/local/bin:/usr/bin:/bin PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
WORKDIR /work
CMD ["sleep", "infinity"]
