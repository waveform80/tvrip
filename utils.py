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

"""Installation utility functions"""

from __future__ import (
    unicode_literals,
    print_function,
    absolute_import,
    division,
    )

import re
import sys

def require_python(minimum):
    "Throws an exception if Python interpreter is below minimum"
    if sys.hexversion < minimum:
        parts = []
        while minimum:
            parts.insert(0, minimum & 0xff)
            minimum >>= 8
        if parts[-1] == 0xf0:
            error = 'Python %d.%d.%d or better is required' % parts[:3]
        else:
            error = 'Python %d.%d.%d (%02x) or better is required' % parts
        raise Exception(error)

def get_version(filename):
    "Simple parser to extract a __version__ variable from a source file"
    version_re = re.compile(r'(\d\.\d(\.\d+)?)')
    with open(filename) as source:
        for line_num, line in enumerate(source):
            if line.startswith('__version__'):
                match = version_re.search(line)
                if not match:
                    raise Exception(
                        'Invalid __version__ string found on '
                        'line %d of %s' % (line_num + 1, filename))
                return match.group(1)
    raise Exception('No __version__ line found in %s' % filename)

def description(filename):
    "Returns the first non-heading paragraph from a ReStructuredText file"
    state = 'before_header'
    result = []
    # We use a simple DFA to parse the file which looks for blank, non-blank,
    # and heading-delimiter lines.
    with open(filename) as rst_file:
        for line in rst_file:
            line = line.rstrip()
            # Manipulate state based on line content
            if line == '':
                if state == 'in_para':
                    state = 'after_para'
            elif line == '=' * len(line):
                if state == 'before_header':
                    state = 'in_header'
                elif state == 'in_header':
                    state = 'before_para'
            else:
                if state == 'before_para':
                    state = 'in_para'
            # Carry out state actions
            if state == 'in_para':
                result.append(line)
            elif state == 'after_para':
                break
    return ' '.join(line.strip() for line in result)

