# vim: set et sw=4 sts=4:

# Copyright 2012-2014 Dave Hughes <dave@waveform.org.uk>.
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

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
    )
str = type('')

import sys
import os
import optparse
import textwrap
import logging
import locale
import traceback
import glob
from itertools import chain

try:
    # Optionally import optcomplete (for auto-completion) if it's installed
    import optcomplete
except ImportError:
    optcomplete = None


# Use the user's default locale instead of C
locale.setlocale(locale.LC_ALL, '')

# Set up a console logging handler which just prints messages without any other
# adornments
_CONSOLE = logging.StreamHandler(sys.stderr)
_CONSOLE.setFormatter(logging.Formatter('%(message)s'))
_CONSOLE.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_CONSOLE)


def normalize_path(path):
    """
    Eliminates symlinks, makes path absolute and normalizes case
    """
    return os.path.normcase(os.path.realpath(os.path.abspath(
        os.path.expanduser(path)
    )))


def glob_arg(arg):
    """
    Perform shell-style globbing of arguments
    """
    if set('*?[') & set(arg):
        args = glob.glob(normalize_path(arg))
        if args:
            return args
    # Return the original parameter in the case where the parameter contains no
    # wildcards or globbing returns no results
    return [arg]


def flatten(arg):
    """
    Flatten one level of nesting
    """
    return chain.from_iterable(arg)


def expand_args(args):
    """
    Expands @response files and wildcards in the command line
    """
    windows = sys.platform.startswith('win')
    result = []
    for arg in args:
        if arg.startswith('@') and len(arg) > 1:
            arg = normalize_path(arg[1:])
            try:
                with open(arg, 'rU') as resp_file:
                    for resp_arg in resp_file:
                        # Only strip the line break (whitespace is
                        # significant)
                        resp_arg = resp_arg.rstrip('\n')
                        # Only perform globbing on response file values for
                        # UNIX
                        if windows:
                            result.append(resp_arg)
                        else:
                            result.extend(glob_arg(resp_arg))
            except IOError as exc:
                raise optparse.OptionValueError(str(exc))
        else:
            result.append(arg)
    # Perform globbing on everything for Windows
    if windows:
        result = list(flatten(glob_arg(f) for f in result))
    return result


class HelpFormatter(optparse.IndentedHelpFormatter):
    """
    Customize the width of help output
    """
    def __init__(self):
        width = 75
        optparse.IndentedHelpFormatter.__init__(
                self, max_help_position=width // 3, width=width)


class OptionParser(optparse.OptionParser):
    """
    Customized OptionParser which raises an exception but doesn't terminate
    """
    def error(self, msg):
        raise optparse.OptParseError(msg)


class TerminalApplication(object):
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

    def __init__(self, version, usage=None, description=None):
        super(TerminalApplication, self).__init__()
        self.wrapper = textwrap.TextWrapper()
        self.wrapper.width = 75
        if usage is None:
            usage = self.__doc__.strip().split('\n')[0]
        if description is None:
            description = self.wrapper.fill('\n'.join(
                line.lstrip()
                for line in self.__doc__.strip().split('\n')[1:]
                if line.lstrip()
                ))
        self.parser = OptionParser(
            usage=usage,
            version=version,
            description=description,
            formatter=HelpFormatter()
            )
        self.parser.set_defaults(
            debug=False,
            logfile='',
            loglevel=logging.WARNING
            )
        self.parser.add_option(
            '-q', '--quiet', dest='loglevel', action='store_const',
            const=logging.ERROR, help='produce less console output')
        self.parser.add_option(
            '-v', '--verbose', dest='loglevel', action='store_const',
            const=logging.INFO, help='produce more console output')
        self.parser.add_option(
            '-l', '--log-file', dest='logfile',
            help='log messages to the specified file')
        if optcomplete:
            opt.completer = optcomplete.RegexCompleter(['.*\.log', '.*\.txt'])
        self.parser.add_option(
            '-P', '--pdb', dest='debug', action='store_true',
            help='run under PDB (debug mode)')
        self.arg_completer = None

    def __call__(self, args=None):
        sys.excepthook = self.handle
        if args is None:
            args = sys.argv[1:]
        if optcomplete:
            optcomplete.autocomplete(self.parser, self.arg_completer)
        elif 'COMP_LINE' in os.environ:
            return 0
        (options, args) = self.parser.parse_args(expand_args(args))
        _CONSOLE.setLevel(options.loglevel)
        if options.logfile:
            logfile = logging.FileHandler(options.logfile)
            logfile.setFormatter(
                logging.Formatter('%(asctime)s, %(levelname)s, %(message)s'))
            logfile.setLevel(logging.DEBUG)
            logging.getLogger().addHandler(logfile)
        if options.debug:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)
        if options.debug:
            import pdb
            return pdb.runcall(self.main, options, args)
        else:
            return self.main(options, args) or 0

    def handle(self, exc_type, exc_value, exc_trace):
        "Global application exception handler"
        if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            # Just ignore system exit and keyboard interrupt errors (after all,
            # they're user generated)
            return 130
        elif issubclass(exc_type, (ValueError, IOError)):
            # For simple errors like IOError just output the message which
            # should be sufficient for the end user (no need to confuse them
            # with a full stack trace)
            logging.critical(str(exc_value))
            return 1
        elif issubclass(exc_type, (optparse.OptParseError,)):
            # For option parser errors output the error along with a message
            # indicating how the help page can be displayed
            logging.critical(str(exc_value))
            logging.critical('Try the --help option for more information.')
            return 2
        else:
            # Otherwise, log the stack trace and the exception into the log
            # file for debugging purposes
            for line in traceback.format_exception(exc_type, exc_value, exc_trace):
                for msg in line.rstrip().split('\n'):
                    logging.critical(msg)
            return 1

    def main(self, options, args):
        "Called as the main body of the utility"
        raise NotImplementedError

