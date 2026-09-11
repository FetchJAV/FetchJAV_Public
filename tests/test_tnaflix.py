import pytest
from bs4 import BeautifulSoup
from M3U8Sites.SiteTnaFlix import (
    SiteTnaFlix,
    TnaFlixBrowser,
    _extract_mp4_sources,
    _extract_source_height,
    _select_source,
    _parse_cards,
)
from video_preview import resolve_preview_source


def test_tnaflix_validate_url():
    valid_urls = [
        'https://www.tnaflix.com/amateur-porn/asian_porn_uncensored_00.59.09.973.mp4/video11893095',
        'http://tnaflix.com/hd-videos/Reinfected-libido/video4205955',
        'https://www.tnaflix.com/video9050525',
        'https://www.tnaflix.com/asian-porn/sample/video12345?from=search',
    ]
    for u in valid_urls:
        vid_id = SiteTnaFlix.validate_url(u)
        assert vid_id is not None
        assert vid_id.isdigit()

    invalid_urls = [
        'https://www.tnaflix.com/featured',
        'https://www.tnaflix.com/categories',
        'https://missav.ai/dm123/en',
        '',
        None,
    ]
    for u in invalid_urls:
        assert SiteTnaFlix.validate_url(u) is None


def test_tnaflix_extract_source_height():
    soup = BeautifulSoup('''
    <video id="video-player">
      <source size="1080" src="https://sl.tnaflix.com/video-1080p_60fps.mp4" type="video/mp4"/>
      <source size="720" src="https://sl.tnaflix.com/video-720p.mp4" type="video/mp4"/>
      <source size="480" src="https://sl.tnaflix.com/video-480p.mp4" type="video/mp4"/>
      <source size="360" src="https://sl.tnaflix.com/video-360p.mp4" type="video/mp4"/>
    </video>
    ''', 'html.parser')
    sources = _extract_mp4_sources(soup)
    assert len(sources) == 4
    assert sources[0]['height'] == 1080
    assert sources[1]['height'] == 720
    assert sources[2]['height'] == 480
    assert sources[3]['height'] == 360


def test_tnaflix_select_source_resolution():
    sources = [
        {'url': 'https://sl.tnaflix.com/video-1080p.mp4', 'height': 1080},
        {'url': 'https://sl.tnaflix.com/video-720p.mp4', 'height': 720},
        {'url': 'https://sl.tnaflix.com/video-480p.mp4', 'height': 480},
        {'url': 'https://sl.tnaflix.com/video-360p.mp4', 'height': 360},
    ]
    assert _select_source(sources, '')['height'] == 1080
    assert _select_source(sources, '720')['height'] == 720
    assert _select_source(sources, '480')['height'] == 480
    assert _select_source(sources, 'lowest')['height'] == 360


def test_tnaflix_is_url_vaildate():
    s = SiteTnaFlix('https://www.tnaflix.com/amateur-porn/test/video12345')
    s._direct_url = None
    s._m3u8url = None
    assert not s.is_url_vaildate()

    s._direct_url = 'https://sl.tnaflix.com/video-1080p.mp4'
    assert s.is_url_vaildate()


def test_tnaflix_preview_source_resolution(monkeypatch):
    test_url = 'https://www.tnaflix.com/amateur-porn/test/video12345'
    mock_html = '''<html>
      <head>
        <meta property="og:title" content="Test TnaFlix Video Title"/>
        <meta property="og:image" content="https://img.tnaflix.com/thumb.jpg"/>
      </head>
      <body>
        <video id="video-player">
          <source size="1080" src="https://sl187.tnaflix.com/video-1080p.mp4" type="video/mp4"/>
        </video>
      </body>
    </html>'''
    class MockResponse:
        status_code = 200
        text = mock_html
        content = mock_html.encode('utf-8')

    monkeypatch.setattr('M3U8Sites.SiteTnaFlix._request', lambda session, url, **kw: MockResponse())

    src = resolve_preview_source(test_url)
    assert not src.error
    assert src.media_kind == 'mp4'
    assert src.media_url == 'https://sl187.tnaflix.com/video-1080p.mp4'
    assert src.title == 'Test TnaFlix Video Title'
    assert src.thumbnail == 'https://img.tnaflix.com/thumb.jpg'
    assert 'Referer' in src.headers


def test_tnaflix_browser_endpoints():
    s_url = TnaFlixBrowser.search_url('asian beauty')
    assert 'search.php?what=' in s_url
    assert 'asian' in s_url

    cat_p2 = TnaFlixBrowser.page_url('https://www.tnaflix.com/asian-porn', 2)
    assert cat_p2 == 'https://www.tnaflix.com/asian-porn/2'

    search_p2 = TnaFlixBrowser.page_url('https://www.tnaflix.com/search.php?what=asian', 2)
    assert 'page=2' in search_p2

    cats = TnaFlixBrowser.fetch_categories()
    assert len(cats) >= 40
    assert any('Amateur' in c['name'] for c in cats)

    sidebar_groups = TnaFlixBrowser.SIDEBAR_TAG_GROUPS
    assert 'Featured & Trending' in sidebar_groups
    assert 'Popular Categories' in sidebar_groups
    assert 'Ethnicity & Region' in sidebar_groups
    assert 'Appearance & Types' in sidebar_groups
    assert 'Acts & Fetishes' in sidebar_groups


def test_tnaflix_parse_cards_thumbnail_ignores_placeholder():
    soup = BeautifulSoup('''
    <div class="col-xs-6">
      <a href="/amateur-porn/test-video/video12345">
        <img class="lazyload" src="/assets/img/video_cover_placeholder.jpg" data-src="https://img.tnaflix.com/thumb/real_12345.jpg" alt="Test Title"/>
        <span class="video-duration">12:34</span>
      </a>
    </div>
    ''', 'html.parser')
    cards = _parse_cards(soup)
    assert len(cards) == 1
    assert cards[0]['thumbnail'] == 'https://img.tnaflix.com/thumb/real_12345.jpg'
    assert 'placeholder' not in cards[0]['thumbnail']
    assert cards[0]['title'] == 'Test Title'

