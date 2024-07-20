import io
import os
from unittest import mock
from contextlib import closing

import pytest

from tvrip.cmdline import *


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

@pytest.fixture()
def cmd(request, stdin_pipe, stdout_pipe):
    stdin_r, _ = stdin_pipe
    _, stdout_w = stdout_pipe
    test_cmd = Cmd(stdin=stdin_r, stdout=stdout_w)
    test_cmd.use_rawinput = False
    yield test_cmd

@pytest.fixture()
def stdin(request, stdin_pipe):
    _, stdin_w = stdin_pipe
    yield stdin_w

@pytest.fixture()
def stdout(request, stdout_pipe):
    stdout_r, _ = stdout_pipe
    yield stdout_r


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


def test_default_action(cmd):
    with pytest.raises(CmdError):
        cmd.default('')


def test_raw_input(cmd, stdin, stdout):
    with mock.patch('tvrip.cmdline.readline') as readline:
        cmd.use_rawinput = True
        stdin.write(' foo \n')
        assert cmd.input('Give me a name: ') == 'foo'
        cmd.stdout.close()
        assert stdout.read() == 'Give me a name: '
        assert readline.remove_history_item.called


def test_input(cmd, stdin, stdout):
    stdin.write('foo\n')
    assert cmd.input('Give me a name: ') == 'foo'
    cmd.stdout.close()
    assert stdout.read() == 'Give me a name: '


def test_input_number(cmd, stdin, stdout):
    stdin.write('42\n')
    assert cmd.input_number(
        range(100), 'What do you get if you multiply six by nine?') == 42
    stdin.write('coffee\n')
    stdin.write('42\n')
    stdin.write('45\n')
    assert cmd.input_number(
        [45], 'What do you get if you multiply six by nine? ') == 45


def test_cmd_error_continues(cmd, stdout):
    assert not cmd.onecmd('help foo\n')
    cmd.stdout.close()
    assert stdout.read().splitlines() == ['Error: Unknown command foo']


def test_cmd_syntaxerror_continues(stdout_pipe):
    stdout_r, stdout_w = stdout_pipe
    class MyCmd(Cmd):
        def do_numbers(self, arg):
            for i in self.parse_number_list(arg):
                print(i)
    cmd = MyCmd(stdout=stdout_w)
    assert not cmd.onecmd('numbers 1-3,foo')
    cmd.stdout.close()
    assert stdout_r.read().splitlines() == [
        "Syntax error: invalid literal for int() with base 10: 'foo'"]


def test_cmd_empty_input(cmd, stdout):
    assert not cmd.onecmd('help foo\n')
    assert not cmd.onecmd('')
    cmd.stdout.close()
    assert stdout.read().splitlines() == ['Error: Unknown command foo', '']


def test_cmd_width_clamp(monkeypatch):
    with monkeypatch.context() as m:
        m.setenv('COLUMNS', '180')
        cmd = Cmd()
        assert cmd.console.width == 120


def test_do_help(cmd, stdout):
    cmd.console.width = 80
    cmd.do_help('')
    cmd.stdout.close()
    assert stdout.read().splitlines() == [
        '╭─────────┬─────────────────────────────────────────────────────────────────╮',
        '│ Command │ Description                                                     │',
        '├─────────┼─────────────────────────────────────────────────────────────────┤',
        '│ exit    │ Exits from the application.                                     │',
        '│ help    │ Displays the available commands or help on a specified command. │',
        '│ quit    │ Exits from the application.                                     │',
        '╰─────────┴─────────────────────────────────────────────────────────────────╯',
    ]


def test_do_help_bad_command(cmd):
    with pytest.raises(CmdError):
        cmd.do_help('foo')


def test_do_help_help(cmd, stdout):
    cmd.do_help('help')
    cmd.stdout.close()
    assert [s.rstrip() for s in stdout.read().splitlines()] == [
        'help',
        '====',
        '',
        '    help [command|setting]',
        '',
        'Description',
        '~~~~~~~~~~~',
        '',
        "The 'help' command displays the list of commands available along with a brief",
        'synopsis of each. When specified with a command, it displays the manual page for',
        'that particular command. When specified with a configuration setting, it',
        'displays information about that setting and its valid options.',
        '',
    ]


def test_do_exit(cmd, stdout):
    with pytest.raises(CmdError):
        cmd.do_exit('foo')
    assert cmd.do_exit('')


def test_error_str():
    assert str(CmdError('no such command foo')) == 'Error: no such command foo'
    assert str(CmdSyntaxError('invalid number a')) == 'Syntax error: invalid number a'
