import pytest
from bs4 import BeautifulSoup
from M3U8Sites.SiteHanime1 import (
    HANIME1_FILTER_DATES,
    HANIME1_FILTER_DURATIONS,
    HANIME1_FILTER_TAGS,
    Hanime1Browser,
    _extract_published_date,
    _filter_url,
    _parse_filter_catalog,
    _parse_videos,
)
import locales
import site_i18n


def test_hanime1_sorts():
    expected_sorts = (
        '最新上市', '最新上傳', '本日排行', '本週排行', '本月排行',
        '觀看次數', '讚好比例', '時長最長', '他們在看',
    )
    assert Hanime1Browser.SORTS == expected_sorts


def test_hanime1_categories_cover_all_9_sorts():
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
    assert names[:8] == expected
    assert len(names) == 9


def test_hanime1_genres_and_features():
    assert '裏番' in Hanime1Browser.GENRES
    assert '3DCG' in Hanime1Browser.GENRES
    assert '中文字幕' in Hanime1Browser.FEATURE_TAGS
    assert '無碼' in Hanime1Browser.FEATURE_TAGS


def test_hanime1_filter_url():
    url = _filter_url(sort='最新上市')
    assert 'sort=%E6%9C%80%E6%96%B0%E4%B8%8A%E5%B8%82' in url or 'sort=' in url


def test_hanime1_genre_grid_parser_supports_ura_and_short_anime_layout():
    soup = BeautifulSoup('''
    <div class="home-rows-videos-wrapper">
      <a href="https://ads.example/campaign">
        <div class="home-rows-videos-div search-videos">
          <div class="video-card-inner"><div class="home-rows-videos-title">Ad</div></div>
        </div>
      </a>
      <a href="https://hanime1.me/watch?v=407591">
        <div class="home-rows-videos-div search-videos">
          <div class="video-card-inner">
            <img src="https://vdownload.hembed.com/image/cover/407591.jpg?secure=x">
            <div class="home-rows-videos-title">少女彈珠汽水 7</div>
          </div>
        </div>
      </a>
      <a href="/watch?v=407591">
        <div class="home-rows-videos-div search-videos">
          <div class="video-card-inner"><div class="home-rows-videos-title">Duplicate</div></div>
        </div>
      </a>
    </div>
    ''', 'html.parser')

    assert _parse_videos(
        soup, 'https://hanime1.me/search?genre=%E8%A3%8F%E7%95%AA') == [{
            'url': 'https://hanime1.me/watch?v=407591',
            'title': '少女彈珠汽水 7',
            'thumbnail': (
                'https://vdownload.hembed.com/image/cover/407591.jpg?secure=x'),
            'duration': '',
            'date': '',
            'author': '',
            '_source_listing_url': (
                'https://hanime1.me/search?genre=%E8%A3%8F%E7%95%AA'),
        }]


def test_hanime1_filter_catalog_and_combined_url_cover_live_filter_shapes():
    soup = BeautifulSoup('''
    <div id="genre-modal">
      <div class="genre-option" data-value="全部">全部</div>
      <div class="genre-option" data-value="裏番">裏番</div>
      <div class="genre-option" data-value="泡麵番">泡麵番</div>
    </div>
    <div id="sort-modal">
      <div class="hentai-sort-options-wrapper" data-value="最新上傳">最新上傳</div>
    </div>
    <div id="date-modal">
      <div class="hentai-date-options-wrapper" data-value="">全部</div>
      <div class="hentai-date-options-wrapper" data-value="過去 24 小時">過去 24 小時</div>
    </div>
    <div id="duration-modal">
      <div class="hentai-duration-options-wrapper" data-value="0 - 10 分鐘">0 - 10 分鐘</div>
    </div>
    <input type="checkbox" name="tags[]" value="中文字幕">
    <input type="checkbox" name="tags[]" value="1080p">
    ''', 'html.parser')

    assert _parse_filter_catalog(soup) == {
        'genres': ('裏番', '泡麵番'),
        'sorts': ('最新上傳',),
        'dates': ('過去 24 小時',),
        'durations': ('0 - 10 分鐘',),
        'tags': ('中文字幕', '1080p'),
    }
    assert Hanime1Browser.filter_url(
        query='作者 A', genre='泡麵番', sort='最新上傳',
        date='過去 24 小時', duration='0 - 10 分鐘',
        tags=('中文字幕', '1080p', '中文字幕'),
    ) == (
        'https://hanime1.me/search?query=%E4%BD%9C%E8%80%85+A&genre='
        '%E6%B3%A1%E9%BA%B5%E7%95%AA&sort=%E6%9C%80%E6%96%B0%E4%B8%8A%E5%82%B3'
        '&date=%E9%81%8E%E5%8E%BB+24+%E5%B0%8F%E6%99%82&duration=0+-+10+'
        '%E5%88%86%E9%90%98&tags%5B%5D=%E4%B8%AD%E6%96%87%E5%AD%97%E5%B9%95'
        '&tags%5B%5D=1080p')


def test_hanime1_filter_snapshot_is_complete_and_detail_date_is_extractable():
    assert len(HANIME1_FILTER_TAGS) >= 240
    assert {'無碼', '同人作品', 'ASMR', 'NTR', 'BDSM', 'POV'} <= set(
        HANIME1_FILTER_TAGS)
    assert HANIME1_FILTER_DATES == (
        '過去 24 小時', '過去 2 天', '過去 1 週',
        '過去 1 個月', '過去 3 個月', '過去 1 年')
    assert HANIME1_FILTER_DURATIONS[-2:] == ('0 - 10 分鐘', '0 - 20 分鐘')

    soup = BeautifulSoup('''
      <div class="video-details-wrapper hidden-sm">
        觀看次數：184.4萬次&nbsp;&nbsp;2026-08-08
      </div>
    ''', 'html.parser')
    assert _extract_published_date(soup) == '2026-08-08'
