# linux/amd64 is the tested initial architecture; do not imply arm64 support.
ARG PYTHON_IMAGE=python:3.14.2-slim-bookworm@sha256:34bb71a7de6dbecc839d8d6f8aaff8c4bf67ce01634764eaf929cb64d3ae315e
ARG DESTINATION_IMAGE=debian:bookworm-slim@sha256:ec31d744f83f4a73447ba045aaab9409997efe5cc706eca4890c1be36cc1606a
FROM rust:1.95.0-slim-bookworm@sha256:6f9e63259f12e1e599296f5ecfed2bae46de4af0ee0525dd8b89c046e236d5c5 AS native-source
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git pkg-config libssl-dev build-essential cmake protobuf-compiler \
    && rm -rf /var/lib/apt/lists/* \
    && curl --fail --location --retry 3 \
      https://github.com/atuinsh/atuin/archive/c58d2e993d05be423315f6ae3739e9ab3e45eea5.tar.gz \
      --output /tmp/atuin-source.tar.gz \
    && printf '%s  %s\n' 1d22939a2c1433730c1ed97ae74ee119d65941a5144e30189cd7e2d76ed46a45 /tmp/atuin-source.tar.gz | sha256sum --check --strict \
    && mkdir -p /opt/atuin \
    && tar -xzf /tmp/atuin-source.tar.gz -C /opt/atuin --strip-components=1 \
    && rm /tmp/atuin-source.tar.gz
WORKDIR /opt/atuin

FROM native-source AS native-build
ENV RUSTUP_TOOLCHAIN=1.95.0
COPY native-helper/Cargo.toml native-helper/build.rs /opt/atuin/crates/atuin-ssh-native/
COPY native-helper/src /opt/atuin/crates/atuin-ssh-native/src
COPY native-helper/Cargo.lock /opt/atuin/Cargo.lock
RUN --mount=type=cache,id=atuin-ssh-rust195-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=atuin-ssh-rust195-amd64-target,target=/opt/atuin/target,sharing=locked \
    cargo build --release --locked -p atuin-ssh-native \
    && mkdir -p /out \
    && install -m 0755 target/release/atuin-ssh-native /out/atuin-ssh-native

FROM native-build AS native-search-build
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY native-helper/patch_search.py /opt/atuin/crates/atuin-ssh-native/patch_search.py
RUN --mount=type=cache,id=atuin-ssh-rust195-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=atuin-ssh-rust195-amd64-target,target=/opt/atuin/target,sharing=locked \
    python3 crates/atuin-ssh-native/patch_search.py /opt/atuin \
    && cargo build --release --locked -p atuin-ssh-native \
    && cargo build --release --locked -p atuin --no-default-features --features client \
    && install -m 0755 target/release/atuin-ssh-native /out/atuin-ssh-native \
    && install -m 0755 target/release/atuin /out/atuin-ssh-search

FROM native-search-build AS benchmark-build
RUN --mount=type=cache,id=atuin-ssh-rust195-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=atuin-ssh-rust195-amd64-target,target=/opt/atuin/target,sharing=locked \
    cargo build --release --locked -p atuin-ssh-native --features benchmark --bin atuin-ssh-bench-seed \
    && install -m 0755 target/release/atuin-ssh-bench-seed /out/atuin-ssh-bench-seed

FROM ${PYTHON_IMAGE} AS foundation
ARG ATUIN_VERSION=18.24.1
ARG ATUIN_SHA256=fe03f652d6545a9d8795b3c2abb84bcddfe831e4b7effb0c2d191a0d70e498a0
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash openssh-client openssh-server ca-certificates curl git less nano \
      ncurses-term procps iproute2 tini tar xz-utils \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && curl --fail --location --retry 3 \
       "https://github.com/atuinsh/atuin/releases/download/v${ATUIN_VERSION}/atuin-x86_64-unknown-linux-musl.tar.gz" \
       --output /tmp/atuin.tar.gz \
    && printf '%s  %s\n' "${ATUIN_SHA256}" /tmp/atuin.tar.gz | sha256sum --check --strict \
    && tar -xzf /tmp/atuin.tar.gz -C /tmp \
    && install -m 0755 /tmp/atuin-x86_64-unknown-linux-musl/atuin /usr/local/bin/atuin \
    && rm -rf /tmp/atuin* \
    && mkdir -p /usr/share/atuin-ssh \
    && dpkg-query -W > /usr/share/atuin-ssh/debian-packages.txt

FROM foundation AS package-build
WORKDIR /build
COPY pyproject.toml requirements-build.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock
COPY src ./src
RUN python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels .

FROM foundation AS runtime
ARG HUB_USER=hubuser
ARG HUB_UID=1000
ARG HUB_GID=1000
COPY --from=native-search-build /out/atuin-ssh-native /usr/local/bin/atuin-ssh-native
COPY --from=native-search-build /out/atuin-ssh-search /usr/local/bin/atuin-ssh-search
COPY --from=native-source /opt/atuin/LICENSE /usr/share/licenses/atuin/LICENSE
RUN groupadd --gid "${HUB_GID}" "${HUB_USER}" \
    && useradd --uid "${HUB_UID}" --gid "${HUB_GID}" --create-home --shell /bin/bash "${HUB_USER}" \
    && usermod --password '*' "${HUB_USER}" \
    && mkdir -p /run/sshd /etc/atuin-ssh /state /run/atuin-ssh \
    && chmod 0700 /state
COPY --from=package-build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links /wheels atuin-ssh \
    && rm -rf /wheels
COPY config/atuin.toml /usr/share/atuin-ssh/config.toml
COPY docker/sshd_config /etc/ssh/sshd_config
COPY docker/hub.bash /etc/atuin-ssh/hub.bash
COPY docker/bash_profile /etc/skel/.bash_profile
COPY docker/entrypoint.sh /usr/local/sbin/atuin-ssh-entrypoint
COPY docker/restore.sh /usr/share/atuin-ssh/restore.sh
COPY docker/verify-restore.py /usr/share/atuin-ssh/verify-restore.py
RUN chmod 0755 /usr/local/sbin/atuin-ssh-entrypoint \
    && chmod 0644 /etc/atuin-ssh/hub.bash /etc/skel/.bash_profile \
    && printf '\n# Initialize local-only Atuin and onward SSH integration.\n. /etc/atuin-ssh/hub.bash\n' >> /etc/skel/.bashrc \
    && cp /etc/skel/.bash_profile "/home/${HUB_USER}/.bash_profile" \
    && cp /etc/skel/.bashrc "/home/${HUB_USER}/.bashrc" \
    && chown "${HUB_UID}:${HUB_GID}" "/home/${HUB_USER}/.bash_profile" "/home/${HUB_USER}/.bashrc"
ENV HUB_USER=${HUB_USER} ATUIN_HOME=/state/atuin ATUIN_CONFIG_DIR=/state/atuin \
    ATUIN_SSH_STATE_DIR=/state/bridge
LABEL org.opencontainers.image.title="atuin-ssh" \
      org.opencontainers.image.description="Persistent local-only Atuin SSH shell hub" \
      org.opencontainers.image.version="0.1.0"
EXPOSE 22
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD /usr/sbin/sshd -t && test -s /run/sshd.pid && kill -0 "$(cat /run/sshd.pid)"
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/sbin/atuin-ssh-entrypoint"]
CMD ["/usr/sbin/sshd", "-D", "-e"]

# The fixture does not install the application or Atuin on its destination.
FROM ${DESTINATION_IMAGE} AS destination
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash openssh-server openssh-client ca-certificates less nano procps tini \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && useradd --create-home --shell /bin/bash remote \
    && usermod --password '*' remote \
    && mkdir -p /run/sshd /state/sshd
COPY docker/sshd_config /etc/ssh/sshd_config
COPY docker/destination-entrypoint.sh /usr/local/sbin/destination-entrypoint
RUN chmod 0755 /usr/local/sbin/destination-entrypoint \
    && sed -i '/^SetEnv /d' /etc/ssh/sshd_config
RUN ! command -v python && ! command -v python3 && ! command -v atuin
EXPOSE 22
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/sbin/destination-entrypoint"]
CMD ["/usr/sbin/sshd", "-D", "-e"]

FROM runtime AS test
COPY --from=benchmark-build /out/atuin-ssh-bench-seed /usr/local/bin/atuin-ssh-bench-seed
RUN apt-get update && apt-get install -y --no-install-recommends strace \
    && rm -rf /var/lib/apt/lists/*
COPY tests /opt/atuin-ssh/tests
COPY docker/privacy-probe.py /opt/atuin-ssh/privacy-probe.py
COPY docker/test-keys.sh /usr/local/sbin/test-keys
RUN chmod 0755 /usr/local/sbin/test-keys
WORKDIR /opt/atuin-ssh
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM runtime AS dev
ENV PYTHONPATH=/workspace/src
RUN sed -i 's|^SetEnv |SetEnv PYTHONPATH=/workspace/src |' /etc/ssh/sshd_config
WORKDIR /workspace
