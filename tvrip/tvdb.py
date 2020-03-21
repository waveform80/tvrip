import json
from datetime import datetime
from urllib.parse import urlsplit
from collections import namedtuple
from itertools import count

import requests


SearchResult = namedtuple('SearchResult', (
    'id',
    'title',
    'aired',
    'status',
    'overview',
))

class TVDB:
    def __init__(self, key, url='https://api.thetvdb.com/'):
        self.key = key
        self.url = urlsplit(url)
        self._token = None

    @property
    def token(self):
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
        return [
            int(season)
            for season in self._get(
                '/series/{id}/episodes/summary'.format(id=program_id),
                {})['data']['airedSeasons']
        ]

    def episodes(self, program_id, season):
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
