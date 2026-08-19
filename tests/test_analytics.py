import pytest
import analytics


def test_client_id():
    cid = analytics.get_client_id()
    assert cid is not None
    assert len(cid) >= 16
    # Second call should return the same cached id
    assert analytics.get_client_id() == cid


def test_track_events():
    analytics.track_app_open(version='0.1.1', lang='en')
    analytics.track_site_switch('HanimeTV')
    analytics.track_preview_open('HanimeTV', 'HLS')
    analytics.track_search('HanimeTV', is_all_sites=False)
    analytics.track_download_start('HanimeTV', '1080')
    analytics.track_download_complete('HanimeTV', 120)


def test_enable_disable():
    analytics.set_enabled(False)
    assert not analytics.is_enabled()
    analytics.track_event('test_disabled')
    analytics.set_enabled(True)
    assert analytics.is_enabled()
