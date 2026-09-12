# https://developers.home-assistant.io/docs/apps/configuration#app-dockerfile
ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

# Install application dependencies
RUN apk add --no-cache \
        git \
        openssh-client \
        python3 \
        inotify-tools

# Copy the application entrypoint
COPY run.sh /
RUN chmod a+x /run.sh

# Copy the application code
COPY rootfs /

CMD [ "/run.sh" ]
