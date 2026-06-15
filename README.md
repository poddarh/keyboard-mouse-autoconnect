# Keyboard Mouse Autoconnect

Small macOS CLI that connects a configured Bluetooth keyboard and mouse when a
specific external display is attached.

The watcher polls the current display list, matches it against
`~/.config/keyboard-mouse-autoconnect/config.toml`, then asks a Bluetooth helper
to connect the paired devices for that display.

## Requirements

- macOS
- Python 3.11+
- A Bluetooth connector helper:

```sh
brew install blueutil
```

`BluetoothConnector` is also supported if it is already on your `PATH`, but
`blueutil` is the recommended backend.

## Quick Start

From this repo:

```sh
python3 -m pip install -e .
kmautoconnect init-config
kmautoconnect list-displays
kmautoconnect list-bluetooth
```

Edit the generated config:

```sh
open ~/.config/keyboard-mouse-autoconnect/config.toml
```

Use the display name, and preferably the display serial if macOS reports one.
Use the Bluetooth addresses for your paired keyboard and mouse.

Example:

```toml
poll_interval = 5
connect_on_start = true
connect_retries = 3
retry_delay = 2

[[links]]
name = "Desk display"
display_name = "DELL U2723QE"
display_serial = "ABC123"

devices = [
  { name = "Keychron K2", address = "AA-BB-CC-DD-EE-FF" },
  { name = "MX Master 3S", address = "11-22-33-44-55-66" },
]
```

Test once:

```sh
kmautoconnect connect-now
```

Run in the foreground:

```sh
kmautoconnect watch
```

Install it as a background LaunchAgent:

```sh
kmautoconnect install-launch-agent
```

Uninstall:

```sh
kmautoconnect uninstall-launch-agent
```

Logs are written to:

```text
~/Library/Logs/keyboard-mouse-autoconnect/
```

## Verify the Tool

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m kmautoconnect.cli list-displays
PYTHONPATH=src python3 -m kmautoconnect.cli list-bluetooth
```

If `connect-now` or `watch` says no Bluetooth connector was found, install
`blueutil` and try again:

```sh
brew install blueutil
```

## Matching Displays

Each `[[links]]` block may include any of these fields:

- `display_name`
- `display_serial`
- `display_vendor_id`
- `display_product_id`
- `display_type`

All fields you include must match. A display serial is usually the safest
identifier when macOS exposes it. Display name alone works well for a single
desk display, but it can match multiple displays of the same model.
