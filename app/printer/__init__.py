from .base import PrinterDriver
from .mock import MockPrinterDriver


def get_driver(printer_config: dict) -> PrinterDriver:
    driver_name = printer_config.get("driver", "mock")
    if driver_name == "escpos":
        from .escpos_driver import EscposPrinterDriver

        return EscposPrinterDriver(printer_config)
    return MockPrinterDriver()
