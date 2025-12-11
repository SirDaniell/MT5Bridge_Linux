# MT5 Bridge Production Deployment

## Installation on Client Machine

### Step 1: Run Setup Script

```bash
# Make executable
chmod +x setup-mt5-bridge.sh

# Run setup (configures X11 access)
./setup-mt5-bridge.sh
```

This script will:
- Configure X11 access for Docker
- Set up display permissions
- Add X11 access to user's shell profile (persistent across reboots)

### Step 2: Start MT5 Bridge

```bash
docker-compose up -d mt5-bridge
```

### Step 3: Complete MT5 Installation

On first startup:
1. MT5 installer window will appear on the client's display
2. User completes installation manually
3. Bridge server starts automatically after installation

## What the Setup Script Does

1. **Detects Display** - Automatically finds the correct DISPLAY value
2. **Configures X11** - Runs `xhost +local:docker` to allow container access
3. **Persistent Configuration** - Adds X11 access to `~/.bashrc` so it persists after reboot
4. **Sets Permissions** - Configures `/tmp/.X11-unix` permissions

## Troubleshooting

### Display Issues

Check display:
```bash
echo $DISPLAY
```

Manually allow X11:
```bash
xhost +local:docker
```

### Container Logs

```bash
docker-compose logs -f mt5-bridge
```

## Security

The setup uses `xhost +local:docker` which only allows local Docker containers to access the X server. This is safe for production use on client machines.

## Uninstall

To revoke X11 access:
```bash
xhost -local:docker
```

Remove from .bashrc:
```bash
sed -i '/xhost +local:docker/d' ~/.bashrc
```
