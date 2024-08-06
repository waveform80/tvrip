# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2022-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import os
import re
import queue
import socket
import warnings
import selectors
import datetime as dt
from pathlib import Path
from unittest import mock
from contextlib import closing, contextmanager
from sqlalchemy import text
from threading import Thread
from itertools import tee

import pytest

from tvrip.database import Episode
from tvrip.ripper import *
from tvrip.ripcmd import *


class Writer(Thread):
    def __init__(self, pipe):
        super().__init__(daemon=True)
        self._pipe = pipe
        self._stop_r, self._stop_w = socket.socketpair()
        self._buf = queue.Queue()
        self._exc = None

    def stop(self, timeout=10):
        self._stop_w.send(b'\0')
        self.join(timeout=timeout)
        if self.is_alive():
            raise RuntimeError('thread failed to stop before timeout')
        if self._exc is not None:
            raise self._exc

    def write(self, s):
        self._buf.put(s)

    def run(self):
        try:
            sel = selectors.DefaultSelector()
            sel.register(self._stop_r, selectors.EVENT_READ)
            sel.register(self._pipe, selectors.EVENT_WRITE)
            while True:
                ready = sel.select(10)
                if not ready:
                    # No test should ever be waiting 10 seconds for anything
                    raise RuntimeError('waited excessive time for input')
                for key, event in ready:
                    if key.fileobj == self._stop_r:
                        self._stop_r.recv(1)
                        return
                    try:
                        self._pipe.write(self._buf.get(block=False))
                    except queue.Empty:
                        pass
        except Exception as exc:
            self._exc = exc


class Reader(Thread):
    def __init__(self, pipe):
        super().__init__(daemon=True)
        self._pipe = pipe
        self._stop_r, self._stop_w = socket.socketpair()
        self._buf = queue.Queue()
        self._exc = None

    def stop(self, timeout=10):
        if self.is_alive():
            self._stop_w.send(b'\0')
        self.join(timeout=timeout)
        if self.is_alive():
            raise RuntimeError('thread failed to stop before timeout')
        if self._exc is not None:
            raise self._exc

    def read(self, timeout=10):
        return self._buf.get(timeout=timeout)

    def read_all(self, timeout=10):
        # Assumes output's been closed and waits for EOF
        self.join(timeout=timeout)
        if self.is_alive():
            raise RuntimeError('waited excessive time for EOF')
        while True:
            try:
                yield self._buf.get(block=False)
            except queue.Empty:
                break

    def run(self):
        try:
            sel = selectors.DefaultSelector()
            sel.register(self._stop_r, selectors.EVENT_READ)
            sel.register(self._pipe, selectors.EVENT_READ)
            while True:
                ready = sel.select(10)
                if not ready:
                    # No test should ever be waiting 10 seconds for anything
                    raise RuntimeError('waited excessive time for output')
                for key, event in ready:
                    if key.fileobj == self._stop_r:
                        self._stop_r.recv(1)
                        return
                    line = self._pipe.readline()
                    if not line:
                        # Output's been closed
                        return
                    self._buf.put(line)
        except Exception as exc:
            self._exc = exc


@contextmanager
def suppress_stdout(cmd):
    save_stdout = cmd.stdout
    save_console_file = cmd.console.file
    try:
        cmd.console.file = cmd.stdout = io.StringIO()
        yield
    finally:
        cmd.console.file = save_console_file
        cmd.stdout = save_stdout


def pairwise(it):
    a, b = tee(it)
    next(b, None)
    return zip(a, b)


def completions(cmd, line):
    if ' ' in line:
        prefix, text = line.lstrip().rsplit(' ', 1)
        start = len(prefix) + 1
        finish = len(line)
        command, *args = prefix.split(' ')
        completer = getattr(cmd, f'complete_{command}')
    else:
        text = line
        start = 0
        finish = len(line)
        completer = cmd.completenames
    return completer(text, line, start, finish)


@pytest.fixture(scope='function')
def stdin_pipe(request):
    ri, wi = os.pipe()
    with \
            closing(os.fdopen(ri, 'r', buffering=1, encoding='utf-8')) as stdin_r, \
            closing(os.fdopen(wi, 'w', buffering=1, encoding='utf-8')) as stdin_w:
        yield stdin_r, stdin_w

@pytest.fixture(scope='function')
def stdout_pipe(request):
    ro, wo = os.pipe()
    with \
            closing(os.fdopen(ro, 'r', buffering=1, encoding='utf-8')) as stdout_r, \
            closing(os.fdopen(wo, 'w', buffering=1, encoding='utf-8')) as stdout_w:
        yield stdout_r, stdout_w

@pytest.fixture(scope='function')
def ripcmd(request, db, stdin_pipe, stdout_pipe, monkeypatch):
    stdin_r, stdin_w = stdin_pipe
    _, stdout_w = stdout_pipe
    stdout_w.reconfigure(write_through=True)
    stdin_w.reconfigure(write_through=True)
    with monkeypatch.context() as m:
        m.setenv('COLUMNS', '100')
        m.setenv('LINES', '50')
        ripcmd = RipCmd(db, stdin=stdin_r, stdout=stdout_w)
        ripcmd.use_rawinput = False
        yield ripcmd

@pytest.fixture()
def stdin(request, stdin_pipe):
    _, stdin_w = stdin_pipe
    yield stdin_w

@pytest.fixture()
def stdout(request, stdout_pipe):
    stdout_r, _ = stdout_pipe
    yield stdout_r

@pytest.fixture()
def reader(request, stdout):
    thread = Reader(stdout)
    thread.start()
    try:
        yield thread
    finally:
        thread.stop()

@pytest.fixture()
def writer(request, stdin):
    thread = Writer(stdin)
    thread.start()
    try:
        yield thread
    finally:
        thread.stop()


def test_parse_episode(db, with_program, ripcmd):
    with db.transaction():
        ep = ripcmd.parse_episode('1')
        assert isinstance(ep, Episode)
        assert ep.episode == 1
        assert ripcmd.parse_episode('4').episode == 4
        with pytest.raises(CmdError):
            ripcmd.parse_episode('foo')
        with pytest.raises(CmdError):
            ripcmd.parse_episode('-1')
        with pytest.raises(CmdError):
            ripcmd.parse_episode('7')
        ripcmd.config = db.set_config(with_program._replace(season=None))
        with pytest.raises(CmdError):
            ripcmd.parse_episode('4')
        ripcmd.config = db.set_config(with_program._replace(
            program=None, season=None))
        with pytest.raises(CmdError):
            ripcmd.parse_episode('4')


def test_parse_episode_range(db, with_program, ripcmd):
    with db.transaction():
        start, end = ripcmd.parse_episode_range('1-3')
        assert isinstance(start, Episode)
        assert isinstance(end, Episode)
        assert start.episode == 1
        assert end.episode == 3
        with pytest.raises(CmdError):
            ripcmd.parse_episode_range('1')


def test_parse_episode_list(db, with_program, ripcmd):
    with db.transaction():
        eps = ripcmd.parse_episode_list('1-3,5')
        assert isinstance(eps, list)
        assert [ep.episode for ep in eps] == [1, 2, 3, 5]
        eps = ripcmd.parse_episode_list('1')
        assert isinstance(eps, list)
        assert [ep.episode for ep in eps] == [1]
        with pytest.raises(CmdError):
            eps = ripcmd.parse_episode_list('')
        with pytest.raises(CmdError):
            eps = ripcmd.parse_episode_list('foo')


def test_parse_title(db, with_config, drive, blank_disc, foo_disc1, ripcmd):
    with pytest.raises(CmdError):
        ripcmd.parse_title('1')
    drive.disc = blank_disc
    ripcmd.do_scan('')
    with pytest.raises(CmdError):
        ripcmd.parse_title('1')
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    with pytest.raises(CmdError):
        ripcmd.parse_title('foo')
    with pytest.raises(CmdError):
        ripcmd.parse_title('4400')
    with pytest.raises(CmdError):
        ripcmd.parse_title('50')
    title = ripcmd.parse_title('1')
    assert isinstance(title, Title)
    assert title.number == 1


def test_parse_title_range(db, with_config, drive, foo_disc1, ripcmd):
    with pytest.raises(CmdError):
        ripcmd.parse_title_range('1')
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    start, finish = ripcmd.parse_title_range('1-5')
    assert isinstance(start, Title)
    assert start.number == 1
    assert isinstance(finish, Title)
    assert finish.number == 5


def test_parse_title_list(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    titles = ripcmd.parse_title_list('1,3-5')
    assert len(titles) == 4
    assert [t.number for t in titles] == [1, 3, 4, 5]


def test_parse_chapter(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    title = ripcmd.disc.titles[1]
    with pytest.raises(CmdError):
        ripcmd.parse_chapter(title, 'foo')
    with pytest.raises(CmdError):
        ripcmd.parse_chapter(title, '10')
    chapter = ripcmd.parse_chapter(title, '1')
    assert chapter.number == 1
    assert chapter.title is title


def test_parse_chapter_range(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    title = ripcmd.disc.titles[1]
    with pytest.raises(CmdError):
        ripcmd.parse_chapter_range(title, '1')
    start, finish = ripcmd.parse_chapter_range(title, '1-4')
    assert isinstance(start, Chapter)
    assert start.number == 1
    assert isinstance(finish, Chapter)
    assert finish.number == 4


def test_parse_title_or_chapter(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    result = ripcmd.parse_title_or_chapter('1')
    assert isinstance(result, Title)
    assert result.number == 1
    title = result
    result = ripcmd.parse_title_or_chapter('1.3')
    assert isinstance(result, Chapter)
    assert result.title is title
    assert result.number == 3


def test_parse_title_or_chapter_range(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    result = ripcmd.parse_title_or_chapter_range('1')
    assert isinstance(result, Title)
    assert result.number == 1
    title = result
    result = ripcmd.parse_title_or_chapter_range('1.2')
    assert isinstance(result, tuple)
    start, finish = result
    assert isinstance(start, Chapter)
    assert start.title is title
    assert start.number == 2
    assert start is finish
    result = ripcmd.parse_title_or_chapter_range('1.1-5')
    start, finish = result
    assert isinstance(start, Chapter)
    assert isinstance(finish, Chapter)
    assert start.title is title
    assert finish.title is title
    assert start.number == 1
    assert finish.number == 5
    result = ripcmd.parse_title_or_chapter_range('1.1-2.5')
    start, finish = result
    assert isinstance(start, Chapter)
    assert isinstance(finish, Chapter)
    assert start.title.number == 1
    assert finish.title.number == 2
    assert start.number == 1
    assert finish.number == 5


def test_print_disc(db, with_config, drive, foo_disc1, ripcmd, reader):
    # Can't print before scanning disc, and none is inserted
    with pytest.raises(CmdError):
        ripcmd.print_disc()

    # Insert disc and scan it, then check printed output
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.print_disc()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert '\n'.join([l.rstrip() for l in reader.read_all()]) == """\
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │       Duration │ Dup │ Audio   │
├───────┼──────────┼────────────────┼─────┼─────────┤
│ 1     │       24 │ 2:31:26.000006 │     │ eng eng │
│ 2     │        5 │ 0:30:00.000002 │     │ eng eng │
│ 3     │        5 │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │        5 │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │        5 │ 0:30:05.000001 │     │ eng eng │
│ 6     │        4 │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │        4 │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │        5 │ 0:31:20.000001 │     │ eng eng │
│ 9     │        2 │        0:05:03 │     │ eng eng │
│ 10    │        2 │        0:07:01 │     │ eng eng │
│ 11    │        3 │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯"""


def test_print_title(db, with_config, drive, blank_disc, foo_disc1, ripcmd, reader):
    # Can't print title prior to scan
    with pytest.raises(CmdError):
        ripcmd.print_title(None)

    # Insert a blank disc and scan it; printing titles still raises error
    drive.disc = blank_disc
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    with pytest.raises(CmdError):
        ripcmd.print_title(None)

    # Insert a disc with titles and scan it; check title output
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.print_title(ripcmd.disc.titles[0])
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert '\n'.join([l.rstrip() for l in reader.read_all()]) == """\
Title 1, duration: 2:31:26.000006, duplicate: no

╭─────────┬─────────────────┬─────────────────┬────────────────╮
│ Chapter │           Start │          Finish │       Duration │
├─────────┼─────────────────┼─────────────────┼────────────────┤
│ 1       │        00:00:00 │ 00:07:08.571429 │ 0:07:08.571429 │
│ 2       │ 00:07:08.571429 │ 00:14:17.142858 │ 0:07:08.571429 │
│ 3       │ 00:14:17.142858 │ 00:21:25.714287 │ 0:07:08.571429 │
│ 4       │ 00:21:25.714287 │ 00:28:34.285716 │ 0:07:08.571429 │
│ 5       │ 00:28:34.285716 │ 00:30:00.000002 │ 0:01:25.714286 │
│ 6       │ 00:30:00.000002 │ 00:41:25.714288 │ 0:11:25.714286 │
│ 7       │ 00:41:25.714288 │ 00:51:25.714288 │        0:10:00 │
│ 8       │ 00:51:25.714288 │ 00:57:08.571431 │ 0:05:42.857143 │
│ 9       │ 00:57:08.571431 │ 00:58:34.285717 │ 0:01:25.714286 │
│ 10      │ 00:58:34.285717 │ 01:00:00.000003 │ 0:01:25.714286 │
│ 11      │ 01:00:00.000003 │ 01:08:35.714289 │ 0:08:35.714286 │
│ 12      │ 01:08:35.714289 │ 01:20:03.333337 │ 0:11:27.619048 │
│ 13      │ 01:20:03.333337 │ 01:25:47.142861 │ 0:05:43.809524 │
│ 14      │ 01:25:47.142861 │ 01:28:39.047623 │ 0:02:51.904762 │
│ 15      │ 01:28:39.047623 │ 01:30:05.000004 │ 0:01:25.952381 │
│ 16      │ 01:30:05.000004 │ 01:38:39.571433 │ 0:08:34.571429 │
│ 17      │ 01:38:39.571433 │ 01:47:14.142862 │ 0:08:34.571429 │
│ 18      │ 01:47:14.142862 │ 01:58:40.238100 │ 0:11:26.095238 │
│ 19      │ 01:58:40.238100 │ 02:00:06.000005 │ 0:01:25.761905 │
│ 20      │ 02:00:06.000005 │ 02:12:02.190481 │ 0:11:56.190476 │
│ 21      │ 02:12:02.190481 │ 02:15:01.238100 │ 0:02:59.047619 │
│ 22      │ 02:15:01.238100 │ 02:22:28.857148 │ 0:07:27.619048 │
│ 23      │ 02:22:28.857148 │ 02:29:56.476196 │ 0:07:27.619048 │
│ 24      │ 02:29:56.476196 │ 02:31:26.000006 │ 0:01:29.523810 │
╰─────────┴─────────────────┴─────────────────┴────────────────╯

╭───────┬──────┬─────────┬──────────┬────────┬──────╮
│ Audio │ Lang │ Name    │ Encoding │ Mix    │ Best │
├───────┼──────┼─────────┼──────────┼────────┼──────┤
│ 1     │ eng  │ English │ ac3      │ stereo │  ✓   │
│ 2     │ eng  │ English │ ac3      │ stereo │      │
╰───────┴──────┴─────────┴──────────┴────────┴──────╯

╭──────────┬──────┬──────────────────────────┬────────┬──────╮
│ Subtitle │ Lang │ Name                     │ Format │ Best │
├──────────┼──────┼──────────────────────────┼────────┼──────┤
│ 1        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │  ✓   │
│ 2        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │      │
│ 3        │ fra  │ Francais (16:9) [VOBSUB] │ vobsub │      │
╰──────────┴──────┴──────────────────────────┴────────┴──────╯"""


def test_print_programs(db, with_program, ripcmd, reader):
    with db.transaction():
        ripcmd.print_programs()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
╭───────────┬─────────┬──────────┬────────╮
│ Program   │ Seasons │ Episodes │ Ripped │
├───────────┼─────────┼──────────┼────────┤
│ Foo & Bar │       2 │        9 │   0.0% │
╰───────────┴─────────┴──────────┴────────╯
"""


def test_print_seasons(db, with_program, ripcmd, reader):
    with db.transaction():
        # Printing seasons with no program selected is an error
        ripcmd.config = db.set_config(with_program._replace(
            program=None, season=None))
        with pytest.raises(CmdError):
            ripcmd.print_seasons()

        # Select program and try again; check printed output
        ripcmd.config = db.set_config(ripcmd.config._replace(
            program=with_program.program))
        ripcmd.print_seasons()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
Seasons for program Foo & Bar

╭─────┬──────────┬────────╮
│ Num │ Episodes │ Ripped │
├─────┼──────────┼────────┤
│ 1   │        5 │   0.0% │
│ 2   │        4 │   0.0% │
╰─────┴──────────┴────────╯
"""


def test_print_episodes(db, with_program, ripcmd, reader):
    with db.transaction():
        # Printing episodes with no season selected is an error
        ripcmd.config = db.set_config(with_program._replace(season=None))
        with pytest.raises(CmdError):
            ripcmd.print_episodes()
        ripcmd.config = db.set_config(with_program._replace(program=None))
        with pytest.raises(CmdError):
            ripcmd.print_episodes()

        # Select a season and try again; check printed output
        ripcmd.config = db.set_config(with_program)
        ripcmd.print_episodes()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
Episodes for season 1 of program Foo & Bar

╭─────┬───────┬────────╮
│ Num │ Title │ Ripped │
├─────┼───────┼────────┤
│ 1   │ Foo   │        │
│ 2   │ Bar   │        │
│ 3   │ Baz   │        │
│ 4   │ Quux  │        │
│ 5   │ Xyzzy │        │
╰─────┴───────┴────────╯
"""


def test_do_config(db, with_program, ripcmd, reader, tmp_path):
    with db.transaction():
        with pytest.raises(CmdError):
            ripcmd.do_config('source')

        ripcmd.do_config('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        alphabetic = re.compile('[a-z]')
        lines = [
            line.rstrip(' │\n')
            for line in reader.read_all()
            if alphabetic.search(line)
        ]
        assert '\n'.join(lines) == f"""\
│ Setting          │ Value
│ atomicparsley    │ AtomicParsley
│ handbrake        │ HandBrakeCLI
│ mkvpropedit      │ mkvpropedit
│ vlc              │ vlc
│ source           │ {tmp_path}/dvd
│ duration         │ 40.0-50.0 (mins)
│ duplicates       │ all
│ target           │ {tmp_path}/videos
│ temp             │ {tmp_path}/tmp
│ template         │ {{program}} - {{id}} - {{name}}.{{ext}}
│ id_template      │ {{season}}x{{episode:02d}}
│ output_format    │ mp4
│ max_resolution   │ 1920x1080
│ decomb           │ auto
│ audio_mix        │ dpl2
│ audio_all        │ off
│ audio_encoding   │ av_aac
│ audio_langs      │ eng
│ subtitle_format  │ none
│ subtitle_all     │ off
│ subtitle_default │ off
│ subtitle_langs   │ eng
│ video_style      │ tv
│ dvdnav           │ on
│ api
│ api_key"""


def test_do_set(ripcmd):
    assert ripcmd.config.dvdnav
    with pytest.raises(CmdError):
        ripcmd.do_set('target')
    with pytest.raises(CmdError):
        ripcmd.do_set('foo bar')
    ripcmd.do_set('dvdnav off')
    assert not ripcmd.config.dvdnav


def test_complete_set(ripcmd):
    assert completions(ripcmd, 'set foo') == []
    assert completions(ripcmd, 'set dvd') == ['dvdnav']
    assert set(completions(ripcmd, 'set audio')) == {
        'audio_mix', 'audio_all', 'audio_langs', 'audio_encoding'}
    assert completions(ripcmd, 'set foo bar') is None
    assert completions(ripcmd, 'set template foo') is None


def test_do_help(db, with_config, ripcmd, reader):
    ripcmd.do_help('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert ''.join(reader.read_all()) == """\
╭───────────┬──────────────────────────────────────────────────────────────────────────────────────╮
│ Command   │ Description                                                                          │
├───────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ automap   │ Maps episodes to titles or chapter ranges automatically                              │
│ config    │ Shows the current set of configuration options                                       │
│ disc      │ Displays information about the last scanned disc                                     │
│ duplicate │ Manually specifies duplicated titles on a disc                                       │
│ episode   │ Modifies a single episode in the current season                                      │
│ episodes  │ Gets or sets the episodes for the current season                                     │
│ exit      │ Exits from the application.                                                          │
│ help      │ Displays the available commands or help on a specified command or configuration      │
│           │ setting                                                                              │
│ map       │ Maps episodes to titles or chapter ranges                                            │
│ play      │ Plays the specified episode                                                          │
│ program   │ Sets the name of the program                                                         │
│ programs  │ Shows the defined programs                                                           │
│ quit      │ Exits from the application.                                                          │
│ rip       │ Starts the ripping and transcoding process                                           │
│ scan      │ Scans the source device for episodes                                                 │
│ season    │ Sets which season of the program the disc contains                                   │
│ seasons   │ Shows the defined seasons of the current program                                     │
│ set       │ Sets a configuration option                                                          │
│ title     │ Displays information about the specified title(s)                                    │
│ unmap     │ Removes an episode mapping                                                           │
│ unrip     │ Changes the status of the specified episode to unripped                              │
╰───────────┴──────────────────────────────────────────────────────────────────────────────────────╯
"""


def test_do_help_with_arg(db, with_config, ripcmd, reader):
    with warnings.catch_warnings():
        # Suppress the particularly silly PendingDeprecationWarning for
        # Node.traverse in docutils (the replacement doesn't even exist yet)
        warnings.filterwarnings('ignore', category=PendingDeprecationWarning)
        with pytest.raises(CmdError), warnings.catch_warnings():
            ripcmd.do_help('foo')
        ripcmd.do_help('duplicates')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert '\n'.join([l.rstrip() for l in reader.read_all()]) == """\
duplicates
==========

    set duplicates all|first|last

This setting specifies the handling of duplicates (detected by title and chapter length) by the
cmd_automap command. For various reasons, it is fairly common to find duplicated tracks on DVDs. The
valid values for this setting are:

all    This is the default setting and indicates that you wish to map and rip all tracks, regardless
       of whether they have been detected as duplicates.

first  Specifies that you only wish to rip the first out of a set of duplicate tracks. In the
       presence of actual duplicates, this is usually the best setting choice.

last   Specifies that you only wish to rip the last out of a set of duplicate tracks.

╭─ Note ───────────────────────────────────────────────────────────────────────────────────────────╮
│ In contrast to DVDs of films, where duplicate tracks are used as an anti-piracy measure, on DVD  │
│ sets of TV series it is occasionally used for "commentary" tracks. Often, duplicated titles have │
│ both audio tracks, but one title will re-order them such that the commentary track is the        │
│ default. This doesn't mean the video blocks are duplicated; just that multiple tracks with       │
│ different meta-data exist.                                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯

See also cmd_automap
"""


def test_set_executable(db, with_config, ripcmd, tmp_path):
    with db.transaction():
        assert ripcmd.config.paths['vlc'] == Path('vlc')
        with pytest.raises(CmdError):
            ripcmd.do_set(f'vlc {tmp_path}/vlc')
        (tmp_path / 'vlc').touch()
        with pytest.raises(CmdError):
            ripcmd.do_set(f'vlc {tmp_path}/vlc')
        (tmp_path / 'vlc').chmod(0o755)
        ripcmd.do_set(f'vlc {tmp_path}/vlc')
        assert ripcmd.config.paths['vlc'] == tmp_path / 'vlc'


def test_complete_set_executable(db, with_config, ripcmd, tmp_path):
    (tmp_path / 'usr' / 'bin').mkdir(parents=True)
    (tmp_path / 'usr' / 'bin' / 'foo').touch(mode=0o755)
    (tmp_path / 'usr' / 'bin' / 'bar').touch(mode=0o755)
    (tmp_path / 'usr' / 'bin' / 'baz').touch(mode=0o644)
    assert completions(ripcmd, f'set vlc {tmp_path}/g') == []
    assert completions(ripcmd, f'set vlc {tmp_path}/u') == ['/usr/']
    assert completions(ripcmd, f'set vlc {tmp_path}/usr/') == ['/bin/']
    assert completions(ripcmd, f'set vlc {tmp_path}/usr/bin/f') == ['/foo']
    assert completions(ripcmd, f'set vlc {tmp_path}/usr/bin/b') == ['/bar']


def test_set_directory(db, with_config, ripcmd, tmp_path):
    with db.transaction():
        (tmp_path / 'target').mkdir()
        (tmp_path / 'bar').touch(mode=0o644)
        assert ripcmd.config.target == tmp_path / 'videos'
        with pytest.raises(CmdError):
            ripcmd.do_set(f'target {tmp_path}/foo')
        with pytest.raises(CmdError):
            ripcmd.do_set(f'target {tmp_path}/bar')
        ripcmd.do_set(f'target {tmp_path}/target')
        assert ripcmd.config.target == tmp_path / 'target'


def test_complete_set_directory(db, with_config, ripcmd, tmp_path):
    (tmp_path / 'target').mkdir()
    (tmp_path / 'bar').touch(mode=0o644)
    assert completions(ripcmd, f'set target {tmp_path}/f') == []
    assert completions(ripcmd, f'set target {tmp_path}/b') == []
    assert completions(ripcmd, f'set target {tmp_path}/tar') == ['/target/']


def test_set_device(db, with_config, ripcmd, tmp_path):
    with db.transaction():
        with mock.patch('tvrip.ripcmd.Path.is_block_device') as is_block_device:
            (tmp_path / 'null').touch(mode=0o644)
            (tmp_path / 'sr0').touch(mode=0o644)
            (tmp_path / 'sr1').touch(mode=0o644)
            is_block_device.return_value = True
            assert ripcmd.config.source == tmp_path / 'dvd'
            ripcmd.do_set(f'source {tmp_path}/sr0')
            assert ripcmd.config.source == tmp_path / 'sr0'
            is_block_device.return_value = False
            with pytest.raises(CmdError):
                ripcmd.do_set(f'source {tmp_path}/null')
            with pytest.raises(CmdError):
                ripcmd.do_set(f'source {tmp_path}/foo')


def test_complete_set_device(db, with_config, ripcmd, tmp_path):
    with mock.patch('tvrip.ripcmd.Path.is_block_device') as is_block_device:
        (tmp_path / 'null').touch(mode=0o644)
        (tmp_path / 'sr0').touch(mode=0o644)
        (tmp_path / 'sr1').touch(mode=0o644)
        is_block_device.return_value = True
        assert completions(ripcmd, f'set source {tmp_path}/f') == []
        assert set(completions(ripcmd, f'set source {tmp_path}/s')) == {'/sr0', '/sr1'}
        is_block_device.return_value = False
        assert completions(ripcmd, f'set source {tmp_path}/s') == []


def test_set_duplicates(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.duplicates == 'all'
        ripcmd.do_set('duplicates first')
        assert ripcmd.config.duplicates == 'first'
        with pytest.raises(CmdError):
            ripcmd.do_set('duplicates foo')


def test_complete_set_duplicates(db, with_config, ripcmd):
    assert completions(ripcmd, 'set duplicates b') == []
    assert completions(ripcmd, 'set duplicates f') == ['first']
    assert set(completions(ripcmd, 'set duplicates ')) == {'all', 'first', 'last'}


def test_set_dvdnav(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.dvdnav
        ripcmd.do_set('dvdnav off')
        assert not ripcmd.config.dvdnav
        with pytest.raises(CmdError):
            ripcmd.do_set('dvdnav foo')


def test_complete_set_dvdnav(db, with_config, ripcmd):
    assert completions(ripcmd, 'set dvdnav b') == []
    assert completions(ripcmd, 'set dvdnav f') == ['false']
    assert completions(ripcmd, 'set dvdnav y') == ['yes']
    assert set(completions(ripcmd, 'set dvdnav o')) == {'off', 'on'}


def test_set_duration(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.duration == (
            dt.timedelta(minutes=40), dt.timedelta(minutes=50))
        ripcmd.do_set('duration 25-35')
        assert ripcmd.config.duration == (
            dt.timedelta(minutes=25), dt.timedelta(minutes=35))
        with pytest.raises(CmdError):
            ripcmd.do_set('duration 20')
        with pytest.raises(CmdError):
            ripcmd.do_set('duration 20-abc')


def test_set_video_style(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.video_style == 'tv'
        ripcmd.do_set('video_style anim')
        assert ripcmd.config.video_style == 'animation'
        with pytest.raises(CmdError):
            ripcmd.do_set('video_style noir')


def test_complete_set_video_style(db, with_config, ripcmd):
    assert completions(ripcmd, 'set video_style b') == []
    assert completions(ripcmd, 'set video_style a') == ['animation']
    assert set(completions(ripcmd, 'set video_style t')) == {'tv', 'television'}


def test_set_langs(db, with_config, ripcmd):
    with db.transaction():
        assert set(ripcmd.config.audio_langs) == {'eng'}
        ripcmd.do_set('audio_langs eng fra jpn')
        assert set(ripcmd.config.audio_langs) == {'eng', 'fra', 'jpn'}
        ripcmd.do_set('audio_langs eng jpn')
        assert set(ripcmd.config.audio_langs) == {'eng', 'jpn'}
        with pytest.raises(CmdError):
            ripcmd.do_set('audio_langs English')
        with pytest.raises(CmdError):
            ripcmd.do_set('audio_langs 123')


def test_complete_set_langs(db, with_config, ripcmd):
    assert completions(ripcmd, 'set audio_langs 1') == []
    assert completions(ripcmd, 'set audio_langs aa') == ['aar']
    assert set(completions(ripcmd, 'set audio_langs fra ro')) == {'roh', 'rom', 'ron'}


def test_set_audio_mix(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.audio_mix == 'dpl2'
        ripcmd.do_set('audio_mix stereo')
        assert ripcmd.config.audio_mix == 'stereo'
        with pytest.raises(CmdError):
            ripcmd.do_set('audio_mix foo')


def test_complete_set_audio_mix(db, with_config, ripcmd):
    assert completions(ripcmd, 'set audio_mix f') == []
    assert completions(ripcmd, 'set audio_mix m') == ['mono']
    assert set(completions(ripcmd, 'set audio_mix s')) == {'stereo', 'surround'}


def test_set_audio_encoding(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.audio_encoding == 'av_aac'
        ripcmd.do_set('audio_encoding mp3')
        assert ripcmd.config.audio_encoding == 'mp3'
        with pytest.raises(CmdError):
            ripcmd.do_set('audio_encoding foo')


def test_complete_set_audio_encoding(db, with_config, ripcmd):
    assert completions(ripcmd, 'set audio_encoding z') == []
    assert completions(ripcmd, 'set audio_encoding m') == ['mp3']
    assert set(completions(ripcmd, 'set audio_encoding fl')) == {
        'flac', 'flac16', 'flac24'}


def test_set_subtitle_format(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.subtitle_format == 'none'
        ripcmd.do_set('subtitle_format vobsub')
        assert ripcmd.config.subtitle_format == 'vobsub'
        with pytest.raises(CmdError):
            ripcmd.do_set('subtitle_format foo')


def test_complete_set_subtitle_format(db, with_config, ripcmd):
    assert completions(ripcmd, 'set subtitle_format f') == []
    assert completions(ripcmd, 'set subtitle_format v') == ['vobsub']
    assert set(completions(ripcmd, 'set subtitle_format b')) == {'bitmap', 'both'}


def test_set_decomb(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.decomb == 'auto'
        ripcmd.do_set('decomb off')
        assert ripcmd.config.decomb == 'off'
        ripcmd.do_set('decomb auto')
        assert ripcmd.config.decomb == 'auto'
        with pytest.raises(CmdError):
            ripcmd.do_set('decomb foo')


def test_complete_set_decomb(db, with_config, ripcmd):
    assert completions(ripcmd, 'set decomb v') == []
    assert completions(ripcmd, 'set decomb a') == ['auto']
    assert set(completions(ripcmd, 'set decomb o')) == {'on', 'off'}


def test_set_template(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.template == '{program} - {id} - {name}.{ext}'
        ripcmd.do_set('template {program}_{id}_{name}.{ext}')
        assert ripcmd.config.template == '{program}_{id}_{name}.{ext}'
        with pytest.raises(CmdError):
            ripcmd.do_set('template {foo}.{ext}')
        with pytest.raises(CmdError):
            ripcmd.do_set('template {foo')
        with pytest.raises(CmdError):
            ripcmd.do_set('template {{now:%k}')


def test_set_id_template(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.id_template == '{season}x{episode:02d}'
        ripcmd.do_set('id_template S{season:02d}E{episode:02d}')
        assert ripcmd.config.id_template == 'S{season:02d}E{episode:02d}'
        with pytest.raises(CmdError):
            ripcmd.do_set('id_template {foo}')
        with pytest.raises(CmdError):
            ripcmd.do_set('id_template {{season}')


def test_set_max_resolution(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.max_resolution == (1920, 1080)
        ripcmd.do_set('max_resolution 1280x720')
        assert ripcmd.config.max_resolution == (1280, 720)
        with pytest.raises(CmdError):
            ripcmd.do_set('max_resolution foo')
        with pytest.raises(CmdError):
            ripcmd.do_set('max_resolution 10x10')


def test_complete_set_max_resolution(db, with_config, ripcmd):
    assert completions(ripcmd, 'set max_resolution foo') == []
    assert completions(ripcmd, 'set max_resolution 6') == ['640x480']
    assert set(completions(ripcmd, 'set max_resolution 1')) == {'1024x576', '1280x720', '1920x1080'}


def test_set_output_format(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.output_format == 'mp4'
        ripcmd.do_set('output_format mkv')
        assert ripcmd.config.output_format == 'mkv'
        with pytest.raises(CmdError):
            ripcmd.do_set('output_format foo')


def test_complete_set_output_format(db, with_config, ripcmd):
    assert completions(ripcmd, 'set output_format foo') == []
    assert completions(ripcmd, 'set output_format mp') == ['mp4']
    assert set(completions(ripcmd, 'set output_format m')) == {'mkv', 'mp4'}


def test_set_api_key(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.api_key == ''
        ripcmd.do_set('api_key 12345678deadd00d12345678beefface')
        assert ripcmd.config.api_key == '12345678deadd00d12345678beefface'
        ripcmd.do_set('api_key -')
        assert ripcmd.config.api_key == ''
        with pytest.raises(CmdError):
            ripcmd.do_set('api_key foo')
        with pytest.raises(CmdError):
            ripcmd.do_set('api_key 12345678')


def test_set_api(db, with_config, ripcmd):
    with db.transaction():
        assert ripcmd.config.api == ''
        ripcmd.do_set('api TVDBv3')
        assert ripcmd.config.api == 'tvdb3'
        with pytest.raises(CmdError):
            ripcmd.do_set('api MyAPI')


def test_do_duplicate(db, with_config, drive, foo_disc1, ripcmd, reader):
    # Test various duplicate scenarios; several cases are tested here including
    # defining new duplicate tracks where none previously existed, marking
    # existing duplicates as non-duplicates, and overwriting the edges of an
    # existing duplicate range with an overlapping definition
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')

    assert ripcmd.disc.titles[2].duplicate == 'first'
    assert ripcmd.disc.titles[3].duplicate == 'last'
    ripcmd.do_duplicate('3')
    assert ripcmd.disc.titles[2].duplicate == 'no'
    assert ripcmd.disc.titles[3].duplicate == 'no'

    ripcmd.do_duplicate('3-5')
    assert ripcmd.disc.titles[2].duplicate == 'first'
    assert ripcmd.disc.titles[3].duplicate == 'yes'
    assert ripcmd.disc.titles[4].duplicate == 'last'

    ripcmd.do_duplicate('1-3')
    assert ripcmd.disc.titles[0].duplicate == 'first'
    assert ripcmd.disc.titles[1].duplicate == 'yes'
    assert ripcmd.disc.titles[2].duplicate == 'last'
    assert ripcmd.disc.titles[3].duplicate == 'first'
    assert ripcmd.disc.titles[4].duplicate == 'last'

    assert ripcmd.disc.titles[9].duplicate == 'no'
    assert ripcmd.disc.titles[10].duplicate == 'no'
    ripcmd.do_duplicate('10-11')
    assert ripcmd.disc.titles[9].duplicate == 'first'
    assert ripcmd.disc.titles[10].duplicate == 'last'


def test_do_episode(db, with_program, ripcmd):
    with db.transaction():
        prog = with_program

        # Cannot edit episodes without a season
        ripcmd.config = db.set_config(with_program._replace(season=None))
        with pytest.raises(CmdError):
            ripcmd.do_episode('delete 4')

        ripcmd.config = db.set_config(with_program._replace(season=2))
        assert len(db.get_episodes()) == 4
        assert db.get_episode(4).title == 'Foo Quux'

        # Test insertion of an episode in the middle of a season
        ripcmd.do_episode('insert 4 Foo Bar Baz')
        assert len(db.get_episodes()) == 5
        assert db.get_episode(4).title == 'Foo Bar Baz'
        assert db.get_episode(5).title == 'Foo Quux'

        # Test deletion of the previously inserted episode
        ripcmd.do_episode('delete 4')
        assert len(db.get_episodes()) == 4
        assert db.get_episode(4).title == 'Foo Quux'

        # Test re-writing an existing episode
        ripcmd.do_episode('update 4 Foo Bar Baz')
        assert len(db.get_episodes()) == 4
        assert db.get_episode(4).title == 'Foo Bar Baz'

        # Cover various syntax errors
        with pytest.raises(CmdError):
            ripcmd.do_episode('foo')
        with pytest.raises(CmdError):
            ripcmd.do_episode('insert 2')
        with pytest.raises(CmdError):
            ripcmd.do_episode('insert two Foo Bar')
        with pytest.raises(CmdError):
            ripcmd.do_episode('foo two Foo Bar')


def test_do_episodes(db, with_program, ripcmd, writer):
    with db.transaction():
        prog = with_program

        # Cannot re-define episodes without a season
        ripcmd.config = db.set_config(with_program._replace(season=None))
        with pytest.raises(CmdError):
            ripcmd.do_episodes('5')

        # Cover various syntax errors
        ripcmd.config = db.set_config(with_program._replace(season=2))
        with pytest.raises(CmdError):
            ripcmd.do_episodes('five')
        with pytest.raises(CmdError):
            ripcmd.do_episodes('-5')
        with pytest.raises(CmdError):
            ripcmd.do_episodes('1000000000')

        # Test manual re-definition of the episodes in a season
        assert [e.title for e in db.get_episodes()] == [
            'Foo Bar - Part 1', 'Foo Bar - Part 2', 'Foo Baz', 'Foo Quux']
        writer.write('Foo for Thought\n')
        writer.write('Raising the Bar\n')
        writer.write('Baz the Magnificent\n')
        ripcmd.do_episodes('3')
        assert [e.title for e in db.get_episodes()] == [
            'Foo for Thought', 'Raising the Bar', 'Baz the Magnificent']

        # Same test with early termination of episode entry
        writer.write('Foo for Thought\n')
        writer.write('Raising the Bar\n')
        writer.write('Baz the Terrible\n')
        writer.write('\n') # terminate early
        ripcmd.do_episodes('5')
        assert [e.title for e in db.get_episodes()] == [
            'Foo for Thought', 'Raising the Bar', 'Baz the Terrible']


def test_do_episodes_print(db, with_program, ripcmd, reader):
    with db.transaction():
        ripcmd.do_episodes('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
Episodes for season 1 of program Foo & Bar

╭─────┬───────┬────────╮
│ Num │ Title │ Ripped │
├─────┼───────┼────────┤
│ 1   │ Foo   │        │
│ 2   │ Bar   │        │
│ 3   │ Baz   │        │
│ 4   │ Quux  │        │
│ 5   │ Xyzzy │        │
╰─────┴───────┴────────╯
"""


def test_do_season(db, with_program, ripcmd, writer):
    with db.transaction():

    # Selecting season without a program is an error
        ripcmd.config = db.set_config(with_program._replace(
            program=None, season=None))
        with pytest.raises(CmdError):
            ripcmd.do_season('1')

        # Cover some syntax errors
        ripcmd.config = db.set_config(with_program._replace(season=2))
        with pytest.raises(CmdError):
            ripcmd.do_season('three')
        with pytest.raises(CmdError):
            ripcmd.do_season('-3')

        # Test selection of an existing season
        ripcmd.do_season('1')
        assert ripcmd.config.season == 1

        # Test manual entry of episodes for new season
        writer.write('3\n')
        writer.write('Foo for Thought\n')
        writer.write('Raising the Bar\n')
        writer.write('Baz the Imperfect\n')
        ripcmd.do_season('3')
        assert ripcmd.config.season == 3
        assert db.get_episode(1).title == 'Foo for Thought'

        # Test aborting manual entry of new season
        writer.write('0\n')
        ripcmd.do_season('4')
        assert ripcmd.config.season == 4
        assert len(db.get_episodes()) == 0


def test_do_season_from_tvdb(db, with_program, ripcmd, tvdbv3, writer):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            api_key='s3cret', api='tvdb3'))
        ripcmd.get_api()

        # Test selecting new season from TVDB results
        assert len(list(db.get_seasons())) == 2
        writer.write('1\n') # select program 1 from results table
        ripcmd.do_season('3')
        assert len(list(db.get_seasons())) == 3

        # Test fallback to manual entry (with abort) after requesting non-existing
        # season from TVDB
        writer.write('1\n') # select program 1 from results table
        writer.write('0\n') # don't define episodes
        ripcmd.do_season('4')
        assert len(list(db.get_seasons())) == 4
        assert len(db.get_episodes()) == 0


def test_complete_do_season(db, with_program, ripcmd):
    assert completions(ripcmd, 'season foo') == []
    assert set(completions(ripcmd, 'season ')) == {'1', '2'}


def test_do_seasons(db, with_program, ripcmd, reader):
    with db.transaction():
        ripcmd.do_seasons('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
Seasons for program Foo & Bar

╭─────┬──────────┬────────╮
│ Num │ Episodes │ Ripped │
├─────┼──────────┼────────┤
│ 1   │        5 │   0.0% │
│ 2   │        4 │   0.0% │
╰─────┴──────────┴────────╯
"""


def test_do_program(db, with_config, ripcmd, writer):
    with db.transaction():
        with pytest.raises(CmdError):
            ripcmd.do_program('')

        # Test manual definition of new program (note fixture is with_config,
        # so the Foo & Bar program isn't defined)
        assert ripcmd.config.program is None
        writer.write('2\n') # define 2 seasons
        writer.write('5\n') # define 5 episodes of season 1
        writer.write('Foo\n')
        writer.write('Bar\n')
        writer.write('Baz\n')
        writer.write('Quux\n')
        writer.write('Xyzzy\n')
        writer.write('4\n') # define 4 episodes of season 2
        writer.write('Foo Bar - Part 1\n')
        writer.write('Foo Bar - Part 2\n')
        writer.write('Foo Baz\n')
        writer.write('Foo Quux\n')
        ripcmd.do_program('Foo & Bar')
        assert ripcmd.config.program == 'Foo & Bar'
        assert len(list(db.get_seasons())) == 2
        assert ripcmd.config.season == 1
        assert len(db.get_episodes()) == 5


def test_do_program_existing(db, with_program, ripcmd):
    with db.transaction():
        # Test selection of existing program
        ripcmd.config = db.set_config(with_program._replace(
            program=None, season=None))
        ripcmd.do_program('Foo & Bar')
        assert ripcmd.config.program == 'Foo & Bar'


def test_do_program_found_in_tvdb(db, with_program, ripcmd, writer, tvdbv3):
    with db.transaction():
        # Test selection of new program that exists in TVDB
        ripcmd.config = db.set_config(with_program._replace(
            api_key='s3cret', api='tvdb3'))
        ripcmd.get_api()
        writer.write('1\n')
        ripcmd.do_program('Up North')
        assert ripcmd.config.program == 'Up North'
        assert ripcmd.config.season == 1
        assert len(list(db.get_seasons())) == 3


def test_do_program_found_ignored(db, with_program, ripcmd, writer, tvdbv3):
    with db.transaction():
        # Test ignoring TVDB results and performing manual entry (with abort)
        ripcmd.config = db.set_config(with_program._replace(
            api_key='s3cret', api='tvdb3'))
        ripcmd.get_api()
        writer.write('0\n')
        writer.write('0\n')
        ripcmd.do_program('The Worst')
        assert ripcmd.config.program == 'The Worst'
        assert ripcmd.config.season is None
        assert len(list(db.get_seasons())) == 0


def test_do_program_not_found_in_tvdb(db, with_program, ripcmd, writer, tvdbv3):
    with db.transaction():
        # Test selecting something not found in TVDB
        ripcmd.config = db.set_config(with_program._replace(
            api_key='s3cret', api='tvdb3'))
        ripcmd.get_api()
        writer.write('0\n')
        ripcmd.do_program('Something New')
        assert ripcmd.config.program == 'Something New'
        assert ripcmd.config.season is None
        assert len(list(db.get_seasons())) == 0


def test_complete_do_program(db, with_program, ripcmd):
    assert completions(ripcmd, 'program blah') == []
    assert completions(ripcmd, 'program Fo') == ['Foo & Bar']


def test_do_programs(db, with_program, ripcmd, reader):
    with db.transaction():
        ripcmd.do_programs('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == """\
╭───────────┬─────────┬──────────┬────────╮
│ Program   │ Seasons │ Episodes │ Ripped │
├───────────┼─────────┼──────────┼────────┤
│ Foo & Bar │       2 │        9 │   0.0% │
╰───────────┴─────────┴──────────┴────────╯
"""


def test_do_disc(db, with_config, drive, foo_disc1, ripcmd, reader):
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.do_disc('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert '\n'.join([l.rstrip() for l in reader.read_all()]) == """\
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │       Duration │ Dup │ Audio   │
├───────┼──────────┼────────────────┼─────┼─────────┤
│ 1     │       24 │ 2:31:26.000006 │     │ eng eng │
│ 2     │        5 │ 0:30:00.000002 │     │ eng eng │
│ 3     │        5 │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │        5 │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │        5 │ 0:30:05.000001 │     │ eng eng │
│ 6     │        4 │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │        4 │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │        5 │ 0:31:20.000001 │     │ eng eng │
│ 9     │        2 │        0:05:03 │     │ eng eng │
│ 10    │        2 │        0:07:01 │     │ eng eng │
│ 11    │        3 │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯"""


def test_do_title(db, with_config, drive, foo_disc1, ripcmd, reader):
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.do_title('1')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert ''.join(reader.read_all()) == """\
Title 1, duration: 2:31:26.000006, duplicate: no

╭─────────┬─────────────────┬─────────────────┬────────────────╮
│ Chapter │           Start │          Finish │       Duration │
├─────────┼─────────────────┼─────────────────┼────────────────┤
│ 1       │        00:00:00 │ 00:07:08.571429 │ 0:07:08.571429 │
│ 2       │ 00:07:08.571429 │ 00:14:17.142858 │ 0:07:08.571429 │
│ 3       │ 00:14:17.142858 │ 00:21:25.714287 │ 0:07:08.571429 │
│ 4       │ 00:21:25.714287 │ 00:28:34.285716 │ 0:07:08.571429 │
│ 5       │ 00:28:34.285716 │ 00:30:00.000002 │ 0:01:25.714286 │
│ 6       │ 00:30:00.000002 │ 00:41:25.714288 │ 0:11:25.714286 │
│ 7       │ 00:41:25.714288 │ 00:51:25.714288 │        0:10:00 │
│ 8       │ 00:51:25.714288 │ 00:57:08.571431 │ 0:05:42.857143 │
│ 9       │ 00:57:08.571431 │ 00:58:34.285717 │ 0:01:25.714286 │
│ 10      │ 00:58:34.285717 │ 01:00:00.000003 │ 0:01:25.714286 │
│ 11      │ 01:00:00.000003 │ 01:08:35.714289 │ 0:08:35.714286 │
│ 12      │ 01:08:35.714289 │ 01:20:03.333337 │ 0:11:27.619048 │
│ 13      │ 01:20:03.333337 │ 01:25:47.142861 │ 0:05:43.809524 │
│ 14      │ 01:25:47.142861 │ 01:28:39.047623 │ 0:02:51.904762 │
│ 15      │ 01:28:39.047623 │ 01:30:05.000004 │ 0:01:25.952381 │
│ 16      │ 01:30:05.000004 │ 01:38:39.571433 │ 0:08:34.571429 │
│ 17      │ 01:38:39.571433 │ 01:47:14.142862 │ 0:08:34.571429 │
│ 18      │ 01:47:14.142862 │ 01:58:40.238100 │ 0:11:26.095238 │
│ 19      │ 01:58:40.238100 │ 02:00:06.000005 │ 0:01:25.761905 │
│ 20      │ 02:00:06.000005 │ 02:12:02.190481 │ 0:11:56.190476 │
│ 21      │ 02:12:02.190481 │ 02:15:01.238100 │ 0:02:59.047619 │
│ 22      │ 02:15:01.238100 │ 02:22:28.857148 │ 0:07:27.619048 │
│ 23      │ 02:22:28.857148 │ 02:29:56.476196 │ 0:07:27.619048 │
│ 24      │ 02:29:56.476196 │ 02:31:26.000006 │ 0:01:29.523810 │
╰─────────┴─────────────────┴─────────────────┴────────────────╯

╭───────┬──────┬─────────┬──────────┬────────┬──────╮
│ Audio │ Lang │ Name    │ Encoding │ Mix    │ Best │
├───────┼──────┼─────────┼──────────┼────────┼──────┤
│ 1     │ eng  │ English │ ac3      │ stereo │  ✓   │
│ 2     │ eng  │ English │ ac3      │ stereo │      │
╰───────┴──────┴─────────┴──────────┴────────┴──────╯

╭──────────┬──────┬──────────────────────────┬────────┬──────╮
│ Subtitle │ Lang │ Name                     │ Format │ Best │
├──────────┼──────┼──────────────────────────┼────────┼──────┤
│ 1        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │  ✓   │
│ 2        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │      │
│ 3        │ fra  │ Francais (16:9) [VOBSUB] │ vobsub │      │
╰──────────┴──────┴──────────────────────────┴────────┴──────╯
"""
    with pytest.raises(CmdError):
        ripcmd.do_title('')


def test_do_play(db, with_config, drive, foo_disc1, ripcmd):
    with pytest.raises(CmdError):
        ripcmd.do_play('')

    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')

    ripcmd.do_play('')
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}' in cmdline

    ripcmd.do_play('1')
    cmdline = drive.run.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert f'dvd://{with_config.source}#1' in cmdline

    with pytest.raises(CmdError):
        # Title 9 is defined as one that plays badly in the drive mock
        ripcmd.do_play('9')


def test_do_scan_one(db, with_config, drive, foo_disc1, tmp_path, ripcmd, reader):
    drive.disc = foo_disc1
    ripcmd.do_scan('1')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert '\n'.join([l.rstrip() for l in reader.read_all()]) == f"""\
Scanning disc in {tmp_path}/dvd
Disc type:
Disc identifier: $H1$6be864bc30cf66e5acb5adf3730fc60e2b4daa83
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 1 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │       Duration │ Dup │ Audio   │
├───────┼──────────┼────────────────┼─────┼─────────┤
│ 1     │       24 │ 2:31:26.000006 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯"""


def test_do_scan_all(db, with_config, drive, foo_disc1, tmp_path, ripcmd, reader):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    assert '\n'.join([l.strip() for l in reader.read_all()]) == f"""\
Scanning disc in {tmp_path}/dvd
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │       Duration │ Dup │ Audio   │
├───────┼──────────┼────────────────┼─────┼─────────┤
│ 1     │       24 │ 2:31:26.000006 │     │ eng eng │
│ 2     │        5 │ 0:30:00.000002 │     │ eng eng │
│ 3     │        5 │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │        5 │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │        5 │ 0:30:05.000001 │     │ eng eng │
│ 6     │        4 │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │        4 │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │        5 │ 0:31:20.000001 │     │ eng eng │
│ 9     │        2 │        0:05:03 │     │ eng eng │
│ 10    │        2 │        0:07:01 │     │ eng eng │
│ 11    │        3 │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯"""


def test_do_scan_bad_title(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    with pytest.raises(CmdError):
        ripcmd.do_scan('9')


def test_do_scan_already_ripped_title(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Simulate already having ripped the first three episodes from this
        # disc
        drive.disc = foo_disc1
        disc = Disc(with_program)
        for i in (1, 2, 3):
            db.rip_episode(i, disc.titles[i])

        ripcmd.do_scan('')
        # After the scan the pre-ripped episodes are already mapped to their
        # corresponding titles
        assert len(ripcmd.episode_map) == 3
        assert {e.episode for e in ripcmd.episode_map.keys()} == {1, 2, 3}
        assert {t.number for t in ripcmd.episode_map.values()} == {2, 3, 4}


def test_do_scan_already_ripped_chapters(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Simulate already having ripped the first three episodes from this
        # disc via chapter mappings
        drive.disc = foo_disc1
        disc = Disc(with_program)
        for i in (1, 2, 3):
            db.rip_episode(i, (
                disc.titles[0].chapters[(i - 1) * 2],
                disc.titles[0].chapters[(i - 1) * 2 + 1]))

        ripcmd.do_scan('')
        # After the scan the pre-ripped episodes are already mapped to their
        # corresponding chapters
        assert len(ripcmd.episode_map) == 3
        assert {e.episode for e in ripcmd.episode_map.keys()} == {1, 2, 3}
        assert {
            (start.number, finish.number)
            for start, finish in ripcmd.episode_map.values()
        } == {(1, 2), (3, 4), (5, 6)}


def test_do_scan_ripped_title_missing(db, with_program, drive, foo_disc1, ripcmd, reader):
    with db.transaction():
        # Simulate having a ripped title that doesn't exist
        db._check_rowcount(db._conn.execute(text(
            """
            UPDATE episodes SET
                disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf',
                disc_title = 12
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            AND episode = 1
            """)))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert len(ripcmd.episode_map) == 0
        assert 'Warning: previously ripped title 12 not found' in ''.join(reader.read_all())


def test_do_scan_ripped_missing(db, with_program, drive, foo_disc1, ripcmd, reader):
    with db.transaction():
        # Simulate having ripped a chapter that doesn't exist
        db._check_rowcount(db._conn.execute(text(
            """
            UPDATE episodes SET
                disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf',
                disc_title = 1,
                start_chapter = 24,
                end_chapter = 26
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            AND episode = 1
            """)))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        # After the scan the pre-ripped episodes are already mapped
        assert len(ripcmd.episode_map) == 0
        assert 'Warning: previously ripped chapters 24, 26 not found' in ''.join(reader.read_all())


def test_do_automap_default(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Automap all 5 episodes of season 1 of Foo & Bar implicitly to all
        # non-duplicate tracks of foo_disc1
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        assert not ripcmd.episode_map
        ripcmd.do_scan('')
        ripcmd.do_automap('')
        assert {
            (episode.episode, title.number)
            for episode, title in ripcmd.episode_map.items()
        } == {(1, 2), (2, 3), (3, 5), (4, 6), (5, 8)}


def test_do_automap_episodes(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Only automap the first three episodes
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        assert not ripcmd.episode_map
        ripcmd.do_scan('')
        ripcmd.do_automap('1-3')
        assert {
            (episode.episode, title.number)
            for episode, title in ripcmd.episode_map.items()
        } == {(1, 2), (2, 3), (3, 5)}


def test_do_automap_manual(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Automap the first three episodes to the first three (non-aggregate)
        # titles of foo_disc1
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='all'))

        drive.disc = foo_disc1
        assert not ripcmd.episode_map
        ripcmd.do_scan('')
        ripcmd.do_automap('1-3 2-4')
        assert {
            (episode.episode, title.number)
            for episode, title in ripcmd.episode_map.items()
        } == {(1, 2), (2, 3), (3, 4)}


def test_do_automap_chapters(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Automap all five episodes of season 1 of Foo & Bar to the aggregated
        # title on foo_disc1
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        assert not ripcmd.episode_map
        ripcmd.do_scan('')
        ripcmd.do_automap('* 1')
        assert {
            (episode.episode, start.number, end.number)
            for episode, (start, end) in ripcmd.episode_map.items()
        } == {(1, 1, 5), (2, 6, 10), (3, 11, 15), (4, 16, 19), (5, 20, 24)}


def test_do_automap_chapters_with_ambiguity(
    db, with_program, drive, foo_disc1, ripcmd, reader, writer
):
    with db.transaction():
        # Automap all five episodes of season 1 of Foo & Bar to the aggregated
        # title on foo_disc1 using a duration limit that's weak enough to allow
        # ambiguity in the chapter selection. Use the writer fixture to inject
        # appropriate responses to resolve the ambiguity
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=28), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.stdout.flush()
        assert not ripcmd.episode_map

        with mock.patch('tvrip.cmdline.Cmd.input') as cmd_input:
            def user_response(prompt):
                m = re.match(
                    r'^Is chapter (?P<title>\d+)\.(?P<chapter>\d+) the start '
                    r'of episode (?P<episode>\d+)\?.*', prompt)
                if m:
                    return (
                        'y'
                        if (int(m.group('episode')), int(m.group('chapter')))
                        in {(1, 1), (2, 6), (3, 11), (4, 16), (5, 20)} else
                        'n')
                else:
                    return ''
            cmd_input.side_effect = user_response
            ripcmd.do_automap('* 1')

        assert {
            (episode.episode, start.number, end.number)
            for episode, (start, end) in ripcmd.episode_map.items()
        } == {(1, 1, 5), (2, 6, 10), (3, 11, 15), (4, 16, 19), (5, 20, 24)}


def test_do_automap_chapters_ambiguous_and_quit(
    db, with_program, drive, foo_disc1, ripcmd, reader, writer
):
    with db.transaction():
        # Same test as immediately above, but test replay and abort works
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=28), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.stdout.flush()
        assert not ripcmd.episode_map

        with mock.patch('tvrip.cmdline.Cmd.input') as cmd_input:
            replay = True
            garbage = True
            def user_response(prompt):
                nonlocal replay, garbage
                m = re.match(
                    r'^Is chapter (?P<title>\d+)\.(?P<chapter>\d+) the start '
                    r'of episode (?P<episode>\d+)\?.*', prompt)
                if m:
                    if m.group('episode') == '2':
                        if replay:
                            replay = False
                            return 'r'
                        elif garbage:
                            garbage = False
                            return 'foo'
                        else:
                            return 'y'
                    else:
                        return 'q'
                else:
                    return ''
            cmd_input.side_effect = user_response
            with pytest.raises(CmdError):
                ripcmd.do_automap('* 1')

        # There should be three executions of VLC: the first for chapter 5/6,
        # then again after the replay request, then for chapter 9/10/11, at
        # which point the user quits early
        vlc_chapters = [
            call.args[0][-1].rsplit('#', 1)[1]
            for call in drive.run.call_args_list
            if call.args[0][0] == 'vlc'
        ]
        assert vlc_chapters in [
            ['1:5', '1:5', '1:9'],
            ['1:6', '1:6', '1:9'],
            ['1:5', '1:5', '1:10'],
            ['1:6', '1:6', '1:10'],
            ['1:5', '1:5', '1:11'],
            ['1:6', '1:6', '1:11'],
        ]


def test_do_map_empty(db, with_program, ripcmd, reader):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            program=None, season=None))
        with pytest.raises(CmdError):
            ripcmd.do_map('')

        ripcmd.config = db.set_config(with_program._replace(season=None))
        with pytest.raises(CmdError):
            ripcmd.do_map('')
        with pytest.raises(CmdError):
            ripcmd.do_map('1')

        ripcmd.config = db.set_config(with_program)
        ripcmd.do_map('')
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert 'Episode map is currently empty' in ''.join(reader.read_all())


def test_do_map_set_titles(
    db, with_program, tmp_path, drive, foo_disc1, ripcmd, reader
):
    with db.transaction():
        drive.disc = foo_disc1
        with suppress_stdout(ripcmd):
            ripcmd.do_scan('')
        ripcmd.do_map('1 2')
        ripcmd.do_map('2 3')
        ripcmd.do_map()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == f"""\
Mapping title 2 (duration 0:30:00.000002) to 1 "Foo"
Mapping title 3 (duration 0:30:00.000001) to 2 "Bar"
Episode Mapping for Foo & Bar season 1:

╭───────┬────────────────┬────────┬─────────┬──────╮
│ Title │       Duration │ Ripped │ Episode │ Name │
├───────┼────────────────┼────────┼─────────┼──────┤
│ 2     │ 0:30:00.000002 │        │       1 │ Foo  │
│ 3     │ 0:30:00.000001 │        │       2 │ Bar  │
╰───────┴────────────────┴────────┴─────────┴──────╯
"""


def test_do_map_set_chapters(
    db, with_program, tmp_path, drive, foo_disc1, ripcmd, reader
):
    with db.transaction():
        drive.disc = foo_disc1
        with suppress_stdout(ripcmd):
            ripcmd.do_scan('')
        ripcmd.do_map('1 1.1-5')
        ripcmd.do_map('2 1.6-10')
        ripcmd.do_map()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == f"""\
Mapping chapters 1.01-05 (duration 0:30:00.000002) to 1 "Foo"
Mapping chapters 1.06-10 (duration 0:30:00.000001) to 2 "Bar"
Episode Mapping for Foo & Bar season 1:

╭─────────┬────────────────┬────────┬─────────┬──────╮
│ Title   │       Duration │ Ripped │ Episode │ Name │
├─────────┼────────────────┼────────┼─────────┼──────┤
│ 1.01-05 │ 0:30:00.000002 │        │       1 │ Foo  │
│ 1.06-10 │ 0:30:00.000001 │        │       2 │ Bar  │
╰─────────┴────────────────┴────────┴─────────┴──────╯
"""


def test_do_unmap_bad(db, with_program, ripcmd):
    with pytest.raises(CmdError):
        ripcmd.do_unmap('')
    with pytest.raises(CmdError):
        ripcmd.do_unmap('1')


def test_do_unmap_everything(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_automap('')
        ripcmd.do_unmap('*')
        assert not ripcmd.episode_map


def test_do_unmap_episode(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_automap('')
        ripcmd.do_unmap('1')
        assert {
            (episode.episode, title.number)
            for episode, title in ripcmd.episode_map.items()
        } == {(2, 3), (3, 5), (4, 6), (5, 8)}


def test_do_rip_mapped(db, with_program, tmp_path, drive, foo_disc1, ripcmd):
    with db.transaction():
        assert not ripcmd.episode_map
        with pytest.raises(CmdError):
            ripcmd.do_rip('')

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_map('1 2')
        ripcmd.do_map('2 3')
        ripcmd.do_rip('')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-o', str(tmp_path / 'videos' / 'Foo & Bar - 1x01 - Foo.mp4')) in pairwise(cmdlines[1])
        assert ('-t', '2') in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'
        assert cmdlines[3][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[3]
        assert ('-t', '3') in pairwise(cmdlines[3])
        assert cmdlines[4][0] == 'AtomicParsley'


def test_do_rip_manual(db, with_program, tmp_path, drive, foo_disc1, ripcmd):
    with db.transaction():
        assert not ripcmd.episode_map
        with pytest.raises(CmdError):
            ripcmd.do_rip('')

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_map('1 2')
        ripcmd.do_map('2 3')
        ripcmd.do_rip('2')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-o', str(tmp_path / 'videos' / 'Foo & Bar - 1x02 - Bar.mp4')) in pairwise(cmdlines[1])
        assert ('-t', '3') in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'


def test_do_rip_skip_ripped(db, with_program, tmp_path, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Simulate already having ripped the first four episodes from this disc
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))
        drive.disc = foo_disc1
        disc = Disc(with_program)
        for episode, title in [(1, 2), (2, 3), (3, 5), (4, 6)]:
            db.rip_episode(episode, disc.titles[title - 1])

        drive.run.reset_mock()
        ripcmd.do_scan('')
        ripcmd.do_automap('')
        ripcmd.do_rip('')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-t', '8') in pairwise(cmdlines[1])
        assert ('-o', str(tmp_path / 'videos' / 'Foo & Bar - 1x05 - Xyzzy.mp4')) in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'


def test_do_rip_chapters(db, with_program, tmp_path, drive, foo_disc1, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_map('1 1.1-5')
        ripcmd.do_rip('')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-o', str(tmp_path / 'videos' / 'Foo & Bar - 1x01 - Foo.mp4')) in pairwise(cmdlines[1])
        assert ('-t', '1') in pairwise(cmdlines[1])
        assert ('-c', '1-5') in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'


def test_do_rip_all_audio_and_subs(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            duration=(dt.timedelta(minutes=29), dt.timedelta(minutes=32)),
            duplicates='first', audio_all=True, subtitle_all=True,
            subtitle_format='vobsub'))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        ripcmd.do_map('1 1.1-5')
        ripcmd.do_rip('')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-a', '1,2') in pairwise(cmdlines[1])
        assert ('-s', '1,2') in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'


def test_do_rip_multi_episode_title(db, with_program, tmp_path, drive, foo_disc2, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            season=2))

        drive.disc = foo_disc2
        ripcmd.do_scan('')
        ripcmd.do_map('1 2')
        ripcmd.do_map('2 2')
        ripcmd.do_rip('')
        cmdlines = [call.args[0] for call in drive.run.call_args_list]
        assert cmdlines[0][0] == 'HandBrakeCLI'
        assert '--scan' in cmdlines[0]
        assert cmdlines[1][0] == 'HandBrakeCLI'
        assert '--scan' not in cmdlines[1]
        assert ('-o', str(tmp_path / 'videos' / 'Foo & Bar - 2x01 2x02 - Foo Bar.mp4')) in pairwise(cmdlines[1])
        assert ('-t', '2') in pairwise(cmdlines[1])
        assert cmdlines[2][0] == 'AtomicParsley'


def test_do_rip_failed(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        ripcmd.config = db.set_config(with_program._replace(
            season=2))

        drive.disc = foo_disc1
        ripcmd.do_scan('')
        # Title 9 always fails
        ripcmd.do_map('1 9')
        with pytest.raises(CmdError):
            ripcmd.do_rip('')


def test_do_unrip(db, with_program, drive, foo_disc1, ripcmd):
    with db.transaction():
        # Simulate already having ripped the first three episodes from this
        # disc
        drive.disc = foo_disc1
        disc = Disc(with_program)
        for i in (1, 2, 3):
            db.rip_episode(i, disc.titles[i])

        with pytest.raises(CmdError):
            ripcmd.do_unrip('')

        episodes = db.get_episodes()
        assert episodes[0].disc_id is not None
        ripcmd.do_unrip('1')
        episodes = db.get_episodes()
        assert episodes[0].disc_id is None
        assert episodes[1].disc_id is not None
        ripcmd.do_unrip('*')
        episodes = db.get_episodes()
        assert episodes[1].disc_id is None
        assert episodes[2].disc_id is None
        # It's not an error to specify episodes that don't exist
        ripcmd.do_unrip('1-10')


def test_interactive(db, with_program, tmp_path, drive, foo_disc1, ripcmd, reader, writer):
    ripcmd.color_prompt = False
    drive.disc = foo_disc1
    with mock.patch('tvrip.ripcmd.RipCmd.do_scan') as do_scan:
        do_scan.side_effect = RuntimeError('DVD on fire')
        # Run something that'll cause a regular command error (just printed, no
        # session rollback)
        writer.write('set video_style foo\n')
        # Run something that'll work and cause a database commit
        writer.write('set video_style animation\n')
        # Run some things that'll cause a full blown exception (session rollback)
        writer.write('scan 9\n')
        writer.write('quit\n')
        with pytest.raises(RuntimeError):
            ripcmd.cmdloop()
        ripcmd.stdout.flush()
        ripcmd.stdout.close()
        assert ''.join(reader.read_all()) == f"""\
[green](tvrip)[/green] Syntax error: Invalid video style foo
[green](tvrip)[/green] [green](tvrip)[/green] """
