FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV NPM_CONFIG_UPDATE_NOTIFIER=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

ARG CODEX_NPM_PACKAGES="@openai/codex codex-cli"

RUN set -eux; \
    installed=0; \
    for pkg in ${CODEX_NPM_PACKAGES}; do \
        if npm install -g "${pkg}"; then \
            installed=1; \
            break; \
        fi; \
    done; \
    if [ "${installed}" -ne 1 ]; then \
        echo "Failed to install Codex CLI from configured package candidates: ${CODEX_NPM_PACKAGES}" >&2; \
        exit 1; \
    fi; \
    if ! command -v codex >/dev/null 2>&1 && command -v codex-cli >/dev/null 2>&1; then \
        ln -sf "$(command -v codex-cli)" /usr/local/bin/codex; \
    fi; \
    command -v codex >/dev/null 2>&1; \
    codex --version

WORKDIR /task

CMD ["sleep", "infinity"]
