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

"""Contains suite-level constants defined as globals"""

import os

# The path under which tvrip-related data will be kept
XDG_CONFIG_HOME = os.environ.get(
    'XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
DATADIR = os.environ.get(
    'TVRIP_CONFIG', os.path.join(XDG_CONFIG_HOME, 'tvrip'))
