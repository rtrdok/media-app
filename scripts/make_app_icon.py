"""Собрать branding/app.ico из Lucide SVG (тот же знак, что в UI)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "branding"
SVG = BRAND / "app-logo.svg"
RENDER = BRAND / "_render"


def main() -> int:
    if not SVG.is_file():
        print("нет", SVG)
        return 1
    RENDER.mkdir(parents=True, exist_ok=True)
    pkg = RENDER / "node_modules" / "@resvg" / "resvg-js"
    if not pkg.is_dir():
        subprocess.check_call(["npm", "init", "-y"], cwd=str(RENDER))
        subprocess.check_call(
            ["npm", "install", "@resvg/resvg-js", "--no-fund", "--no-audit"],
            cwd=str(RENDER),
        )
    script = r"""
const { Resvg } = require('@resvg/resvg-js');
const fs = require('fs');
const svg = fs.readFileSync('../app-logo.svg');
for (const [name, w] of [['app.png', 512], ['app-64.png', 64]]) {
  const r = new Resvg(svg, { fitTo: { mode: 'width', value: w }, background: 'rgba(0,0,0,0)' });
  fs.writeFileSync('../' + name, r.render().asPng());
}
"""
    subprocess.check_call(["node", "-e", script], cwd=str(RENDER))

    from PIL import Image

    master = Image.open(BRAND / "app.png").convert("RGBA")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [master.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    imgs[-1].save(
        BRAND / "app.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=imgs[:-1],
    )
    print("ok", BRAND / "app.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
