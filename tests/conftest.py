# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2021-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import json
import struct
import subprocess
import datetime as dt
from pathlib import Path
from unittest import mock
from binascii import crc32
from threading import Thread
from itertools import groupby
from ctypes import create_string_buffer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tvrip import database
from tvrip.tvdb import TVDBv3, TVDBv4


@pytest.fixture()
def db(request, tmp_path):
    with database.Database(tmp_path / 'tvrip.db') as db:
        yield db


@pytest.fixture()
def with_schema(request, db):
    with db:
        db.migrate()
        yield db.get_version()


@pytest.fixture()
def with_config(request, db, with_schema, tmp_path):
    cfg = database.Config(
        program=None,
        season=None,
        api_key='',
        api='',
        audio_all=False,
        audio_encoding='av_aac',
        audio_mix='dpl2',
        audio_langs=['eng'],
        decomb='auto',
        duplicates='all',
        duration=[dt.timedelta(minutes=40), dt.timedelta(minutes=50)],
        dvdnav=True,
        id_template='{season}x{episode:02d}',
        max_resolution=[1920, 1080],
        output_format='mp4',
        paths={
            'atomicparsley': Path('AtomicParsley'),
            'handbrake': Path('HandBrakeCLI'),
            'mkvpropedit': Path('mkvpropedit'),
            'vlc': Path('vlc'),
        },
        source=tmp_path / 'dvd',
        subtitle_all=False,
        subtitle_default=False,
        subtitle_format='none',
        subtitle_langs=['eng'],
        target=tmp_path / 'videos',
        template='{program} - {id} - {name}.{ext}',
        temp=tmp_path / 'tmp',
        video_style='tv',
    )
    cfg.temp.mkdir()
    cfg.target.mkdir()
    cfg.source.touch(mode=0o644)
    with db.transaction():
        db.set_config(cfg)
    yield cfg


@pytest.fixture()
def with_program(request, db, with_config):
    cfg = with_config
    program = 'Foo & Bar'
    data = [
        (1, 1, 'Foo'),
        (1, 2, 'Bar'),
        (1, 3, 'Baz'),
        (1, 4, 'Quux'),
        (1, 5, 'Xyzzy'),
        (2, 1, 'Foo Bar - Part 1'),
        (2, 2, 'Foo Bar - Part 2'),
        (2, 3, 'Foo Baz'),
        (2, 4, 'Foo Quux'),
    ]
    with db.transaction():
        db.add_program(program)
        cfg = db.set_config(cfg._replace(program=program))
        for (season,), episodes in groupby(data, key=lambda row: row[:1]):
            db.add_season(season)
            cfg = db.set_config(cfg._replace(season=season))
            for season, episode, title in episodes:
                db.add_episode(episode, title)
        cfg = db.set_config(cfg._replace(season=1))
    yield cfg


def make_disc(tracks, play_all_tracks=None, audio_tracks=('eng', 'eng'),
              subtitle_tracks=('eng', 'eng', 'fra')):
    chapters = [
        tuple(
            title_duration * scale / sum(title_chapters)
            for scale in title_chapters
        )
        for title_duration, title_chapters in tracks
    ]
    if play_all_tracks is not None:
        # Make the first track the concatenation of the non-duplicate tracks
        chapters[:0] = [sum((chapters[i] for i in play_all_tracks), ())]

    languages = {
        'eng': 'English',
        'fra': 'Francais',
    }
    return {
        'TitleList': [
            {
                'AudioList': [
                    {
                        'BitRate': 192000,
                        'ChannelLayoutName': 'stereo',
                        'CodecName': 'ac3',
                        'Language': languages[lang],
                        'LanguageCode': lang,
                        'SampleRate': 48000,
                        'TrackNumber': audio_track,
                    }
                    for audio_track, lang in enumerate(audio_tracks, start=1)
                ],
                'SubtitleList': [
                    {
                        'SourceName': 'VOBSUB',
                        'Language': f'{languages[lang]} (16:9) [VOBSUB]',
                        'LanguageCode': lang,
                        'TrackNumber': sub_track,
                    }
                    for sub_track, lang in enumerate(subtitle_tracks, start=1)
                ],
                'ChapterList': [
                    {
                        'Name': f'Chapter {chapter}',
                        'Duration': {
                            'Hours': duration.total_seconds() // 3600,
                            'Minutes': duration.total_seconds() // 60 % 60,
                            'Seconds': duration.total_seconds() % 60,
                            'Ticks': duration.total_seconds() * 90000,
                        },
                    }
                    for chapter, duration in enumerate(title_chapters, start=1)
                ],
                'Crop': [0, 0, 0, 0],
                'Duration': {
                    'Hours': title_duration.total_seconds() // 3600,
                    'Minutes': (title_duration.total_seconds() // 60) % 60,
                    'Seconds': title_duration.total_seconds() % 60,
                    'Ticks': title_duration.total_seconds() * 90000,
                },
                'FrameRate': {
                    'Den': 1080000,
                    'Num': 27000000,
                },
                'Geometry': {
                    'Height': 576,
                    'Width': 720,
                    'PAR': {'Den': 15, 'Num': 16},
                },
                'Index': title_track,
                'InterlaceDetected': False,
            }
            for title_track, title_chapters in enumerate(chapters, start=1)
            for title_duration in (sum(title_chapters, dt.timedelta(0)),)
        ]
    }


@pytest.fixture()
def blank_disc(request):
    return make_disc([])


@pytest.fixture()
def foo_disc1(request):
    durations = [
        dt.timedelta(minutes=30),
        dt.timedelta(minutes=30),
        dt.timedelta(minutes=30),
        dt.timedelta(minutes=30, seconds=5),
        dt.timedelta(minutes=30, seconds=1),
        dt.timedelta(minutes=30, seconds=1),
        dt.timedelta(minutes=31, seconds=20),
        dt.timedelta(minutes=5, seconds=3),
        dt.timedelta(minutes=7, seconds=1),
        dt.timedelta(minutes=31, seconds=30),
    ]
    chapters = [
        (5, 5, 5, 5, 1),
        (8, 7, 4, 1, 1),
        (8, 7, 4, 1, 1), # track 3 duplicates track 2
        (6, 8, 4, 2, 1),
        (6, 6, 8, 1),
        (6, 6, 8, 1), # track 6 duplicates track 5
        (8, 2, 5, 5, 1),
        (1, 1),
        (1, 1),
        (8, 8, 1),
    ]
    return make_disc(
        tracks=zip(durations, chapters),
        play_all_tracks=(0, 1, 3, 4, 6),
        audio_tracks=('eng', 'eng'),
        subtitle_tracks=('eng', 'eng', 'fra'),
    )


@pytest.fixture()
def foo_disc2(request):
    durations = [
        dt.timedelta(minutes=61, seconds=12),
        dt.timedelta(minutes=30, seconds=5),
        dt.timedelta(minutes=30, seconds=1),
    ]
    chapters = [
        (5, 5, 5, 5, 5, 7, 4, 2, 1),
        (8, 8, 8, 8, 1),
        (6, 6, 8, 1),
    ]
    return make_disc(
        tracks=zip(durations, chapters),
        play_all_tracks=range(3),
        audio_tracks=('eng', 'eng'),
        subtitle_tracks=('eng', 'eng', 'fra'),
    )


@pytest.fixture()
def drive(request, tmp_path):
    def mock_vlc(cmdline, **kwargs):
        path = cmdline[-1]
        match = re.match(
            r'dvd://'
            r'(?P<source>[^#]+)'
            r'(?:#(?P<title>\d+)(?::(?P<chapter>\d+))?)?',
            path)
        if not match:
            return subprocess.CompletedProcess(
                args=cmdline, returncode=1, stdout='', stderr='invalid source')
        source = match.group('source')
        if source != str(tmp_path / 'dvd'):
            return subprocess.CompletedProcess(
                args=cmdline, returncode=1, stdout='', stderr='bad device')
        if match.group('title'):
            title = int(match.group('title')) - 1
            if not 0 <= title < len(proc.disc['TitleList']):
                return subprocess.CompletedProcess(
                    args=cmdline, returncode=1, stdout='', stderr='bad title')
            if match.group('chapter'):
                chapter = int(match.group('chapter')) - 1
                if not 0 <= chapter < len(proc.disc['TitleList'][title]['ChapterList']):
                    return subprocess.CompletedProcess(
                        args=cmdline, returncode=1,
                        stdout='', stderr='bad chapter')
            # Title 9 always fails to read (8 because title is -1 above)
            if title == 8:
                return subprocess.CompletedProcess(
                    args=cmdline, returncode=1,
                    stdout='', stderr='could not read disc')
        return mock.Mock(args=cmdline, returncode=0, stdout='', stderr='')

    def mock_atomicparsley(cmdline, **kwargs):
        source = Path(cmdline[1])
        target = Path(cmdline[cmdline.index('-o') + 1])
        with target.open('w') as target_file:
            with source.open('r') as source_file:
                target_file.write(source_file.read())
            target_file.write(json.dumps(cmdline))
            target_file.write('\n')
        return subprocess.CompletedProcess(
            args=cmdline, returncode=0,
            stdout='', stderr=f'Tagging {target}')

    def mock_handbrake(cmdline, **kwargs):
        source = cmdline[cmdline.index('-i') + 1]
        if proc.disc is None:
            if '--no-dvdnav' in cmdline:
                error = f"libdvdread: Can't open {source} for reading"
            else:
                error = "libdvdnav: vm: failed to open/read the DVD"
            return mock.Mock(args=cmdline, returncode=0, stdout='', stderr=error)
        if source != str(tmp_path / 'dvd'):
            return subprocess.CompletedProcess(
                args=cmdline, returncode=0, stdout='', stderr='')
        data = proc.disc.copy()
        if '-t' in cmdline:
            title = int(cmdline[cmdline.index('-t') + 1])
            # Title 9 always fails
            if title == 9:
                return subprocess.CompletedProcess(
                    args=cmdline, returncode=1,
                    stdout='', stderr='libdvdnav: vm: failed to open/read the DVD')
            if title != 0:
                data['TitleList'] = [
                    t for t in data['TitleList']
                    if t['Index'] == title
                ]
        if '--scan' in cmdline:
            stderr = f"""\
libdvdnav: Random stuff
libdvdnav: DVD Title: FOO AND BAR
libdvdnav: DVD Serial Number: 123456789
"""
            stdout = f"""\
Version: {{
    "Name": "HandBrake",
    "System": "Linux",
    "Type": "developer",
}}
Progress: {{
    "Scanning": {{
        "Preview": 0,
        "PreviewCount": 1,
        "Progress": 0.0,
        "SequenceID": 0,
        "Title": 1,
        "TitleCount": 1
    }},
    "State": "SCANNING"
}}
JSON Title Set: {json.dumps(data)}
"""
        else:
            target = Path(cmdline[cmdline.index('-o') + 1])
            stdout = ''
            stderr = f'Ripping to {target}'
            target.write_text(json.dumps(cmdline) + '\n')
        return subprocess.CompletedProcess(
            args=cmdline, returncode=0, stdout=stdout, stderr=stderr)

    def mock_run(cmdline, **kwargs):
        if cmdline[0] == 'HandBrakeCLI':
            result = mock_handbrake(cmdline, **kwargs)
        elif cmdline[0] == 'vlc':
            result = mock_vlc(cmdline, **kwargs)
        elif cmdline[0] == 'AtomicParsley':
            result = mock_atomicparsley(cmdline, **kwargs)
        else:
            result = subprocess.CompletedProcess(
                args=cmdline, returncode=127, stdout='',
                stderr=f'Command {cmdline[0]} not found')
        if kwargs.get('check') and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmdline[0], result.stdout, result.stderr)
        return result

    with mock.patch('tvrip.ripper.proc') as proc:
        proc.disc = None
        proc.run.side_effect = mock_run
        yield proc


class MockTVDBHandler(BaseHTTPRequestHandler):
    pass


class MockTVDBv3Handler(MockTVDBHandler):
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/search/series':
            self.handle_search(query['name'][0])
            return
        elif url.path.startswith('/series/'):
            try:
                quoted_id = url.path.split('/')[2]
                program_id = unquote(quoted_id)
                program = self.server.programs[program_id]
            except KeyError:
                pass
            else:
                if url.path == f'/series/{quoted_id}/episodes/summary':
                    self.handle_summary(program_id, program)
                    return
                elif url.path == f'/series/{quoted_id}/episodes/query':
                    self.handle_query(program_id, program, query)
                    return
        self.send_error(404, 'Not found')

    def do_POST(self):
        if self.path == '/login':
            assert self.headers['Accept'] == 'application/vnd.thetvdb.v3'
            assert self.headers['Content-Type'] == 'application/json'
            body_len = int(self.headers.get('Content-Length', 0))
            assert body_len > 0
            body = json.loads(self.rfile.read(body_len))
            if body['apikey'] == self.server.key:
                self.send_json({'token': 'foo'})
            else:
                self.send_error(401, 'Not authorized')
            return
        self.send_error(404, 'Not found')

    def send_json(self, data):
        buf = json.dumps(data).encode('utf-8')
        self.send_response(200, 'OK')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(buf))
        self.end_headers()
        self.wfile.write(buf)

    def handle_search(self, name):
        self.send_json(
            {'data': [
                {
                    'id': key,
                    'seriesName': key,
                    'firstAired': dt.datetime(
                        2020, 1, 1, 13, 37).strftime('%Y-%m-%d'),
                    'status': 'Ended',
                    'overview': data['description'],
                }
                for key, data in self.server.programs.items()
                if name in key
            ]}
        )

    def handle_summary(self, name, program):
        self.send_json({
            'data': {
                'airedSeasons': [str(season) for season in program['seasons']]
            }
        })

    def handle_query(self, name, program, query):
        season = int(query['airedSeason'][0])
        page = int(query['page'][0])
        episodes = sorted(program['seasons'].get(season, {}).items())
        self.send_json({
            'links': {'last': (len(episodes) // 5) + 1},
            'data': [
                {
                    'airedEpisodeNumber': ep_num,
                    'episodeName': ep_name,
                }
                for ep_num, ep_name in episodes[(page - 1) * 5:page * 5]
            ],
        })


class MockTVDBv4Handler(MockTVDBHandler):
    seasons_re = re.compile(
        r'/series/(?P<program_id>\d+)/extended$')
    episodes_re = re.compile(
        r'/series/(?P<program_id>\d+)/episodes/(?P<season_type>.+)$')

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/search':
            self.handle_search(
                query['query'][0],
                query['type'][0],
                limit=int(query.get('limit', [20])[0]))
            return
        elif matched := self.seasons_re.match(unquote(url.path)):
            try:
                self.handle_seasons(
                    int(matched.group('program_id')),
                    meta=query['meta'][0],
                    short=query['short'][0] == 'true')
            except KeyError:
                pass
            else:
                return
        elif matched := self.episodes_re.match(unquote(url.path)):
            try:
                self.handle_episodes(
                    int(matched.group('program_id')),
                    season=int(query['season'][0]),
                    season_type=matched.group('season_type'),
                    page=int(query['page'][0]))
            except KeyError:
                pass
            else:
                return
        self.send_error(404, 'Not found')

    def do_POST(self):
        if self.path == '/login':
            assert self.headers['Accept'] == 'application/vnd.thetvdb.v4'
            assert self.headers['Content-Type'] == 'application/json'
            body_len = int(self.headers.get('Content-Length', 0))
            assert body_len > 0
            body = json.loads(self.rfile.read(body_len))
            if body['apikey'] == self.server.key:
                self.send_json({'status': 'success', 'data': {'token': 'foo'}})
            else:
                self.send_error(401, 'Not authorized')
            return
        self.send_error(404, 'Not found')

    def send_json(self, data):
        buf = json.dumps(data).encode('utf-8')
        self.send_response(200, 'OK')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(buf))
        self.end_headers()
        self.wfile.write(buf)

    def handle_search(self, program, program_type='series', limit=20):
        if program == 'Fail!':
            self.send_json({'status': 'failure'})
        else:
            results = {
                key: data for key, data in self.server.programs.items()
                if program in key and program_type == 'series'
            }
            self.send_json(
                {
                    'status': 'success',
                    'data': [
                        {
                            'objectID': f'series-{id}',
                            'aliases': [],
                            'country': 'usa',
                            'id': f'series-{id}',
                            'name': key,
                            'first_air_time': dt.datetime(
                                2020, 1, 1, 13, 37).strftime('%Y-%m-%d'),
                            'overview': data['description'],
                            'primary_language': 'eng',
                            'primary_type': program_type,
                            'status': 'Ended',
                            'type': program_type,
                            'tvdb_id': str(id),
                            'year': '2020',
                            'network': 'BBC USA',
                            'remote_ids': [],
                        }
                        for key, data in results.items()
                        for id in (crc32(key.encode('utf-8')),)
                    ][:limit],
                    'links': {
                        'prev': None,
                        'self': (
                            f'{self.server.url}/search?query={program}&'
                            f'types={program_type}&page=0'),
                        'next': (
                            f'{self.server.url}/search?query={program}&'
                            f'types={program_type}&page=1'),
                        'total_items': len(results),
                        'page_size': limit,
                    }
                }
            )

    def handle_seasons(self, program_id, meta='episodes', short=True):
        for program, data in self.server.programs.items():
            if crc32(program.encode('utf-8')) == program_id:
                break
        else:
            raise KeyError(program_id)
        self.send_json(
            {
                'status': 'success',
                'data': {
                    'id': program_id,
                    'name': program,
                    'firstAired': dt.datetime(2020, 1, 1, 13, 37).strftime('%Y-%m-%d'),
                    'lastAired': '',
                    'nextAired': '',
                    'score': 100,
                    'status': {
                        'id': 2,
                        'name': 'Ended',
                        'recordType': 'series',
                        'keepUpdated': False,
                    },
                    'originalCountry': 'usa',
                    'originalLanguage': 'eng',
                    'defaultSeasonType': 1,
                    'isOrderRandomized': False,
                    'averageRuntime': 35,
                    'overview': data['description'],
                    'year': '2020',
                    'artworks': None,
                    'companies': [],
                    'originalNetwork': {},
                    'latestNetwork': {},
                    'genres': [],
                    'trailers': [],
                    'lists': [],
                    'characters': None,
                    'airsDays': {
                        'monday':    True,
                        'tuesday':   False,
                        'wednesday': False,
                        'thursday':  False,
                        'friday':    False,
                        'saturday':  False,
                        'sunday':    False,
                    },
                    'airsTime': '13:37',
                    'episodes': [
                        {
                            'id': crc32(f'{program}-S{season:02d}E{episode:02d}'.encode('utf-8')),
                            'seriesId': program_id,
                            'name': program,
                            'aired': (
                                dt.datetime(2020, 1, 1, 13, 37) +
                                dt.timedelta(weeks=episode - 1)
                            ).strftime('%Y-%m-%d'),
                            'runtime': 35,
                            'overview': '',
                            'isMovie': 0,
                            'seasons': None,
                            'number': episode,
                            'absoluteNumber': 0,
                            'seasonNumber': season,
                            'year': '2020',
                        }
                        for season, episodes in data['seasons'].items()
                        for episode, title in episodes.items()
                    ],
                    'seasons': [
                        {
                            'id': crc32(f'{program}-S{season:02d}'.encode('utf-8')),
                            'seriesId': program_id,
                            'type': {
                                'id': 1,
                                'name': 'Aired Order',
                                'type': 'official',
                                'alternateName': None,
                            },
                            'number': season,
                        }
                        for season, episodes in data['seasons'].items()
                    ],
                    'tags': [],
                    'contentRatings': [],
                    'seasonTypes': [
                        {
                            'id': 1,
                            'name': 'Aired Order',
                            'type': 'official',
                            'alternateName': None,
                        }
                    ],
                }
            }
        )

    def handle_episodes(self, program_id, season, season_type, page=0, limit=10):
        for program, data in self.server.programs.items():
            if crc32(program.encode('utf-8')) == program_id:
                break
        else:
            raise KeyError(program_id)
        self.send_json(
            {
                'status': 'success',
                'data': {
                    'series': {
                        'id': program_id,
                        'name': program,
                        'firstAired': dt.datetime(
                            2020, 1, 1, 13, 37).strftime('%Y-%m-%d'),
                        'lastAired': '',
                        'nextAired': '',
                        'score': 100,
                        'status': {
                            'id': 2,
                            'name': 'Ended',
                            'recordType': 'series',
                            'keepUpdated': False,
                        },
                        'originalCountry': 'usa',
                        'originalLanguage': 'eng',
                        'defaultSeasonType': 1,
                        'isOrderRandomized': False,
                        'averageRuntime': 35,
                        'overview': data['description'],
                        'episodes': None,
                        'year': '2020',
                    },
                    'episodes': [
                        {
                            'id': crc32(f'{program}-S{int(season):02d}E{episode:02d}'.encode('utf-8')),
                            'seriesId': program_id,
                            'name': title,
                            'aired': (
                                dt.datetime(2020, 1, 1, 13, 37) +
                                dt.timedelta(weeks=episode - 1)
                            ).strftime('%Y-%m-%d'),
                            'runtime': 35,
                            'overview': '',
                            'isMovie': 0,
                            'seasons': None,
                            'number': episode,
                            'absoluteNumber': 0,
                            'seasonNumber': season,
                            'year': '2020',
                        }
                        for episode, title
                        in data['seasons'].get(season, {}).items()
                        if (page * limit) <= episode < ((page + 1) * limit)
                    ],
                },
                'links': {
                    'prev': None,
                    'self': (
                        f'{self.server.url}series/{program_id}/episodes/'
                        f'{season_type}?season={season}&page={page}'
                    ),
                    'next': (
                        f'{self.server.url}series/{program_id}/episodes/'
                        f'{season_type}?season={season}&page={page + 1}'
                    )
                    if (page + 1) * limit < len(data['seasons'].get(season, {}))
                    else None,
                    'total_items': len(data['seasons'].get(season, {})),
                    'page_size': limit,
                }
            }
        )


class MockTVDBServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True

    def __init__(self, handler, key='s3cret'):
        assert issubclass(handler, MockTVDBHandler)
        super().__init__(('127.0.0.1', 0), handler)
        hostname, port, *other = self.server_address
        self.url = f'http://{hostname}:{port}/'
        self.key = key
        self.programs = {
            'Up North': {
                'description':
                    "A completely made up show that has absolutely nothing to "
                    "do with Due South. At all. No, really...",
                'seasons': {
                    1: {
                        1: "Free Willy",
                        2: "Dog Day Afternoon",
                        3: "Manhunter",
                        4: "They Shoot Horses, Don't They?",
                    },
                    2: {
                        1: "Up",
                        2: "Pole",
                        3: "Silent",
                        4: "Two in the Bush",
                    },
                    3: {},
                },
            },
            'Foo & Bar': {
                'description':
                    "The adventures of Foo and Bar in Xyzzy-land",
                'seasons': {
                    1: {
                        1: 'Foo',
                        2: 'Bar',
                        3: 'Baz',
                        4: 'Quux',
                        5: 'Xyzzy',
                    },
                    2: {
                        1: 'Foo Bar - Part 1',
                        2: 'Foo Bar - Part 2',
                        3: 'Foo Baz',
                        4: 'Foo Quux',
                    },
                    3: {
                        1: 'Foo for Thought',
                        2: 'Raising the Bar',
                        3: 'Baz the Undefeated',
                    },
                },
            },
            'The Worst Show in the World': {
                'description':
                    "Honestly ... it hasn't even got any episodes! You may "
                    "think Galactica 1980 was bad, but at least it had some "
                    "episodes. And a theme. And writers. Okay, bad ones, but "
                    "it had some! Alright, that's probably enough waffle for "
                    "testing purposes.",
                'seasons': {},
            },
            'Edge of Testness': {
                'description':
                    "Yorkshireman Ron Coward investigates all the edge "
                    "cases that the tests haven't yet covered...",
                'seasons': {
                    0: {
                        0: 'Alternative Starting',
                        1: None,
                        6: 'Alternative Ending',
                    },
                    1: {
                        1: 'Unwelcome Arrival',
                        2: 'Into the Light',
                        3: 'Albatross of Attestation',
                        4: 'Breakthru',
                        5: 'Southland',
                        6: 'Fission',
                    },
                    2: {
                        1: 'An',
                        2: 'Overly',
                        3: 'Long',
                        4: 'Season',
                        5: 'That',
                        6: 'Just',
                        7: 'Drags',
                        8: 'On',
                        9: 'and On',
                        10: 'and On',
                        11: 'and On',
                        12: 'Which',
                        13: 'Is - Part 1',
                        14: 'Is - Part 2',
                        15: 'Purely',
                        16: 'An Excuse',
                        17: 'To Test',
                        18: 'Paging',
                        19: 'In',
                        20: 'The',
                        21: 'Client',
                    }
                }
            },
        }


def tvdb_fixture(handler):
    server = MockTVDBServer(handler)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def tvdbv3(request):
    for server in tvdb_fixture(MockTVDBv3Handler):
        with mock.patch('tvrip.tvdb.TVDBv3.api_url', server.url):
            yield server


@pytest.fixture()
def tvdbv4(request):
    for server in tvdb_fixture(MockTVDBv4Handler):
        with mock.patch('tvrip.tvdb.TVDBv4.api_url', server.url):
            yield server


@pytest.fixture(params=[
    (TVDBv3, MockTVDBv3Handler, 'tvrip.tvdb.TVDBv3.api_url'),
    (TVDBv4, MockTVDBv4Handler, 'tvrip.tvdb.TVDBv4.api_url'),
])
def tvdb(request):
    client, handler, mock_url = request.param
    for server in tvdb_fixture(handler):
        with mock.patch(mock_url, server.url):
            yield client, server
