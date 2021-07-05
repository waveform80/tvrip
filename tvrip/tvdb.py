# vim: set et sw=4 sts=4:

# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
#
# This file is part of tvrip.
#
# tvrip is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# tvrip.  If not, see <http://www.gnu.org/licenses/>.

"""
A trivial interface to `The TVDB`_ for tvrip.

The :class:`TVDB` class defined in this module provides a few simple methods
for searching program titles, and retrieving the seasons & episodes available
within specific programs (which is pretty much all tvrip requires).

.. _The TVDB: https://thetvdb.com/
"""

from datetime import datetime
from urllib.parse import urlsplit
from collections import namedtuple
from itertools import count

import requests


class SearchResult(namedtuple('SearchResult', (
    'id',
    'title',
    'aired',
    'status',
    'overview',
))):
    "Represents an individual search result returned from :meth:`TVDB.search`."


class TVDB:
    """
    Provides a trivial interface to `The TVDB`_ service.

    Instances are constructed with a mandatory API *key* and an optional API
    *url*. The :meth:`search` method can be used to find programs matching a
    particular sub-string. After establishing a program ID, the :meth:`seasons`
    and :meth:`episodes` methods can be used to retrieve program contents.

    .. _The TVDB: https://thetvdb.com/
    """

    def __init__(self, key, url='https://api.thetvdb.com/'):
        self.key = key
        self.url = urlsplit(url)
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
                self.url._replace(path='/login').geturl(),
                headers=headers,
                json={'apikey': self.key})
            resp.raise_for_status()
            self._token = resp.json()['token']
        return self._token

    def _get(self, path, params):
        headers = {
            'Content-Type': 'application/json',
            'Accept':       'application/vnd.thetvdb.v3',
            'Authorization': 'Bearer {}'.format(self.token),
        }
        resp = requests.get(
            self.url._replace(path=path).geturl(),
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
        collections number their "seasons" by year of release.
        """
        return [
            int(season)
            for season in self._get(
                '/series/{id}/episodes/summary'.format(id=program_id),
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
                '/series/{id}/episodes/query'.format(id=program_id),
                {'airedSeason': season, 'page': page})
            for entry in resp['data']:
                # Exclude entries with episode number 0 (these tend to be
                # broken), same for things with a NULL episode name
                if entry['airedEpisodeNumber'] > 0:
                    if entry.get('episodeName') is not None:
                        yield (entry['airedEpisodeNumber'], entry['episodeName'])
            if page >= resp['links']['last']:
                break
