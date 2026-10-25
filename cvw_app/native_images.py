"""Bounded native-image inspection and deterministic orientation previews.

No paths, fetching, admission, or retained derivatives live here. Coordinates
are pixel edges: raw_to_normalized maps (x, y) to (a*x+b*y+c, d*x+e*y+f).
Preview pixels are orientation evidence, never an authoritative replacement.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import re
from io import BytesIO
import threading
from typing import Any, Iterator
import warnings
import zlib

from PIL import Image, ImageOps, PngImagePlugin, UnidentifiedImageError


MEDIA_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_INPUT_PIXELS = 16_000_000
MAX_INPUT_EDGE = 16_384
PREVIEW_EDGE = 1280
MAX_OUTPUT_PIXELS = PREVIEW_EDGE * PREVIEW_EDGE
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
TRANSFORM_VERSION = "cvw-native-preview-v1"
JPEG_TRANSFORM_VERSION = "cvw-native-preview-jpeg-v2"
REGION_TRANSFORM_VERSION = "cvw-native-region-v1"
# Reject excess concurrent work, rather than retaining an unbounded decode queue.
_WORK_SLOTS = threading.BoundedSemaphore(2)


class NativeImageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@contextmanager
def image_work() -> Iterator[None]:
    if not _WORK_SLOTS.acquire(blocking=False):
        raise NativeImageError("image-busy", "Native image work is busy; retry this selected image.")
    try:
        yield
    finally:
        _WORK_SLOTS.release()


def check_input_size(length: int) -> None:
    if length > MAX_INPUT_BYTES:
        raise NativeImageError("image-too-large", f"Compressed native image exceeds {MAX_INPUT_BYTES} bytes.")


def _check_dimensions(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise NativeImageError("image-corrupt", "Native image dimensions must be positive.")
    if max(width, height) > MAX_INPUT_EDGE or width * height > MAX_INPUT_PIXELS:
        raise NativeImageError("image-too-large", "Native image exceeds the decoded dimension/pixel budget.")


def _preflight_webp(payload: bytes) -> tuple[int, int]:
    """Bound every declared WebP canvas before Pillow constructs its decoder.

    Pillow's WebP Image.open constructs WebPAnimDecoder, which allocates canvas
    buffers before reporting image.size. Checking dimensions after open is too
    late. Read the RIFF/VP8X/VP8/VP8L headers without invoking libwebp first.
    """
    if (len(payload) < 20 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP"
            or int.from_bytes(payload[4:8], "little") + 8 != len(payload)):
        raise NativeImageError("image-corrupt", "WebP RIFF header or declared file size is invalid.")
    offset = 12
    canvas = None
    frame = None
    seen: set[bytes] = set()
    # A still image needs only a handful of chunks. Refuse unusual expansion
    # rather than walking millions of empty chunks within the compressed budget.
    for _ in range(1024):
        if offset == len(payload):
            break
        if offset + 8 > len(payload):
            raise NativeImageError("image-corrupt", "WebP chunk header is truncated.")
        kind = payload[offset:offset + 4]
        length = int.from_bytes(payload[offset + 4:offset + 8], "little")
        start = offset + 8
        end = start + length
        padded_end = end + (length & 1)
        if padded_end > len(payload) or (length & 1 and payload[end] != 0):
            raise NativeImageError("image-corrupt", "WebP chunk size or padding is invalid.")
        if kind in {b"ANIM", b"ANMF"}:
            raise NativeImageError("image-unsupported", "Animated WebP does not support native previews.")
        if kind not in {b"VP8X", b"VP8 ", b"VP8L", b"ALPH", b"ICCP", b"EXIF", b"XMP "}:
            raise NativeImageError("image-unsupported", "WebP contains a chunk outside the supported still-image profile.")
        if kind in seen or (not seen and kind not in {b"VP8X", b"VP8 ", b"VP8L"}):
            raise NativeImageError("image-corrupt", "WebP contains duplicated or misordered headers.")
        if kind == b"VP8X":
            if seen or length != 10 or payload[start] & 0xC1 or payload[start + 1:start + 4] != b"\0\0\0":
                raise NativeImageError("image-corrupt", "WebP extended header is invalid.")
            if payload[start] & 0x02:
                raise NativeImageError("image-unsupported", "Animated WebP does not support native previews.")
            canvas = (1 + int.from_bytes(payload[start + 4:start + 7], "little"),
                      1 + int.from_bytes(payload[start + 7:start + 10], "little"))
            _check_dimensions(*canvas)
        elif kind in {b"VP8 ", b"VP8L"}:
            if frame is not None:
                raise NativeImageError("image-corrupt", "WebP must contain exactly one still-image bitstream.")
            if kind == b"VP8 ":
                if length < 10 or payload[start] & 1 or payload[start + 3:start + 6] != b"\x9d\x01\x2a":
                    raise NativeImageError("image-corrupt", "WebP VP8 key-frame header is invalid.")
                frame = (int.from_bytes(payload[start + 6:start + 8], "little") & 0x3FFF,
                         int.from_bytes(payload[start + 8:start + 10], "little") & 0x3FFF)
            else:
                if length < 5 or payload[start] != 0x2F:
                    raise NativeImageError("image-corrupt", "WebP lossless header is invalid.")
                bits = int.from_bytes(payload[start + 1:start + 5], "little")
                if bits >> 29:
                    raise NativeImageError("image-unsupported", "WebP lossless version is unsupported.")
                frame = (1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF))
            _check_dimensions(*frame)
            if canvas is not None and canvas != frame:
                raise NativeImageError("image-corrupt", "WebP canvas and still-image dimensions disagree.")
        seen.add(kind)
        offset = padded_end
    if offset != len(payload):
        raise NativeImageError("image-too-large", "WebP exceeds the bounded chunk-header work budget.")
    if frame is None:
        raise NativeImageError("image-corrupt", "WebP has no supported still-image header.")
    return canvas or frame


def _png_exif(payload: bytes) -> bytes:
    """Find EXIF even after IDAT without Pillow's getexif pixel-load fallback."""
    offset = 8
    exif = b""
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(payload):
            raise NativeImageError("image-corrupt", "PNG contains a truncated chunk.")
        kind = payload[offset + 4:offset + 8]
        if kind == b"eXIf":
            if length > 1024 * 1024:
                raise NativeImageError("image-too-large", "PNG EXIF exceeds the metadata budget.")
            if zlib.crc32(payload[offset + 4:end - 4]) != int.from_bytes(payload[end - 4:end], "big"):
                raise NativeImageError("image-corrupt", "PNG EXIF integrity check failed.")
            exif = payload[offset + 8:end - 4]
        offset = end
        if kind == b"IEND":
            return exif
    raise NativeImageError("image-corrupt", "PNG has no complete end chunk.")


def _inspect(image: Image.Image, media_type: str, payload: bytes) -> dict[str, Any]:
    if image.format != MEDIA_FORMATS[media_type]:
        raise NativeImageError("image-unsupported", "Image encoding does not match the admitted media type.")
    width, height = image.size
    _check_dimensions(width, height)
    if getattr(image, "n_frames", 1) != 1:
        raise NativeImageError("image-unsupported", "Only single-frame PNG, JPEG, and WebP images support previews.")
    if media_type == "image/png":
        image.info["exif"] = _png_exif(payload)
    orientation = image.getexif().get(274, 1)
    if not isinstance(orientation, int) or orientation not in range(1, 9):
        raise NativeImageError("image-unsupported", "Native image has an unsupported EXIF orientation.")
    transforms = {
        1: [1, 0, 0, 0, 1, 0], 2: [-1, 0, width, 0, 1, 0],
        3: [-1, 0, width, 0, -1, height], 4: [1, 0, 0, 0, -1, height],
        5: [0, 1, 0, 1, 0, 0], 6: [0, -1, height, 1, 0, 0],
        7: [0, -1, height, -1, 0, width], 8: [0, 1, 0, -1, 0, width],
    }
    normalized = (height, width) if orientation >= 5 else (width, height)
    scale = min(1, PREVIEW_EDGE / max(normalized))
    output = tuple(max(1, int(edge * scale)) for edge in normalized)
    jpeg_preview = media_type == "image/jpeg"
    encoding_settings = ({"quality": 85, "subsampling": 2, "optimize": False, "progressive": False}
                         if jpeg_preview else {"compress_level": 6, "optimize": False})
    return {
        "original_dimensions": {"width": width, "height": height, "basis": "encoded-image-header"},
        "normalized_dimensions": {"width": normalized[0], "height": normalized[1]},
        "orientation": {"exif": orientation, "coordinate_space": "orientation-normalized-pixel-edges",
                        "raw_to_normalized": transforms[orientation]},
        "preview": {"variant": "preview", "width": output[0], "height": output[1],
                    "media_type": "image/jpeg" if jpeg_preview else "image/png",
                    "transform_version": JPEG_TRANSFORM_VERSION if jpeg_preview else TRANSFORM_VERSION,
                    "encoding": "JPEG" if jpeg_preview else "PNG", "encoding_lossless": not jpeg_preview,
                    "encoding_settings": encoding_settings},
        "metadata_basis": "verified source bytes; header inspection is not pixel decode",
    }


@contextmanager
def _opened(payload: bytes, media_type: str) -> Iterator[Image.Image]:
    if media_type not in MEDIA_FORMATS:
        raise NativeImageError("image-unsupported", "Previews support only admitted single-frame PNG, JPEG, and WebP images.")
    check_input_size(len(payload))
    webp_dimensions = _preflight_webp(payload) if media_type == "image/webp" else None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload), formats=[MEDIA_FORMATS[media_type]]) as image:
                if webp_dimensions is not None and image.size != webp_dimensions:
                    raise NativeImageError("image-corrupt", "WebP decoder dimensions differ from its bounded headers.")
                yield image
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise NativeImageError("image-too-large", "Native image exceeds the decoder pixel budget.") from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        if isinstance(error, NativeImageError):
            raise
        raise NativeImageError("image-corrupt", "Native image is corrupt or cannot be decoded safely.") from error


def inspect_image(payload: bytes, media_type: str) -> dict[str, Any]:
    with _opened(payload, media_type) as image:
        return _inspect(image, media_type, payload)


def parse_region(value: str) -> tuple[int, int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4}),(?:0|[1-9][0-9]{0,4}),[1-9][0-9]{0,4},[1-9][0-9]{0,4}", value):
        raise NativeImageError("image-region-invalid", "region must be canonical x,y,width,height integers in normalized pixel edges.")
    return tuple(int(part) for part in value.split(","))


def region_plan(info: dict[str, Any], region: tuple[int, int, int, int]) -> dict[str, Any]:
    if info.get("error", {}).get("code") == "image-busy":
        raise NativeImageError("image-busy", "Native image work is busy; retry this selected image.")
    x, y, width, height = region
    dimensions = info.get("normalized_dimensions")
    if not dimensions or info.get("error"):
        raise NativeImageError("image-unsupported", "Exact region dimensions and orientation are unavailable.")
    if x < 0 or y < 0 or width < 1 or height < 1 or x + width > dimensions["width"] or y + height > dimensions["height"]:
        raise NativeImageError("image-region-invalid", "Region lies outside the orientation-normalized image.")
    if width * height > MAX_OUTPUT_PIXELS:
        raise NativeImageError("image-too-large", "Region exceeds the output pixel budget; request a smaller exact region.")
    a, b, c, d, e, f = info["orientation"]["raw_to_normalized"]
    determinant = a * e - b * d
    raw_edges = [[(e * (nx - c) - b * (ny - f)) // determinant,
                  (-d * (nx - c) + a * (ny - f)) // determinant]
                 for nx, ny in ((x, y), (x + width, y), (x + width, y + height), (x, y + height))]
    return {"variant": "region", "region": list(region), "coordinate_space": "orientation-normalized-pixel-edges",
            "raw_edge_corners": raw_edges, "frame": 0, "page": None, "page_state": "not-applicable",
            "output": {"width": width, "height": height, "media_type": "image/png", "sha256": None},
            "transform": {"version": REGION_TRANSFORM_VERSION, "orientation": "exif-transpose",
                          "scale_x": 1, "scale_y": 1, "resize": "none", "encoding": "PNG", "lossless": True}}


def _region_png_color(payload: bytes) -> PngImagePlugin.PngInfo:
    # Pillow decodes RGB16 PNG to RGB8. Refuse before that implicit quantization.
    if len(payload) < 29 or payload[24] == 16:
        raise NativeImageError("image-unsupported", "16-bit PNG detail is unsupported; use original bytes.")
    color = PngImagePlugin.PngInfo()
    offset = 8
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset:offset + 4], "big")
        kind = payload[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            raise NativeImageError("image-corrupt", "PNG contains a truncated chunk.")
        if kind in {b"cICP", b"mDCv", b"cLLi"}:
            raise NativeImageError("image-unsupported", "PNG HDR/color metadata is unsupported for exact regions; use original bytes.")
        if kind in {b"gAMA", b"cHRM", b"sRGB"}:
            color.add(kind, payload[offset + 8:end - 4])
        offset = end
        if kind == b"IEND":
            break
    return color


def region_image(payload: bytes, media_type: str, region: tuple[int, int, int, int]) -> tuple[bytes, dict[str, Any]]:
    with _opened(payload, media_type) as image:
        metadata = _inspect(image, media_type, payload)
        plan = region_plan(metadata, region)
        if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
            raise NativeImageError("image-unsupported", f"Exact region pixel mode {image.mode} is unsupported; use original bytes.")
        pnginfo = _region_png_color(payload) if media_type == "image/png" else None
        image.verify()
    with _opened(payload, media_type) as image:
        image.load()
        with ImageOps.exif_transpose(image) as normalized:
            x, y, width, height = region
            with normalized.crop((x, y, x + width, y + height)) as cropped:
                mode = cropped.mode
                retained = {key: normalized.info[key] for key in ("icc_profile", "transparency") if key in normalized.info}
                cropped.info.clear()
                with BytesIO() as buffer:
                    cropped.save(buffer, format="PNG", compress_level=6, optimize=False, pnginfo=pnginfo, **retained)
                    result = buffer.getvalue()
    if len(result) > MAX_OUTPUT_BYTES:
        raise NativeImageError("image-too-large", "Region exceeds the output byte budget.")
    metadata.update(plan)
    metadata["output"].update({"bytes": len(result), "sha256": hashlib.sha256(result).hexdigest()})
    metadata["transform"].update({"mode": mode, "decoded_sample_depth": 1 if mode == "1" else 8,
        "compress_level": 6, "optimize": False, "color_management": "No color conversion; ICC, PNG gamma/chromaticity/sRGB and transparency retained when present",
        "metadata": "Color semantics retained; orientation applied; other metadata removed"})
    metadata["meaning"] = "Exact decoded source samples after orientation and crop; PNG adds no lossy encoding. Original remains authoritative; browser color rendering is not assessed."
    return result, metadata


def preview_image(payload: bytes, media_type: str) -> tuple[bytes, dict[str, Any]]:
    # Verify container integrity before reopening for decode. Both use one
    # request's exact verified buffer; no mutable-file reread or derived cache.
    with _opened(payload, media_type) as image:
        metadata = _inspect(image, media_type, payload)
        image.verify()
    with _opened(payload, media_type) as image:
        image.load()
        with ImageOps.exif_transpose(image) as normalized:
            output = metadata["preview"]
            size = (output["width"], output["height"])
            if size[0] * size[1] > MAX_OUTPUT_PIXELS:
                raise NativeImageError("image-too-large", "Preview exceeds the output pixel budget.")
            # Explicit RGB(A), no contrast/sharpening/OCR, no metadata passthrough.
            mode = "RGBA" if "A" in normalized.getbands() or "transparency" in normalized.info else "RGB"
            with normalized.convert(mode) as converted:
                with converted.resize(size, Image.Resampling.LANCZOS) as resized:
                    resized.info.clear()
                    with BytesIO() as buffer:
                        resized.save(buffer, format=output["encoding"], **output["encoding_settings"])
                        result = buffer.getvalue()
    if len(result) > MAX_OUTPUT_BYTES:
        raise NativeImageError("image-too-large", "Preview exceeds the output byte budget.")
    metadata.update({
        "variant": "preview", "output": {"width": size[0], "height": size[1], "media_type": output["media_type"],
                                        "bytes": len(result), "sha256": hashlib.sha256(result).hexdigest()},
        "transform": {"version": output["transform_version"], "orientation": "exif-transpose", "resize": "lanczos",
                      "max_edge": PREVIEW_EDGE, "upscale": False, "mode": mode,
                      "encoding": output["encoding"], "encoding_lossless": output["encoding_lossless"],
                      **output["encoding_settings"], "metadata": "removed",
                      "color_management": "decoder conversion; embedded profiles not applied",
                      "scale_x": size[0] / metadata["normalized_dimensions"]["width"],
                      "scale_y": size[1] / metadata["normalized_dimensions"]["height"]},
        "meaning": "Orientation preview only; original remains authoritative. Fine detail requires original or exact region.",
    })
    return result, metadata
