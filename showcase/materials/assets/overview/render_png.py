#!/usr/bin/env python3
"""Render the maintained 16:9 overview SVGs into web-uploadable PNGs.

SVG remains the editable source.  This named publication command exists for
forums and social platforms that do not accept SVG uploads.  Each PNG is first
captured in a temporary directory and replaces its stable counterpart only
after a minimal signature and dimension check.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
WIDTH = 1600
HEIGHT = 900
SOURCES = (
    HERE / "protocol-model-overview.zh.svg",
    HERE / "protocol-model-overview.en.svg",
)


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"Firefox did not produce a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    firefox = shutil.which("firefox")
    if firefox is None:
        raise SystemExit("Firefox is required to render the overview PNGs")

    # Stage beside the targets so the final os.replace remains atomic even
    # when the operating system's general temporary directory is another
    # filesystem.
    with TemporaryDirectory(prefix=".overview-build-", dir=HERE) as temporary:
        staging = Path(temporary)
        rendered: list[tuple[Path, Path]] = []
        for source in SOURCES:
            target_name = source.with_suffix(".png").name
            staged = staging / target_name
            process = subprocess.run(
                (
                    firefox,
                    "--headless",
                    "--screenshot",
                    str(staged),
                    "--window-size",
                    f"{WIDTH},{HEIGHT}",
                    source.as_uri(),
                ),
                text=True,
                capture_output=True,
            )
            if process.returncode != 0:
                detail = process.stderr.strip() or process.stdout.strip()
                raise RuntimeError(f"Firefox failed to render {source.name}: {detail}")
            dimensions = _png_dimensions(staged)
            if dimensions != (WIDTH, HEIGHT):
                raise RuntimeError(
                    f"unexpected PNG dimensions for {source.name}: {dimensions}"
                )
            rendered.append((staged, HERE / target_name))

        for staged, target in rendered:
            staged.replace(target)
            print(f"Published {target.relative_to(HERE.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
