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
import locale
import argparse
import traceback
from collections import namedtuple, OrderedDict

if sys.platform.startswith('win'):
    from .win import term_size  # pragma: no cover
else:
    from .posix import term_size  # pragma: no cover


# Use the user's default locale instead of C
locale.setlocale(locale.LC_ALL, '')
