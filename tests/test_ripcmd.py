import io
import os
from unittest import mock
from contextlib import closing

import pytest

from tvrip.ripcmd import *


@pytest.fixture(scope='function')
def _ripcmd(request, db):
    ri, wi = os.pipe()
    ro, wo = os.pipe()
    with \
            closing(os.fdopen(ri, 'r', buffering=1, encoding='utf-8')) as stdin_r, \
            closing(os.fdopen(wi, 'w', buffering=1, encoding='utf-8')) as stdin_w, \
            closing(os.fdopen(ro, 'r', buffering=1, encoding='utf-8')) as stdout_r, \
            closing(os.fdopen(wo, 'w', buffering=1, encoding='utf-8')) as stdout_w:
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
    title = ripcmd.parse_title('1')
    assert isinstance(title, Title)
    assert title.number == 1
