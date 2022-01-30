import io
import os
from unittest import mock
from contextlib import closing

import pytest

from tvrip.cmdline import *


@pytest.fixture(scope='function')
def _cmd(request):
    ri, wi = os.pipe()
    ro, wo = os.pipe()
    with \
            closing(os.fdopen(ri, 'r', buffering=1, encoding='utf-8')) as stdin_r, \
            closing(os.fdopen(wi, 'w', buffering=1, encoding='utf-8')) as stdin_w, \
            closing(os.fdopen(ro, 'r', buffering=1, encoding='utf-8')) as stdout_r, \
            closing(os.fdopen(wo, 'w', buffering=1, encoding='utf-8')) as stdout_w:
        test_cmd = Cmd(stdin=stdin_r, stdout=stdout_w)
        test_cmd.use_rawinput = False
        yield stdin_w, stdout_r, test_cmd

@pytest.fixture()
def cmd(request, _cmd):
    stdin, stdout, cmd = _cmd
    yield cmd

@pytest.fixture()
def stdin(request, _cmd):
    stdin, stdout, cmd = _cmd
    yield stdin

@pytest.fixture()
def stdout(request, _cmd):
    stdin, stdout, cmd = _cmd
    yield stdout


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


def test_parse_docstring(cmd):
    s = f"""
    This is a long paragraph that is split over several lines, which the
    docstring parser ought to concatenate into a single string.

    This is a nother paragraph which, because it is preceded by a blank line,
    should appear in another separate string. The following lines, however,
    should *not* be treated as paragraph as they start with {cmd.base_prompt}:

    {cmd.base_prompt}command example
    {cmd.base_prompt}an other command

    Finally, a single-line paragraph for good measure.
    """
    assert cmd.parse_docstring(s) == [
        "This is a long paragraph that is split over several lines, which the "
        "docstring parser ought to concatenate into a single string.",
        "This is a nother paragraph which, because it is preceded by a blank "
        "line, should appear in another separate string. The following lines, "
        "however, should *not* be treated as paragraph as they start with "
        f"{cmd.base_prompt}:",
        f"{cmd.base_prompt}command example",
        f"{cmd.base_prompt}an other command",
        "Finally, a single-line paragraph for good measure."
    ]
    assert cmd.parse_docstring('') == []


def test_default_action(cmd):
    with pytest.raises(CmdError):
        cmd.default('')


def test_wrap_output(cmd, term_size):
    s = (
        "A very long string which is definitely longer than 80 characters and "
        "will therefore require wrapping to output at the default terminal "
        "width. It also has some trailing whitespace\t ")
    assert cmd.wrap(s) == (
        "A very long string which is definitely longer than 80 characters and will\n"
        "therefore require wrapping to output at the default terminal width. It also\n"
        "has some trailing whitespace\n")
    assert cmd.wrap(s, newline=False) == (
        "A very long string which is definitely longer than 80 characters and will\n"
        "therefore require wrapping to output at the default terminal width. It also\n"
        "has some trailing whitespace\t ")
    assert cmd.wrap(s.rstrip(), newline=False) == (
        "A very long string which is definitely longer than 80 characters and will\n"
        "therefore require wrapping to output at the default terminal width. It also\n"
        "has some trailing whitespace")
    assert cmd.wrap(s, wrap=False) == s + '\n'
    assert cmd.wrap(s, wrap=False, newline=False) == s


def test_raw_input(cmd, stdout, term_size):
    with mock.patch('tvrip.cmdline.readline') as readline, \
            mock.patch('tvrip.cmdline.input') as my_input:
        cmd.use_rawinput = True
        my_input.return_value = ' foo '
        assert cmd.input('Give me a name: ') == 'foo'
        cmd.stdout.close()
        assert stdout.read() == ''
        assert my_input.called_with('Give me a name: ')
        assert readline.remove_history_item.called


def test_input(cmd, stdin, stdout, term_size):
    stdin.write('foo\n')
    assert cmd.input('Give me a name: ') == 'foo'
    cmd.stdout.close()
    assert stdout.read() == 'Give me a name: '


def test_input_number(cmd, stdin, stdout, term_size):
    stdin.write('42\n')
    assert cmd.input_number(
        range(100), 'What do you get if you multiply six by nine?') == 42
    stdin.write('coffee\n')
    stdin.write('42\n')
    stdin.write('45\n')
    assert cmd.input_number(
        [45], 'What do you get if you multiply six by nine? ') == 45


def test_cmd_error_continues(cmd, stdout, term_size):
    assert not cmd.onecmd('help foo\n')
    cmd.stdout.close()
    assert stdout.read().splitlines() == ['Unknown command foo']


def test_pprint(cmd, stdout, term_size):
    s = (
        "The pprint method is a very simple wrapper around the 'wrap' method "
        "which simply calls TextWrapper.fill to re-format its input string as "
        "multiple word-broken lines determine by the prevailing terminal's "
        "width")
    cmd.pprint(s)
    cmd.stdout.close()
    assert stdout.read().splitlines() == [
        "The pprint method is a very simple wrapper around the 'wrap' method which",
        "simply calls TextWrapper.fill to re-format its input string as multiple word-",
        "broken lines determine by the prevailing terminal's width",
    ]


def test_pprint_table(cmd, stdout, term_size):
    data = (
        ('Episode', 'Description'),
        ('1', "The pilot episode in which the creators desperately attempt to "
         "convince test audiences and studio executives that they're onto a "
         "winner"),
        ('2', "The re-made at the last minute pilot, demanded by the studio "
         "execs who thought your pilot was 'too dark' and which will be shown "
         "confusingly out of order"),
    )
    cmd.pprint_table(data)
    cmd.stdout.close()
    assert stdout.read().splitlines() == [
        "╭─────────┬──────────────────────────────────────────────────────────────────╮",
        "│ Episode │ Description                                                      │",
        "╞═════════╪══════════════════════════════════════════════════════════════════╡",
        "│ 1       │ The pilot episode in which the creators desperately attempt to   │",
        "│         │ convince test audiences and studio executives that they're onto  │",
        "│         │ a winner                                                         │",
        "│ 2       │ The re-made at the last minute pilot, demanded by the studio     │",
        "│         │ execs who thought your pilot was 'too dark' and which will be    │",
        "│         │ shown confusingly out of order                                   │",
        "╰─────────┴──────────────────────────────────────────────────────────────────╯",
    ]


def test_do_help(cmd, stdout, term_size):
    cmd.do_help('')
    cmd.stdout.close()
    assert stdout.read().splitlines() == [
        '╭─────────┬─────────────────────────────────────────────────────────────────╮',
        '│ Command │ Description                                                     │',
        '╞═════════╪═════════════════════════════════════════════════════════════════╡',
        '│ exit    │ Exits from the application.                                     │',
        '│ help    │ Displays the available commands or help on a specified command. │',
        '│ quit    │ Exits from the application.                                     │',
        '╰─────────┴─────────────────────────────────────────────────────────────────╯',
    ]


def test_do_help_bad_command(cmd):
    with pytest.raises(CmdError):
        cmd.do_help('foo')


def test_do_help_help(cmd, stdout, term_size):
    cmd.do_help('help')
    cmd.stdout.close()
    assert stdout.read().splitlines() == [
        "The 'help' command is used to display the help text for a command or, if no",
        "command is specified, it presents a list of all available commands along with",
        "a brief description of each.",
        "",
    ]


def test_do_help_examples(cmd, stdout, term_size):
    save_help = Cmd.do_help.__doc__
    try:
        Cmd.do_help.__doc__ = """
        Provides help on commands.

        The 'help' command is used to output help on commands! I mean what did you
        think it did?! For example:

        {prompt}help
        {prompt}help help
        """.format(prompt=cmd.base_prompt)
        cmd.do_help('help')
        cmd.stdout.close()
        assert stdout.read().splitlines() == [
            "The 'help' command is used to output help on commands! I mean what did you",
            "think it did?! For example:",
            "",
            "  (Cmd) help",
            "  (Cmd) help help",
            "",
        ]
    finally:
        Cmd.do_help.__doc__ = save_help


def test_do_exit(cmd, stdout, term_size):
    with pytest.raises(CmdError):
        cmd.do_exit('foo')
    assert cmd.do_exit('')
