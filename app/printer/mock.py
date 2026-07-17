"""Dev/test printer driver: 'prints' by saving the rendered card to a PNG
under output/ so the render can be eyeballed without any hardware."""
import time
from pathlib import Path

from PIL import Image

from .base import PrinterDriver

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"


class MockPrinterDriver(PrinterDriver):
    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_output: Path | None = None

    def print_image(self, image: Image.Image) -> dict:
        filename = f"card_{int(time.time() * 1000)}.png"
        path = self.output_dir / filename
        image.save(path)
        self.last_output = path
        print(f"  [mock printer] wrote {path}")
        return {"ok": True, "detail": f"saved to {path.name}"}

    def status(self) -> dict:
        return {
            "driver": "mock",
            "connected": True,
            "detail": f"writing PNGs to {self.output_dir}",
        }
