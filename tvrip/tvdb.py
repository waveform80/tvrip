# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2020-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
A trivial interface to `The TVDB`_ for tvrip.

The :class:`TVDB` class defined in this module provides a few simple methods
for searching program titles, and retrieving the seasons & episodes available
within specific programs (which is pretty much all tvrip requires).

.. _The TVDB: https://thetvdb.com/
"""

from itertools import count
from datetime import datetime
from collections import namedtuple
from urllib.parse import urlsplit, urlencode

import requests


class SearchResult(namedtuple('SearchResult', (
    'id',
    'title',
    'aired',
    'status',
    'overview',
))):
    "Represents an individual search result returned from :meth:`TVDB.search`."


class TVDBv3:
    """
    Provides a trivial interface to `The TVDB`_ service, specifically the
    legacy API.

    Instances are constructed with a mandatory API *key* and an optional API
    *url*. The :meth:`search` method can be used to find programs matching a
    particular sub-string. After establishing a program ID, the :meth:`seasons`
    and :meth:`episodes` methods can be used to retrieve program contents.

    .. _The TVDB: https://thetvdb.com/
    """
    api_url = 'https://api.thetvdb.com/'

    def __init__(self, key, url=None):
        if url is None:
            url = self.api_url
        self.url = urlsplit(url)
        self.key = key
        self._token = None

    @property
    def token(self):
        "Returns the current session authorization token."
        if self._token is None:
            headers = {
                'Content-Type': 'application/json',
                'Accept':       'application/vnd.thetvdb.v3',
            }
            resp = requests.post(
                self._resolve_path('/login'),
                headers=headers,
                json={'apikey': self.key})
            resp.raise_for_status()
            self._token = resp.json()['token']
        return self._token

    def _resolve_path(self, path):
        new_path = self.url.path.rstrip('/') + '/' + path.lstrip('/')
        return self.url._replace(path=new_path).geturl()

    def _get(self, path, params):
        headers = {
            'Content-Type': 'application/json',
            'Accept':       'application/vnd.thetvdb.v3',
            'Authorization': f'Bearer {self.token}',
        }
        resp = requests.get(
            self._resolve_path(path),
            headers=headers,
            params=params)
        resp.raise_for_status()
        return resp.json()

    def search(self, program):
        """
        Given a *program* name to search for, returns an iterable of
        :class:`SearchResult` entities representing all matching programs.
        """
        return [
            SearchResult(
                entry['id'],
                entry['seriesName'],
                datetime.strptime(entry['firstAired'], '%Y-%m-%d')
                    if entry.get('firstAired') else None,
                entry['status'],
                entry.get('overview', ''))
            for entry in self._get(
                '/search/series', {'name': program})['data']
            # Series without an overview are usually extremely niche;
            # exclude them
            if entry.get('overview')
        ]

    def seasons(self, program_id):
        """
        Given a *program_id*, returns an iterable of integers representing the
        available seasons of the program that currently exist. Note that these
        do **not** have to start at 1. For example, several historical
        collections number their "seasons" by year of release, and "specials"
        typically appear under season 0.
        """
        return [
            int(season)
            for season in self._get(
                f'/series/{program_id}/episodes/summary',
                {})['data']['airedSeasons']
        ]

    def episodes(self, program_id, season):
        """
        Given a *program_id* and a *season* (presumably a value returned by
        :meth:`seasons` with the equivalent *program_id*), returns an iterable
        of (episode-number, episode-name) tuples.
        """
        for page in count(start=1):
            resp = self._get(
                f'/series/{program_id}/episodes/query',
                {'airedSeason': season, 'page': page})
            for entry in resp['data']:
                # Exclude entries with episode number 0 (these tend to be
                # broken), same for things with a NULL episode name
                if entry['airedEpisodeNumber'] > 0:
                    if entry.get('episodeName') is not None:
                        yield (entry['airedEpisodeNumber'], entry['episodeName'])
            if page >= resp['links']['last']:
                break


class TVDBv4:
    """
    Provides a trivial interface to `The TVDB`_ service, specifically the newer
    v4 API.

    Instances are constructed with a mandatory API *key* and an optional API
    *url*. The :meth:`search` method can be used to find programs matching a
    particular sub-string. After establishing a program ID, the :meth:`seasons`
    and :meth:`episodes` methods can be used to retrieve program contents.

    .. _The TVDB: https://thetvdb.com/
    """
    api_url = 'https://api4.thetvdb.com/v4'
    api_key = '6c479d57-cdde-4bec-8e7e-2d547908d52d'

    def __init__(self, key, url=None):
        if url is None:
            url = self.api_url
        self.url = urlsplit(url)
        # We ignore the initializer's key here as we only want to use the
        # application-specified key
        self.key = self.api_key
        self._token = None

    @property
    def token(self):
        "Returns the current session authorization token."
        if self._token is None:
            headers = {
                'Content-Type': 'application/json',
                'Accept':       'application/vnd.thetvdb.v4',
            }
            resp = requests.post(
                self.url._replace(path=self._resolve_path('/login')).geturl(),
                headers=headers,
                json={'apikey': self.key})
            resp.raise_for_status()
            self._token = resp.json()['data']['token']
        return self._token

    def _resolve_path(self, path):
        return self.url.path.rstrip('/') + '/' + path.lstrip('/')

    def _get(self, path, params):
        return self._get_url(self.url._replace(
            path=self._resolve_path(path),
            query=urlencode(params, doseq=True)).geturl())

    def _get_url(self, url):
        headers = {
            'Content-Type': 'application/json',
            'Accept':       'application/vnd.thetvdb.v4',
            'Authorization': f'Bearer {self.token}',
        }
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data['status'] != 'success':
            raise RuntimeError(
                f'TVDBv4 API call failed with status {data["status"]}')
        return data

    def search(self, program):
        """
        Given a *program* name to search for, returns an iterable of
        :class:`SearchResult` entities representing all matching programs.
        """
        return [
            SearchResult(
                int(entry['tvdb_id']),
                entry.get('translations', {}).get('eng', entry['name']),
                datetime.strptime(entry['first_air_time'], '%Y-%m-%d')
                    if entry.get('first_air_time') else None,
                entry['status'],
                entry.get('overviews', {}).get('eng', entry.get('overview', '')),
            )
            for entry in self._get(
                '/search', {
                    'query': program,
                    'type': 'series',
                    'limit': 20,
                })['data']
            # Series without an overview are usually extremely niche;
            # exclude them
            if entry.get('overview')
            or entry.get('overviews', {}).get('eng', '')
        ]

    def seasons(self, program_id):
        """
        Given a *program_id*, returns an iterable of integers representing the
        available seasons of the program that currently exist. Note that these
        do **not** have to start at 1. For example, several historical
        collections number their "seasons" by year of release, and "specials"
        typically appear under season 0.
        """
        return [
            season['number']
            for season in self._get(
                f'/series/{program_id}/extended',
                {'meta': 'episodes', 'short': 'true'})['data']['seasons']
            if season.get('type', {}).get('type', 'official') == 'official'
        ]

    def episodes(self, program_id, season):
        """
        Given a *program_id* and a *season* (presumably a value returned by
        :meth:`seasons` with the equivalent *program_id*), returns an iterable
        of (episode-number, episode-name) tuples.
        """
        resp = self._get(
            f'/series/{program_id}/episodes/official',
            {'season': season, 'page': 0})
        while True:
            for entry in resp['data']['episodes']:
                # Exclude entries with episode number 0 (these tend to be
                # broken), same for things with a NULL episode name
                if entry['number'] > 0:
                    if entry.get('name') is not None:
                        yield (entry['number'], entry['name'])
            next_url = resp['links'].get('next')
            if next_url is None:
                break
            else:
                resp = self._get_url(next_url)
