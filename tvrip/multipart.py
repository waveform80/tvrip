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
Functions for determining how many episodes comprise a multi-part episode, and
what the name of that multi-part episode should be.
"""


def prefix(episodes):
    "Finds the number of multipart episodes at the start of *episodes*"
    # A crude heuristic based on episode titles ending in " - Part n", "(n)",
    # the subsequent episode titles being simply '"'
    first_name = episodes[0].name
    for n, e in enumerate(episodes[1:], start=2):
        if e.name == '"':
            continue
        elif e.name.endswith('Part %d' % n):
            if e.name[:-6] == first_name[:-6]:
                continue
        elif e.name.endswith('(%d)' % n):
            if e.name[:-3] == first_name[:-3]:
                continue
        break
    return n - 1


def name(episodes):
    if len(episodes) == 1:
        return episodes[0].name
    elif all(e.name == '"' for e in episodes[1:]):
        return episodes[0].name
    elif episodes[0].name.endswith('(1)'):
        return episodes[0].name[:-3].rstrip(' -,:')
    elif episodes[0].name.endswith('Part 1'):
        return episodes[0].name[:-6].rstrip(' -,:')
    else:
        raise ValueError('unable to extract multipart episode name')
