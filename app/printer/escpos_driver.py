"""Real thermal printing via python-escpos. Connection details (USB vendor/
product ID, serial device, or network host) come from data/config.json.
Connection is attempted lazily and failures are caught, never raised,
so a missing/unplugged printer doesn't take the whole app down — the
web UI just reports it as disconnected."""
from PIL import Image

from .base import PrinterDriver


class EscposPrinterDriver(PrinterDriver):
    def __init__(self, printer_config: dict):
        self.config = printer_config
        self._printer = None
        self._error: str | None = None
        self._connect()

    def _connect(self) -> None:
        connection = self.config.get("connection", "usb")
        try:
            if connection == "usb":
                from escpos.printer import Usb

                vendor_id = int(self.config.get("usb_vendor_id", "0x0000"), 16)
                product_id = int(self.config.get("usb_product_id", "0x0000"), 16)
                self._printer = Usb(vendor_id, product_id)
            elif connection == "serial":
                from escpos.printer import Serial

                self._printer = Serial(
                    devfile=self.config.get("serial_device", "/dev/serial0"),
                    baudrate=int(self.config.get("serial_baudrate", 19200)),
                )
            elif connection == "network":
                from escpos.printer import Network

                self._printer = Network(
                    host=self.config.get("network_host", ""),
                    port=int(self.config.get("network_port", 9100)),
                )
            else:
                raise ValueError(f"Unknown escpos connection type: {connection}")
            self._error = None
        except Exception as e:
            self._printer = None
            self._error = str(e)
            print(f"  [escpos printer] connection failed: {e}")

    def print_image(self, image: Image.Image) -> dict:
        if self._printer is None:
            self._connect()
        if self._printer is None:
            return {"ok": False, "detail": f"printer not connected: {self._error}"}
        try:
            self._printer.image(image, impl="bitImageRaster")
            self._printer.cut()
            return {"ok": True, "detail": "sent to printer"}
        except Exception as e:
            self._error = str(e)
            self.close()
            return {"ok": False, "detail": f"print failed: {e}"}

    def status(self) -> dict:
        return {
            "driver": "escpos",
            "connected": self._printer is not None,
            "detail": self._error or f"connected via {self.config.get('connection')}",
        }

    def close(self) -> None:
        if self._printer is not None:
            try:
                self._printer.close()
            except Exception as e:
                print(f"  [escpos printer] error closing connection: {e}")
            self._printer = None
