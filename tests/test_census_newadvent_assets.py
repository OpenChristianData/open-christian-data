import hashlib
import json

from build.tools.census_newadvent_assets import inventory


def test_source_images_links_and_unresolved_assets_are_separate_from_navigation(tmp_path):
    payload = b'<html><body><img src="../images/logo.gif"><link rel="stylesheet" href="../utility/screen6.css"><div id="springfield2"><p><a href="../images/full.jpg"><img src="../images/thumb.jpg" alt="Plan"></a><img src="https://other.example/a.png"><img srcset="a.png 1x,b.png 2x"></p></div><div id="ogdenville"><p>Footer</p></div></body></html>'
    (tmp_path / "000001.html").write_bytes(payload)
    url = "https://www.newadvent.org/cathen/01001a.htm"
    receipt = {"contract": "ocd-newadvent-retained-cohort-v1", "members": [{"url": url, "final_url": url, "http_status": 200, "status": "retained", "path": "000001.html", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]}
    (tmp_path / "acquisition.json").write_text(json.dumps(receipt), encoding="utf-8")
    result = inventory([tmp_path])
    assert result["image_urls"] == ["https://www.newadvent.org/images/full.jpg", "https://www.newadvent.org/images/thumb.jpg"]
    assert len(result["unresolved"]) == 2
    assert result["occurrences"][0]["disposition"] == "excluded-site-navigation-image"
    assert result["work_completeness_established"] is False
    assert result["stylesheet_urls"] == ["https://www.newadvent.org/utility/screen6.css"]
