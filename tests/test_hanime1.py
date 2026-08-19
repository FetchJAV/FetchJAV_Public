import pytest
from M3U8Sites.SiteHanime1 import Hanime1Browser, _filter_url
import locales
import site_i18n


def test_hanime1_sorts():
    expected_sorts = (
        '最新上市', '最新上傳', '本日排行', '本週排行', '本月排行',
        '觀看次數', '讚好比例', '時長最長',
    )
    assert Hanime1Browser.SORTS == expected_sorts


def test_hanime1_categories_only_contain_8_sorts():
    locales.set_lang('en')
    cats = Hanime1Browser.fetch_categories()
    names = [c['name'] for c in cats]
    expected = [
        'Latest Release',
        'Latest Upload',
        'Daily Popular',
        'Weekly Popular',
        'Monthly Popular',
        'Most Viewed',
        'Top Rated',
        'Longest Duration',
    ]
    assert names == expected


def test_hanime1_genres_and_features():
    assert '裏番' in Hanime1Browser.GENRES
    assert '3DCG' in Hanime1Browser.GENRES
    assert '中文字幕' in Hanime1Browser.FEATURE_TAGS
    assert '無碼' in Hanime1Browser.FEATURE_TAGS


def test_hanime1_filter_url():
    url = _filter_url(sort='最新上市')
    assert 'sort=%E6%9C%80%E6%96%B0%E4%B8%8A%E5%B8%82' in url or 'sort=' in url
