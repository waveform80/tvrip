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

"""Contains suite-level constants defined as globals"""

from __future__ import unicode_literals, print_function, absolute_import, division

import os

# The path under which tvrip-related data will be kept
DATADIR = os.path.expanduser('~/.tvrip') # must be absolute
if not os.path.exists(DATADIR):
    os.mkdir(DATADIR)
