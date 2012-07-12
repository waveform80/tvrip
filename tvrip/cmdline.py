# vim: set et sw=4 sts=4:

# Copyright 2012 Dave Hughes.
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

"""Enhanced version of the standard Python Cmd command line interpreter.

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

from __future__ import (
    unicode_literals, print_function, absolute_import, division)

import os
import re
import cmd
import readline
import locale
from textwrap import TextWrapper
from tvrip.termsize import terminal_size

COLOR_BOLD    = '\033[1m'
COLOR_BLACK   = '\033[30m'
COLOR_RED     = '\033[31m'
COLOR_GREEN   = '\033[32m'
COLOR_YELLOW  = '\033[33m'
COLOR_BLUE    = '\033[34m'
COLOR_MAGENTA = '\033[35m'
COLOR_CYAN    = '\033[36m'
COLOR_WHITE   = '\033[37m'
COLOR_RESET   = '\033[0m'
ENCODING = locale.getdefaultlocale()[1]

__all__ = ['CmdError', 'CmdSyntaxError', 'Cmd']


class CmdError(Exception):
    "Base class for non-fatal Cmd errors"

class CmdSyntaxError(CmdError):
    "Exception raised when the user makes a syntax error"

class Cmd(cmd.Cmd):
    "An enhanced version of the standard Cmd command line processor"
    use_rawinput = True
    history_file = None
    history_size = 1000 # <0 implies infinite history

    def __init__(self, color_prompt=True):
        cmd.Cmd.__init__(self)
        self._wrapper = TextWrapper()
        self.color_prompt = color_prompt
        self.base_prompt = self.prompt

    def parse_boolean(self, s):
        """Parse a boolean value.

        Given a string, interprets it as a boolean value (True, False).
        """
        try:
            return {
                'false': False,
                'off':   False,
                'no':    False,
                'n':     False,
                '0':     False,
                'true':  True,
                'on':    True,
                'yes':   True,
                'y':     True,
                '1':     True,
            }[s.strip().lower()]
        except KeyError:
            raise CmdSyntaxError("invalid boolean literal '%s'" % s)

    def parse_number_range(self, s):
        """Parse a dash-separated number range.

        Given a string containing two dash-separated numbers, returns the integer
        value of the start and end of the range.
        """
        try:
            start, finish = (int(i) for i in s.split('-', 1))
        except ValueError, exc:
            raise CmdSyntaxError(exc)
        if finish < start:
            raise CmdSyntaxError('%d-%d range goes backwards' % (start, finish))
        return start, finish

    def parse_number_list(self, s):
        """Parse a comma-separated list of dash-separated number ranges.

        Given a string containing comma-separated numbers or ranges of numbers,
        returns a sequence of all specified numbers (ranges of numbers are expanded
        by this method).
        """
        result = []
        for i in s.split(','):
            if '-' in i:
                start, finish = self.parse_number_range(i)
                result.extend(range(start, finish + 1))
            else:
                try:
                    result.append(int(i))
                except ValueError, exc:
                    raise CmdSyntaxError(exc)
        return result

    def parse_docstring(self, docstring):
        """Utility method for converting docstrings into help-text"""
        lines = [line.strip() for line in docstring.splitlines()]
        result = ['']
        for line in lines:
            if result:
                if line:
                    if line.startswith(self.base_prompt):
                        if result[-1]:
                            result.append(line)
                        else:
                            result[-1] = line
                    else:
                        if result[-1]:
                            result[-1] += ' ' + line
                        else:
                            result[-1] = line
                else:
                    result.append('')
        if not result[-1]:
            result = result[:-1]
        return result

    def complete_path(self, text, line, start, finish):
        """Utility routine used by path completion methods"""
        path, _ = os.path.split(line)
        return [
            item
            for item in os.listdir(os.path.expanduser(path))
            if item.startswith(text)
        ]

    def default(self, line):
        raise CmdSyntaxError('Syntax error: %s' % line)

    def emptyline(self):
        # Do not repeat commands when given an empty line
        pass

    def preloop(self):
        if self.color_prompt:
            self.prompt = COLOR_BOLD + COLOR_GREEN + self.prompt + COLOR_RESET
        if self.history_file:
            readline.read_history_file(self.history_file)

    def precmd(self, line):
        # Reset the prompt to its uncolored variant for the benefit of any
        # command handlers that don't expect ANSI color sequences in it
        self.prompt = self.base_prompt
        # Ensure input is given as unicode
        return line.decode(ENCODING)

    def postcmd(self, stop, line):
        # Set the prompt back to its colored variant, if required
        if self.color_prompt:
            self.prompt = COLOR_BOLD + COLOR_GREEN + self.prompt + COLOR_RESET
        return stop

    def postloop(self):
        readline.set_history_length(self.history_size)
        readline.write_history_file(self.history_file)

    def onecmd(self, line):
        # Just catch and report CmdError's; don't terminate execution because
        # of them
        try:
            return cmd.Cmd.onecmd(self, line)
        except CmdError, exc:
            self.pprint(unicode(exc) + '\n')

    whitespace_re = re.compile(r'\s+$')
    def wrap(self, s, newline=True, wrap=True, initial_indent='',
            subsequent_indent=''):
        """Utility method for wrapping a paragraph of text to the terminal"""
        suffix = ''
        if newline:
            suffix = '\n'
        elif wrap:
            match = self.whitespace_re.search(s)
            if match:
                suffix = match.group()
        if wrap:
            self._wrapper.width = terminal_size()[0] - 2
            self._wrapper.initial_indent = initial_indent
            self._wrapper.subsequent_indent = subsequent_indent
            s = self._wrapper.fill(s)
        return s + suffix

    def input(self, prompt=''):
        """Utility method for prompting and reading input from the user"""
        lines = self.wrap(prompt, newline=False).split('\n')
        prompt = lines[-1]
        s = ''.join(line + '\n' for line in lines[:-1])
        if isinstance(s, unicode):
            s = s.encode(ENCODING)
        self.stdout.write(s)
        return raw_input(prompt).decode(ENCODING).strip()

    def pprint(self, s, newline=True, wrap=True,
            initial_indent='', subsequent_indent=''):
        """Utility method for pretty-printing text to the terminal"""
        s = self.wrap(s, newline, wrap, initial_indent, subsequent_indent)
        if isinstance(s, unicode):
            s = s.encode(ENCODING)
        self.stdout.write(s)

    def pprint_table(self, data, header_rows=1, footer_rows=0):
        """Utility method for pretty-printing a table of data"""
        # Calculate the maximum length of each column. Note that zip(*data) is
        # a quick trick for transposing a list of lists, assuming each row in
        # data is of equal length
        lengths = [
            max(len(unicode(item)) for item in row)
            for row in zip(*data)
        ]
        # Take a copy of data that we can insert header and footer lines into
        data = list(data)
        if header_rows > 0:
            data.insert(header_rows, tuple('-' * i for i in lengths))
        if footer_rows > 0:
            data.insert(-footer_rows, tuple('-' * i for i in lengths))
        # Print the result. Note that we avoid pprint here as we deliberately
        # don't want to wrap anything (in the vague hope that the terminal is
        # wide enough).
        # XXX Improve algorithm to reduce column widths when terminal is slim
        for row in data:
            self.stdout.write(' '.join(
                '%-*s' % (length, s) for (length, s) in zip(lengths, row)
            ) + '\n')

    def do_help(self, arg):
        """Displays the available commands or help on a specified command.

        The 'help' command is used to display the help text for a command or,
        if no command is specified, it presents a list of all available
        commands along with a brief description of each.
        """
        if arg:
            if not hasattr(self, 'do_%s' % arg):
                raise CmdError('Unknown command %s' % arg)
            paras = self.parse_docstring(getattr(self, 'do_%s' % arg).__doc__)
            for para in paras[1:]:
                if para.startswith(self.base_prompt):
                    self.pprint('  ' + para, wrap=False)
                else:
                    self.pprint(para)
                    self.pprint('')
            if paras[-1].startswith(self.base_prompt):
                self.pprint('')
        else:
            commands = [
                (
                    method[3:],
                    self.parse_docstring(getattr(self, method).__doc__)[0]
                )
                for method in self.get_names()
                if method.startswith('do_')
                and method != 'do_EOF'
            ]
            # Size the column containing the method names, ensuring it is no
            # wider than one third of the terminal width
            maxlen = min(
                max(len(command) for (command, help) in commands) + 2,
                terminal_size()[0] / 3
            )
            indent = ' ' * maxlen
            for (command, help_text) in commands:
                if len(command) <= maxlen:
                    self.pprint('%-*s%s' % (maxlen, command, help_text),
                        subsequent_indent=indent)
                else:
                    self.pprint(command)
                    self.pprint(help_text, initial_indent=indent,
                        subsequent_indent=indent)

    def do_exit(self, arg):
        """Exits from the application.

        Syntax: exit

        The 'exit' command is used to terminate the application. You can also
        use the standard UNIX Ctrl+D end of file sequence to quit.
        """
        if arg:
            raise CmdSyntaxError('Unknown argument %s' % arg)
        self.pprint('')
        return True

    do_EOF = do_exit

