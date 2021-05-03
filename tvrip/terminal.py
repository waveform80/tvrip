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
Defines base classes for command line utilities.

This module defines a TerminalApplication class which provides common
facilities to command line applications: a help screen, universal file
globbing, response file handling, and common logging configuration and options.
"""

import os
import sys
import struct
import locale
import argparse
import traceback
import configparser
from collections import namedtuple, OrderedDict


# Use the user's default locale instead of C
locale.setlocale(locale.LC_ALL, '')


if sys.platform.startswith('win'):
    # ctypes query_console_size() adapted from
    # http://code.activestate.com/recipes/440694/
    import ctypes

    def term_size():
        "Returns the size (cols, rows) of the console"

        def get_handle_size(handle):
            "Subroutine for querying terminal size from std handle"
            handle = ctypes.windll.kernel32.GetStdHandle(handle)
            if handle:
                buf = ctypes.create_string_buffer(22)
                if ctypes.windll.kernel32.GetConsoleScreenBufferInfo(
                        handle, buf):
                    (left, top, right, bottom) = struct.unpack(
                        'hhhhHhhhhhh', buf.raw)[5:9]
                    return (right - left + 1, bottom - top + 1)
            return None

        stdin, stdout, stderr = -10, -11, -12
        return (
            get_handle_size(stderr) or
            get_handle_size(stdout) or
            get_handle_size(stdin) or
            # Default
            (80, 25)
        )

else:
    # POSIX query_console_size() adapted from
    # http://mail.python.org/pipermail/python-list/2006-February/365594.html
    # http://mail.python.org/pipermail/python-list/2000-May/033365.html
    import fcntl
    import termios

    def term_size():
        "Returns the size (cols, rows) of the console"

        def get_handle_size(handle):
            "Subroutine for querying terminal size from std handle"
            try:
                buf = fcntl.ioctl(handle, termios.TIOCGWINSZ, '12345678')
                row, col = struct.unpack('hhhh', buf)[0:2]
                return (col, row)
            except OSError:
                return None

        stdin, stdout, stderr = 0, 1, 2
        # Try stderr first as it's the least likely to be redirected
        result = (
            get_handle_size(stderr) or
            get_handle_size(stdout) or
            get_handle_size(stdin)
        )
        if not result:
            try:
                fd = os.open(os.ctermid(), os.O_RDONLY)
            except OSError:
                pass
            else:
                try:
                    result = get_handle_size(fd)
                finally:
                    os.close(fd)
        if not result:
            try:
                result = (os.environ['COLUMNS'], os.environ['LINES'])
            except KeyError:
                # Default
                result = (80, 24)
        return result


class ErrorAction(namedtuple('ErrorAction', ('message', 'exitcode'))):
    """
    Named tuple dictating the action to take in response to an unhandled
    exception of the type it is associated with in :class:`ErrorHandler`.
    The *message* is an iterable of lines to be output as critical error
    log messages, and *exitcode* is an integer to return as the exit code of
    the process.

    Either of these can also be functions which will be called with the
    exception info (type, value, traceback) and will be expected to return
    an iterable of lines (for *message*) or an integer (for *exitcode*).
    """


class ErrorHandler:
    """
    Global configurable application exception handler. For "basic" errors (I/O
    errors, keyboard interrupt, etc.) just the error message is printed as
    there's generally no need to confuse the user with a complete stack trace
    when it's just a missing file. Other exceptions, however, are logged with
    the usual full stack trace.

    The configuration can be augmented with other exception classes that should
    be handled specially by treating the instance as a dictionary mapping
    exception classes to :class:`ErrorAction` tuples (or any 2-tuple, which
    will be converted to an :class:`ErrorAction`).

    For example::

        >>> import sys
        >>> sys.excepthook = ErrorHandler()
        >>> sys.excepthook[KeyboardInterrupt]
        (None, 1)
        >>> sys.excepthook[SystemExit]
        (None, <function ErrorHandler.exc_value at 0x7f6178915e18>)
        >>> sys.excepthook[ValueError] = (sys.excepthook.exc_message, 3)
        >>> sys.excepthook[Exception] = ("An error occurred", 1)
        >>> raise ValueError("foo is not an integer")
        foo is not an integer

    Note the lack of a traceback in the output; if the example were a script
    it would also have exited with return code 3.
    """
    def __init__(self):
        self._config = OrderedDict([
            # Exception type,        (handler method, exit code)
            (SystemExit,             (None, self.exc_value)),
            (KeyboardInterrupt,      (None, 2)),
            (argparse.ArgumentError, (self.syntax_error, 2)),
        ])

    @staticmethod
    def exc_message(exc_type, exc_value, exc_tb):
        """
        Extracts the message associated with the exception (by calling
        :class:`str` on the exception instance). The result is returned as a
        one-element list containing the message.
        """
        return [str(exc_value)]

    @staticmethod
    def exc_value(exc_type, exc_value, exc_tb):
        """
        Returns the first argument of the exception instance. In the case of
        :exc:`SystemExit` this is the expected return code of the script.
        """
        return exc_value.args[0]

    @staticmethod
    def syntax_error(exc_type, exc_value, exc_tb):
        """
        Returns the message associated with the exception, and an additional
        line suggested the user try the ``--help`` option. This should be used
        in response to exceptions indicating the user made an error in their
        command line.
        """
        return ErrorHandler.exc_message(exc_type, exc_value, exc_tb) + [
            'Try the --help option for more information.',
        ]

    def clear(self):
        """
        Remove all pre-defined error handlers.
        """
        self._config.clear()

    def __len__(self):
        return len(self._config)

    def __contains__(self, key):
        return key in self._config

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = ErrorAction(*value)

    def __delitem__(self, key):
        del self._config[key]

    def __call__(self, exc_type, exc_value, exc_tb):
        for exc_class, (message, value) in self._config.items():
            if issubclass(exc_type, exc_class):
                if callable(message):
                    message = message(exc_type, exc_value, exc_tb)
                if callable(value):
                    value = value(exc_type, exc_value, exc_tb)
                if message is not None:
                    for line in message:
                        print(line, file=sys.stderr)
                    sys.stderr.flush()
                raise SystemExit(value)
        # Otherwise, log the stack trace and the exception into the log
        # file for debugging purposes
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            for msg in line.rstrip().split('\n'):
                print(msg, file=sys.stderr)
        sys.stderr.flush()
        raise SystemExit(1)
