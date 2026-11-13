from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_product_frontend_assets_are_complete():
    html = (FRONTEND / "product.html").read_text(encoding="utf-8")
    js = (FRONTEND / "product.js").read_text(encoding="utf-8")

    for asset in (
        "product.html",
        "product.js",
        "product.css",
        "product-extra.css",
        "place-detail.css",
    ):
        assert (FRONTEND / asset).is_file(), asset

    assert 'lang="zh-CN"' in html
    assert "TripFlow" in html
    assert "首页" in html or "灵感首页" in html
    assert "探索" in html
    assert "我的" in html
    assert "product.js" in html
    assert "product.css" in html
    assert "tripDetail" in html
    assert "activities" in html
    assert "replanCandidates" in html
    assert "versions" in html
    assert "/api/v1/guides/draft" in js
    assert "/api/v1/pois/search" in js
    assert "/api/v2/itineraries/" in js
    assert "delayEvent" in html
    assert "closedEvent" in html
    assert "skipEvent" in html
    assert "route-source" in js
    assert "看差异" in js
