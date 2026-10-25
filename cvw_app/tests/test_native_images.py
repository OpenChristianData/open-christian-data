"""Ticket 12: bounded derivatives, exact authority, and honest metadata."""
from __future__ import annotations

import hashlib
import http.client
from io import BytesIO
import json
import os
from pathlib import Path
import random
from urllib.parse import urlencode

from PIL import Image, ImageFile, PngImagePlugin, WebPImagePlugin
import pytest

from cvw_app import native_images as images
from cvw_app.review_contract import ReviewContractError
from cvw_app.serving_identity import runtime_identity
from cvw_app.tests.test_review_work_catalog import evidence_pair  # noqa: F401
from cvw_app.tests.test_review_service import _start_server, _stop_server


def encoded(size=(9, 6), *, kind="PNG", orientation=1, textured=False, **settings) -> bytes:
    with Image.new("RGB", size, "white") as image:
        if textured:
            # Deterministic synthetic texture catches JPEG-to-PNG size inflation.
            image.frombytes(random.Random(12).randbytes(size[0] * size[1] * 3))
        image.putpixel((0, 0), (255, 0, 0))
        image.putpixel((size[0] - 1, size[1] - 1), (0, 0, 255))
        exif = Image.Exif()
        exif[274] = orientation
        with BytesIO() as buffer:
            image.save(buffer, format=kind, exif=exif, **settings)
            return buffer.getvalue()


def identity(application):
    source = application._work("brief-example")["stages"]["source"]["artifacts"][0]
    return ("brief-example", "source", source["id"], source["version"], source["sha256"])


def test_brief_preview_and_region_recover_after_image_capacity_returns(evidence_pair):
    application, selection, _ = evidence_pair("source.png", encoded())
    with images.image_work(), images.image_work():
        busy = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert busy["left"]["image"]["native_image"]["error"]["code"] == "image-busy"
    assert busy["left"]["image"]["preview_request"] is None

    retry = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert "error" not in retry["left"]["image"]["native_image"]
    selected = identity(application)
    assert retry["left"]["image"]["preview_request"]["expected_sha256"] == selected[4]
    for variant in ("preview", "region"):
        image_selection = {"variant": variant}
        options = {}
        if variant == "region":
            image_selection.update(region="0,0,2,2", source_sha256=selected[4])
            options["region"] = "0,0,2,2"
        view = application.compare_view("brief-example", **selection, left_image=image_selection)
        assert view["left"]["image_selection"] == image_selection
        output, metadata = application.stage_image(*selected, variant=variant, **options)
        assert hashlib.sha256(output).hexdigest() == metadata["output"]["sha256"]
        assert metadata["source"]["sha256"] == selected[4]


def test_region_planning_reports_retryable_capacity_error(evidence_pair):
    application, selection, _ = evidence_pair("source.png", encoded())
    selected = identity(application)
    region = {"variant": "region", "region": "0,0,2,2", "source_sha256": selected[4]}
    with images.image_work(), images.image_work():
        with pytest.raises(images.NativeImageError) as caught:
            application.compare_view("brief-example", **selection, left_image=region)
    assert caught.value.code == "image-busy"
    assert "retry" in str(caught.value)
    assert application.compare_view("brief-example", **selection, left_image=region)["left"]["image_request"]


@pytest.mark.parametrize("kind,media", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_supported_metadata_without_pixel_decode(kind, media, monkeypatch):
    payload = encoded(kind=kind, orientation=6)
    def no_load(*args, **kwargs):
        raise AssertionError("Metadata must not decode pixels")
    monkeypatch.setattr(ImageFile.ImageFile, "load", no_load)
    info = images.inspect_image(payload, media)
    assert info["normalized_dimensions"] == {"width": 6, "height": 9}
    assert info["orientation"]["exif"] == 6
    assert info["preview"]["media_type"] == ("image/jpeg" if kind == "JPEG" else "image/png")
    if kind == "JPEG":
        assert info["preview"]["transform_version"] == "cvw-native-preview-jpeg-v2"
        assert info["preview"]["encoding"] == "JPEG"
        assert info["preview"]["encoding_lossless"] is False
        assert info["preview"]["encoding_settings"] == {
            "quality": 85, "subsampling": 2, "optimize": False, "progressive": False,
        }


def webp_chunks(*chunks: tuple[bytes, bytes]) -> bytes:
    body = b"WEBP" + b"".join(kind + len(data).to_bytes(4, "little") + data + (b"\0" if len(data) & 1 else b"")
                              for kind, data in chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def webp_header(kind: bytes, width: int, height: int) -> bytes:
    if kind == b"VP8X":
        return b"\0\0\0\0" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    if kind == b"VP8 ":
        return b"\x10\0\0\x9d\x01\x2a" + width.to_bytes(2, "little") + height.to_bytes(2, "little")
    return b"\x2f" + ((width - 1) | ((height - 1) << 14)).to_bytes(4, "little")


@pytest.mark.parametrize("kind,width,height", [(b"VP8X", 5000, 4000), (b"VP8 ", 5000, 4000),
                                             (b"VP8L", 5000, 4000), (b"VP8X", 100000, 1)])
def test_webp_oversize_is_refused_before_canvas_decoder_allocation(kind, width, height, monkeypatch):
    # Only tiny declared headers are built. No giant image or decoder allocation.
    payload = webp_chunks((kind, webp_header(kind, width, height)))
    calls = []
    def decoder_must_not_run(*args):
        calls.append(args)
        raise AssertionError("WebP canvas decoder constructed before dimension admission")
    monkeypatch.setattr(WebPImagePlugin._webp, "WebPAnimDecoder", decoder_must_not_run)
    for operation in (images.inspect_image, images.preview_image, lambda payload, media: images.region_image(payload, media, (0, 0, 1, 1))):
        with pytest.raises(images.NativeImageError) as caught:
            operation(payload, "image/webp")
        assert caught.value.code == "image-too-large"
    assert calls == []


@pytest.mark.parametrize("failure", ["truncated", "mismatch", "duplicate", "animation-flag", "animation-chunk", "unknown", "lossless-version"])
def test_malformed_or_unsupported_webp_headers_fail_before_decoder(failure, monkeypatch):
    extended = webp_header(b"VP8X", 3, 2)
    frame = webp_header(b"VP8L", 3, 2)
    chunks = [(b"VP8X", extended), (b"VP8L", frame)]
    if failure == "mismatch":
        chunks[1] = (b"VP8L", webp_header(b"VP8L", 2, 2))
    if failure == "duplicate":
        chunks.insert(1, chunks[0])
    if failure == "animation-flag":
        chunks[0] = (b"VP8X", b"\x02" + extended[1:])
    if failure == "animation-chunk":
        chunks.insert(1, (b"ANIM", b"\0" * 6))
    if failure == "unknown":
        chunks.append((b"UNKN", b""))
    if failure == "lossless-version":
        chunks[1] = (b"VP8L", frame[:4] + bytes([frame[4] | 0x20]))
    payload = webp_chunks(*chunks)
    if failure == "truncated":
        payload = payload[:-1]
    def decoder_must_not_run(*args):
        raise AssertionError("Malformed header reached the canvas decoder")
    monkeypatch.setattr(WebPImagePlugin._webp, "WebPAnimDecoder", decoder_must_not_run)
    with pytest.raises(images.NativeImageError) as caught:
        images.inspect_image(payload, "image/webp")
    assert caught.value.code in {"image-corrupt", "image-unsupported"}


@pytest.mark.parametrize("lossless", [False, True])
def test_simple_webp_bitstream_headers_keep_valid_preview_support(lossless):
    with Image.new("RGB", (7, 5), "red") as source, BytesIO() as buffer:
        source.save(buffer, format="WEBP", lossless=lossless)
        payload = buffer.getvalue()
    assert payload[12:16] == (b"VP8L" if lossless else b"VP8 ")
    preview, metadata = images.preview_image(payload, "image/webp")
    assert metadata["original_dimensions"]["width"] == 7
    assert metadata["output"]["height"] == 5
    assert preview.startswith(b"\x89PNG")


@pytest.mark.parametrize("orientation", range(1, 9))
def test_orientation_pixel_mapping_and_lossless_png_preview(orientation):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (15, 25, 35), (45, 55, 65), (75, 85, 95)]
    with Image.new("RGB", (3, 2)) as source, BytesIO() as buffer:
        source.putdata(colors)
        exif = Image.Exif()
        exif[274] = orientation
        source.save(buffer, format="PNG", exif=exif)
        payload = buffer.getvalue()
    preview, info = images.preview_image(payload, "image/png")
    with Image.open(BytesIO(preview)) as result:
        a, b, c, d, e, f = info["orientation"]["raw_to_normalized"]
        for y in range(2):
            for x in range(3):
                mapped = (int(a*(x+.5) + b*(y+.5) + c), int(d*(x+.5) + e*(y+.5) + f))
                assert result.getpixel(mapped) == colors[y * 3 + x]
        assert 274 not in result.getexif()
    assert info["output"]["sha256"] == hashlib.sha256(preview).hexdigest()
    assert info["transform"]["encoding_lossless"] is True
    assert images.preview_image(payload, "image/png") == (preview, info)


@pytest.mark.parametrize("name,kind,media,settings", [
    ("source.png", "PNG", "image/png", {"compress_level": 0}),
    ("source.jpg", "JPEG", "image/jpeg", {"quality": 70, "textured": True}),
])
def test_preview_bound_and_exact_identity_reuses_one_verified_request_buffer(evidence_pair, monkeypatch, name, kind, media, settings):
    payload = encoded((2400, 1800), kind=kind, **settings)
    application, selection, source = evidence_pair(name, payload)
    brief = application.compare_view("brief-example", **selection, evidence_brief=True)
    assert brief["left"]["image"]["native_image"]["preview"]["width"] == 1280
    assert brief["left"]["image"]["preview_request"]["expected_sha256"] == hashlib.sha256(payload).hexdigest()
    original_open = Path.open
    reads = []
    def record_open(path, *args, **kwargs):
        if path == source.resolve():
            reads.append(path)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", record_open)
    preview, info = application.stage_image(*identity(application))
    assert reads == [source.resolve()]
    assert info["output"]["width"] == 1280 and info["output"]["height"] == 960
    assert len(preview) < len(payload)
    assert preview.startswith(b"\xff\xd8\xff" if kind == "JPEG" else b"\x89PNG")
    with Image.open(BytesIO(preview)) as decoded:
        decoded.load()
        assert decoded.size == (1280, 960)
        assert decoded.format == kind
        assert 274 not in decoded.getexif()
    assert info["source"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert info["source"]["member"]["path"] == source.name
    planned = brief["left"]["image"]["native_image"]["preview"]
    assert info["output"]["media_type"] == planned["media_type"] == media
    assert info["output"]["sha256"] == hashlib.sha256(preview).hexdigest()
    assert info["transform"]["version"] == planned["transform_version"]
    assert info["transform"]["encoding"] == planned["encoding"] == kind
    assert info["transform"]["encoding_lossless"] is (kind == "PNG")
    for setting, value in planned["encoding_settings"].items():
        assert info["transform"][setting] == value
    assert application.stage_bytes(*identity(application)) == (payload, media)


@pytest.mark.parametrize("name,kind", [("source.png", "PNG"), ("source.jpg", "JPEG")])
def test_warm_cache_does_not_authorize_changed_same_size_mtime_bytes(evidence_pair, name, kind):
    application, selection, source = evidence_pair(name, encoded(kind=kind))
    application.compare_view("brief-example", **selection)
    selected = identity(application)
    with pytest.raises(ReviewContractError):
        application.stage_image(*selected[:-1], "0" * 64)
    with pytest.raises(ReviewContractError):
        application.stage_image(*selected[:2], "wrong", *selected[3:])
    before = source.stat()
    changed = bytearray(source.read_bytes())
    changed[-1] ^= 1
    source.write_bytes(changed)
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ReviewContractError, match="sha256"):
        application.stage_image(*selected)
    with pytest.raises(ReviewContractError, match="sha256"):
        application.stage_image(*selected, variant="region", region="0,0,1,1")
    with pytest.raises(ReviewContractError, match="sha256"):
        application.stage_bytes(*selected)


@pytest.mark.parametrize("case,code", [("corrupt", "image-corrupt"), ("oversize-bytes", "image-too-large"),
                                     ("oversize-pixels", "image-too-large"), ("unsupported", "image-unsupported"),
                                     ("animated", "image-unsupported"), ("output", "image-too-large")])
def test_explicit_failures(case, code, monkeypatch):
    payload, media = encoded(), "image/png"
    if case == "corrupt":
        payload = payload[:40]
    if case == "oversize-bytes":
        monkeypatch.setattr(images, "MAX_INPUT_BYTES", len(payload) - 1)
    if case == "oversize-pixels":
        monkeypatch.setattr(images, "MAX_INPUT_PIXELS", 5)
    if case == "unsupported":
        media = "image/tiff"
    if case == "output":
        monkeypatch.setattr(images, "MAX_OUTPUT_PIXELS", 1)
    if case == "animated":
        with Image.new("RGB", (9, 6), "red") as first, Image.new("RGB", (9, 6), "blue") as second, BytesIO() as buffer:
            first.save(buffer, format="PNG", save_all=True, append_images=[second], duration=100)
            payload = buffer.getvalue()
    with pytest.raises(images.NativeImageError) as caught:
        images.preview_image(payload, media)
    assert caught.value.code == code


def test_work_bound_and_runtime_codecs_are_explicit():
    with images.image_work(), images.image_work():
        with pytest.raises(images.NativeImageError, match="busy"):
            with images.image_work():
                pytest.fail("Over-budget work was admitted")
    runtime = runtime_identity()
    assert runtime["distributions"]["Pillow"] == Image.__version__
    assert runtime["image_codecs"]["jpg"]
    assert runtime["image_codecs"]["webp"]


@pytest.mark.parametrize("name,kind,media", [("source.png", "PNG", "image/png"), ("source.jpg", "JPEG", "image/jpeg")])
def test_http_image_identity_headers_and_rejections(evidence_pair, tmp_path, name, kind, media):
    application, _, _ = evidence_pair(name, encoded(kind=kind))
    selected = identity(application)
    params = dict(expected_artifact=selected[2], expected_version=selected[3], expected_sha256=selected[4], variant="preview")
    base = "/api/review/v1/works/brief-example/stages/source/image?"
    server, thread, events = _start_server(tmp_path, application=application)
    def get(query):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request("GET", base + query)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()
    try:
        status, headers, body = get(urlencode(params))
        assert status == 200 and headers["Content-Type"] == media
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-CVW-Request-ID"]
        metadata = json.loads(headers["X-CVW-Image-Metadata"])
        assert metadata["source"]["sha256"] == selected[4]
        assert metadata["output"]["media_type"] == media
        with Image.open(BytesIO(body)) as decoded:
            decoded.load()
            assert decoded.format == kind and decoded.size == (9, 6)
        assert headers["X-CVW-Output-SHA256"] == hashlib.sha256(body).hexdigest()
        for query in [urlencode({**params, "expected_sha256": "0" * 64}), urlencode({**params, "variant": "huge"}),
                      urlencode(params) + "&path=outside.png", urlencode(params) + "&variant=preview",
                      urlencode({key: value for key, value in params.items() if key != "expected_sha256"})]:
            status, _, body = get(query)
            assert status == 422 and json.loads(body)["error"]["code"] == "artifact-invalid"
    finally:
        _stop_server(server, thread)
    assert len([event for event, _ in events if event == "request"]) == 6

@pytest.mark.parametrize("orientation,expected", [
    (1, [1, 2, 4, 5]), (2, [3, 2, 6, 5]), (3, [6, 5, 3, 2]), (4, [4, 5, 1, 2]),
    (5, [1, 4, 2, 5]), (6, [4, 1, 5, 2]), (7, [6, 3, 5, 2]), (8, [3, 6, 2, 5]),
])
def test_region_preserves_known_samples_with_independent_orientation_oracle(orientation, expected):
    # Literal output oracle; never derives expected pixels using the production affine/crop.
    with Image.new("L", (3, 2)) as source:
        source.putdata([1, 2, 3, 4, 5, 6])
        exif = Image.Exif(); exif[274] = orientation
        with BytesIO() as buffer:
            source.save(buffer, format="PNG", exif=exif)
            payload = buffer.getvalue()
    output, info = images.region_image(payload, "image/png", (0, 0, 2, 2))
    with Image.open(BytesIO(output)) as result:
        assert result.mode == "L" and result.size == (2, 2)
        assert list(result.getdata()) == expected
        assert 274 not in result.getexif()
    assert info["transform"]["resize"] == "none" and info["transform"]["scale_x"] == 1
    assert info["output"]["sha256"] == hashlib.sha256(output).hexdigest()
    assert info["frame"] == 0 and info["page"] is None and info["page_state"] == "not-applicable"
    if orientation == 6:
        plan = images.region_plan(info, (0, 1, 2, 2))
        assert plan["raw_edge_corners"] == [[1, 2], [1, 0], [3, 0], [3, 2]]


@pytest.mark.parametrize("value", ["", "-1,0,1,1", "+1,0,1,1", "0,0,0,1", "0,0,1,0", "0,0,1.5,2", "0,0,NaN,2", "0,0,Infinity,2", "01,0,1,1", "0,0,1,1,1", "0, 0,1,1", "0,0,100000,1"])
def test_region_tuple_is_strict(value):
    with pytest.raises(images.NativeImageError, match="canonical"):
        images.parse_region(value)


@pytest.mark.parametrize("box", [(9, 0, 1, 1), (0, 5, 1, 2), (0, 0, 1281, 1280)])
def test_region_bounds_fail_before_pixel_load(box, monkeypatch):
    payload = encoded((1281, 1280) if box[2] > 1000 else (9, 6))
    monkeypatch.setattr(ImageFile.ImageFile, "load", lambda *args: pytest.fail("Rejected region decoded pixels"))
    with pytest.raises(images.NativeImageError):
        images.region_image(payload, "image/png", box)


@pytest.mark.parametrize("mode", ["1", "L", "LA", "P", "RGB", "RGBA"])
@pytest.mark.parametrize("profile", ["icc", "srgb"])
def test_region_preserves_supported_sample_modes_and_png_color(mode, profile):
    with Image.new(mode, (4, 3)) as source:
        if mode == "P":
            source.putpalette([x for i in range(256) for x in (i, 255-i, i)])
        source.putdata(list(range(12)) if mode in {"L", "P"} else [source.getpixel((0, 0))] * 12)
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add(b"gAMA", (45455).to_bytes(4, "big"))
        pnginfo.add(b"sRGB", b"\0")
        with BytesIO() as buffer:
            source.save(buffer, format="PNG", pnginfo=pnginfo, **({"icc_profile": b"retained-profile"} if profile == "icc" else {}), **({"transparency": 0} if mode == "P" else {}))
            payload = buffer.getvalue()
        expected = [source.getpixel((x, y)) for y in (1, 2) for x in (1, 2)]
    output, info = images.region_image(payload, "image/png", (1, 1, 2, 2))
    with Image.open(BytesIO(output)) as result:
        assert result.mode == mode and list(result.getdata()) == expected
        assert result.info["gamma"] == 0.45455
        if profile == "srgb": assert result.info["srgb"] == 0
        else: assert result.info["icc_profile"] == b"retained-profile"
        if mode == "P":
            assert result.getpalette()[3:6] == [1, 254, 1] and result.info["transparency"] == 0
    assert info["transform"]["mode"] == mode
    assert info["transform"]["decoded_sample_depth"] == (1 if mode == "1" else 8)
    assert "sample_depth" not in info["transform"]


@pytest.mark.parametrize("mode,format,media", [("CMYK", "JPEG", "image/jpeg"), ("I;16", "PNG", "image/png")])
def test_region_refuses_sample_quantization(mode, format, media):
    with Image.new(mode, (2, 2)) as source, BytesIO() as buffer:
        source.save(buffer, format=format)
        payload = buffer.getvalue()
    with pytest.raises(images.NativeImageError) as caught:
        images.region_image(payload, media, (0, 0, 1, 1))
    assert caught.value.code == "image-unsupported"


def test_region_refuses_unsupported_hdr_metadata():
    pnginfo = PngImagePlugin.PngInfo(); pnginfo.add(b"cICP", b"\x01\x01\x00\x01")
    with pytest.raises(images.NativeImageError, match="HDR/color"):
        images.region_image(encoded(pnginfo=pnginfo), "image/png", (0, 0, 1, 1))


@pytest.mark.parametrize("kind,media", [("JPEG", "image/jpeg"), ("WEBP", "image/webp")])
def test_region_adds_no_lossy_step_to_decoded_jpeg_or_webp(kind, media):
    payload = encoded(kind=kind)
    with Image.open(BytesIO(payload)) as source:
        expected = [source.getpixel((x, y)) for y in range(2) for x in range(3)]
    output, _ = images.region_image(payload, media, (0, 0, 3, 2))
    with Image.open(BytesIO(output)) as result:
        assert list(result.getdata()) == expected


def test_independent_region_brief_is_a_plan_then_exact_request_reuses_verified_buffer(evidence_pair, monkeypatch):
    application, selection, source = evidence_pair("source.png", encoded((9, 6), orientation=6))
    selected = identity(application)
    selection.update(right_stage="source", right_recorded=selection["left_recorded"])
    left = {"variant": "region", "region": "0,1,2,3", "source_sha256": selected[4]}
    right = {"variant": "region", "region": "3,4,3,4", "source_sha256": selected[4]}
    with monkeypatch.context() as guard:
        guard.setattr("cvw_app.review_contract.region_image", lambda *args: pytest.fail("Brief generated unrequested pixels"))
        brief = application.compare_view("brief-example", **selection, left_image=left, right_image=right, evidence_brief=True)
    for side, request in (("left", left), ("right", right)):
        plan = brief[side]["image"]["request"]
        assert plan["state"] == "requested-not-generated" and plan["output"]["sha256"] is None
        assert plan["region"] == list(map(int, request["region"].split(",")))
        assert f"{side}_region=" in brief["detail"]["target"]
        assert "variant=region" in plan["target"]
    assert application.compare_view("brief-example", **selection, left_image=right, right_image=left)["route_digest"] != brief["route_digest"]
    from cvw_app.review_contract import RouteStaleError
    with pytest.raises(RouteStaleError):
        application.compare_view("brief-example", **selection, left_image=right, right_image=left, echoed_route_digest=brief["route_digest"])
    with pytest.raises(ReviewContractError, match="sha256"):
        application.compare_view("brief-example", **selection, left_image={**left, "source_sha256": "0"*64})
    original_open = Path.open
    reads = []
    def record_open(path, *args, **kwargs):
        if path == source.resolve(): reads.append(path)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", record_open)
    output, metadata = application.stage_image(*selected, variant="region", region=left["region"])
    assert reads == [source.resolve()]
    assert metadata["source"]["member"]["path"] == source.name
    assert metadata["source"]["sha256"] == selected[4]
    assert metadata["output"]["width"] == 2 and metadata["output"]["height"] == 3
    assert hashlib.sha256(output).hexdigest() == metadata["output"]["sha256"]


def test_http_region_route_and_brief_roundtrip(evidence_pair, tmp_path):
    application, selection, _ = evidence_pair("source.png", encoded())
    selected = identity(application)
    params = dict(expected_artifact=selected[2], expected_version=selected[3], expected_sha256=selected[4], variant="region", region="0,0,2,2")
    base = "/api/review/v1/works/brief-example/stages/source/image?"
    server, thread, _ = _start_server(tmp_path, application=application)
    def get(route):
        connection = http.client.HTTPConnection(*server.server_address, timeout=5)
        try:
            connection.request("GET", route)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally: connection.close()
    try:
        status, headers, body = get(base + urlencode(params))
        assert status == 200 and headers["X-CVW-Output-SHA256"] == hashlib.sha256(body).hexdigest()
        assert json.loads(headers["X-CVW-Image-Metadata"])["region"] == [0, 0, 2, 2]
        for query in [urlencode(params)+"&region=1,1,1,1", urlencode({**params,"variant":"preview"}), urlencode({**params,"region":"9,0,1,1"}), urlencode({k:v for k,v in params.items() if k!="region"})]:
            assert get(base + query)[0] == 422
        query = {"linked":"false", "correspondence":"absent", "left_region":"0,0,2,2", "left_image_sha256":selected[4], "representation":"brief"}
        for side in ("left", "right"):
            recorded = selection[f"{side}_recorded"]
            query.update({f"{side}_stage":selection[f"{side}_stage"], f"{side}_artifact":recorded.artifact_id, f"{side}_version":recorded.version, f"{side}_location":recorded.location})
        route = "/api/review/v1/works/brief-example/compare?"
        status, _, body = get(route + urlencode(query)); assert status == 200
        brief = json.loads(body)
        status, _, body = get(brief["detail"]["target"]); assert status == 200
        assert json.loads(body)["left"]["image_selection"]["region"] == "0,0,2,2"
        for invalid in [{**query,"left_image":"original"}, {k:v for k,v in query.items() if k!="left_image_sha256"}]:
            assert get(route + urlencode(invalid))[0] == 422
        assert get(route + urlencode(query)+"&left_region=1,1,1,1")[0] == 422
    finally: _stop_server(server, thread)
