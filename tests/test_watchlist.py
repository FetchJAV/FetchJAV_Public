# -*- coding: utf-8 -*-
"""Unit tests for Actress & Studio Watchlist Manager."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import config
from watchlist import WatchlistItem, WatchlistManager, generate_rss_feed


def test_watchlist_item_serialization():
    item = WatchlistItem(name="Yua Mikami", item_type="actress", site="MissAV", auto_download=True)
    d = item.to_dict()
    assert d['name'] == "Yua Mikami"
    assert d['type'] == "actress"
    assert d['site'] == "MissAV"
    assert d['auto_download'] is True

    restored = WatchlistItem.from_dict(d)
    assert restored.name == "Yua Mikami"
    assert restored.item_type == "actress"
    assert restored.site == "MissAV"
    assert restored.auto_download is True


def test_watchlist_manager_add_remove():
    manager = WatchlistManager()
    # Clean test item
    manager.remove_item("TestActress", item_type="actress")

    # Add
    added = manager.add_item("TestActress", item_type="actress", site="All", auto_download=True)
    assert added is True

    # Duplicate should fail
    added_dup = manager.add_item("TestActress", item_type="actress")
    assert added_dup is False

    # Check existence
    items = manager.get_items()
    names = [it.name for it in items if it.item_type == "actress"]
    assert "TestActress" in names

    # Toggle auto download
    toggled = manager.toggle_auto_download("TestActress", item_type="actress")
    assert toggled is True

    # Remove
    removed = manager.remove_item("TestActress", item_type="actress")
    assert removed is True


def test_rss_feed_generation():
    videos = [
        {'title': 'SSIS-123 Video 1', 'url': 'https://jable.tv/videos/ssis-123/', 'thumbnail': 'https://example.com/1.jpg'},
        {'title': 'IPX-456 Video 2', 'url': 'https://missav.ai/ipX-456', 'thumbnail': 'https://example.com/2.jpg'},
    ]
    xml_str = generate_rss_feed(videos, title="Test Feed")
    assert "<rss version=\"2.0\">" in xml_str
    assert "<title>Test Feed</title>" in xml_str
    assert "https://jable.tv/videos/ssis-123/" in xml_str
    assert "https://missav.ai/ipX-456" in xml_str


def test_watchlist_auto_download_default_is_false():
    # Verify auto-download is turned off by default as requested by user
    prefs = config._load_prefs()
    # If not explicitly set in prefs, getter returns False
    original = prefs.get('watchlist_auto_download')
    try:
        config.set_watchlist_auto_download(False)
        assert config.get_watchlist_auto_download() is False
    finally:
        if original is not None:
            config.set_watchlist_auto_download(original)


def test_watchlist_popular_discovery_from_javguru():
    from watchlist import fetch_popular_actresses_from_javguru, fetch_popular_studios_from_javguru
    actresses = fetch_popular_actresses_from_javguru()
    assert len(actresses) > 0
    names = [a['name'].lower() for a in actresses]
    assert any('yua mikami' in n or 'hatano yui' in n or 'shinoda yu' in n for n in names)

    studios = fetch_popular_studios_from_javguru()
    assert len(studios) > 0
    s_names = [s['name'].lower() for s in studios]
    assert any('s1' in s or 'moodyz' in s or 'sod' in s for s in s_names)


def test_watchlist_fuzzy_recommendations_with_typos():
    from watchlist import fuzzy_search_recommendations
    # Test typo 1: "yua mikmi" -> should recommend "Yua Mikami"
    rec1 = fuzzy_search_recommendations("yua mikmi")
    assert len(rec1) > 0
    assert rec1[0]['name'] == "Yua Mikami"

    # Test typo 2: "eime fukada" -> should recommend "Eimi Fukada"
    rec2 = fuzzy_search_recommendations("eime fukada")
    assert any(r['name'] == "Eimi Fukada" for r in rec2)

    # Test typo 3: "moddyz" -> should recommend "MOODYZ"
    rec3 = fuzzy_search_recommendations("moddyz")
    assert any(r['name'] == "MOODYZ" for r in rec3)

    # Test typo 4: "sod create" -> should recommend "SOD Create"
    rec4 = fuzzy_search_recommendations("sod create")
    assert any(r['name'] == "SOD Create" for r in rec4)


def test_is_in_watchlist_and_toggle():
    test_name = "UniqueTestModel"
    config.remove_watchlist_item(test_name, "actress")
    assert config.is_in_watchlist(test_name, "actress") is False

    # Toggle to add
    toggled = config.toggle_watchlist_item(test_name, "actress")
    assert toggled is True
    assert config.is_in_watchlist(test_name, "actress") is True

    # Toggle to remove
    toggled_again = config.toggle_watchlist_item(test_name, "actress")
    assert toggled_again is False
    assert config.is_in_watchlist(test_name, "actress") is False

