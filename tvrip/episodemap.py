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

"""A custom mapping class for episodes and disc-titles.

The EpisodeMap class defined in this module is a simple dict variant which
includes some additional methods for automatically calculating a mapping that
meets certain criteria (duration-based).
"""

from __future__ import unicode_literals, print_function, absolute_import, division

import logging
from datetime import timedelta
from itertools import izip, groupby
from operator import attrgetter

__all__ = ['EpisodeMap']


def partition(seq, counts):
    """Make an iterator that returns seq in chunks of length found in counts"""
    # partition(range(10), [3, 1, 2]) --> [[0, 1, 2], [3], [4, 5]]
    index = 0
    for count in counts:
        yield seq[index:index + count]
        index += count

def valid(mapping, unripped, chapters, duration_min, duration_max):
    """Checks whether a possible mapping is valid"""
    return (
        # Check the mapping doesn't specify more episodes than are available
        (len(mapping) <= len(unripped)) and
        # Check the mapping doesn't exceed the number of available chapters
        (sum(mapping) == len(chapters)) and
        # Check each grouping of chapters has a valid duration
        all(
            duration[0] <= sum(
                (chapter.duration for chapter in episode_chapters),
                timedelta()
            ) <= duration[1]
            for episode_chapters in partition(chapters, mapping)
        )
    )

def calculate(unripped, chapters, duration_min, duration_max,
        mapping=[], solutions=[]):
    """Recursive function for calculating mapping solutions"""
    duration = timedelta()
    # We represent mappings within this function as a list of chapter counts,
    # hence the mapping [2, 3, 4, 2] means the first episode consists of two
    # chapters, the second episode consists of the next three chapters and so
    # on. The loop below takes the slice of the available chapters beyond those
    # already mapped, and attempts to add each chapter in turn to the next
    # unripped episode.
    for count, chapter in enumerate(chapters[sum(mapping):]):
        duration += chapter.duration
        if duration > duration_max:
            # If we've exceeded the maximum duration, stop. We break here as all
            # further solutions down this branch would be invalid
            break
        elif duration >= duration_min:
            new_map = mapping + [count + 1]
            # If the duration of the group of chapters is within range, check
            # whether the mapping is a whole is valid and add it to the
            # solutions list if so
            if valid(new_map, unripped, chapters, duration_min, duration_max):
                solutions.append(new_map)
            # Regardless of whether the current mapping is valid (it could be
            # the start of a valid mapping), recursively call ourselves with
            # the new group appended to the mapping
            calculate(unripped, chapters, duration_min, duration_max, new_map, solutions)
    if not mapping:
        return solutions


class EpisodeMap(dict):
    def __iter__(self):
        for episode in sorted(self, key=attrgetter('number')):
            yield episode

    def iterkeys(self):
        for k in self:
            yield k

    def iteritems(self):
        for k in self:
            yield (k, self[k])

    def automap(self, unripped, unmapped):
        pass

    def automap_titles(self, to_map, unripped):
        logging.debug(u'Attempting title-based mapping')
        result = {}
        try_chapters = True
        for title in to_map:
            if self.config.duration_min <= title.duration <= self.config.duration_max:
                result[episode] = title
                if len(result) == len(unripped):
                    break
            else:
                logging.debug(u'Title %d is not an episode (duration: %s)' % (
                    title.number,
                    title.duration,
                ))
        return result

    def automap_chapters(self, to_map, unripped):
        logging.debug(u'Attempting chapter-based mapping')
        title = sorted(to_map, key=attrgetter('duration'))[-1]
        logging.debug(u'Longest title is %d (duration: %s), containing '
            '%d chapters' % (
            title.number,
            title.duration,
            len(title.chapters),
        ))
        to_map = title.chapters
        # XXX Remove trailing empty chapters
        result = []
        def output(chapters, unripped, solution):
            start_chapter = 1
            for episode, count in zip(unripped, solution):
                self.cmd.pprint(u'Episode %d = Chapter %d-%d (%s)' % (
                    episode.number,
                    start_chapter,
                    start_chapter + count - 1,
                    str(sum((
                        c.duration
                        for c in to_map[start_chapter - 1:start_chapter + count - 1]
                    ), timedelta()))
                ))
                start_chapter += count
        solutions = explore(to_map, unripped)
        if len(solutions) > 1:
            self.cmd.pprint(u'Found %d potential chapter mappings' % len(solutions))
            for index, solution in enumerate(solutions):
                self.cmd.pprint(u'')
                self.cmd.pprint(u'Solution %d' % (index + 1))
                output(to_map, unripped, solution)
            self.cmd.pprint(u'')
            try:
                selection = int(self.input('Enter solution number to use [1-%d] ' % len(solutions)))
                if not 1 <= selection <= len(solutions):
                    raise ValueError
            except ValueError:
                while True:
                    try:
                        selection = int(self.input('Invalid input. Please enter a number [1-%d] ' % len(solutions)))
                        if not 1 <= selection <= len(solutions):
                            raise ValueError
                    except ValueError:
                        pass
                    else:
                        break
            solution = solutions[selection - 1]
        elif len(solutions) == 1:
            self.cmd.pprint(u'Solution:')
            output(to_map, unripped, solutions[0])
            solution = solutions[0]
        else:
            self.cmd.pprint(u'No potential chapter mappings found')
            return {}
        return dict(
            (episode, (chapters[0], chapters[-1]))
            for (episode, chapters) in zip(unripped, partition(to_map, solution))
        )

