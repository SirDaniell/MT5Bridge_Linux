# ==============================================================================
# CRITICAL STABILITY WARNING - DO NOT MODIFY WITHOUT BACKUP
# ==============================================================================
# This Dockerfile implements a specific, proven configuration for running MT5 on 
# Linux via Wine with GUI support. 
# 
# Key Requirements Preserved Here:
# 1. User switching (root -> wineuser) happens in Dockerfile, NOT startup script
# 2. Uses python-embed zip instead of installer
# 3. Explicitly installs Wine 10.0+ from WineHQ
# 4. Supports host X11 display forwarding for installer GUI
# 
# IF YOU MODIFY THIS, YOU RISK BREAKING THE BRIDGE.
# ==============================================================================

FROM debian:bookworm-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    gnupg2 \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Enable multiarch
RUN dpkg --add-architecture i386

# Add WineHQ repository
RUN mkdir -pm755 /etc/apt/keyrings && \
    wget -O /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key && \
    wget -NP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources

# Install Wine and dependencies
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --install-recommends \
    winehq-stable=10.0.0.0~bookworm-1 \
    wine-stable=10.0.0.0~bookworm-1 \
    wine-stable-i386=10.0.0.0~bookworm-1 \
    wine-stable-amd64=10.0.0.0~bookworm-1 \
    curl \
    procps \
    unzip \
    python3 \
    python3-pip \
    winbind \
    cabextract \
    sudo \
    xvfb \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Winetricks manually
RUN wget -q https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks -O /usr/local/bin/winetricks && \
    chmod +x /usr/local/bin/winetricks

WORKDIR /app

# Download Python and pip (will extract at runtime)
RUN wget -q https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip -O /app/python.zip && \
    wget -q https://bootstrap.pypa.io/get-pip.py -O /app/get-pip.py

# Copy application files
COPY mt5_bridge.py /app/mt5_bridge.py
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Create directories
RUN mkdir -p /var/log/mt5 && \
    mkdir -p /tmp/runtime-wineuser && \
    chmod 700 /tmp/runtime-wineuser

# Create non-root user for Wine (Wine works better as non-root)
RUN useradd -m -s /bin/bash wineuser && \
    chown -R wineuser:wineuser /app && \
    chown -R wineuser:wineuser /tmp/runtime-wineuser && \
    echo "wineuser ALL=(ALL) NOPASSWD: /bin/chown, /usr/bin/killall" >> /etc/sudoers

# Set environment variables
ENV WINEPREFIX=/home/wineuser/.wine
ENV WINEARCH=win64
ENV WINEDEBUG=-all

# Switch to wineuser
USER wineuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
    CMD curl -f http://localhost:5000/test || exit 1

CMD ["/startup.sh"]
