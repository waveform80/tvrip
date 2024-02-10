import re
import json
import struct
import subprocess
import datetime as dt
from pathlib import Path
from unittest import mock
from threading import Thread
from itertools import groupby
from ctypes import create_string_buffer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tvrip import database


@pytest.fixture()
def db(request):
    url = 'sqlite:///'  # uses :memory: database
    session = database.init_session(url)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def with_config(request, db, tmp_path):
    cfg = database.Configuration()
    tmp = tmp_path / 'tmp'
    tmp.mkdir()
    cfg.temp = str(tmp)
    target = tmp_path / 'videos'
    target.mkdir()
    cfg.target = str(target)
    source = tmp_path / 'dvd'
    source.touch(mode=0o644)
    cfg.source = str(source)
    db.add(cfg)
    db.add(database.AudioLanguage(cfg, 'eng'))
    db.add(database.SubtitleLanguage(cfg, 'eng'))
    db.add(database.ConfigPath(cfg, 'handbrake', 'HandBrakeCLI'))
    db.add(database.ConfigPath(cfg, 'atomicparsley', 'AtomicParsley'))
    db.add(database.ConfigPath(cfg, 'vlc', 'vlc'))
    db.commit()
    yield cfg


@pytest.fixture()
def with_program(request, db, with_config):
    cfg = with_config
    prog = database.Program('Foo & Bar')
    db.add(prog)
    cfg.program = prog
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
    for (season_num,), episodes in groupby(data, key=lambda row: row[:1]):
        season = database.Season(prog, season_num)
        db.add(season)
        cfg.season = season
        for season_num, episode_num, episode_name in episodes:
            episode = database.Episode(season, episode_num, episode_name)
            db.add(episode)
    yield prog


@pytest.fixture()
def term_size(request):
    with mock.patch('tvrip.terminal.posix.fcntl') as fnctl, \
            mock.patch('tvrip.terminal.win.ctypes') as ctypes:
        width, height = 80, 24
        def unix_patch(handle, ctrl, buf):
            return struct.pack('hhhh', height, width, 0, 0)
        def win_patch(*args):
            buf[:] = struct.pack('hhhhHhhhhhh', 0, 0, 0, 0, 0, 0, 0, 0, 0, width - 1, height - 1, 0, 0)
            return True
        fnctl.ioctl.side_effect = unix_patch
        ctypes.create_string_buffer = create_string_buffer
        ctypes.windll.kernel32.GetConsoleScreenBufferInfo.side_effect = win_patch
        def change(new_width, new_height):
            nonlocal width, height
            width = new_width
            height = new_height
        yield change


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
                        'Language': '{lang} (16:9) [VOBSUB]'.format(lang=languages[lang]),
                        'LanguageCode': lang,
                        'TrackNumber': sub_track,
                    }
                    for sub_track, lang in enumerate(subtitle_tracks, start=1)
                ],
                'ChapterList': [
                    {
                        'Name': 'Chapter {chapter}'.format(chapter=chapter),
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
        match = re.match(r'dvd://(?P<source>[^#]+)(?:#(?P<title>\d+)(?::(?P<chapter>\d+))?)?', path)
        if not match:
            return subprocess.CompletedProcess(
                args=cmdline, returncode=1, stdout='', stderr='invalid source')
        source = match.group('source')
        if match.group('title'):
            title = int(match.group('title')) - 1
            if not 0 <= title < len(proc.disc['TitleList']):
                return subprocess.CompletedProcess(
                    args=cmdline, returncode=1, stdout='', stderr='bad title')
            if match.group('chapter'):
                chapter = int(match.group('chapter')) - 1
                if not 0 <= chapter < len(proc.disc['TitleList'][title]['ChapterList']):
                    return subprocess.CompletedProcess(
                        args=cmdline, returncode=1, stdout='', stderr='bad chapter')
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
            stdout='', stderr='Tagging {target}'.format(target=target))

    def mock_handbrake(cmdline, **kwargs):
        if proc.disc is None:
            if '--no-dvdnav' in cmdline:
                error = "libdvdread: Can't open {source} for reading".format(source=source)
            else:
                error = "libdvdnav: vm: failed to open/read the DVD"
            return mock.Mock(args=cmdline, returncode=0, stdout='', stderr=error)
        source = cmdline[cmdline.index('-i') + 1]
        if source != str(tmp_path / 'dvd'):
            return subprocess.CompletedProcess(
                args=cmdline, returncode=0, stdout='', stderr='')
        data = proc.disc.copy()
        if '-t' in cmdline:
            title = int(cmdline[cmdline.index('-t') + 1])
            if title != 0:
                data['TitleList'] = [
                    t for t in data['TitleList']
                    if t['Index'] == title
                ]
        if '--scan' in cmdline:
            stderr = """\
libdvdnav: Random stuff
libdvdnav: DVD Title: FOO AND BAR
libdvdnav: DVD Serial Number: 123456789
"""
            stdout = """\
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
JSON Title Set: {json}
""".format(json=json.dumps(data))
        else:
            target = Path(cmdline[cmdline.index('-o') + 1])
            stdout = ''
            stderr = 'Ripping to {target}'.format(target=target)
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
                stderr='Command {cmdline[0]} not found'.format(cmdline=cmdline))
        if kwargs.get('check') and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmdline[0], result.stdout, result.stderr)
        return result

    def mock_check_call(cmdline, **kwargs):
        result = mock_run(cmdline, **kwargs)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmdline[0], result.stdout, result.stderr)

    with mock.patch('tvrip.ripper.proc') as proc:
        proc.disc = None
        proc.run.side_effect = mock_run
        proc.check_call.side_effect = mock_check_call
        yield proc


class MockTVDBHandler(BaseHTTPRequestHandler):
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
                if url.path == '/series/{id}/episodes/summary'.format(id=quoted_id):
                    self.handle_summary(program_id, program)
                    return
                elif url.path == '/series/{id}/episodes/query'.format(id=quoted_id):
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


class MockTVDBServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True

    def __init__(self, url, key='s3cret'):
        super().__init__(('127.0.0.1', 0), MockTVDBHandler)
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
        }


@pytest.fixture()
def tvdb(request):
    server = MockTVDBServer('http://127.0.0.1:8000/')
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
