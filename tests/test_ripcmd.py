import io
import os
import select
from unittest import mock
from contextlib import closing, contextmanager
from threading import Thread, Event

import pytest

from tvrip.ripper import *
from tvrip.ripcmd import *


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
        command, text = line.lstrip().split(' ', 1)
        start = len(command) + 1
        finish = len(line)
        completer = getattr(cmd, f'complete_{command}')
    else:
        text = line
        start = 0
        finish = len(line)
        completer = cmd.completenames
    return completer(text, line, start, finish)


@pytest.fixture(scope='function')
def _ripcmd(request, db):
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
def readout(request, stdout, tmp_path):
    thread = Reader(stdout)
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


def test_parse_title(drive, blank_disc, foo_disc1, ripcmd):
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


def test_parse_title_range(drive, foo_disc1, ripcmd):
    with pytest.raises(CmdError):
        ripcmd.parse_title_range('1')
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    start, finish = ripcmd.parse_title_range('1-5')
    assert isinstance(start, Title)
    assert start.number == 1
    assert isinstance(finish, Title)
    assert finish.number == 5


def test_parse_title_list(drive, foo_disc1, ripcmd):
    drive.disc = foo_disc1
    ripcmd.do_scan('')
    titles = ripcmd.parse_title_list('1,3-5')
    assert len(titles) == 4
    assert [t.number for t in titles] == [1, 3, 4, 5]


def test_parse_chapter(drive, foo_disc1, ripcmd):
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


def test_parse_chapter_range(drive, foo_disc1, ripcmd):
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


def test_parse_title_or_chapter(drive, foo_disc1, ripcmd):
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


def test_parse_title_or_chapter_range(drive, foo_disc1, ripcmd):
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


def test_pprint_disc(drive, foo_disc1, ripcmd, readout):
    with pytest.raises(CmdError):
        ripcmd.pprint_disc()
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


def test_pprint_title(drive, blank_disc, foo_disc1, ripcmd, readout):
    with pytest.raises(CmdError):
        ripcmd.pprint_title(None)
    drive.disc = blank_disc
    with suppress_stdout(ripcmd):
        ripcmd.do_scan('')
    with pytest.raises(CmdError):
        ripcmd.pprint_title(None)
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
    ripcmd.config.program = None
    with pytest.raises(CmdError):
        ripcmd.pprint_seasons()
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
    ripcmd.config.season = None
    with pytest.raises(CmdError):
        ripcmd.pprint_episodes()
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

source           = /dev/dvd
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
╭───────────┬──────────────────────────────────────────────────────────────────────────────────────────╮
│ Command   │ Description                                                                              │
╞═══════════╪══════════════════════════════════════════════════════════════════════════════════════════╡
│ automap   │ Maps episodes to titles or chapter ranges automatically.                                 │
│ config    │ Shows the current set of configuration options.                                          │
│ disc      │ Displays information about the last scanned disc.                                        │
│ duplicate │ Manually specifies duplicated titles on a disc.                                          │
│ episode   │ Modifies a single episode in the current season.                                         │
│ episodes  │ Gets or sets the episodes for the current season.                                        │
│ exit      │ Exits from the application.                                                              │
│ help      │ Displays the available commands or help on a specified command or configuration setting. │
│ map       │ Maps episodes to titles or chapter ranges.                                               │
│ play      │ Plays the specified episode.                                                             │
│ program   │ Sets the name of the program.                                                            │
│ programs  │ Shows the defined programs.                                                              │
│ quit      │ Exits from the application.                                                              │
│ rip       │ Starts the ripping and transcoding process.                                              │
│ scan      │ Scans the source device for episodes.                                                    │
│ season    │ Sets which season of the program the disc contains.                                      │
│ seasons   │ Shows the defined seasons of the current program.                                        │
│ set       │ Sets a configuration option.                                                             │
│ title     │ Displays information about the specified title(s).                                       │
│ unmap     │ Removes an episode mapping.                                                              │
│ unrip     │ Changes the status of the specified episode to unripped.                                 │
╰───────────┴──────────────────────────────────────────────────────────────────────────────────────────╯
"""


def test_do_help_config(ripcmd, readout):
    with pytest.raises(CmdError):
        ripcmd.do_help('foo')
    ripcmd.do_help('duplicates')
    ripcmd.stdout.flush()
    ripcmd.stdout.close()
    readout.wait(10)
    assert ''.join(readout.lines) == """\
This configuration option can be set to "all", "first", or "last". When "all", duplicate titles will be treated
individually and will all be considered for auto-mapping. When "first" only the first of a set of duplicates will be
considered for auto-mapping, and conversely when "last" only the last of a set of duplicates will be used.

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
