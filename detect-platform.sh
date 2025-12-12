#!/bin/bash
# detect-platform.sh
# Detects platform and sets environment variables

echo "🔍 Detecting platform..."

OS=$(uname -s)
ARCH=$(uname -m)

echo "  OS: $OS"
echo "  ARCH: $ARCH"

# Determine strategy
if [ -n "$FORCE_INSTALL_STRATEGY" ] && [ "$FORCE_INSTALL_STRATEGY" != "auto" ]; then
    echo "  Strategy forced to: $FORCE_INSTALL_STRATEGY"
    STRATEGY="$FORCE_INSTALL_STRATEGY"
else
    if [ "$OS" = "Linux" ] && [ "$ARCH" = "x86_64" ]; then
        # Check if we have Wine installed
        if command -v wine &> /dev/null; then
            STRATEGY="wine"
        else
            STRATEGY="native"
        fi
    else
        STRATEGY="native"
    fi
fi

echo "  Selected Strategy: $STRATEGY"

# Save to env file for other scripts
echo "PLATFORM_OS=$OS" > /app/platform-info.env
echo "PLATFORM_ARCH=$ARCH" >> /app/platform-info.env
echo "INSTALL_STRATEGY=$STRATEGY" >> /app/platform-info.env

export PLATFORM_OS=$OS
export PLATFORM_ARCH=$ARCH
export INSTALL_STRATEGY=$STRATEGY
