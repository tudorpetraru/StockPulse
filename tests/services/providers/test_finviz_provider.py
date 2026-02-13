from app.services.providers.finviz_provider import _extract_latest_price_target


def test_extract_latest_price_target_handles_arrow_ranges():
    assert _extract_latest_price_target("$325 \u2192 $340") == 340.0
    assert _extract_latest_price_target("$300") == 300.0
    assert _extract_latest_price_target("N/A") is None
