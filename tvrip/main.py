#!/usr/bin/env python
# vim: set et sw=4 sts=4:

import pdb
import sys
import os
import re
import logging
import traceback
from optparse import OptionParser
from tvrip.cmdline import RipCmd

__version__ = '0.5'

def tvrip_main(args=None):
    if args is None:
        args = sys.argv[1:]
    parser = OptionParser(
        usage=u'%prog [options]',
        description=u"""\
This utility simplifies the extraction and transcoding of a DVD containing part
of a season of a given TV program, including ripping and OCRing subtitles into
a text-based form like SubRip.""")
    parser.set_defaults(
        debug=False,
        test=False,
        logfile='',
        loglevel=logging.WARNING
    )
    parser.add_option(u'-q', u'--quiet', dest=u'loglevel', action=u'store_const', const=logging.ERROR,
        help=u"""produce less console output""")
    parser.add_option(u'-v', u'--verbose', dest=u'loglevel', action=u'store_const', const=logging.INFO,
        help=u"""produce more console output""")
    parser.add_option(u'-l', u'--log-file', dest=u'logfile',
        help=u"""log messages to the specified file""")
    parser.add_option(u'-n', u'--dry-run', dest=u'test', action=u'store_true',
        help=u"""test a configuration without actually executing anything""")
    (options, args) = parser.parse_args(args)
    if options.debug:
        options.loglevel = logging.DEBUG
    else:
        sys.excepthook = handle_exception
    # Set up the logging handlers
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(u'%(message)s'))
    console.setLevel(options.loglevel)
    logging.getLogger().addHandler(console)
    if options.logfile:
        logfile = logging.FileHandler(options.logfile)
        logfile.setFormatter(logging.Formatter(u'%(asctime)s, %(levelname)s, %(message)s'))
        logfile.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(logfile)
    logging.getLogger().setLevel(options.loglevel)
    # Check a device has been specified
    if len(args) != 0:
        parser.error(u'you may not specify any filenames')
    # Start the interpreter
    r = RipCmd()
    r.pprint(u'TV Ripper %s' % __version__)
    r.pprint(u'Type "help" for more information.')
    r.cmdloop()

def handle_exception(type, value, tb):
    u"""Exception handler for non-debug mode."""
    # I/O errors should be simple to solve - no need to bother the user with a
    # full stack trace, just the error message will suffice. Same for user
    # interrupts
    if issubclass(type, (IOError, KeyboardInterrupt)):
        logging.critical(str(value))
    else:
        # Otherwise, log the stack trace and the exception into the log file
        # for debugging purposes
        for line in traceback.format_exception(type, value, tb):
            for s in line.rstrip().split('\n'):
                logging.critical(s)
    # Exit with a non-zero code
    sys.exit(1)

if __name__ == u'__main__':
    main()
    sys.exit(0)
