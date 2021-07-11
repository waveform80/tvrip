import re
import json
import subprocess
from pathlib import Path
from datetime import timedelta
from itertools import groupby
from unittest import mock

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
            for title_duration in (sum(title_chapters, timedelta(0)),)
        ]
    }


@pytest.fixture()
def disc1(request):
    durations = [
        timedelta(minutes=30),
        timedelta(minutes=30),
        timedelta(minutes=30),
        timedelta(minutes=30, seconds=5),
        timedelta(minutes=30, seconds=1),
        timedelta(minutes=30, seconds=1),
        timedelta(minutes=31, seconds=20),
        timedelta(minutes=5, seconds=3),
        timedelta(minutes=7, seconds=1),
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
    ]
    return make_disc(
        tracks=zip(durations, chapters),
        play_all_tracks=(0, 1, 3, 4, 6),
        audio_tracks=('eng', 'eng'),
        subtitle_tracks=('eng', 'eng', 'fra'),
    )


@pytest.fixture()
def disc2(request):
    durations = [
        timedelta(minutes=31, seconds=10),
        timedelta(minutes=30, seconds=2),
        timedelta(minutes=30, seconds=5),
        timedelta(minutes=30, seconds=1),
    ]
    chapters = [
        (5, 5, 5, 5, 1),
        (5, 7, 4, 1, 1),
        (8, 8, 8, 8, 1),
        (6, 6, 8, 1),
    ]
    return make_disc(
        tracks=zip(durations, chapters),
        play_all_tracks=range(4),
        audio_tracks=('eng', 'eng'),
        subtitle_tracks=('eng', 'eng', 'fra'),
    )


@pytest.fixture()
def drive(request):
    def mock_vlc(cmdline, **kwargs):
        path = cmdline[-1]
        match = re.match(r'dvd://(?P<source>[^#]+)(?:#(?P<title>\d+)(?::(?P<chapter>\d+))?)?', path)
        if not match:
            return mock.Mock(
                args=cmdline, returncode=1, stdout='', stderr='invalid source')
        source = match.group('source')
        if match.group('title'):
            title = int(match.group('title')) - 1
            if not 0 <= title < len(proc.disc['TitleList']):
                return mock.Mock(
                    args=cmdline, returncode=1, stdout='', stderr='bad title')
            if match.group('chapter'):
                chapter = int(match.group('chapter')) - 1
                if not 0 <= chapter < len(proc.disc['TitleList'][title]['ChapterList']):
                    return mock.Mock(
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
        return mock.Mock(args=cmdline, returncode=0, stdout='',
                         stderr='Tagging {target}'.format(target=target))

    def mock_handbrake(cmdline, **kwargs):
        if proc.disc is None:
            if '--no-dvdnav' in cmdline:
                error = "libdvdread: Can't open {source} for reading".format(source=source)
            else:
                error = "libdvdnav: vm: failed to open/read the DVD"
            return mock.Mock(args=cmdline, returncode=0, stdout='', stderr=error)
        source = cmdline[cmdline.index('-i') + 1]
        if source != '/dev/dvd':
            return mock.Mock(args=cmdline, returncode=0, stdout='', stderr='')
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
        return mock.Mock(args=cmdline, returncode=0,
                         stdout=stdout, stderr=stderr)

    def mock_run(cmdline, **kwargs):
        if cmdline[0] == 'HandBrakeCLI':
            return mock_handbrake(cmdline, **kwargs)
        elif cmdline[0] == 'vlc':
            return mock_vlc(cmdline, **kwargs)
        elif cmdline[0] == 'AtomicParsley':
            return mock_atomicparsley(cmdline, **kwargs)
        else:
            return mock.Mock(
                args=cmdline, returncode=127, stdout='',
                stderr='Command {cmdline[0]} not found'.format(cmdline=cmdline))

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
