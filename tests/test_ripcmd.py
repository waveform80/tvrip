import io
import os
import select
import datetime as dt
from pathlib import Path
from unittest import mock
from contextlib import closing, contextmanager
from threading import Thread, Event

import pytest

from tvrip.ripper import *
from tvrip.ripcmd import *


class Writer(Thread):
    def __init__(self, pipe):
        super().__init__(target=self.write, daemon=True)
        self.pipe = pipe
        self.stop = Event()
        self.lines = []
        self.exc = None

    def write(self):
        try:
            poll = select.poll()
            poll.register(self.pipe, select.POLLOUT)
            while not self.stop.wait(0.01):
                if poll.poll(10):
                    try:
                        line = self.lines.pop(0)
                    except IndexError:
                        pass
                    else:
                        self.pipe.write(line)
                else:
                    raise RuntimeError('waited excessive time for input')
        except Exception as exc:
            self.exc = exc

    def wait(self, timeout=None):
        self.join(timeout)
        if self.is_alive():
            raise RuntimeError('thread failed to stop before timeout')
        if self.exc is not None:
            raise self.exc


class Reader(Thread):
    def __init__(self, pipe):
        super().__init__(target=self.read, daemon=True)
        self.pipe = pipe
        self.stop = Event()
        self.lines = []
        self.exc = None

    def read(self):
        try:
            poll = select.poll()
            poll.register(self.pipe, select.POLLIN)
            while not self.stop.wait(0):
                if poll.poll(10):
                    line = self.pipe.readline()
                    if not line:
                        break
                    self.lines.append(line)
                else:
                    # No test should ever wait 10 seconds for output; probably
                    # means something's awaiting input which it'll never get
                    raise RuntimeError('waited excessive time for output')
        except Exception as exc:
            self.exc = exc

    def wait(self, timeout=None):
        self.join(timeout)
        if self.is_alive():
            raise RuntimeError('thread failed to stop before timeout')
        if self.exc is not None:
            raise self.exc


@contextmanager
def suppress_stdout(cmd):
    save_stdout = cmd.stdout
    try:
        cmd.stdout = io.StringIO()
        yield
    finally:
        cmd.stdout = save_stdout


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
def _ripcmd(request, db):
    with mock.patch('tvrip.cmdline.term_size') as term_size:
        term_size.return_value = (100, 50)
        ri, wi = os.pipe()
        ro, wo = os.pipe()
        with \
                closing(os.fdopen(ri, 'r', buffering=1, encoding='utf-8')) as stdin_r, \
                closing(os.fdopen(wi, 'w', buffering=1, encoding='utf-8')) as stdin_w, \
                closing(os.fdopen(ro, 'r', buffering=1, encoding='utf-8')) as stdout_r, \
                closing(os.fdopen(wo, 'w', buffering=1, encoding='utf-8')) as stdout_w:
            stdout_w.reconfigure(write_through=True)
            stdin_w.reconfigure(write_through=True)
            test_ripcmd = RipCmd(db, stdin=stdin_r, stdout=stdout_w)
            test_ripcmd.use_rawinput = False
            yield stdin_w, stdout_r, test_ripcmd

@pytest.fixture()
def ripcmd(request, _ripcmd):
    stdin, stdout, cmd = _ripcmd
    yield cmd

@pytest.fixture()
def stdin(request, _ripcmd):
    stdin, stdout, cmd = _ripcmd
    yield stdin

@pytest.fixture()
def stdout(request, _ripcmd):
    stdin, stdout, cmd = _ripcmd
    yield stdout

@pytest.fixture()
def readout(request, stdout):
    thread = Reader(stdout)
    thread.start()
    try:
        yield thread
    finally:
        thread.stop.set()
        thread.wait(10)

@pytest.fixture()
def writein(request, stdin):
    thread = Writer(stdin)
    thread.start()
    try:
        yield thread
    finally:
        thread.stop.set()
        thread.wait(10)


def test_new_init_db(db, ripcmd):
    # Without with_program, the db should be entirely blank, causing the
    # initializer to handle creating all default structures
    assert db.query(Configuration).one()


def test_parse_episode(db, with_program, ripcmd):
    ep = ripcmd.parse_episode('1')
    assert isinstance(ep, Episode)
    assert ep.number == 1
    assert ripcmd.parse_episode('4').number == 4
    with pytest.raises(CmdError):
        ripcmd.parse_episode('foo')
    with pytest.raises(CmdError):
        ripcmd.parse_episode('-1')
    with pytest.raises(CmdError):
        ripcmd.parse_episode('7')
    ripcmd.config.season = None
    with pytest.raises(CmdError):
        ripcmd.parse_episode('4')
    ripcmd.config.program = None
    with pytest.raises(CmdError):
        ripcmd.parse_episode('4')


def test_parse_episode_range(db, with_program, ripcmd):
    start, end = ripcmd.parse_episode_range('1-3')
    assert isinstance(start, Episode)
    assert isinstance(end, Episode)
    assert start.number == 1
    assert end.number == 3
    with pytest.raises(CmdError):
        ripcmd.parse_episode_range('1')


def test_parse_episode_list(db, with_program, ripcmd):
    ripcmd.config.season = ripcmd.config.program.seasons[0]
    ripcmd.session.commit()
    eps = ripcmd.parse_episode_list('1-3,5')
    assert isinstance(eps, list)
    assert [ep.number for ep in eps] == [1, 2, 3, 5]
    eps = ripcmd.parse_episode_list('1')
    assert isinstance(eps, list)
    assert [ep.number for ep in eps] == [1]
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


def test_clear_episodes_default(db, with_program, ripcmd):
    ripcmd.config.season = ripcmd.config.program.seasons[0]
    ripcmd.session.commit()
    assert ripcmd.config.season.episodes
    ripcmd.clear_episodes()
    ripcmd.session.commit()
    assert not ripcmd.config.season.episodes


def test_clear_episodes(db, with_program, ripcmd):
    ripcmd.config.season = ripcmd.config.program.seasons[0]
    ripcmd.session.commit()
    assert ripcmd.config.season.episodes
    ripcmd.clear_episodes(ripcmd.config.season)
    ripcmd.session.commit()
    assert not ripcmd.config.season.episodes


def test_pprint_disc(db, with_config, drive, foo_disc1, ripcmd, readout):
    # Can't print before scanning disc, and none is inserted
    with pytest.raises(CmdError):
        ripcmd.pprint_disc()

    # Insert disc and scan it, then check printed output
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.pprint_disc()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │ Duration       │ Dup │ Audio   │
╞═══════╪══════════╪════════════════╪═════╪═════════╡
│ 1     │ 24       │ 2:31:26.000006 │     │ eng eng │
│ 2     │ 5        │ 0:30:00.000002 │     │ eng eng │
│ 3     │ 5        │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │ 5        │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │ 5        │ 0:30:05.000001 │     │ eng eng │
│ 6     │ 4        │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │ 4        │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │ 5        │ 0:31:20.000001 │     │ eng eng │
│ 9     │ 2        │ 0:05:03        │     │ eng eng │
│ 10    │ 2        │ 0:07:01        │     │ eng eng │
│ 11    │ 3        │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯
"""


def test_pprint_title(db, with_config, drive, blank_disc, foo_disc1, ripcmd, readout):
    # Can't print title prior to scan
    with pytest.raises(CmdError):
        ripcmd.pprint_title(None)

    # Insert a blank disc and scan it; printing titles still raises error
    drive.disc = blank_disc
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    with pytest.raises(CmdError):
        ripcmd.pprint_title(None)

    # Insert a disc with titles and scan it; check title output
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.pprint_title(ripcmd.disc.titles[0])
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Title 1, duration: 2:31:26.000006, duplicate: no

╭─────────┬─────────────────┬─────────────────┬────────────────╮
│ Chapter │ Start           │ Finish          │ Duration       │
╞═════════╪═════════════════╪═════════════════╪════════════════╡
│ 1       │ 00:00:00        │ 00:07:08.571429 │ 0:07:08.571429 │
│ 2       │ 00:07:08.571429 │ 00:14:17.142858 │ 0:07:08.571429 │
│ 3       │ 00:14:17.142858 │ 00:21:25.714287 │ 0:07:08.571429 │
│ 4       │ 00:21:25.714287 │ 00:28:34.285716 │ 0:07:08.571429 │
│ 5       │ 00:28:34.285716 │ 00:30:00.000002 │ 0:01:25.714286 │
│ 6       │ 00:30:00.000002 │ 00:41:25.714288 │ 0:11:25.714286 │
│ 7       │ 00:41:25.714288 │ 00:51:25.714288 │ 0:10:00        │
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
╞═══════╪══════╪═════════╪══════════╪════════╪══════╡
│ 1     │ eng  │ English │ ac3      │ stereo │ ✓    │
│ 2     │ eng  │ English │ ac3      │ stereo │      │
╰───────┴──────┴─────────┴──────────┴────────┴──────╯

╭──────────┬──────┬──────────────────────────┬────────┬──────╮
│ Subtitle │ Lang │ Name                     │ Format │ Best │
╞══════════╪══════╪══════════════════════════╪════════╪══════╡
│ 1        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │ ✓    │
│ 2        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │      │
│ 3        │ fra  │ Francais (16:9) [VOBSUB] │ vobsub │      │
╰──────────┴──────┴──────────────────────────┴────────┴──────╯
"""


def test_pprint_programs(db, with_program, ripcmd, readout):
    ripcmd.pprint_programs()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
╭───────────┬─────────┬──────────┬────────╮
│ Program   │ Seasons │ Episodes │ Ripped │
╞═══════════╪═════════╪══════════╪════════╡
│ Foo & Bar │ 2       │ 9        │   0.0% │
╰───────────┴─────────┴──────────┴────────╯
"""


def test_pprint_seasons(db, with_program, ripcmd, readout):
    # Printing seasons with no program selected is an error
    ripcmd.config.program = None
    with pytest.raises(CmdError):
        ripcmd.pprint_seasons()

    # Select program and try again; check printed output
    ripcmd.config.program = with_program
    ripcmd.pprint_seasons()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Seasons for program Foo & Bar

╭─────┬──────────┬────────╮
│ Num │ Episodes │ Ripped │
╞═════╪══════════╪════════╡
│ 1   │ 5        │   0.0% │
│ 2   │ 4        │   0.0% │
╰─────┴──────────┴────────╯
"""


def test_pprint_seasons_specific(db, with_program, ripcmd, readout):
    # Same test as above but with season explicitly specified in call
    ripcmd.pprint_seasons(with_program)
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Seasons for program Foo & Bar

╭─────┬──────────┬────────╮
│ Num │ Episodes │ Ripped │
╞═════╪══════════╪════════╡
│ 1   │ 5        │   0.0% │
│ 2   │ 4        │   0.0% │
╰─────┴──────────┴────────╯
"""


def test_pprint_episodes(db, with_program, ripcmd, readout):
    # Printing episodes with no season selected is an error
    ripcmd.config.season = None
    with pytest.raises(CmdError):
        ripcmd.pprint_episodes()

    # Select a season and try again; check printed output
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.pprint_episodes()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Episodes for season 1 of program Foo & Bar

╭─────┬───────┬────────╮
│ Num │ Title │ Ripped │
╞═════╪═══════╪════════╡
│ 1   │ Foo   │        │
│ 2   │ Bar   │        │
│ 3   │ Baz   │        │
│ 4   │ Quux  │        │
│ 5   │ Xyzzy │        │
╰─────┴───────┴────────╯
"""


def test_pprint_episodes_specific(db, with_program, ripcmd, readout):
    # Same test as above but with an explicitly specified episode in the call
    ripcmd.pprint_episodes(with_program.seasons[0])
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Episodes for season 1 of program Foo & Bar

╭─────┬───────┬────────╮
│ Num │ Title │ Ripped │
╞═════╪═══════╪════════╡
│ 1   │ Foo   │        │
│ 2   │ Bar   │        │
│ 3   │ Baz   │        │
│ 4   │ Quux  │        │
│ 5   │ Xyzzy │        │
╰─────┴───────┴────────╯
"""


def test_do_config(db, with_program, ripcmd, readout, tmp_path):
    ripcmd.do_config()
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == f"""\
External Utility Paths:

atomicparsley    = AtomicParsley
handbrake        = HandBrakeCLI
vlc              = vlc

Scanning Configuration:

source           = {tmp_path}/dvd
duration         = 40.0-50.0 (mins)
duplicates       = all

Ripping Configuration:

target           = {tmp_path}/videos
temp             = {tmp_path}/tmp
template         = {{program}} - {{id}} - {{name}}.{{ext}}
id_template      = {{season}}x{{episode:02d}}
output_format    = mp4
max_resolution   = 1920x1080
decomb           = off
audio_mix        = dpl2
audio_all        = off
audio_langs      = eng
subtitle_format  = none
subtitle_all     = off
subtitle_default = off
subtitle_langs   = eng
video_style      = tv
dvdnav           = yes
api_url          = https://api.thetvdb.com/
api_key          =
"""


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
    assert set(completions(ripcmd, 'set audio')) == {'audio_mix', 'audio_all', 'audio_langs'}
    assert completions(ripcmd, 'set foo bar') is None
    assert completions(ripcmd, 'set template foo') is None


def test_do_help(ripcmd, readout):
    ripcmd.do_help('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
╭───────────┬────────────────────────────────────────────────────────────────────────────────────╮
│ Command   │ Description                                                                        │
╞═══════════╪════════════════════════════════════════════════════════════════════════════════════╡
│ automap   │ Maps episodes to titles or chapter ranges automatically.                           │
│ config    │ Shows the current set of configuration options.                                    │
│ disc      │ Displays information about the last scanned disc.                                  │
│ duplicate │ Manually specifies duplicated titles on a disc.                                    │
│ episode   │ Modifies a single episode in the current season.                                   │
│ episodes  │ Gets or sets the episodes for the current season.                                  │
│ exit      │ Exits from the application.                                                        │
│ help      │ Displays the available commands or help on a specified command or configuration    │
│           │ setting.                                                                           │
│ map       │ Maps episodes to titles or chapter ranges.                                         │
│ play      │ Plays the specified episode.                                                       │
│ program   │ Sets the name of the program.                                                      │
│ programs  │ Shows the defined programs.                                                        │
│ quit      │ Exits from the application.                                                        │
│ rip       │ Starts the ripping and transcoding process.                                        │
│ scan      │ Scans the source device for episodes.                                              │
│ season    │ Sets which season of the program the disc contains.                                │
│ seasons   │ Shows the defined seasons of the current program.                                  │
│ set       │ Sets a configuration option.                                                       │
│ title     │ Displays information about the specified title(s).                                 │
│ unmap     │ Removes an episode mapping.                                                        │
│ unrip     │ Changes the status of the specified episode to unripped.                           │
╰───────────┴────────────────────────────────────────────────────────────────────────────────────╯
"""


def test_do_help_config(ripcmd, readout):
    with pytest.raises(CmdError):
        ripcmd.do_help('foo')
    ripcmd.do_help('duplicates')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
This configuration option can be set to "all", "first", or "last". When "all", duplicate titles
will be treated individually and will all be considered for auto-mapping. When "first" only the
first of a set of duplicates will be considered for auto-mapping, and conversely when "last" only
the last of a set of duplicates will be used.

"""


def test_set_executable(db, with_config, ripcmd, tmp_path):
    assert ripcmd.config.get_path('vlc') == 'vlc'
    with pytest.raises(CmdError):
        ripcmd.do_set(f'vlc {tmp_path}/vlc')
    (tmp_path / 'vlc').touch()
    with pytest.raises(CmdError):
        ripcmd.do_set(f'vlc {tmp_path}/vlc')
    (tmp_path / 'vlc').chmod(0o755)
    ripcmd.do_set(f'vlc {tmp_path}/vlc')
    assert ripcmd.config.get_path('vlc') == f'{tmp_path}/vlc'


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
    (tmp_path / 'target').mkdir()
    (tmp_path / 'bar').touch(mode=0o644)
    assert ripcmd.config.target == str(tmp_path / 'videos')
    with pytest.raises(CmdError):
        ripcmd.do_set(f'target {tmp_path}/foo')
    with pytest.raises(CmdError):
        ripcmd.do_set(f'target {tmp_path}/bar')
    ripcmd.do_set(f'target {tmp_path}/target')
    assert ripcmd.config.target == f'{tmp_path}/target'


def test_complete_set_directory(db, with_config, ripcmd, tmp_path):
    (tmp_path / 'target').mkdir()
    (tmp_path / 'bar').touch(mode=0o644)
    assert completions(ripcmd, f'set target {tmp_path}/f') == []
    assert completions(ripcmd, f'set target {tmp_path}/b') == []
    assert completions(ripcmd, f'set target {tmp_path}/tar') == ['/target/']


def test_set_device(db, with_config, ripcmd, tmp_path):
    with mock.patch('tvrip.ripcmd.Path.is_block_device') as is_block_device:
        (tmp_path / 'null').touch(mode=0o644)
        (tmp_path / 'sr0').touch(mode=0o644)
        (tmp_path / 'sr1').touch(mode=0o644)
        is_block_device.return_value = True
        assert ripcmd.config.source == str(tmp_path / 'dvd')
        ripcmd.do_set(f'source {tmp_path}/sr0')
        assert ripcmd.config.source == str(tmp_path / 'sr0')
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
    assert ripcmd.config.duration_min == dt.timedelta(minutes=40)
    assert ripcmd.config.duration_max == dt.timedelta(minutes=50)
    ripcmd.do_set('duration 25-35')
    assert ripcmd.config.duration_min == dt.timedelta(minutes=25)
    assert ripcmd.config.duration_max == dt.timedelta(minutes=35)
    with pytest.raises(CmdError):
        ripcmd.do_set('duration 20')
    with pytest.raises(CmdError):
        ripcmd.do_set('duration 20-abc')


def test_set_video_style(db, with_config, ripcmd):
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
    assert set(l.lang for l in ripcmd.config.audio_langs) == {'eng'}
    ripcmd.do_set('audio_langs eng fra jpn')
    ripcmd.session.commit()
    assert set(l.lang for l in ripcmd.config.audio_langs) == {'eng', 'fra', 'jpn'}
    ripcmd.do_set('audio_langs eng jpn')
    ripcmd.session.commit()
    assert set(l.lang for l in ripcmd.config.audio_langs) == {'eng', 'jpn'}


def test_complete_set_langs(db, with_config, ripcmd):
    assert completions(ripcmd, 'set audio_langs 1') == []
    assert completions(ripcmd, 'set audio_langs aa') == ['aar']
    assert set(completions(ripcmd, 'set audio_langs fra ro')) == {'roh', 'rom', 'ron'}


def test_set_audio_mix(db, with_config, ripcmd):
    assert ripcmd.config.audio_mix == 'dpl2'
    ripcmd.do_set('audio_mix stereo')
    assert ripcmd.config.audio_mix == 'stereo'
    with pytest.raises(CmdError):
        ripcmd.do_set('audio_mix foo')


def test_complete_set_audio_mix(db, with_config, ripcmd):
    assert completions(ripcmd, 'set audio_mix f') == []
    assert completions(ripcmd, 'set audio_mix m') == ['mono']
    assert set(completions(ripcmd, 'set audio_mix s')) == {'stereo', 'surround'}


def test_set_subtitle_format(db, with_config, ripcmd):
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
    assert ripcmd.config.id_template == '{season}x{episode:02d}'
    ripcmd.do_set('id_template S{season:02d}E{episode:02d}')
    assert ripcmd.config.id_template == 'S{season:02d}E{episode:02d}'
    with pytest.raises(CmdError):
        ripcmd.do_set('id_template {foo}')
    with pytest.raises(CmdError):
        ripcmd.do_set('id_template {{season}')


def test_set_max_resolution(db, with_config, ripcmd):
    assert ripcmd.config.width_max == 1920
    assert ripcmd.config.height_max == 1080
    ripcmd.do_set('max_resolution 1280x720')
    assert ripcmd.config.width_max == 1280
    assert ripcmd.config.height_max == 720
    with pytest.raises(CmdError):
        ripcmd.do_set('max_resolution foo')
    with pytest.raises(CmdError):
        ripcmd.do_set('max_resolution 10x10')


def test_complete_set_max_resolution(db, with_config, ripcmd):
    assert completions(ripcmd, 'set max_resolution foo') == []
    assert completions(ripcmd, 'set max_resolution 6') == ['640x480']
    assert set(completions(ripcmd, 'set max_resolution 1')) == {'1024x576', '1280x720', '1920x1080'}


def test_set_output_format(db, with_config, ripcmd):
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
    assert ripcmd.config.api_key == ''
    ripcmd.do_set('api_key 12345678deadd00d12345678beefface')
    assert ripcmd.config.api_key == '12345678deadd00d12345678beefface'
    with pytest.raises(CmdError):
        ripcmd.do_set('api_key foo')
    with pytest.raises(CmdError):
        ripcmd.do_set('api_key 12345678')


def test_set_api_url(db, with_config, ripcmd):
    assert ripcmd.config.api_url == 'https://api.thetvdb.com/'
    ripcmd.do_set('api_url https://example.com/')
    assert ripcmd.config.api_url == 'https://example.com/'


def test_do_duplicate(db, with_config, drive, foo_disc1, ripcmd, readout):
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
    prog = with_program

    # Cannot edit episodes without a season
    ripcmd.config.program = prog
    ripcmd.config.season = None
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_episode('delete 4')

    ripcmd.config.season = prog.seasons[1]
    ripcmd.session.commit()
    assert len(ripcmd.config.season.episodes) == 4
    assert ripcmd.config.season.episodes[3].name == 'Foo Quux'

    # Test insertion of an episode in the middle of a season
    ripcmd.do_episode('insert 4 Foo Bar Baz')
    ripcmd.session.commit()
    assert len(ripcmd.config.season.episodes) == 5
    assert ripcmd.config.season.episodes[3].name == 'Foo Bar Baz'
    assert ripcmd.config.season.episodes[4].name == 'Foo Quux'

    # Test deletion of the previously inserted episode
    ripcmd.do_episode('delete 4')
    ripcmd.session.commit()
    assert len(ripcmd.config.season.episodes) == 4
    assert ripcmd.config.season.episodes[3].name == 'Foo Quux'

    # Test re-writing an existing episode
    ripcmd.do_episode('update 4 Foo Bar Baz')
    ripcmd.session.commit()
    assert len(ripcmd.config.season.episodes) == 4
    assert ripcmd.config.season.episodes[3].name == 'Foo Bar Baz'

    # Cover various syntax errors
    with pytest.raises(CmdError):
        ripcmd.do_episode('foo')
    with pytest.raises(CmdError):
        ripcmd.do_episode('insert 2')
    with pytest.raises(CmdError):
        ripcmd.do_episode('insert two Foo Bar')
    with pytest.raises(CmdError):
        ripcmd.do_episode('foo two Foo Bar')


def test_do_episodes(db, with_program, ripcmd, writein):
    prog = with_program

    # Cannot re-define episodes without a season
    ripcmd.config.program = prog
    ripcmd.config.season = None
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_episodes('5')

    # Cover various syntax errors
    ripcmd.config.season = prog.seasons[1]
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_episodes('five')
    with pytest.raises(CmdError):
        ripcmd.do_episodes('-5')
    with pytest.raises(CmdError):
        ripcmd.do_episodes('1000000000')

    # Test manual re-definition of the episodes in a season
    assert [e.name for e in ripcmd.config.season.episodes] == [
        'Foo Bar - Part 1', 'Foo Bar - Part 2', 'Foo Baz', 'Foo Quux']
    writein.lines.append('Foo for Thought\n')
    writein.lines.append('Raising the Bar\n')
    writein.lines.append('Baz the Magnificent\n')
    ripcmd.do_episodes('3')
    ripcmd.session.commit()
    assert [e.name for e in ripcmd.config.season.episodes] == [
        'Foo for Thought', 'Raising the Bar', 'Baz the Magnificent']

    # Same test with early termination of episode entry
    writein.lines.append('Foo for Thought\n')
    writein.lines.append('Raising the Bar\n')
    writein.lines.append('Baz the Terrible\n')
    writein.lines.append('\n') # terminate early
    ripcmd.do_episodes('5')
    ripcmd.session.commit()
    assert [e.name for e in ripcmd.config.season.episodes] == [
        'Foo for Thought', 'Raising the Bar', 'Baz the Terrible']


def test_do_episodes_print(db, with_program, ripcmd, readout):
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.session.commit()
    ripcmd.do_episodes('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Episodes for season 1 of program Foo & Bar

╭─────┬───────┬────────╮
│ Num │ Title │ Ripped │
╞═════╪═══════╪════════╡
│ 1   │ Foo   │        │
│ 2   │ Bar   │        │
│ 3   │ Baz   │        │
│ 4   │ Quux  │        │
│ 5   │ Xyzzy │        │
╰─────┴───────┴────────╯
"""


def test_do_season(db, with_program, ripcmd, writein):
    prog = with_program

    # Selecting season without a program is an error
    ripcmd.config.program = None
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_season('1')

    # Cover some syntax errors
    ripcmd.config.program = prog
    ripcmd.config.season = prog.seasons[1]
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_season('three')
    with pytest.raises(CmdError):
        ripcmd.do_season('-3')

    # Test selection of an existing season
    ripcmd.do_season('1')
    ripcmd.session.commit()
    assert ripcmd.config.season == prog.seasons[0]

    # Test manual entry of episodes for new season
    writein.lines.append('3\n')
    writein.lines.append('Foo for Thought\n')
    writein.lines.append('Raising the Bar\n')
    writein.lines.append('Baz the Imperfect\n')
    ripcmd.do_season('3')
    ripcmd.session.commit()
    assert ripcmd.config.season.number == 3
    assert ripcmd.config.season.episodes[0].name == 'Foo for Thought'

    # Test aborting manual entry of new season
    writein.lines.append('0\n')
    ripcmd.do_season('4')
    ripcmd.session.commit()
    assert ripcmd.config.season.number == 4
    assert len(ripcmd.config.season.episodes) == 0


def test_do_season_from_tvdb(db, with_program, ripcmd, tvdb, writein):
    ripcmd.config.api_key = 's3cret'
    ripcmd.config.api_url = tvdb.url
    ripcmd.set_api()
    ripcmd.session.commit()

    # Test selecting new season from TVDB results
    assert len(ripcmd.config.program.seasons) == 2
    writein.lines.append('1\n') # select program 1 from results table
    ripcmd.do_season('3')
    assert len(ripcmd.config.program.seasons) == 3
    ripcmd.session.commit()

    # Test fallback to manual entry (with abort) after requesting non-existing
    # season from TVDB
    writein.lines.append('1\n') # select program 1 from results table
    writein.lines.append('0\n') # don't define episodes
    ripcmd.do_season('4')
    assert len(ripcmd.config.program.seasons) == 4
    assert len(ripcmd.config.season.episodes) == 0


def test_complete_do_season(db, with_program, ripcmd):
    assert completions(ripcmd, 'season foo') == []
    assert set(completions(ripcmd, 'season ')) == {'1', '2'}


def test_do_seasons(db, with_program, ripcmd, readout):
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.session.commit()
    ripcmd.do_seasons('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Seasons for program Foo & Bar

╭─────┬──────────┬────────╮
│ Num │ Episodes │ Ripped │
╞═════╪══════════╪════════╡
│ 1   │ 5        │   0.0% │
│ 2   │ 4        │   0.0% │
╰─────┴──────────┴────────╯
"""


def test_do_program(db, with_config, ripcmd, writein):
    with pytest.raises(CmdError):
        ripcmd.do_program('')

    # Test manual definition of new program (note fixture is with_config, so
    # the Foo & Bar program isn't defined)
    assert ripcmd.config.program is None
    writein.lines.append('2\n') # define 2 seasons
    writein.lines.append('5\n') # define 5 episodes of season 1
    writein.lines.append('Foo\n')
    writein.lines.append('Bar\n')
    writein.lines.append('Baz\n')
    writein.lines.append('Quux\n')
    writein.lines.append('Xyzzy\n')
    writein.lines.append('4\n') # define 4 episodes of season 2
    writein.lines.append('Foo Bar - Part 1\n')
    writein.lines.append('Foo Bar - Part 2\n')
    writein.lines.append('Foo Baz\n')
    writein.lines.append('Foo Quux\n')
    ripcmd.do_program('Foo & Bar')
    assert ripcmd.config.program.name == 'Foo & Bar'
    assert len(ripcmd.config.program.seasons) == 2
    assert ripcmd.config.season.number == 1
    assert len(ripcmd.config.season.episodes) == 5


def test_do_program_existing(db, with_program, ripcmd):
    # Test selection of existing program
    ripcmd.config.program = None
    ripcmd.do_program('Foo & Bar')
    assert ripcmd.config.program.name == 'Foo & Bar'


def test_do_program_found_in_tvdb(db, with_program, ripcmd, writein, tvdb):
    # Test selection of new program that exists in TVDB
    ripcmd.config.api_key = 's3cret'
    ripcmd.config.api_url = tvdb.url
    ripcmd.set_api()
    writein.lines.append('1\n')
    ripcmd.do_program('Up')
    assert ripcmd.config.program.name == 'Up North'
    assert ripcmd.config.season.number == 1
    assert len(ripcmd.config.program.seasons) == 2


def test_do_program_found_ignored(db, with_program, ripcmd, writein, tvdb):
    # Test ignoring TVDB results and performing manual entry (with abort)
    ripcmd.config.api_key = 's3cret'
    ripcmd.config.api_url = tvdb.url
    ripcmd.set_api()
    writein.lines.append('0\n')
    writein.lines.append('0\n')
    ripcmd.do_program('The Worst')
    assert ripcmd.config.program.name == 'The Worst'
    assert ripcmd.config.season is None
    assert len(ripcmd.config.program.seasons) == 0


def test_do_program_not_found_in_tvdb(db, with_program, ripcmd, writein, tvdb):
    # Test selecting something not found in TVDB
    ripcmd.config.api_key = 's3cret'
    ripcmd.config.api_url = tvdb.url
    ripcmd.set_api()
    writein.lines.append('0\n')
    ripcmd.do_program('Something New')
    assert ripcmd.config.program.name == 'Something New'
    assert ripcmd.config.season is None
    assert len(ripcmd.config.program.seasons) == 0


def test_complete_do_program(db, with_program, ripcmd):
    assert completions(ripcmd, 'program blah') == []
    assert completions(ripcmd, 'program Fo') == ['Foo & Bar']


def test_do_programs(db, with_program, ripcmd, readout):
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.session.commit()
    ripcmd.do_programs('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
╭───────────┬─────────┬──────────┬────────╮
│ Program   │ Seasons │ Episodes │ Ripped │
╞═══════════╪═════════╪══════════╪════════╡
│ Foo & Bar │ 2       │ 9        │   0.0% │
╰───────────┴─────────┴──────────┴────────╯
"""


def test_do_disc(db, with_config, drive, foo_disc1, ripcmd, readout):
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.do_disc('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │ Duration       │ Dup │ Audio   │
╞═══════╪══════════╪════════════════╪═════╪═════════╡
│ 1     │ 24       │ 2:31:26.000006 │     │ eng eng │
│ 2     │ 5        │ 0:30:00.000002 │     │ eng eng │
│ 3     │ 5        │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │ 5        │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │ 5        │ 0:30:05.000001 │     │ eng eng │
│ 6     │ 4        │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │ 4        │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │ 5        │ 0:31:20.000001 │     │ eng eng │
│ 9     │ 2        │ 0:05:03        │     │ eng eng │
│ 10    │ 2        │ 0:07:01        │     │ eng eng │
│ 11    │ 3        │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯
"""


def test_do_title(db, with_config, drive, foo_disc1, ripcmd, readout):
    drive.disc = foo_disc1
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    ripcmd.do_title('1')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
Title 1, duration: 2:31:26.000006, duplicate: no

╭─────────┬─────────────────┬─────────────────┬────────────────╮
│ Chapter │ Start           │ Finish          │ Duration       │
╞═════════╪═════════════════╪═════════════════╪════════════════╡
│ 1       │ 00:00:00        │ 00:07:08.571429 │ 0:07:08.571429 │
│ 2       │ 00:07:08.571429 │ 00:14:17.142858 │ 0:07:08.571429 │
│ 3       │ 00:14:17.142858 │ 00:21:25.714287 │ 0:07:08.571429 │
│ 4       │ 00:21:25.714287 │ 00:28:34.285716 │ 0:07:08.571429 │
│ 5       │ 00:28:34.285716 │ 00:30:00.000002 │ 0:01:25.714286 │
│ 6       │ 00:30:00.000002 │ 00:41:25.714288 │ 0:11:25.714286 │
│ 7       │ 00:41:25.714288 │ 00:51:25.714288 │ 0:10:00        │
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
╞═══════╪══════╪═════════╪══════════╪════════╪══════╡
│ 1     │ eng  │ English │ ac3      │ stereo │ ✓    │
│ 2     │ eng  │ English │ ac3      │ stereo │      │
╰───────┴──────┴─────────┴──────────┴────────┴──────╯

╭──────────┬──────┬──────────────────────────┬────────┬──────╮
│ Subtitle │ Lang │ Name                     │ Format │ Best │
╞══════════╪══════╪══════════════════════════╪════════╪══════╡
│ 1        │ eng  │ English (16:9) [VOBSUB]  │ vobsub │ ✓    │
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


def test_do_scan_no_source(db, with_config, ripcmd):
    ripcmd.config.source = ''
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_scan('')


def test_do_scan_no_duration(db, with_config, ripcmd):
    ripcmd.config.duration_min = dt.timedelta(0)
    ripcmd.config.duration_max = dt.timedelta(0)
    ripcmd.session.commit()
    with pytest.raises(CmdError):
        ripcmd.do_scan('')


def test_do_scan_one(db, with_config, drive, foo_disc1, tmp_path, ripcmd, readout):
    drive.disc = foo_disc1
    ripcmd.do_scan('1')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == f"""\
Scanning disc in {tmp_path}/dvd
Disc type:
Disc identifier: $H1$6be864bc30cf66e5acb5adf3730fc60e2b4daa83
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 1 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │ Duration       │ Dup │ Audio   │
╞═══════╪══════════╪════════════════╪═════╪═════════╡
│ 1     │ 24       │ 2:31:26.000006 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯
"""


def test_do_scan_all(db, with_config, drive, foo_disc1, tmp_path, ripcmd, readout):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == f"""\
Scanning disc in {tmp_path}/dvd
Disc type:
Disc identifier: $H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf
Disc serial: 123456789
Disc name: FOO AND BAR
Disc has 11 titles

╭───────┬──────────┬────────────────┬─────┬─────────╮
│ Title │ Chapters │ Duration       │ Dup │ Audio   │
╞═══════╪══════════╪════════════════╪═════╪═════════╡
│ 1     │ 24       │ 2:31:26.000006 │     │ eng eng │
│ 2     │ 5        │ 0:30:00.000002 │     │ eng eng │
│ 3     │ 5        │ 0:30:00.000001 │ ━┓  │ eng eng │
│ 4     │ 5        │ 0:30:00.000001 │ ━┛  │ eng eng │
│ 5     │ 5        │ 0:30:05.000001 │     │ eng eng │
│ 6     │ 4        │ 0:30:01.000001 │ ━┓  │ eng eng │
│ 7     │ 4        │ 0:30:01.000001 │ ━┛  │ eng eng │
│ 8     │ 5        │ 0:31:20.000001 │     │ eng eng │
│ 9     │ 2        │ 0:05:03        │     │ eng eng │
│ 10    │ 2        │ 0:07:01        │     │ eng eng │
│ 11    │ 3        │ 0:31:30.000001 │     │ eng eng │
╰───────┴──────────┴────────────────┴─────┴─────────╯
"""


def test_do_scan_bad_title(db, with_config, drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    with pytest.raises(CmdError):
        ripcmd.do_scan('9')


def test_do_scan_already_ripped_title(db, with_program, drive, foo_disc1, ripcmd):
    # Simulate already having ripped the first three episodes from this disc
    season = ripcmd.config.season
    for i in range(3):
        season.episodes[i].disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf'
        season.episodes[i].disc_title = i + 2
    ripcmd.session.commit()

    drive.disc = foo_disc1
    ripcmd.do_scan('')
    # After the scan the pre-ripped episodes are already mapped to their
    # corresponding titles
    assert len(ripcmd.episode_map) == 3
    assert {e.number for e in ripcmd.episode_map.keys()} == {1, 2, 3}
    assert {t.number for t in ripcmd.episode_map.values()} == {2, 3, 4}


def test_do_scan_already_ripped_chapters(db, with_program, drive, foo_disc1, ripcmd):
    # Simulate already having ripped the first three episodes from this disc
    season = ripcmd.config.season
    for i in range(3):
        season.episodes[i].disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf'
        season.episodes[i].disc_title = 1
        season.episodes[i].start_chapter = (i * 2) + 1
        season.episodes[i].end_chapter = (i * 2) + 2
    ripcmd.session.commit()

    drive.disc = foo_disc1
    ripcmd.do_scan('')
    # After the scan the pre-ripped episodes are already mapped to their
    # corresponding chapters
    assert len(ripcmd.episode_map) == 3
    assert {e.number for e in ripcmd.episode_map.keys()} == {1, 2, 3}
    assert {
        (start.number, finish.number)
        for start, finish in ripcmd.episode_map.values()
    } == {(1, 2), (3, 4), (5, 6)}


def test_do_scan_ripped_title_missing(db, with_program, drive, foo_disc1, ripcmd, readout):
    # Simulate having ripped a title that doesn't exist
    season = ripcmd.config.season
    season.episodes[0].disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf'
    season.episodes[0].disc_title = 12
    ripcmd.session.commit()

    drive.disc = foo_disc1
    ripcmd.do_scan('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert len(ripcmd.episode_map) == 0
    assert 'Warning: previously ripped title 12 not found' in ''.join(readout.lines)


def test_do_scan_ripped_missing(db, with_program, drive, foo_disc1, ripcmd, readout):
    # Simulate having ripped a chapter that doesn't exist
    season = ripcmd.config.season
    season.episodes[0].disc_id = '$H1$95b276dd0eed858ce07b113fb0d48521ac1a7caf'
    season.episodes[0].disc_title = 1
    season.episodes[0].start_chapter = 24
    season.episodes[0].end_chapter = 26
    ripcmd.session.commit()

    drive.disc = foo_disc1
    ripcmd.do_scan('')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    # After the scan the pre-ripped episodes are already mapped
    assert len(ripcmd.episode_map) == 0
    assert 'Warning: previously ripped chapters 24, 26 not found' in ''.join(readout.lines)


def test_do_automap_default(db, with_program, drive, foo_disc1, ripcmd):
    # Automap all 5 episodes of season 1 of Foo & Bar implicitly to all
    # non-duplicate tracks of foo_disc1
    ripcmd.config.duration_min = dt.timedelta(minutes=29)
    ripcmd.config.duration_max = dt.timedelta(minutes=32)
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.config.duplicates = 'first'
    ripcmd.session.commit()

    drive.disc = foo_disc1
    assert not ripcmd.episode_map
    ripcmd.do_scan('')
    ripcmd.do_automap('')
    assert {
        (episode.number, title.number)
        for episode, title in ripcmd.episode_map.items()
    } == {(1, 2), (2, 3), (3, 5), (4, 6), (5, 8)}


def test_do_automap_episodes(db, with_program, drive, foo_disc1, ripcmd):
    # Only automap the first three episodes
    ripcmd.config.duration_min = dt.timedelta(minutes=29)
    ripcmd.config.duration_max = dt.timedelta(minutes=32)
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.config.duplicates = 'first'
    ripcmd.session.commit()

    drive.disc = foo_disc1
    assert not ripcmd.episode_map
    ripcmd.do_scan('')
    ripcmd.do_automap('1-3')
    assert {
        (episode.number, title.number)
        for episode, title in ripcmd.episode_map.items()
    } == {(1, 2), (2, 3), (3, 5)}


def test_do_automap_manual(db, with_program, drive, foo_disc1, ripcmd):
    # Automap the first three episodes to the first three (non-aggregate)
    # titles of foo_disc1
    ripcmd.config.duration_min = dt.timedelta(minutes=29)
    ripcmd.config.duration_max = dt.timedelta(minutes=32)
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.config.duplicates = 'all'
    ripcmd.session.commit()

    drive.disc = foo_disc1
    assert not ripcmd.episode_map
    ripcmd.do_scan('')
    ripcmd.do_automap('1-3 2-4')
    assert {
        (episode.number, title.number)
        for episode, title in ripcmd.episode_map.items()
    } == {(1, 2), (2, 3), (3, 4)}


def test_do_automap_chapters(db, with_program, drive, foo_disc1, ripcmd):
    # Automap all five episodes of season 1 of Foo & Bar to the aggregated
    # title on foo_disc1
    ripcmd.config.duration_min = dt.timedelta(minutes=29)
    ripcmd.config.duration_max = dt.timedelta(minutes=32)
    ripcmd.config.season = with_program.seasons[0]
    ripcmd.config.duplicates = 'first'
    ripcmd.session.commit()

    drive.disc = foo_disc1
    assert not ripcmd.episode_map
    ripcmd.do_scan('')
    ripcmd.do_automap('* 1')
    assert {
        (episode.number, start.number, end.number)
        for episode, (start, end) in ripcmd.episode_map.items()
    } == {(1, 1, 5), (2, 6, 10), (3, 11, 15), (4, 16, 19), (5, 20, 24)}
