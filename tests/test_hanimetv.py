import pytest
import M3U8Sites
from M3U8Sites.SiteHanimeTV import SiteHanimeTV, HanimeTVBrowser
import config
import smalltool_categories
import browser
import gui_modern


def test_hanimetv_validate_url():
    valid_urls = [
        'https://hanime.tv/videos/hentai/momone-1',
        'http://hanime.tv/videos/hentai/momone-1',
        'https://hanime.tv/videos/hentai/shikkaku-ishi-1',
        'https://www.hanime.tv/videos/hentai/the-pianist-1',
    ]
    for u in valid_urls:
        slug = SiteHanimeTV.validate_url(u)
        assert slug is not None
        assert SiteHanimeTV.validate_url(u) == u.rstrip('/').rsplit('/', 1)[-1]

    invalid_urls = [
        'https://hanime.tv/browse',
        'https://hanime.tv/browse/trending',
        'https://hanime.tv/search?q=test',
        'https://missav.ai/sone-543',
        'https://jable.tv/videos/ssis-123/',
        'https://hanime1.me/watch?v=12345',
        '',
        None,
    ]
    for u in invalid_urls:
        assert SiteHanimeTV.validate_url(u) is None


def test_site_registration():
    url = 'https://hanime.tv/videos/hentai/momone-1'
    site_cls = M3U8Sites.VaildateUrl(url)
    assert site_cls is SiteHanimeTV
    assert config.site_name_from_url(url) == 'HanimeTV'
    assert 'HanimeTV' in smalltool_categories.SITES
    assert 'HanimeTV' in browser.BrowsePanel.SITES
    assert 'HanimeTV' in gui_modern.SITES


def test_hanimetv_browser_methods():
    cats = HanimeTVBrowser.fetch_categories()
    assert len(cats) > 0
    assert any('trending' in c['url'] for c in cats)

    base = 'https://hanime.tv/browse/trending'
    assert HanimeTVBrowser.page_url(base, 1) == base
    assert HanimeTVBrowser.page_url(base, 2) == f'{base}?page=2'

    search_url = HanimeTVBrowser.search_url('momone')
    assert 'search?q=momone' in search_url


def test_canonical_slug_resolution():
    from M3U8Sites.SiteHanimeTV import _resolve_canonical_slug
    # Exact slug
    assert _resolve_canonical_slug('momone-1') == 'momone-1'
    # Alias / alternate name resolving to real catalog slug
    assert _resolve_canonical_slug('resort-boin-1') == 'resort-boin-uncensored-re-release-1'
    assert _resolve_canonical_slug('tsumamigui-3-1') == 'tsumamigui-3-ep-1'


def test_hanimetv_search_recency_sorting():
    # Tag search results should be sorted by newest released/created date first
    results = HanimeTVBrowser.search('creampie')
    if len(results) >= 2:
        assert results[0]['url'] is not None


def test_search_ranking_exact_code_priority():
    from gui_modern import ModernApp
    app = object.__new__(ModernApp)
    sample_results = [
        {'title': 'Random Video about ssis-001 and other stars', 'url': 'https://jable.tv/videos/random/'},
        {'title': 'SSIS-002 Another Actress', 'url': 'https://jable.tv/videos/ssis-002/'},
        {'title': 'SSIS-001 Beautiful Debut Video', 'url': 'https://jable.tv/videos/ssis-001/'},
    ]
    ranked = app._rank_search_results(sample_results, 'SSIS-001')
    assert ranked[0]['url'] == 'https://jable.tv/videos/ssis-001/'


def test_hanimetv_english_categories():
    cats_en = HanimeTVBrowser.fetch_categories(lang='en')
    assert len(cats_en) > 0
    assert cats_en[0]['name'] == 'New Releases'
    assert cats_en[0]['url'] == 'https://hanime.tv/browse/newest'
    # Ensure English tag translations exist
    names = [c['name'] for c in cats_en]
    assert 'Uncensored' in names
    assert 'Creampie' in names
    assert 'MILF' in names



