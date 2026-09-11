import itertools

import pytest

from video_identity import (
    DEFAULT_VERSION_PREFERENCE,
    MAX_SOURCE_SUBTITLE_EVIDENCE_TEXT,
    SUBTITLE_BADGE_COLORS,
    SUBTITLE_BADGE_ORDER,
    TRUSTED_CHINESE_SUBTITLE_EVIDENCE,
    VALID_VERSION_PREFERENCES,
    badge_langs_from_label,
    canonical_code,
    dedupe_video_candidates,
    detect_dub_langs,
    detect_subtitle_langs,
    detect_video_card_badges,
    normalize_source_subtitle_evidence,
    normalize_version_preference,
    site_from_url,
    trusted_chinese_subtitle_evidence,
    video_code,
    video_versions,
)


@pytest.mark.parametrize(('raw', 'expected'), [
    ('IPZZ-905', 'ipzz-905'),
    ('[Chinese Subtitles] SNOS-223', 'snos-223'),
    ('FC2PPV 4931572', 'fc2-ppv-4931572'),
    ('FC2-PPV-1657563', 'fc2-ppv-1657563'),
    ('020121_429-paco', '020121-429'),
    ('1pondo-123456_789', '1pondo-123456-789'),
    ('HEYZO-1234 sample title', 'heyzo-1234'),
    ('random article 440577', ''),
    ('no confirmed code', ''),
])
def test_canonical_code_only_returns_confirmed_code_shapes(raw, expected):
    assert canonical_code(raw) == expected


@pytest.mark.parametrize(('video', 'expected'), [
    ({'_site': 'JableTV', 'url': 'https://jable.tv/videos/IPZZ-905/'},
     'ipzz-905'),
    ({'_site': 'MissAV',
      'url': 'https://missav.ai/cn/mimk-284-chinese-subtitle'},
     'mimk-284'),
    ({'_site': 'MissAV',
      'url': 'https://missav.ai/mimk-284-uncensored-leak'},
     'mimk-284'),
    ({'_site': 'SupJav', 'url': 'https://supjav.com/440577.html',
      'title': '[Reducing Mosaic] IPZZ-905'},
     'ipzz-905'),
    ({'_site': 'SupJav', 'url': 'https://supjav.com/440578.html',
      'title': 'FC2PPV 4931572'},
     'fc2-ppv-4931572'),
    ({'_site': 'SupJav', 'url': 'https://supjav.com/440579.html',
      'title': 'random article 440577'},
     ''),
])
def test_video_code_uses_site_specific_evidence(video, expected):
    assert video_code(video) == expected


@pytest.mark.parametrize(('url', 'expected'), [
    ('https://jable.tv/videos/ipzz-905/', 'JableTV'),
    ('https://cn.jable.tv/videos/ipzz-905/', 'JableTV'),
    ('https://missav.ai/mimk-284', 'MissAV'),
    ('https://missav.ws/mimk-284', 'MissAV'),
    ('https://supjav.com/440577.html', 'SupJav'),
    ('https://example.com/ipzz-905', ''),
])
def test_site_from_url(url, expected):
    assert site_from_url(url) == expected


@pytest.mark.parametrize(('video', 'expected'), [
    ({
        'url': 'https://missav.ai/cn/mimk-284-chinese-subtitle',
    }, ('missav-url-chinese-subtitle',)),
    ({
        'url': 'https://missav.ai/cn/mimk-284-chinese-subtitles',
    }, ('missav-url-chinese-subtitle',)),
    ({
        '_site': 'JableTV',
        '_target_id': 'category:chinese-subtitle',
        'url': 'https://jable.tv/videos/ipzz-905/',
    }, ('jable-category-chinese-subtitle',)),
    ({
        '_site': 'MissAV',
        '_target_id': 'feed:chinese-subtitle',
        'url': 'https://missav.ws/ipzz-905',
    }, ('missav-category-chinese-subtitle',)),
    ({
        '_site': 'SupJav',
        '_target_id': 'category:chinese-subtitles',
        'url': 'https://supjav.com/440577.html',
    }, ('supjav-category-chinese-subtitle',)),
    ({
        '_site': 'JableTV',
        'url': 'https://jable.tv/videos/ipzz-905/',
        '_source_listing_url':
            'https://jable.tv/categories/chinese-subtitle/',
    }, ('jable-category-chinese-subtitle',)),
    ({
        '_site': 'MissAV',
        'url': 'https://missav.ai/ipzz-905',
        '_source_listing_url':
            'https://missav.ai/dm278/cn/chinese-subtitle',
    }, ('missav-category-chinese-subtitle',)),
    ({
        '_site': 'SupJav',
        'url': 'https://supjav.com/440577.html',
        '_source_listing_url':
            'https://supjav.com/zh/category/chinese-subtitles',
    }, ('supjav-category-chinese-subtitle',)),
])
def test_trusted_chinese_subtitle_evidence_uses_structural_source_signals(
        video, expected):
    assert trusted_chinese_subtitle_evidence(video) == expected


@pytest.mark.parametrize('video', [
    # /cn/ controls the MissAV site language; it is not subtitle evidence.
    {'url': 'https://missav.ai/cn/mimk-284'},
    # Display-title heuristics remain useful for browse badges/deduplication
    # but are intentionally too weak to suppress requested work.
    {'url': 'https://supjav.com/1.html',
     'title': '[Chinese Subtitles] IPZZ-905'},
    {'url': 'https://jable.tv/videos/ipzz-905/',
     'title': 'A discussion about 中文字幕'},
    {'url': 'https://jable.tv/videos/ipzz-905-c/'},
    {
        '_site': 'JableTV',
        '_target_id': 'feed:latest',
        'url': 'https://jable.tv/videos/ipzz-905/',
    },
    {
        '_site': 'MissAV',
        '_target_id': 'feed:latest',
        'url': 'https://missav.ai/ipzz-905',
    },
    {
        '_site': 'SupJav',
        '_target_id': 'category:reducing-mosaic',
        'url': 'https://supjav.com/1.html',
    },
    {
        '_site': 'MissAV',
        'url': 'https://missav.ai/ipzz-905',
        '_hls_subtitle_renditions': [
            {'language': 'zh', 'uri': 'subtitles/zh.m3u8'},
        ],
    },
    {'url': 'https://missav.evil.example/ipzz-905-chinese-subtitle'},
    {'url': 'https://example.test/ipzz-905-chinese-subtitle'},
    {'url': 'http://missav.ai/ipzz-905-chinese-subtitle'},
    {
        '_site': 'JableTV',
        '_target_id': 'category:chinese-subtitle',
    },
    {
        'url': 'https://evil.jable.tv/videos/ipzz-905/',
        '_source_subtitle_evidence':
            'jable-category-chinese-subtitle',
    },
    {
        'url': 'https://missav.evil.example/ipzz-905',
        '_source_subtitle_evidence':
            'missav-category-chinese-subtitle',
    },
    {
        'url': 'https://supjav.evil.example/1.html',
        '_source_subtitle_evidence':
            'supjav-category-chinese-subtitle',
    },
    {
        '_site': 'SupJav',
        'url': 'https://supjav.com/1.html',
        '_source_listing_url':
            'http://supjav.com/category/chinese-subtitles',
    },
    {
        '_site': 'JableTV',
        '_target_id': 'category:chinese-subtitle',
        'url': 'https://supjav.com/1.html',
    },
])
def test_trusted_chinese_subtitle_evidence_fails_closed(video):
    assert trusted_chinese_subtitle_evidence(video) == ()


def test_source_subtitle_evidence_normalizer_is_allowlisted_and_bounded():
    expected = tuple(sorted(TRUSTED_CHINESE_SUBTITLE_EVIDENCE))
    assert normalize_source_subtitle_evidence(
        '|'.join(reversed(expected))) == expected
    assert normalize_source_subtitle_evidence(
        ['missav-url-chinese-subtitle', 'forged']) == (
            'missav-url-chinese-subtitle',)
    assert normalize_source_subtitle_evidence(
        'x' * (MAX_SOURCE_SUBTITLE_EVIDENCE_TEXT + 1)) == ()
    assert normalize_source_subtitle_evidence(
        ['missav-url-chinese-subtitle']
        * (len(TRUSTED_CHINESE_SUBTITLE_EVIDENCE) + 1)) == ()
    assert normalize_source_subtitle_evidence(
        '|'.join(
            ['missav-url-chinese-subtitle']
            * (len(TRUSTED_CHINESE_SUBTITLE_EVIDENCE) + 1))) == ()


@pytest.mark.parametrize(('video', 'expected'), [
    ({'_target_id': 'category:chinese-subtitle'}, {'chinese-subtitle'}),
    ({'_target_id': 'feed:chinese-subtitle'}, {'chinese-subtitle'}),
    ({'_target_id': 'category:uncensored'}, {'uncensored'}),
    ({'_target_id': 'feed:uncensored-leak'}, {'uncensored'}),
    ({'_target_id': 'category:censored'}, {'standard'}),
    ({'_target_id': 'category:english-subtitles'}, {'english-subtitle'}),
    ({'_target_id': 'category:reducing-mosaic'}, {'reducing-mosaic'}),
    ({'url': 'https://missav.ai/mimk-284-chinese-subtitle'},
     {'chinese-subtitle'}),
    ({'url': 'https://missav.ai/mimk-284-uncensored-leak'},
     {'uncensored'}),
    ({'title': '[English Subtitles] FSDSS-622'}, {'english-subtitle'}),
    ({'title': '[Reduced Mosaic] IPZZ-905'}, {'reducing-mosaic'}),
    ({'title': '[Uncensored] FC2PPV 4937463'}, {'uncensored'}),
    ({'title': 'DLDSS-507'}, {'standard'}),
])
def test_video_versions_cover_all_supported_sources(video, expected):
    assert video_versions(video) == expected


def _version_candidates():
    return [
        {'_site': 'JableTV', '_target_id': 'category:chinese-subtitle',
         'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905'},
        {'_site': 'MissAV', '_target_id': 'feed:uncensored-leak',
         'url': 'https://missav.ai/ipzz-905-uncensored-leak',
         'title': 'IPZZ-905'},
        {'_site': 'MissAV', '_target_id': 'feed:latest',
         'url': 'https://missav.ai/ipzz-905', 'title': 'IPZZ-905'},
        {'_site': 'SupJav', '_target_id': 'category:english-subtitles',
         'url': 'https://supjav.com/440576.html',
         'title': '[English Subtitles] IPZZ-905'},
        {'_site': 'SupJav', '_target_id': 'category:reducing-mosaic',
         'url': 'https://supjav.com/440577.html',
         'title': '[Reducing Mosaic] IPZZ-905'},
    ]


@pytest.mark.parametrize(('preference', 'expected_url'), [
    ('chinese-subtitle', 'https://jable.tv/videos/ipzz-905/'),
    ('uncensored', 'https://missav.ai/ipzz-905-uncensored-leak'),
    ('standard', 'https://missav.ai/ipzz-905'),
    ('english-subtitle', 'https://supjav.com/440576.html'),
    ('reducing-mosaic', 'https://supjav.com/440577.html'),
])
def test_preference_wins_across_sources_regardless_of_scan_order(
        preference, expected_url):
    candidates = _version_candidates()
    for order in itertools.permutations(candidates):
        kept, decisions = dedupe_video_candidates(
            [dict(video) for video in order], preference)
        assert [video['url'] for video in kept] == [expected_url]
        assert len(decisions) == len(candidates) - 1


def test_same_url_across_categories_unions_version_evidence():
    latest = {
        '_site': 'JableTV', '_target_id': 'feed:latest',
        'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905',
    }
    chinese = {
        '_site': 'JableTV', '_target_id': 'category:chinese-subtitle',
        'url': latest['url'], 'title': 'IPZZ-905',
    }
    standard_elsewhere = {
        '_site': 'MissAV', '_target_id': 'feed:latest',
        'url': 'https://missav.ai/ipzz-905', 'title': 'IPZZ-905',
    }

    kept, _ = dedupe_video_candidates(
        [latest, standard_elsewhere, chinese], 'chinese-subtitle')

    assert kept == [latest]
    assert latest['_versions'] == ['chinese-subtitle']
    assert chinese['_versions'] == ['chinese-subtitle']
    assert latest['_source_subtitle_evidence'] == (
        'jable-category-chinese-subtitle',)
    assert chinese['_source_subtitle_evidence'] == (
        'jable-category-chinese-subtitle',)
    assert trusted_chinese_subtitle_evidence(latest) == (
        'jable-category-chinese-subtitle',)


def test_same_url_title_heuristic_does_not_become_source_subtitle_evidence():
    plain = {
        '_site': 'JableTV', '_target_id': 'feed:latest',
        'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905',
    }
    title_only = {
        '_site': 'JableTV', '_target_id': 'feed:latest',
        'url': plain['url'], 'title': '[Chinese Subtitles] IPZZ-905',
    }

    kept, _ = dedupe_video_candidates(
        [plain, title_only], 'chinese-subtitle')

    assert kept == [plain]
    assert trusted_chinese_subtitle_evidence(plain) == ()


def test_same_version_cross_site_tie_has_stable_source_order():
    candidates = [
        {'_site': 'SupJav', '_target_id': 'category:chinese-subtitles',
         'url': 'https://supjav.com/1.html', 'title': 'IPZZ-905'},
        {'_site': 'MissAV', '_target_id': 'feed:chinese-subtitle',
         'url': 'https://missav.ai/ipzz-905-chinese-subtitle',
         'title': 'IPZZ-905'},
        {'_site': 'JableTV', '_target_id': 'category:chinese-subtitle',
         'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905'},
    ]
    for order in itertools.permutations(candidates):
        kept, _ = dedupe_video_candidates(
            [dict(video) for video in order], 'chinese-subtitle')
        assert kept[0]['_site'] == 'JableTV'


def test_successful_preferred_download_prevents_cross_site_redownload():
    existing = {
        '_site': 'JableTV', '_target_id': 'category:chinese-subtitle',
        'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905',
        '_already_seen': True,
    }
    new = {
        '_site': 'MissAV', '_target_id': 'feed:chinese-subtitle',
        'url': 'https://missav.ai/ipzz-905-chinese-subtitle',
        'title': 'IPZZ-905',
    }

    kept, _ = dedupe_video_candidates(
        [existing, new], 'chinese-subtitle')

    assert kept == [existing]


def test_new_preferred_version_can_upgrade_prior_unpreferred_download():
    existing = {
        '_site': 'JableTV', '_target_id': 'feed:latest',
        'url': 'https://jable.tv/videos/ipzz-905/', 'title': 'IPZZ-905',
        '_already_seen': True,
    }
    new = {
        '_site': 'SupJav', '_target_id': 'category:reducing-mosaic',
        'url': 'https://supjav.com/440577.html', 'title': 'IPZZ-905',
    }

    kept, _ = dedupe_video_candidates([existing, new], 'reducing-mosaic')

    assert kept == [new]


def test_unconfirmed_codes_only_dedupe_by_exact_url():
    first = {'_site': 'SupJav', 'url': 'https://example.com/a',
             'title': 'unknown release'}
    same_url = {'_site': 'MissAV', 'url': 'https://example.com/a',
                'title': 'another unknown release'}
    different_url = {'_site': 'JableTV', 'url': 'https://example.com/b',
                     'title': 'unknown release'}

    kept, decisions = dedupe_video_candidates(
        [first, same_url, different_url], DEFAULT_VERSION_PREFERENCE)

    assert [video['url'] for video in kept] == [
        'https://example.com/a', 'https://example.com/b']
    assert len(decisions) == 1


@pytest.mark.parametrize('value', [None, '', 'bogus', object()])
def test_invalid_preferences_fall_back_to_chinese(value):
    assert normalize_version_preference(value) == DEFAULT_VERSION_PREFERENCE


def test_legacy_uncensored_value_is_normalized():
    assert normalize_version_preference('uncensored-leak') == 'uncensored'
    assert VALID_VERSION_PREFERENCES == {
        'chinese-subtitle', 'uncensored', 'standard',
        'english-subtitle', 'reducing-mosaic',
    }


@pytest.mark.parametrize(('label', 'expected'), [
    ('zh', ('CH',)),
    ('zh-TW', ('CH',)),
    ('zh-CN', ('CH',)),
    ('繁體中文', ('CH',)),
    ('簡體中文', ('CH',)),
    ('中文字幕', ('CH',)),
    ('en', ('EN',)),
    ('English', ('EN',)),
    ('eng', ('EN',)),
    ('ja-en', ('EN',)),
    ('ja', ('JA',)),
    ('Japanese', ('JA',)),
    ('日本語', ('JA',)),
    ('ko', ('KO',)),
    ('Korean', ('KO',)),
    ('韓文', ('KO',)),
    ('', ()),
    ('unknown', ()),
])
def test_badge_langs_from_label(label, expected):
    assert badge_langs_from_label(label) == expected


def test_subtitle_badge_colors_and_order():
    assert 'EN' in SUBTITLE_BADGE_COLORS
    assert 'JA' in SUBTITLE_BADGE_COLORS
    assert 'CH' in SUBTITLE_BADGE_COLORS
    assert 'KO' in SUBTITLE_BADGE_COLORS
    assert 'EN' in SUBTITLE_BADGE_ORDER
    assert 'JA' in SUBTITLE_BADGE_ORDER
    assert 'CH' in SUBTITLE_BADGE_ORDER


@pytest.mark.parametrize(('video', 'expected'), [
    # Chinese subtitle in title
    ({'title': 'IPZZ-905 [中文字幕]', 'url': 'https://jable.tv/videos/ipzz-905/'}, ('CH',)),
    ({'title': 'SNOS-223 【中字】', 'url': 'https://jable.tv/videos/snos-223/'}, ('CH',)),
    ({'title': 'MIDE-123 (中字)', 'url': 'https://jable.tv/videos/mide-123/'}, ('CH',)),
    ({'title': 'IPX-456 繁中', 'url': 'https://jable.tv/videos/ipx-456/'}, ('CH',)),
    ({'title': 'IPX-789 [Chinese Subtitles]', 'url': 'https://supjav.com/789.html'}, ('CH',)),
    # Chinese subtitle in URL
    ({'title': 'mimk-284', 'url': 'https://missav.ai/cn/mimk-284-chinese-subtitle'}, ('CH',)),
    ({'title': 'ipzz-905', 'url': 'https://jable.tv/videos/ipzz-905-c/'}, ('CH',)),
    ({'title': 'ipzz-905', 'url': 'https://missav.ai/ipzz-905-c'}, ('CH',)),
    # English subtitle in title
    ({'title': 'STARS-123 [Eng Sub]', 'url': 'https://jable.tv/videos/stars-123/'}, ('EN',)),
    ({'title': 'IPX-555 【英字】', 'url': 'https://jable.tv/videos/ipx-555/'}, ('EN',)),
    ({'title': 'MIDE-999 English Subtitles', 'url': 'https://supjav.com/999.html'}, ('EN',)),
    # English subtitle in URL
    ({'title': 'mide-789', 'url': 'https://missav.ai/mide-789-english-subtitle'}, ('EN',)),
    # Japanese subtitle in title
    ({'title': 'FC2-PPV-1234567 [日本語字幕]', 'url': 'https://supjav.com/123.html'}, ('JA',)),
    ({'title': 'FC2-PPV-1234568 日文字幕', 'url': 'https://supjav.com/124.html'}, ('JA',)),
    # Korean subtitle
    ({'title': 'FC2-PPV-1234569 [韓文字幕]', 'url': 'https://supjav.com/125.html'}, ('KO',)),
    # Unsubtitled video
    ({'title': 'SSIS-123 Regular Video', 'url': 'https://jable.tv/videos/ssis-123/'}, ()),
])
def test_detect_subtitle_langs_online_signals(video, expected):
    assert detect_subtitle_langs(video) == expected


def test_detect_subtitle_langs_local_files(tmp_path):
    video = {'title': 'SSIS-888 Sample', 'url': 'https://jable.tv/videos/ssis-888/'}
    assert detect_subtitle_langs(video, dest=str(tmp_path)) == ()

    # Create local Chinese srt
    (tmp_path / 'ssis-888.zh-TW.srt').write_text('1\n00:00:00 --> 00:00:01\nTest', encoding='utf-8')
    assert detect_subtitle_langs(video, dest=str(tmp_path)) == ('CH',)

    # Create local English srt as well
    (tmp_path / 'ssis-888.en.srt').write_text('1\n00:00:00 --> 00:00:01\nTest', encoding='utf-8')
    assert detect_subtitle_langs(video, dest=str(tmp_path)) == ('EN', 'CH')


def test_detect_subtitle_langs_cached_subtitles():
    class FakeCache:
        def list_cached_subtitles(self, code):
            if code == 'ssis-777':
                return [{'lang_code': 'ja', 'metadata': {'language': 'Japanese'}}]
            return []

    video = {'title': 'SSIS-777 Sample', 'url': 'https://jable.tv/videos/ssis-777/'}
    assert detect_subtitle_langs(video, cache=FakeCache()) == ('JA',)


@pytest.mark.parametrize(('video', 'expected_dubs'), [
    ({'title': 'Sample [中文配音]', 'url': 'https://hanime1.me/watch?v=123'}, ('CH',)),
    ({'title': 'Sample [國語配音]', 'url': 'https://hanime1.me/watch?v=124'}, ('CH',)),
    ({'title': 'Sample 【中配】', 'url': 'https://hanime1.me/watch?v=125'}, ('CH',)),
    ({'title': 'Sample Chinese Dub', 'url': 'https://hanime1.me/watch?v=126'}, ('CH',)),
    ({'title': 'Sample', 'tags': ['中文配音'], 'url': 'https://hanime1.me/watch?v=127'}, ('CH',)),
    ({'title': 'Sample [英語配音]', 'url': 'https://hanime1.me/watch?v=128'}, ('EN',)),
    ({'title': 'Sample English Dub', 'url': 'https://hanime1.me/watch?v=129'}, ('EN',)),
    ({'title': 'Sample [日語配音]', 'url': 'https://hanime1.me/watch?v=130'}, ('JA',)),
    ({'title': 'Sample Japanese Dub', 'url': 'https://hanime1.me/watch?v=131'}, ('JA',)),
    ({'title': 'Regular Video', 'url': 'https://hanime1.me/watch?v=132'}, ()),
])
def test_detect_dub_langs(video, expected_dubs):
    assert detect_dub_langs(video) == expected_dubs


def test_detect_video_card_badges():
    # Chinese Dub video
    v_cn_dub = {'title': 'Hanime Video [中文配音]', 'url': 'https://hanime1.me/watch?v=101'}
    badges = detect_video_card_badges(v_cn_dub)
    badge_texts = [b['text'] for b in badges]
    assert 'CH DUB' in badge_texts

    # English Dub video
    v_en_dub = {'title': 'Anime Video [English Dub]', 'url': 'https://hanime1.me/watch?v=102'}
    badges = detect_video_card_badges(v_en_dub)
    badge_texts = [b['text'] for b in badges]
    assert 'EN DUB' in badge_texts

    # Japanese Dub video
    v_ja_dub = {'title': 'Anime Video [日語配音]', 'url': 'https://hanime1.me/watch?v=103'}
    badges = detect_video_card_badges(v_ja_dub)
    badge_texts = [b['text'] for b in badges]
    assert 'JA DUB' in badge_texts

    # Chinese Sub video
    v_cn_sub = {'title': 'IPZZ-905 [中文字幕]', 'url': 'https://jable.tv/videos/ipzz-905/'}
    badges = detect_video_card_badges(v_cn_sub)
    badge_texts = [b['text'] for b in badges]
    assert 'CH SUB' in badge_texts

    # English Sub video
    v_en_sub = {'title': 'STARS-123 [Eng Sub]', 'url': 'https://jable.tv/videos/stars-123/'}
    badges = detect_video_card_badges(v_en_sub)
    badge_texts = [b['text'] for b in badges]
    assert 'EN SUB' in badge_texts

    # Uncensored Chinese Sub video
    v_uncensored = {'title': 'IPZZ-905 [中文字幕] 無碼流出', 'url': 'https://jable.tv/videos/ipzz-905/'}
    badges = detect_video_card_badges(v_uncensored)
    badge_texts = [b['text'] for b in badges]
    assert 'CH SUB' in badge_texts
    assert 'UNCENSORED' in badge_texts


def test_series_extraction_and_sorting():
    from video_identity import extract_series_info, is_same_series, normalize_series_key

    # 1. Test Day N
    b1, n1, l1 = extract_series_info({'title': 'Stepsis Day 1', 'url': 'https://hanime.tv/videos/hentai/stepsis-day-1'})
    b2, n2, l2 = extract_series_info({'title': 'Stepsis Day 2', 'url': 'https://hanime.tv/videos/hentai/stepsis-day-2'})
    b3, n3, l3 = extract_series_info({'title': 'step sis day 3', 'url': 'https://hanime.tv/videos/hentai/stepsis-day-3'})

    assert normalize_series_key(b1) == normalize_series_key(b2) == normalize_series_key(b3) == 'stepsis'
    assert n1 == 1 and n2 == 2 and n3 == 3
    assert 'Day 1' in l1 and 'Day 2' in l2 and 'Day 3' in l3

    assert is_same_series({'title': 'Stepsis Day 1'}, {'title': 'Stepsis Day 2'})
    assert is_same_series({'title': 'Stepsis Day 1'}, {'title': 'Step Sis Day 3'})

    # 2. Test Part N / Trailing number
    m1_b, m1_n, m1_l = extract_series_info('Momone 1')
    m2_b, m2_n, m2_l = extract_series_info('Momone 2')
    assert normalize_series_key(m1_b) == normalize_series_key(m2_b) == 'momone'
    assert m1_n == 1 and m2_n == 2

    # 3. Test Japanese 前編 / 後編
    t1_b, t1_n, t1_l = extract_series_info('Tsumamigui 3 前編')
    t2_b, t2_n, t2_l = extract_series_info('Tsumamigui 3 後編')
    assert t1_n == 1 and t2_n == 3
    assert is_same_series('Tsumamigui 3 前編', 'Tsumamigui 3 後編')

    # 4. Sorting test
    raw_list = [
        {'title': 'Stepsis Day 3', '_series_part': 3},
        {'title': 'Stepsis Day 1', '_series_part': 1},
        {'title': 'Stepsis Day 2', '_series_part': 2},
    ]
    sorted_list = sorted(raw_list, key=lambda x: x['_series_part'])
    assert [v['title'] for v in sorted_list] == ['Stepsis Day 1', 'Stepsis Day 2', 'Stepsis Day 3']



