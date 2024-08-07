# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2011-2014 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Enhanced version of the standard Python Cmd command line interpreter.

This module defines an enhanced version of the standard Python Cmd command line
base class. The extra facilities provided are:

* Colored prompts

* Utility methods for parsing common syntax (number ranges, lists)

* Utility methods to aid in readline-completion

* Persistent readline history

* Session terminates on EOF (Ctrl+D on Linux)

* Custom exception class for command handlers which does not terminate the
  application but is simply caught and printed verbatim

* Methods for pretty-printing text (with wrapping and variable indentation)
  and tables

* A method for accepting prompted user input

* An enhanced do_help method which extracts documentation from do_ docstrings
"""

import os
import re
import cmd
import readline
from unittest import mock
from textwrap import dedent
from importlib import resources
from contextlib import ExitStack

from rich import box
from rich.console import Console
from rich.table import Table

from .richrst import RestructuredText, rest_theme


class CmdError(Exception):
    "Base class for non-fatal Cmd errors"
    def __str__(self):
        return f'Error: {self.args[0]}'

    def __rich__(self):
        return f'[red]Error:[/red] {self.args[0]}'


class CmdSyntaxError(CmdError):
    "Exception raised when the user makes a syntax error"
    def __str__(self):
        return f'Syntax error: {self.args[0]}'

    def __rich__(self):
        return f'[red]Syntax error:[/red] {self.args[0]}'


class CmdContext:
    def __init__(self, console):
        self.console = console

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        exc_type, exc_value, exc_tb = exc_info
        if exc_type is not None and issubclass(exc_type, CmdError):
            self.console.print(exc_value)
            return True
        else:
            return False


class Cmd(cmd.Cmd):
    """
    An enhanced version of the standard Cmd command line processor, using rich
    for console output.
    """
    history_file = None
    history_size = 1000  # <0 implies infinite history

    def __init__(self, stdin=None, stdout=None):
        super().__init__(stdin=stdin, stdout=stdout)
        self.console = Console(highlight=False, theme=rest_theme, file=stdout)
        # Clamp the console width for readability
        if self.console.width > 120:
            self.console.width = 120

    @staticmethod
    def parse_bool(value, default=None):
        """
        Parse a string containing a boolean value.

        Given a string representing a boolean value, this method returns True
        or False, or raises a ValueError if the conversion cannot be performed.
        """
        value = value.lower()
        if value == '' and default is not None:
            return default
        elif value in set(('0', 'false', 'off', 'no', 'n')):
            return False
        elif value in set(('1', 'true', 'on', 'yes', 'y')):
            return True
        else:
            raise ValueError(f'Invalid boolean expression {value}')

    @staticmethod
    def parse_number_range(s):
        """
        Parse a dash-separated number range.

        Given a string containing two dash-separated numbers, returns the
        integer value of the start and end of the range.
        """
        try:
            start, finish = (int(i) for i in s.split('-', 1))
        except ValueError as exc:
            raise CmdSyntaxError(exc) from None
        if finish < start:
            raise CmdSyntaxError(f'{start}-{finish} range goes backwards')
        return start, finish

    @staticmethod
    def parse_number_list(s):
        """
        Parse a comma-separated list of dash-separated number ranges.

        Given a string containing comma-separated numbers or ranges of numbers,
        returns a sequence of all specified numbers (ranges of numbers are
        expanded by this method).
        """
        result = []
        for i in s.split(','):
            if '-' in i:
                start, finish = Cmd.parse_number_range(i)
                result.extend(range(start, finish + 1))
            else:
                try:
                    result.append(int(i))
                except ValueError as exc:
                    raise CmdSyntaxError(exc) from None
        return result

    def default(self, line):
        raise CmdSyntaxError(line)

    def emptyline(self):
        # Do not repeat commands when given an empty line
        self.console.print('')
        return False

    def cmdloop(self, intro=None):
        # This is evil, but unfortunately there's no other way (other than
        # re-implemting the entire cmdloop method)
        with mock.patch('cmd.input', self.console.input):
            return super().cmdloop(intro)

    def preloop(self):
        if (
            self.use_rawinput and self.history_file and
            os.path.exists(self.history_file)
        ):
            readline.read_history_file(self.history_file)

    def postloop(self):
        if self.use_rawinput:
            readline.set_history_length(self.history_size)
            readline.write_history_file(self.history_file)

    def cmdcontext(self):
        """
        Provides a :class:`contextlib.ExitStack` which forms the context of
        command execution by :meth:`onecmd`. By default, a :class:`CmdContext`
        is in the stack to suppress all :exc:`CmdError` exceptions. This may
        be overridden to add more context managers.
        """
        stack = ExitStack()
        stack.enter_context(CmdContext(self.console))
        return stack

    def onecmd(self, line):
        with self.cmdcontext() as stack:
            return super().onecmd(line)

    whitespace_re = re.compile(r'\s+$')

    def input(self, prompt=''):
        "Prompts and reads input from the user"
        if self.use_rawinput:
            result = self.console.input(prompt, stream=self.stdin).strip()
            # Strip the history from readline (we only want commands in the
            # history)
            readline.remove_history_item(
                readline.get_current_history_length() - 1)
        else:
            self.stdout.write(prompt)
            result = self.stdin.readline().strip()
        return result

    def input_number(self, valid, prompt=''):
        """
        Prompts and reads numeric input (from a limited set of *valid* inputs,
        which can be any iterable supporting "in") from the user.
        """
        suffix = f'[{min(valid)}-{max(valid)}]'
        prompt = f'{prompt} {suffix} '
        while True:
            try:
                result = int(self.input(prompt))
                if result not in valid:
                    raise ValueError('out of range')
            except ValueError:
                self.stdout.write('Invalid input\n')
                continue
            else:
                return result

    def do_help(self, arg):
        """
        Displays the available commands or help on a specified command.
        """
        if arg:
            if not hasattr(self, f'do_{arg}'):
                raise CmdError(f'Unknown command {arg}')
            with resources.files('tvrip') as root:
                source = RestructuredText.from_path(
                    root / 'docs' / f'cmd_{arg}.rst')
                self.console.print(source)
        else:
            table = Table(box=box.ROUNDED)
            table.add_column('Command', no_wrap=True)
            table.add_column('Description')
            for method in self.get_names():
                if method.startswith('do_') and method != 'do_EOF':
                    name = method[3:]
                    description = getattr(self, method).__doc__
                    description = ' '.join(
                        line.strip()
                        for line in dedent(description).splitlines()
                        if line.strip()
                    )
                    table.add_row(name, description)
            self.console.print(table)

    def do_exit(self, arg):
        """
        Exits from the application.
        """
        if arg:
            raise CmdSyntaxError('Unknown argument %s' % arg)
        self.console.print('')
        return True

    do_quit = do_exit

    do_EOF = do_exit
