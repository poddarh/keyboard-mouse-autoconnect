import unittest

from kmautoconnect.cli import (
    BluetoothDevice,
    Display,
    bluetooth_devices_from_system_profiler,
    config_for_link,
    normalize_address,
)


class CliTests(unittest.TestCase):
    def test_display_matches_all_configured_fields(self) -> None:
        display = Display(
            name="DELL UP3017",
            serial="ABC123",
            vendor_id="0x10ac",
            product_id="0x1234",
        )

        self.assertTrue(display.matches({"display_name": "dell up3017", "display_serial": "ABC123"}))
        self.assertFalse(display.matches({"display_name": "DELL UP3017", "display_serial": "WRONG"}))

    def test_bluetooth_devices_from_system_profiler_preserves_names_and_state(self) -> None:
        payload = {
            "SPBluetoothDataType": [
                {
                    "device_connected": [
                        {
                            "Magic Trackpad": {
                                "device_address": "D0:C0:50:BB:42:C2",
                            }
                        }
                    ],
                    "device_not_connected": [
                        {
                            "Magic Keyboard": {
                                "device_address": "80:4A:14:7B:7A:4D",
                            }
                        }
                    ],
                }
            ]
        }

        devices = bluetooth_devices_from_system_profiler(payload)

        self.assertEqual(
            [(device.name, device.address, device.connected) for device in devices],
            [
                ("Magic Trackpad", "d0-c0-50-bb-42-c2", True),
                ("Magic Keyboard", "80-4a-14-7b-7a-4d", False),
            ],
        )

    def test_normalize_address_accepts_common_formats(self) -> None:
        self.assertEqual(normalize_address("80:4A:14:7B:7A:4D"), "80-4a-14-7b-7a-4d")
        self.assertEqual(normalize_address("804A147B7A4D"), "80-4a-14-7b-7a-4d")

    def test_config_for_link_uses_display_and_devices(self) -> None:
        display = Display(name="DELL UP3017", serial="SERIAL1")
        devices = [
            BluetoothDevice(name="Magic Keyboard", address="80-4a-14-7b-7a-4d", connected=True),
            BluetoothDevice(name="Magic Trackpad", address="d0-c0-50-bb-42-c2", connected=True),
        ]

        config = config_for_link(display, devices)

        self.assertIn('display_name = "DELL UP3017"', config)
        self.assertIn('display_serial = "SERIAL1"', config)
        self.assertIn('{ name = "Magic Keyboard", address = "80-4a-14-7b-7a-4d" }', config)


if __name__ == "__main__":
    unittest.main()
