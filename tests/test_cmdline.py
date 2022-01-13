import io

import pytest

from tvrip.cmdline import *


@pytest.fixture()
def _cmd(request):
    with io.StringIO() as stdin, io.StringIO() as stdout:
        yield stdin, stdout, Cmd(stdin=stdin, stdout=stdout)

@pytest.fixture()
def cmd(_cmd):
    stdin, stdout, cmd = _cmd
    yield cmd

@pytest.fixture()
def stdin(_cmd):
    stdin, stdout, cmd = _cmd
    yield stdin.write

@pytest.fixture()
def stdout(_cmd):
    stdin, stdout, cmd = _cmd
    yield stdout.read


def test_parse_bool():
    assert Cmd.parse_bool('Y') == True
    assert Cmd.parse_bool('n') == False
    assert Cmd.parse_bool('off') == False
    assert Cmd.parse_bool('', default=True) == True
    with pytest.raises(ValueError):
        Cmd.parse_bool('')
    with pytest.raises(ValueError):
        Cmd.parse_bool('foo')


def test_parse_number_range():
    assert Cmd.parse_number_range('5-10') == (5, 10)
    assert Cmd.parse_number_range('1-2') == (1, 2)
    assert Cmd.parse_number_range('2-2') == (2, 2)
    with pytest.raises(CmdError):
        Cmd.parse_number_range('')
    with pytest.raises(CmdError):
        Cmd.parse_number_range('1')
    with pytest.raises(CmdError):
        Cmd.parse_number_range('-1')
    with pytest.raises(CmdError):
        Cmd.parse_number_range('2-1')


def test_parse_number_list():
    assert Cmd.parse_number_list('1') == [1]
    assert Cmd.parse_number_list('1,2') == [1, 2]
    assert Cmd.parse_number_list('2,1') == [2, 1]
    assert Cmd.parse_number_list('1,2-4') == [1, 2, 3, 4]
    assert Cmd.parse_number_list('1,3-5') == [1, 3, 4, 5]
    assert Cmd.parse_number_list('3-5') == [3, 4, 5]
    assert Cmd.parse_number_list('3-5,1') == [3, 4, 5, 1]
    with pytest.raises(CmdError):
        Cmd.parse_number_list('')
    with pytest.raises(CmdError):
        Cmd.parse_number_list('-1')
    with pytest.raises(CmdError):
        Cmd.parse_number_list('2-1')
    with pytest.raises(CmdError):
        Cmd.parse_number_list('3,2-1')
