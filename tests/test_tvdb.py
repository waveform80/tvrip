# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2022-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import http.server

import pytest

from tvrip.tvdb import *


def test_tvdb_cached_login(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    assert not api._token
    assert api.token
    assert api._token
    assert api.token


def test_tvdb_search(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    result = api.search('Up North')
    assert len(result) == 1
    assert result[0].title == 'Up North'
    assert result[0].status == 'Ended'


def test_tvdb_seasons(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    assert (
        set(api.seasons(api.search('Up North')[0].id)) ==
        tvdbv3.programs['Up North']['seasons'].keys()
    )


def test_tvdb_episodes(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    assert list(api.episodes(api.search('Up North')[0].id, 2)) == sorted(
        tvdbv3.programs['Up North']['seasons'][2].items())


def test_tvdb_episodes_ignore(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 4)) == []


def test_tvdb_episodes_pages(tvdbv3):
    api = TVDBv3(url=tvdbv3.url, key='s3cret')
    assert list(api.episodes(api.search('Foo & Bar')[0].id, 1)) == sorted(
        tvdbv3.programs['Foo & Bar']['seasons'][1].items())
