"""Render the scripted demo to PNGs: one screenshot per scene plus a 25 fps frame sequence for a GIF.

python tools/screenshots.py shots          # headless by default

docs/media/gameplay.gif (8 s, 640 px, under 6 MB) was made from shots/gif_race with ffmpeg + ImageMagick:
VF='scale=640:-1:flags=neighbor,split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];'
VF+='[b][p]paletteuse=dither=none:diff_mode=rectangle'
ffmpeg -framerate 25 -t 8 -i shots/gif_race/frame_%04d.png -vf "$VF" big.gif
magick big.gif -coalesce -fuzz 3% -layers OptimizeTransparency docs/media/gameplay.gif
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--window", action="store_true", help="show the window instead of running headless")
    parser.add_argument("--seed", type=int, default=2022)
    args = parser.parse_args()
    if not args.window:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    sys.path.insert(0, str(ROOT / "src"))
    from jogo_de_carro.demo import run_demo

    for path in run_demo(args.out_dir, seed=args.seed):
        print(path)


if __name__ == "__main__":
    main()
