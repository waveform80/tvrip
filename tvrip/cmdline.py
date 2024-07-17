# vim: set et sw=4 sts=4:

# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
#
# This file is part of tvrip.
#
# tvrip is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# tvrip.  If not, see <http://www.gnu.org/licenses/>.

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
from textwrap import dedent
from importlib import resources
from unittest import mock

from rich import box
from rich.console import Console
from rich.table import Table

from .richrst import RestructuredText, rest_theme


class CmdError(Exception):
    "Base class for non-fatal Cmd errors"
    def __str__(self):
        return f'Error: {super().__str__()}'

    def __rich__(self):
        return f'[red]Error:[/red] {super().__str__()}'


class CmdSyntaxError(CmdError):
    "Exception raised when the user makes a syntax error"
    def __str__(self):
        return f'Syntax error: {super().__str__()}'

    def __rich__(self):
        return f'[red]Syntax error:[/red] {super().__str__()}'


class Cmd(cmd.Cmd):
    """
    An enhanced version of the standard Cmd command line processor, using rich
    for console output.
    """
    history_file = None
    history_size = 1000  # <0 implies infinite history

    def __init__(self, stdin=None, stdout=None):
        super().__init__(stdin=stdin, stdout=stdout)
        self.console = Console(highlight=False, theme=rest_theme)
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
            raise ValueError(
                'Invalid boolean expression {}'.format(value))

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
            raise CmdSyntaxError(
                '{}-{} range goes backwards'.format(start, finish))
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

    def cmdloop(self, intro=None):
        # This is evil, but unfortunately there's no other way (other than
        # re-implemting the entire cmdloop method)
        with mock.patch('cmd.input', self.console.input):
            super().cmdloop(intro)

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

    def onecmd(self, line):
        # Just catch and report CmdError's; don't terminate execution because
        # of them
        try:
            return super().onecmd(line)
        except CmdError as exc:
            self.console.print(exc)
            return False

    whitespace_re = re.compile(r'\s+$')

    def input(self, prompt=''):
        "Prompts and reads input from the user"
        lines = self.wrap(prompt, newline=False).split('\n')
        prompt = lines[-1]
        s = ''.join(line + '\n' for line in lines[:-1])
        self.stdout.write(s)
        if self.use_rawinput:
            result = input(prompt).strip()
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
        suffix = '[{min}-{max}]'.format(
            min=min(valid), max=max(valid))
        prompt = '{prompt} {suffix} '.format(prompt=prompt, suffix=suffix)
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

        The 'help' command is used to display the help text for a command or,
        if no command is specified, it presents a list of all available
        commands along with a brief description of each.
        """
        if arg:
            if not hasattr(self, f'do_{arg}'):
                raise CmdError('Unknown command {}'.format(arg))
            with resources.files('tvrip') as root:
                source = RestructuredText.from_path(root / f'cmd_{arg}.rst')
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
