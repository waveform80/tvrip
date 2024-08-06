# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2022-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import http.server

import pytest

from tvrip.tvdb import *


def test_tvdb3_init():
    api = TVDBv3(key='foo')
    assert api.key == 'foo'
    api = TVDBv3(key='')
    assert api.key == TVDBv3.api_key


def test_tvdb4_init():
    api = TVDBv4(key='foo')
    assert api.key == 'foo'
    api = TVDBv4(key='')
    assert api.key == TVDBv4.api_key


def test_tvdb_cached_login(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret', url=server.url)
    assert not api._token
    assert api.token
    assert api._token
    assert api.token


def test_tvdb_search(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    result = api.search('Up North')
    assert len(result) == 1
    assert result[0].title == 'Up North'
    assert result[0].status == 'Ended'


def test_tvdb_seasons(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert (
        set(api.seasons(api.search('Up North')[0].id)) ==
        server.programs['Up North']['seasons'].keys()
    )


def test_tvdb_episodes(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Up North')[0].id, 2)) == sorted(
        server.programs['Up North']['seasons'][2].items())


def test_tvdb_no_episodes(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Up North')[0].id, 3)) == []


def test_tvdb_episodes_ignore(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 4)) == []


def test_tvdb_episodes_ignore_zeros_and_nulls(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Edge of Testness')[0].id, 0)) == [
        (6, 'Alternative Ending')]


def test_tvdb_episodes_pages(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 1)) == sorted(
        server.programs['Foo & Bar']['seasons'][1].items())


def test_tvdb_episodes_pages_multi(tvdb):
    client_class, server = tvdb
    api = client_class(key='s3cret')
    assert list(api.episodes(api.search('Edge of Testness')[0].id, 2)) == sorted(
        server.programs['Edge of Testness']['seasons'][2].items())


def test_tvdb4_failure(tvdbv4):
    api = TVDBv4(key='s3cret')
    with pytest.raises(RuntimeError):
        api.search('Fail!')
