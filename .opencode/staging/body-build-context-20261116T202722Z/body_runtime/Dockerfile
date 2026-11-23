FROM rust:1.90.0-slim-bookworm@sha256:64232e656c058f4468e8d024e990acff04f0fd5a5c0a88a574dc37773d7325c9 AS build
WORKDIR /src/body_runtime
COPY body_runtime/Cargo.toml body_runtime/Cargo.lock ./
COPY body_runtime/core_manifest.json ./core_manifest.json
COPY body_runtime/architect_runtime_permission.json ./architect_runtime_permission.json
COPY body_runtime/src ./src
COPY local_security_core/src/body_authority.rs /src/local_security_core/src/body_authority.rs
RUN cargo test --locked && cargo build --release --locked

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
RUN useradd --system --uid 10001 --no-create-home body
COPY --from=build /src/body_runtime/target/release/aios-body-runtime /usr/local/bin/aios-body-runtime
COPY body_runtime/requirements-body.lock /tmp/requirements-body.lock
RUN python -m pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements-body.lock \
    && rm /tmp/requirements-body.lock
WORKDIR /opt/aios_rebuild
COPY body_runtime/core_manifest.json body_runtime/kernel_probe.py ./body_runtime/
COPY backup_core/*.py ./backup_core/
COPY carma_core/*.py ./carma_core/
COPY consciousness_core/*.py ./consciousness_core/
COPY data_core/*.py ./data_core/
COPY data_core/config/aios_config.json ./data_core/config/aios_config.json
COPY dream_core/*.py ./dream_core/
COPY enterprise_core/*.py ./enterprise_core/
COPY fractal_core/*.py ./fractal_core/
COPY game_core/*.py ./game_core/
COPY infra_core/*.py ./infra_core/
COPY luna_core/*.py ./luna_core/
COPY marketplace_core/*.py ./marketplace_core/
COPY music_core/*.py ./music_core/
COPY privacy_core/*.py ./privacy_core/
COPY privacy_core/privacy_config.json ./privacy_core/privacy_config.json
COPY rag_core/*.py ./rag_core/
COPY security_core/*.py ./security_core/
COPY streamlit_core/streamlit_core.py ./streamlit_core/
COPY streamlit_core/core/*.py ./streamlit_core/core/
COPY support_core/*.py ./support_core/
COPY support_core/core/*.py ./support_core/core/
COPY template_core/*.py ./template_core/
COPY utils_core/ ./utils_core/
COPY main_core/*.py ./main_core/
RUN mkdir -p ./data_core/FractalCache ./data_core/log ./dream_core/state \
    ./memory ./marketplace_core/config ./music_core/config ./music_core/music_library \
    ./template_core/config
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    AIOS_WORKSPACE_ROOT=/opt/aios_rebuild \
    AIOS_ROOT=/opt/aios_rebuild \
    AIOS_PYTHON_ENV_PATH=/usr/local/bin \
    AIOS_LOG_DIR=/tmp/aios/log \
    AIOS_DEBUG_DIR=/tmp/aios/debug
USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python", "-u", "/opt/aios_rebuild/body_runtime/kernel_probe.py"]
