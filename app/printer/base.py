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
