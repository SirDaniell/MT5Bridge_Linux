# MT5 Bridge Setup Instructions

## Prerequisites

Before starting the MT5 bridge container, you need to allow Docker to access your X11 display:

```bash
# Allow local connections to X server (run this on your host machine)
xhost +local:docker
```

## Finding Your Display

Check your DISPLAY variable:
```bash
echo $DISPLAY
```

Common values:
- `:0` - First display (most common)
- `:1` - Second display
- `:10` - SSH X11 forwarding

## Starting the Container

```bash
# Set your DISPLAY variable (if different from :0)
export DISPLAY=:0

# Start the container
docker-compose up -d mt5-bridge

# View logs
docker-compose logs -f mt5-bridge
```

## MT5 Terminal Installation

When the container starts for the first time:
1. The MT5 installer will open a window on your display
2. Complete the installation manually
3. The installer window will appear on your host machine
4. After installation, the bridge server will start automatically

## Troubleshooting

### "cannot open display" error
```bash
# Allow X11 connections
xhost +local:docker

# Or allow all (less secure)
xhost +
```

### Wrong DISPLAY value
```bash
# Update docker-compose.yml with correct DISPLAY
# Or set environment variable
export DISPLAY=:1  # or whatever your display is
docker-compose up -d mt5-bridge
```

### Reset after testing
```bash
# Revoke X11 access when done
xhost -local:docker
```

## Security Note

The `xhost +local:docker` command allows Docker containers to access your X server.
This is safe for local development but should not be used in production environments.
