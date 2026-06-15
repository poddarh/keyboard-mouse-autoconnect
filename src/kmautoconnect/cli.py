from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 is unsupported.
    tomllib = None  # type: ignore[assignment]


APP_NAME = "keyboard-mouse-autoconnect"
DEFAULT_CONFIG = Path.home() / ".config" / APP_NAME / "config.toml"
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
LAUNCH_AGENT_ID = "local.keyboard-mouse-autoconnect"


@dataclass(frozen=True)
class Display:
    name: str
    serial: str | None = None
    vendor_id: str | None = None
    product_id: str | None = None
    display_type: str | None = None
    resolution: str | None = None

    def matches(self, criteria: dict[str, Any]) -> bool:
        checks = {
            "display_name": self.name,
            "display_serial": self.serial,
            "display_vendor_id": self.vendor_id,
            "display_product_id": self.product_id,
            "display_type": self.display_type,
        }
        for key, actual in checks.items():
            expected = criteria.get(key)
            if expected in (None, ""):
                continue
            if str(actual or "").casefold() != str(expected).casefold():
                return False
        return True

    @property
    def stable_key(self) -> str:
        parts = [self.name, self.serial or "", self.vendor_id or "", self.product_id or ""]
        return "|".join(parts)


@dataclass(frozen=True)
class BluetoothDevice:
    name: str | None
    address: str
    connected: bool | None = None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except UserFacingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


class UserFacingError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kmautoconnect",
        description="Connect Bluetooth devices when a configured macOS display is attached.",
    )
    parser.set_defaults(func=lambda _args: parser.print_help() or 0)

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Config file path. Default: {DEFAULT_CONFIG}",
    )

    subparsers = parser.add_subparsers(dest="command")

    list_displays = subparsers.add_parser("list-displays", help="Print currently attached displays.")
    add_subcommand_config_arg(list_displays)
    list_displays.add_argument("--json", action="store_true", help="Print raw JSON-friendly output.")
    list_displays.set_defaults(func=cmd_list_displays)

    list_bt = subparsers.add_parser("list-bluetooth", help="Print paired Bluetooth devices.")
    add_subcommand_config_arg(list_bt)
    list_bt.add_argument("--json", action="store_true", help="Print raw JSON-friendly output.")
    list_bt.set_defaults(func=cmd_list_bluetooth)

    init_config = subparsers.add_parser("init-config", help="Create an editable example config.")
    add_subcommand_config_arg(init_config)
    init_config.add_argument("--force", action="store_true", help="Overwrite an existing config.")
    init_config.set_defaults(func=cmd_init_config)

    connect_now = subparsers.add_parser(
        "connect-now",
        help="Connect devices for displays that are attached right now, then exit.",
    )
    add_subcommand_config_arg(connect_now)
    connect_now.set_defaults(func=cmd_connect_now)

    watch = subparsers.add_parser("watch", help="Poll for configured display connections.")
    add_subcommand_config_arg(watch)
    watch.add_argument("--once", action="store_true", help="Run one poll cycle, then exit.")
    watch.set_defaults(func=cmd_watch)

    install_agent = subparsers.add_parser(
        "install-launch-agent",
        help="Install a macOS LaunchAgent that runs this tool in the background.",
    )
    add_subcommand_config_arg(install_agent)
    install_agent.add_argument(
        "--python",
        dest="python_bin",
        default=sys.executable,
        help=f"Python executable for LaunchAgent. Default: {sys.executable}",
    )
    install_agent.set_defaults(func=cmd_install_launch_agent)

    uninstall_agent = subparsers.add_parser(
        "uninstall-launch-agent",
        help="Unload and remove the macOS LaunchAgent.",
    )
    add_subcommand_config_arg(uninstall_agent)
    uninstall_agent.set_defaults(func=cmd_uninstall_launch_agent)

    return parser


def add_subcommand_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"Config file path. Default: {DEFAULT_CONFIG}",
    )


def cmd_list_displays(args: argparse.Namespace) -> int:
    displays = current_displays()
    payload = [display_to_dict(display) for display in displays]
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if not displays:
        print("No displays found.")
        return 0
    print_table(
        ["name", "serial", "vendor_id", "product_id", "type", "resolution"],
        [
            [
                display.name,
                display.serial or "",
                display.vendor_id or "",
                display.product_id or "",
                display.display_type or "",
                display.resolution or "",
            ]
            for display in displays
        ],
    )
    return 0


def cmd_list_bluetooth(args: argparse.Namespace) -> int:
    devices = paired_bluetooth_devices()
    payload = [device_to_dict(device) for device in devices]
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if not devices:
        print("No paired Bluetooth devices found.")
        print("If this looks wrong, install blueutil: brew install blueutil")
        return 0
    print_table(
        ["name", "address", "connected"],
        [[device.name or "", device.address, connected_label(device.connected)] for device in devices],
    )
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    path: Path = args.config.expanduser()
    if path.exists() and not args.force:
        raise UserFacingError(f"{path} already exists. Use --force to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_config(), encoding="utf-8")
    print(f"Wrote {path}")
    print("Edit it with one display and the Bluetooth device addresses you want linked.")
    return 0


def cmd_connect_now(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    connector = BluetoothConnector.from_environment()
    matched = connect_for_current_displays(config, connector, force=True)
    if matched == 0:
        print("No configured display is currently attached.")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    connector = BluetoothConnector.from_environment()
    poll_interval = float(config.get("poll_interval", 5))
    connect_on_start = bool(config.get("connect_on_start", True))
    seen_display_keys: set[str] = set()

    print(f"Watching displays using {args.config.expanduser()}")
    print(f"Bluetooth backend: {connector.name}")

    first_cycle = True
    while True:
        displays = current_displays()
        current_keys = {display.stable_key for display in displays}
        newly_attached = first_cycle and connect_on_start
        if not first_cycle:
            newly_attached = bool(current_keys - seen_display_keys)

        if newly_attached:
            connect_for_displays(config, connector, displays, force=False)

        seen_display_keys = current_keys
        first_cycle = False

        if args.once:
            return 0
        time.sleep(poll_interval)


def cmd_install_launch_agent(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser()
    if not config_path.exists():
        raise UserFacingError(f"{config_path} does not exist. Run init-config first.")

    agent_path = launch_agent_path()
    log_dir = DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    agent_path.parent.mkdir(parents=True, exist_ok=True)

    package_root = Path(__file__).resolve().parents[2]
    plist = {
        "Label": LAUNCH_AGENT_ID,
        "ProgramArguments": [
            args.python_bin,
            "-m",
            "kmautoconnect.cli",
            "--config",
            str(config_path),
            "watch",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / "stdout.log"),
        "StandardErrorPath": str(log_dir / "stderr.log"),
        "EnvironmentVariables": {
            "PYTHONPATH": str(package_root / "src"),
            "PATH": os.environ.get("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        },
    }
    with agent_path.open("wb") as handle:
        plistlib.dump(plist, handle)

    run(["launchctl", "bootout", f"gui/{os.getuid()}", str(agent_path)], check=False)
    run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(agent_path)])
    run(["launchctl", "enable", f"gui/{os.getuid()}/{LAUNCH_AGENT_ID}"], check=False)
    run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LAUNCH_AGENT_ID}"], check=False)
    print(f"Installed and started {agent_path}")
    print(f"Logs: {log_dir}")
    return 0


def cmd_uninstall_launch_agent(_args: argparse.Namespace) -> int:
    agent_path = launch_agent_path()
    run(["launchctl", "bootout", f"gui/{os.getuid()}", str(agent_path)], check=False)
    if agent_path.exists():
        agent_path.unlink()
        print(f"Removed {agent_path}")
    else:
        print(f"{agent_path} was not installed.")
    return 0


def current_displays() -> list[Display]:
    payload = system_profiler_json("SPDisplaysDataType")
    displays: list[Display] = []
    for gpu in payload.get("SPDisplaysDataType", []):
        for item in gpu.get("spdisplays_ndrvs", []):
            name = first_present(
                item.get("_name"),
                item.get("spdisplays_display-product-name"),
                item.get("spdisplays_display_product_name"),
            )
            if not name:
                continue
            displays.append(
                Display(
                    name=str(name),
                    serial=as_optional_string(item.get("spdisplays_display_serial_number")),
                    vendor_id=as_optional_string(
                        first_present(
                            item.get("spdisplays_display-vendor-id"),
                            item.get("spdisplays_display_vendor-id"),
                            item.get("spdisplays_display_vendor_id"),
                        )
                    ),
                    product_id=as_optional_string(
                        first_present(
                            item.get("spdisplays_display-product-id"),
                            item.get("spdisplays_display_product-id"),
                            item.get("spdisplays_display_product_id"),
                        )
                    ),
                    display_type=as_optional_string(item.get("spdisplays_display_type")),
                    resolution=as_optional_string(item.get("spdisplays_resolution")),
                )
            )
    return displays


def paired_bluetooth_devices() -> list[BluetoothDevice]:
    blueutil = shutil.which("blueutil")
    if blueutil:
        result = run([blueutil, "--paired", "--format", "json"], check=False)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                return sorted(
                    [
                        BluetoothDevice(
                            name=item.get("name"),
                            address=normalize_address(item.get("address", "")),
                            connected=item.get("connected"),
                        )
                        for item in payload
                        if item.get("address")
                    ],
                    key=lambda item: ((item.name or "").casefold(), item.address),
                )
            except json.JSONDecodeError:
                pass

    payload = system_profiler_json("SPBluetoothDataType")
    found: dict[str, BluetoothDevice] = {}
    for device in bluetooth_devices_from_system_profiler(payload):
        found[device.address] = device
    for node in walk_dicts(payload):
        address = first_present(
            node.get("device_address"),
            node.get("Device Address"),
            node.get("address"),
        )
        if not address:
            continue
        name = first_present(node.get("device_name"), node.get("_name"), node.get("name"))
        connected = parse_connected(first_present(node.get("device_isconnected"), node.get("Connected")))
        normalized = normalize_address(str(address))
        existing = found.get(normalized)
        if existing is None or (not existing.name and name):
            found[normalized] = BluetoothDevice(
                name=as_optional_string(name),
                address=normalized,
                connected=connected if connected is not None else existing.connected if existing else None,
            )
    return sorted(found.values(), key=lambda item: ((item.name or "").casefold(), item.address))


def bluetooth_devices_from_system_profiler(payload: dict[str, Any]) -> list[BluetoothDevice]:
    devices: list[BluetoothDevice] = []
    for adapter in payload.get("SPBluetoothDataType", []):
        for section_name, connected in (
            ("device_connected", True),
            ("device_not_connected", False),
        ):
            for wrapped_device in adapter.get(section_name, []):
                if not isinstance(wrapped_device, dict):
                    continue
                for name, properties in wrapped_device.items():
                    if not isinstance(properties, dict):
                        continue
                    address = properties.get("device_address")
                    if not address:
                        continue
                    devices.append(
                        BluetoothDevice(
                            name=str(name),
                            address=normalize_address(str(address)),
                            connected=connected,
                        )
                    )
    return devices


def connect_for_current_displays(config: dict[str, Any], connector: "BluetoothConnector", force: bool) -> int:
    return connect_for_displays(config, connector, current_displays(), force=force)


def connect_for_displays(
    config: dict[str, Any],
    connector: "BluetoothConnector",
    displays: list[Display],
    force: bool,
) -> int:
    links = config.get("links", [])
    if not isinstance(links, list):
        raise UserFacingError("Config key 'links' must be a TOML array of tables.")

    matched = 0
    for link in links:
        if not isinstance(link, dict):
            continue
        matching_displays = [display for display in displays if display.matches(link)]
        if not matching_displays:
            continue
        matched += 1
        link_name = link.get("name") or link.get("display_name") or "display link"
        display_names = ", ".join(display.name for display in matching_displays)
        print(f"Matched {link_name}: {display_names}")
        connect_link_devices(config, connector, link, force=force)
    return matched


def connect_link_devices(
    config: dict[str, Any],
    connector: "BluetoothConnector",
    link: dict[str, Any],
    force: bool,
) -> None:
    retries = int(link.get("connect_retries", config.get("connect_retries", 3)))
    retry_delay = float(link.get("retry_delay", config.get("retry_delay", 2)))
    devices = link.get("devices", [])
    if not isinstance(devices, list):
        raise UserFacingError("'devices' must be a TOML array.")

    for item in devices:
        if isinstance(item, str):
            name = None
            address = item
        elif isinstance(item, dict):
            name = as_optional_string(item.get("name"))
            address = item.get("address")
        else:
            continue
        if not address:
            continue
        label = f"{name} ({address})" if name else str(address)
        if not force and connector.is_connected(str(address)):
            print(f"Already connected: {label}")
            continue
        connect_with_retries(connector, str(address), label, retries, retry_delay)


def connect_with_retries(
    connector: "BluetoothConnector",
    address: str,
    label: str,
    retries: int,
    retry_delay: float,
) -> None:
    for attempt in range(1, retries + 1):
        print(f"Connecting {label} (attempt {attempt}/{retries})")
        result = connector.connect(address)
        if result.returncode == 0:
            print(f"Connected or connection requested: {label}")
            return
        stderr = result.stderr.strip()
        if stderr:
            print(stderr, file=sys.stderr)
        if attempt < retries:
            time.sleep(retry_delay)
    print(f"Could not connect {label}", file=sys.stderr)


class BluetoothConnector:
    def __init__(self, name: str, binary: str):
        self.name = name
        self.binary = binary

    @classmethod
    def from_environment(cls) -> "BluetoothConnector":
        blueutil = shutil.which("blueutil")
        if blueutil:
            return cls("blueutil", blueutil)
        bluetooth_connector = shutil.which("BluetoothConnector")
        if bluetooth_connector:
            return cls("BluetoothConnector", bluetooth_connector)
        raise UserFacingError(
            "No Bluetooth connector found. Install one with: brew install blueutil"
        )

    def connect(self, address: str) -> subprocess.CompletedProcess[str]:
        normalized = normalize_address(address)
        if self.name == "blueutil":
            return run([self.binary, "--connect", normalized], check=False)
        return run([self.binary, "--connect", normalized], check=False)

    def is_connected(self, address: str) -> bool:
        normalized = normalize_address(address)
        if self.name == "blueutil":
            result = run([self.binary, "--is-connected", normalized], check=False)
            return result.returncode == 0 and result.stdout.strip().lower() in {"1", "true", "yes"}
        return False


def load_config(path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    if not expanded.exists():
        raise UserFacingError(f"{expanded} does not exist. Run init-config first.")
    with expanded.open("rb") as handle:
        return tomllib.load(handle)


def system_profiler_json(data_type: str) -> dict[str, Any]:
    result = run(["system_profiler", "-json", data_type])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise UserFacingError(f"system_profiler returned invalid JSON for {data_type}") from exc


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise UserFacingError(f"{' '.join(command)} failed: {detail}")
    return result


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def example_config() -> str:
    return f"""# Keyboard Mouse Autoconnect
# 1. Run: kmautoconnect list-displays
# 2. Run: kmautoconnect list-bluetooth
# 3. Replace the example values below.

poll_interval = 5
connect_on_start = true
connect_retries = 3
retry_delay = 2

[[links]]
name = "Desk display"
display_name = "DELL U2723QE"
# Use display_serial when available; it is more stable than name alone.
# display_serial = "ABC123"

devices = [
  {{ name = "Keyboard", address = "AA-BB-CC-DD-EE-FF" }},
  {{ name = "Mouse", address = "11-22-33-44-55-66" }},
]
"""


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_ID}.plist"


def normalize_address(address: str) -> str:
    compact = "".join(ch for ch in address.strip().lower() if ch.isalnum())
    if len(compact) == 12:
        return "-".join(compact[index : index + 2] for index in range(0, 12, 2))
    return address.strip().lower().replace(":", "-")


def display_to_dict(display: Display) -> dict[str, str | None]:
    return {
        "name": display.name,
        "serial": display.serial,
        "vendor_id": display.vendor_id,
        "product_id": display.product_id,
        "type": display.display_type,
        "resolution": display.resolution,
    }


def device_to_dict(device: BluetoothDevice) -> dict[str, str | bool | None]:
    return {
        "name": device.name,
        "address": device.address,
        "connected": device.connected,
    }


def connected_label(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def as_optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def parse_connected(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"yes", "true", "1", "connected"}:
        return True
    if text in {"no", "false", "0", "not connected"}:
        return False
    return None


def walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk_dicts(child))
    return found


if __name__ == "__main__":
    raise SystemExit(main())
