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
./setup.sh
```

The setup script will:

- create `.venv` if it does not already exist
- install the project into that virtual environment
- prompt you to choose from currently attached displays
- default to the Bluetooth devices that are currently connected
- write `~/.config/keyboard-mouse-autoconnect/config.toml`
- install and start the macOS LaunchAgent by default

If the Bluetooth helper is missing, install it and rerun setup:

```sh
brew install blueutil
./setup.sh
```

You can also run the guided setup directly after installing the package:

```sh
kmautoconnect setup
```

To write config without installing the background service:

```sh
kmautoconnect setup --skip-service
```

The generated config can be edited later:

```sh
open ~/.config/keyboard-mouse-autoconnect/config.toml
```

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
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/kmautoconnect list-displays
.venv/bin/kmautoconnect list-bluetooth
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
