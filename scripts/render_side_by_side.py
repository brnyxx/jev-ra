"""Render two recordings side by side at 1x speed, with a running clock over each column.

GIF always (pillow). MP4 as well when ffmpeg is on PATH; its absence is reported, not fatal.
"""

import argparse
import itertools
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger("render_side_by_side")

DEFAULT_FPS = 10
COLUMN_WIDTH = 640
GIF_COLOURS = 64
GUTTER = 8
HEADER = 44
INK = (17, 18, 20)
PAPER = (250, 250, 250)
AMBER = (245, 158, 11)


def read_manifest(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text() if path.is_dir() else path.read_text())
    directory = path if path.is_dir() else path.parent
    frames = manifest["frames"]
    # The recorder writes frames in order; anything else means the recording is unusable.
    if any(b["ms"] < a["ms"] for a, b in itertools.pairwise(frames)):
        raise ValueError(f"{path}: frame timestamps are not monotonic")
    manifest["directory"] = str(directory)
    return manifest


def frame_at(manifest, at_ms):
    chosen = None
    for frame in manifest["frames"]:
        if frame["ms"] > at_ms:
            break
        chosen = frame
    return chosen or (manifest["frames"][0] if manifest["frames"] else None)


def load_frame(manifest, frame, size):
    if frame is None:
        return Image.new("RGB", size, INK)
    image = Image.open(Path(manifest["directory"]) / frame["file"]).convert("RGB")
    return image.resize(size, Image.LANCZOS)


def clock(ms):
    return f"{ms / 1000:6.2f}s"


def compose(manifests, at_ms, column, height):
    canvas = Image.new("RGB", (column * len(manifests) + GUTTER * (len(manifests) - 1), height + HEADER), INK)
    draw = ImageDraw.Draw(canvas)
    for index, manifest in enumerate(manifests):
        x = index * (column + GUTTER)
        finished = at_ms >= manifest["elapsed_ms"]
        frame = frame_at(manifest, at_ms)
        canvas.paste(load_frame(manifest, frame, (column, height)), (x, HEADER))
        shown = min(at_ms, manifest["elapsed_ms"])
        draw.text((x + 10, 8), manifest["label"], fill=PAPER)
        draw.text((x + column - 96, 8), clock(shown), fill=AMBER if finished else PAPER)
        if finished:
            draw.text((x + column - 190, 8), manifest.get("status", "done"), fill=AMBER)
    return canvas


def render(manifest_paths, out_stem, fps=DEFAULT_FPS, column=COLUMN_WIDTH, height=450):
    manifests = [read_manifest(path) for path in manifest_paths]
    if not manifests:
        raise ValueError("nothing to render")
    span = max(manifest["elapsed_ms"] for manifest in manifests)
    step = round(1000 / fps)
    frames = [compose(manifests, at, column, height) for at in range(0, span + step, step)]
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    gif = out_stem.with_suffix(".gif")
    # A full-colour screen recording is megabytes per second as a GIF; one shared palette is not.
    palette = frames[0].quantize(colors=GIF_COLOURS, method=Image.MEDIANCUT)
    flattened = [frame.quantize(palette=palette, dither=Image.FLOYDSTEINBERG) for frame in frames]
    flattened[0].save(gif, save_all=True, append_images=flattened[1:], duration=step, loop=0, optimize=True)
    written = [gif]
    mp4 = encode_mp4(frames, out_stem, fps)
    if mp4:
        written.append(mp4)
    return written


def encode_mp4(frames, out_stem, fps):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.info("ffmpeg is not on PATH; wrote the GIF only")
        return None
    staging = Path(out_stem).parent / f".{Path(out_stem).name}-frames"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for index, frame in enumerate(frames):
            frame.save(staging / f"{index:06d}.png")
        mp4 = Path(out_stem).with_suffix(".mp4")
        subprocess.run(
            [ffmpeg, "-y", "-framerate", str(fps), "-i", str(staging / "%06d.png"),
             "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(mp4)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return mp4
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="render_side_by_side", description=__doc__.splitlines()[0])
    parser.add_argument("manifests", nargs="+", help="recording directories or manifest.json paths")
    parser.add_argument("--out", required=True, help="output path without extension")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--width", type=int, default=COLUMN_WIDTH, help="width of one column in pixels")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    height = round(args.width * 450 / COLUMN_WIDTH)
    for path in render(args.manifests, args.out, args.fps, column=args.width, height=height):
        logger.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
