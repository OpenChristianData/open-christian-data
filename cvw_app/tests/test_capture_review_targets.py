import pytest

from cvw_app.capture_review import CaptureError, locate_target, validate_targets


def spec(**overrides):
    return {
        "scope_selector": "pre",
        "scope_prefix": "Source slot 00004:",
        "literal": "real meaning",
        "occurrence": 0,
        **overrides,
    }


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"left": spec()},
        {"left": spec(), "right": spec(), "extra": spec()},
        {"left": spec(occurrence=True), "right": spec()},
        {"left": spec(occurrence=-1), "right": spec()},
        {"left": spec(literal=""), "right": spec()},
        {"left": spec(unexpected="x"), "right": spec()},
    ],
)
def test_validate_targets_rejects_incomplete_or_invalid_specs(value):
    with pytest.raises(CaptureError):
        validate_targets(value)


def test_validate_targets_accepts_exact_pair():
    targets = {"left": spec(), "right": spec(occurrence=1)}
    assert validate_targets(targets) == targets


@pytest.mark.parametrize(
    "result, message",
    [
        ({"error": "scope absent", "count": 0}, "scope absent"),
        ({"error": "ambiguous scope", "count": 2}, "ambiguous scope"),
        ({"error": "target occurrence absent", "count": 1}, "occurrence absent"),
        ({"visible": False}, "clipped"),
    ],
)
def test_locate_target_fails_closed(result, message):
    class Page:
        def evaluate(self, _script, _arguments):
            return result

    with pytest.raises(CaptureError, match=message):
        locate_target(Page(), "left", spec())


def test_locate_target_returns_measured_visible_anchor():
    expected = {
        "literal": "real meaning",
        "scope_selector": "pre",
        "scope_prefix": "Source slot 00004:",
        "match_count": 2,
        "occurrence": 1,
        "rect": {"top": 20, "bottom": 40},
        "scroll": {"after": {"scrollTop": 500, "scrollHeight": 2000, "clientHeight": 600}},
        "visible": True,
    }

    class Page:
        def evaluate(self, _script, _arguments):
            return expected

    assert locate_target(Page(), "right", spec(occurrence=1)) == expected


def test_capture_target_outside_browser_viewport_fails_closed():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_content('''<div style="height:1286px"></div>
            <div data-review-side="left"><article class="artifact-content">
            <pre>Source slot 00004: real meaning</pre></article></div>''')
        with pytest.raises(CaptureError, match="clipped"):
            locate_target(page, "left", spec())
        browser.close()


@pytest.mark.parametrize("separation", [360, 1400])
def test_capture_frame_checks_both_final_targets(separation):
    import io

    from PIL import Image
    from playwright.sync_api import sync_playwright

    from cvw_app.capture_review import capture_target_frame

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_content(f'''<style>body {{margin:0;height:4000px}}
            article {{position:absolute;width:500px;height:200px;overflow:auto}}
            pre {{margin:0}} .space {{height:500px}}</style>
            <div data-review-side="left"><article class="artifact-content"
              style="top:1286px;left:100px"><div class="space"></div>
              <pre>Source slot 00004: real meaning</pre><div class="space"></div>
            </article></div>
            <div data-review-side="right"><article class="artifact-content"
              style="top:{1286 + separation}px;left:800px"><div class="space"></div>
              <pre>Source slot 00004: real meaning</pre><div class="space"></div>
            </article></div>''')
        targets = {
            side: spec(scope_selector=f'[data-review-side="{side}"] pre')
            for side in ("left", "right")
        }
        if separation > 1000:
            with pytest.raises(CaptureError, match="clipped"):
                capture_target_frame(page, targets)
        else:
            evidence, png = capture_target_frame(page, targets)
            with Image.open(io.BytesIO(png)) as frame:
                assert frame.size == (1440, 1000)
            for side in ("left", "right"):
                measured = locate_target(page, side, targets[side], scroll=False)
                assert evidence[side]["rect"] == measured["rect"]
                assert evidence[side]["visible"] is True
                assert 0 <= measured["rect"]["top"] < measured["rect"]["bottom"] <= 1000
                assert 0 <= measured["rect"]["left"] < measured["rect"]["right"] <= 1440
        browser.close()
