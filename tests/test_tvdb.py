import http.server

import pytest

from tvrip.tvdb import *


def test_tvdb_cached_login(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    assert not api._token
    assert api.token
    assert api._token
    assert api.token


def test_tvdb_search(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    result = api.search('Up North')
    assert len(result) == 1
    assert result[0].title == 'Up North'
    assert result[0].status == 'Ended'


def test_tvdb_seasons(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    assert set(api.seasons(api.search('Up North')[0].id)) == tvdb.programs['Up North'].keys()


def test_tvdb_episodes(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    assert list(api.episodes(api.search('Up North')[0].id, 2)) == sorted(
        tvdb.programs['Up North'][2].items())


def test_tvdb_episodes_ignore(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 4)) == []


def test_tvdb_episodes_pages(tvdb):
    api = TVDB(key='s3cret', url=tvdb.url)
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 1)) == sorted(
        tvdb.programs['Foo & Bar'][1].items())
