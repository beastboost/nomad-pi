#!/usr/bin/env python3
"""A733 GStreamer/OpenMAX HLS worker for Nomad.

This worker intentionally runs under the system Python, not Nomad's venv,
because PyGObject/GStreamer bindings are provided by the distro/vendor image.
It produces MPEG-TS HLS for browser/Safari compatibility and exits non-zero on
pipeline failure so HLSManager can fall back to FFmpeg/libx264.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys

try:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst  # type: ignore
except Exception as exc:  # pragma: no cover - depends on host media stack
    print(f"GStreamer Python bindings unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)


def _quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def build_pipeline(source: str, output_dir: Path, width: int | None, height: int | None) -> str:
    uri = Path(source).resolve().as_uri()
    caps = "video/x-raw,format=I420"
    if width and height:
        caps += f",width={int(width)},height={int(height)}"

    playlist = output_dir / "index.m3u8"
    segments = output_dir / "segment_%05d.ts"

    # Define both named elements before linking dynamic decodebin branches to
    # them. uridecodebin selects the appropriate demuxer/decoder; the process
    # environment ranks A733 OMX decoders above software where available.
    return " ".join([
        "uridecodebin", f"uri={_quote(uri)}", "name=dec",
        "hlssink2", "name=hls",
        f"location={_quote(str(segments))}",
        f"playlist-location={_quote(str(playlist))}",
        "target-duration=4", "max-files=0", "playlist-length=0",
        "dec.", "!", "queue", "max-size-time=3000000000", "!",
        "videoconvert", "!", "videoscale", "!", caps, "!",
        "omxh264videoenc", "name=videoenc", "!",
        "h264parse", "config-interval=-1", "!", "queue", "!", "hls.video",
        "dec.", "!", "queue", "max-size-time=3000000000", "!",
        "audioconvert", "!", "audioresample", "!",
        "avenc_aac", "bitrate=192000", "!", "aacparse", "!", "queue", "!", "hls.audio",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    Gst.init(None)
    description = build_pipeline(
        args.source,
        output_dir,
        args.width or None,
        args.height or None,
    )
    try:
        pipeline = Gst.parse_launch(description)
    except Exception as exc:
        print(f"Could not build A733 GStreamer HLS pipeline: {exc}", file=sys.stderr)
        return 3

    encoder = pipeline.get_by_name("videoenc")
    if encoder is not None and args.bitrate > 0:
        prop = encoder.find_property("bitrate")
        if prop is not None:
            try:
                encoder.set_property("bitrate", int(args.bitrate))
            except Exception as exc:
                print(f"Ignoring unsupported OMX bitrate value: {exc}", file=sys.stderr)

    stopping = False

    def stop_handler(_signum, _frame):
        nonlocal stopping
        stopping = True
        try:
            pipeline.send_event(Gst.Event.new_eos())
        except Exception:
            pass

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    pipeline.set_state(Gst.State.PAUSED)
    state_result, _state, _pending = pipeline.get_state(15 * Gst.SECOND)
    if state_result == Gst.StateChangeReturn.FAILURE:
        pipeline.set_state(Gst.State.NULL)
        print("A733 GStreamer pipeline failed while prerolling", file=sys.stderr)
        return 4

    if args.start > 0:
        ok = pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(args.start * Gst.SECOND),
        )
        if not ok:
            pipeline.set_state(Gst.State.NULL)
            print(f"A733 GStreamer pipeline could not seek to {args.start:.3f}s", file=sys.stderr)
            return 5

    pipeline.set_state(Gst.State.PLAYING)
    bus = pipeline.get_bus()
    exit_code = 0
    try:
        while True:
            message = bus.timed_pop_filtered(
                Gst.SECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is None:
                continue
            if message.type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                print(f"GStreamer error: {err}", file=sys.stderr)
                if debug:
                    print(debug, file=sys.stderr)
                exit_code = 6
                break
            if message.type == Gst.MessageType.EOS:
                break
    finally:
        pipeline.set_state(Gst.State.NULL)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
