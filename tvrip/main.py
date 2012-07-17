#!/usr/bin/env python
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

"""Implements the main loop and option parser for the tvrip application"""

from __future__ import (
    unicode_literals,
    print_function,
    absolute_import,
    division
    )

import sys
import logging
import traceback
from optparse import OptionParser, OptParseError
from tvrip.ripcmd import RipCmd

__version__ = '0.7'


# Set up a console logging handler which just prints messages without any other
# adornments
CONSOLE = logging.StreamHandler(sys.stderr)
CONSOLE.setFormatter(logging.Formatter('%(message)s'))
CONSOLE.setLevel(logging.DEBUG)
logging.getLogger().addHandler(CONSOLE)


def main(args=None):
    parser = OptionParser(
        usage='%prog [options]',
        description="""\
This utility simplifies the extraction and transcoding of a DVD containing part
of a season of a given TV program, including ripping and OCRing subtitles into
a text-based form like SubRip.""")
    parser.set_defaults(
        debug=False,
        test=False,
        logfile='',
        loglevel=logging.WARNING
    )
    parser.add_option(
        '-q', '--quiet', dest='loglevel', action='store_const',
        const=logging.ERROR, help='produce less console output')
    parser.add_option(
        '-v', '--verbose', dest='loglevel', action='store_const',
        const=logging.INFO, help='produce more console output')
    parser.add_option(
        '-l', '--log-file', dest='logfile',
        help='log messages to the specified file')
    parser.add_option(
        '-n', '--dry-run', dest='test', action='store_true',
        help='test a configuration without actually executing anything')
    sys.excepthook = handle_exception
    if args is None:
        args = sys.argv[1:]
    (options, args) = parser.parse_args(args)
    CONSOLE.setLevel(options.loglevel)
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
    # Check a device has been specified
    if len(args) != 0:
        parser.error('you may not specify any filenames')
    # Start the interpreter
    cmd = RipCmd()
    cmd.pprint('TVRip %s' % __version__)
    cmd.pprint('Type "help" for more information.')
    cmd.cmdloop()

def handle_exception(exc_type, exc_value, exc_tb):
    "Friendly exception handler"
    if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
        # Just ignore system exit and keyboard interrupt errors (after all,
        # they're user generated)
        sys.exit(130)
    elif issubclass(exc_type, (ValueError, IOError)):
        # For simple errors like IOError just output the message which
        # should be sufficient for the end user (no need to confuse them
        # with a full stack trace)
        logging.critical(str(exc_value))
        sys.exit(1)
    elif issubclass(exc_type, (OptParseError,)):
        # For option parser errors output the error along with a message
        # indicating how the help page can be displayed
        logging.critical(str(exc_value))
        logging.critical('Try the --help option for more information.')
        sys.exit(2)
    else:
        # Otherwise, log the stack trace and the exception into the log file
        # for debugging purposes
        for line in traceback.format_exception(exc_type, exc_value, exc_tb):
            for s in line.rstrip().split('\n'):
                logging.critical(s)
        sys.exit(1)

if __name__ == '__main__':
    main()
    sys.exit(0)
