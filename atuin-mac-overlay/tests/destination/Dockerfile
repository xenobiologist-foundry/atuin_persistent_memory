FROM debian:bookworm-slim@sha256:ec31d744f83f4a73447ba045aaab9409997efe5cc706eca4890c1be36cc1606a AS bash44-build
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates build-essential patch libncurses-dev
COPY build-bash44.sh /tmp/build-bash44.sh
COPY bash44-sources.sha256 /tmp/bash44-sources.sha256
RUN /bin/bash /tmp/build-bash44.sh

FROM debian:bookworm-slim@sha256:ec31d744f83f4a73447ba045aaab9409997efe5cc706eca4890c1be36cc1606a AS modern
RUN apt-get update && apt-get install -y --no-install-recommends bash openssh-server less ca-certificates \
    && useradd -m -s /bin/bash remote && usermod -p '*' remote \
    && mkdir -p /run/sshd /home/remote/.ssh /destination-only-completion-directory \
    && ! command -v python3 && ! command -v atuin
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]

FROM modern AS legacy
COPY --from=bash44-build /out/bash44 /bin/bash
RUN usermod -s /bin/sh remote && /bin/bash --version
