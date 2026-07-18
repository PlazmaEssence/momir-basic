"""Printer driver interface. Every driver renders the same PIL image the
same way; drivers only differ in where that image ends up."""
from abc import ABC, abstractmethod

from PIL import Image


class PrinterDriver(ABC):
    @abstractmethod
    def print_image(self, image: Image.Image) -> dict:
        """Send the image to the printer. Returns a small status dict."""

    @abstractmethod
    def status(self) -> dict:
        """Returns {'driver': str, 'connected': bool, 'detail': str}."""

    def close(self) -> None:
        """Releases any underlying connection/handle. Called before a driver
        instance is discarded (e.g. settings change swaps in a new one) so
        it doesn't leak a claimed USB interface or open socket/serial port."""
