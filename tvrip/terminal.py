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

import sys
import os
import argparse
import logging
import locale
import traceback
import configparser
from collections import namedtuple, OrderedDict

try:
    # Optionally import argcomplete (for auto-completion) if it's installed
    import argcomplete
except ImportError:
    argcomplete = None


# Use the user's default locale instead of C
locale.setlocale(locale.LC_ALL, '')

# Set up a console logging handler which just prints messages without any other
# adornments. This will be used for logging messages sent before we "properly"
# configure logging according to the user's preferences
_CONSOLE = logging.StreamHandler(sys.stderr)
_CONSOLE.setFormatter(logging.Formatter('%(message)s'))
_CONSOLE.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_CONSOLE)


class TerminalApplication:
    """
    Base class for command line applications.

    This class provides command line parsing, file globbing, response file
    handling and common logging configuration for command line utilities.
    Descendent classes should override the main() method to implement their
    main body, and __init__() if they wish to extend the command line options.
    """
    # Get the default output encoding from the default locale
    encoding = locale.getdefaultlocale()[1]

    # This class is the abstract base class for each of the command line
    # utility classes defined. It provides some basic facilities like an option
    # parser, console pretty-printing, logging and exception handling

    def __init__(
            self, version, description=None, config_files=None,
            config_section=None, config_bools=None):
        super(TerminalApplication, self).__init__()
        if description is None:
            description = self.__doc__
        self.parser = argparse.ArgumentParser(
            description=description,
            fromfile_prefix_chars='@')
        self.parser.add_argument(
            '--version', action='version', version=version)
        if config_files:
            self.config = configparser.ConfigParser(interpolation=None)
            self.config_files = config_files
            self.config_section = config_section
            self.config_bools = config_bools
            self.parser.add_argument(
                '-c', '--config', metavar='FILE',
                help='specify the configuration file to load')
        else:
            self.config = None
        self.parser.set_defaults(log_level=logging.WARNING)
        self.parser.add_argument(
            '-q', '--quiet', dest='log_level', action='store_const',
            const=logging.ERROR, help='produce less console output')
        self.parser.add_argument(
            '-v', '--verbose', dest='log_level', action='store_const',
            const=logging.INFO, help='produce more console output')
        arg = self.parser.add_argument(
            '-l', '--log-file', metavar='FILE',
            help='log messages to the specified file')
        if argcomplete:
            arg.completer = argcomplete.FilesCompleter(['*.log', '*.txt'])
        self.parser.add_argument(
            '-P', '--pdb', dest='debug', action='store_true', default=False,
            help='run under PDB (debug mode)')

    def __call__(self, args=None):
        if args is None:
            args = sys.argv[1:]
        if argcomplete:
            argcomplete.autocomplete(self.parser, exclude=['-P'])
        elif 'COMP_LINE' in os.environ:
            return 0
        sys.excepthook = ErrorHandler()
        sys.excepthook[OSError] = (sys.excepthook.exc_message, 1)
        args = self.read_configuration(args)
        args = self.parser.parse_args(args)
        self.configure_logging(args)
        if args.debug:
            try:
                import pudb
            except ImportError:
                pudb = None
                import pdb
            return (pudb or pdb).runcall(self.main, args)
        else:
            return self.main(args) or 0

    def read_configuration(self, args):
        if not self.config:
            return args
        # Parse the --config argument only
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('-c', '--config', dest='config', action='store')
        conf_args, args = parser.parse_known_args(args)
        if conf_args.config:
            self.config_files.append(conf_args.config)
        logging.info(
            'Reading configuration from %s', ', '.join(self.config_files))
        conf_read = self.config.read(self.config_files)
        if conf_args.config and conf_args.config not in conf_read:
            self.parser.error('unable to read %s' % conf_args.config)
        if conf_read:
            if self.config_bools is None:
                self.config_bools = ['pdb']
            else:
                self.config_bools = ['pdb'] + self.config_bools
            if not self.config_section:
                self.config_section = self.config.sections()[0]
            if self.config_section not in self.config.sections():
                self.parser.error(
                    'unable to locate [%s] section in configuration' % self.config_section)
            self.parser.set_defaults(**{
                key:
                self.config.getboolean(self.config_section, key)
                if key in self.config_bools else
                self.config.get(self.config_section, key)
                for key in self.config.options(self.config_section)
                })
        return args

    def configure_logging(self, args):
        _CONSOLE.setLevel(args.log_level)
        if args.log_file:
            log_file = logging.FileHandler(args.log_file)
            log_file.setFormatter(
                logging.Formatter('%(asctime)s, %(levelname)s, %(message)s'))
            log_file.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(log_file)
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

    def main(self, args):
        "Called as the main body of the utility"
        raise NotImplementedError


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
            _('Try the --help option for more information.'),
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
                        logging.critical(line)
                    sys.stderr.flush()
                raise SystemExit(value)
        # Otherwise, log the stack trace and the exception into the log
        # file for debugging purposes
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            for msg in line.rstrip().split('\n'):
                logging.critical(msg.replace('%', '%%'))
        sys.stderr.flush()
        raise SystemExit(1)
