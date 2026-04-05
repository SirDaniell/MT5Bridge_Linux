# MT5 Bridge - Critical Configuration

> [!WARNING]
> **STABILITY NOTICE**: The configuration in this directory is finely tuned to run MetaTrader 5 on Linux using Wine. **Do not modify `Dockerfile`, `startup.sh`, or `mt5_bridge.py` without testing on a clean environment.**

## How It Works

This bridge runs a Windows-based Python environment inside Wine, which connects to the MT5 terminal using the `MetaTrader5` Python library.

### Key Components

1.  **Wine Environment**: Runs as `wineuser` (non-root) for stability.
2.  **Display**: Uses the host's X11 display (`DISPLAY=:0`) to allow the MT5 installer GUI to show up.
3.  **Python**: Uses an embedded Windows Python 3.10 distributable, extracted at runtime.
4.  **MT5 Terminal**: Installed manually via GUI or auto-detected if mounted.

## Installation / Setup

1.  **Enable X11 Access** (Run on host once):
    ```bash
    ./setup-x11-access.sh
    ```

2.  **Start the Bridge**:
    ```bash
    docker-compose up -d mt5-bridge
    ```

3.  **Install MT5 (First Run)**:
    - If MT5 is not found, call `POST /install` on port 5000.
    - The installer GUI will appear on your screen.
    - Complete the installation manually.

## Troubleshooting

-   **IPC Timeout**: MT5 is running but not responding. Usually means a dialog is blocking it (e.g., login window). Check the GUI.
-   **Display not found**: Ensure `setup-x11-access.sh` was run and check logs for `Cannot connect to X server`.
-   **File not found**: The path in `mt5_bridge.py` must match exactly where MT5 was installed (`/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe`).
