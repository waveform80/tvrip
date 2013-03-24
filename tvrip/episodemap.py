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

from __future__ import (
    unicode_literals,
    print_function,
    absolute_import,
    division,
    )

import logging
from datetime import timedelta
from operator import attrgetter
from tvrip.database import Episode
from tvrip.ripper import Title, Chapter

__all__ = [
    'EpisodeMap',
    'MapError',
    'NoMappingError',
    'NoSolutionsError',
    'MultipleSolutionsError'
    ]


def partition(seq, counts):
    "An iterator that returns seq in chunks of length found in counts"
    # partition(range(10), [3, 1, 2]) --> [[0, 1, 2], [3], [4, 5]]
    index = 0
    for count in counts:
        yield seq[index:index + count]
        index += count

def partition_ends(seq, counts):
    "An iterator that returns the start and end of chunks of seq defined by counts"
    # partition_ends(range(10), [3, 1, 2]) --> [(0, 2), (3, 3), (4, 5)]
    for s in partition(seq, counts):
        yield (s[0], s[-1])

def valid(mapping, chapters, episodes, duration_min, duration_max):
    "Checks whether a possible mapping is valid"
    return (
        # Check the mapping covers all the specified episodes
        (len(mapping) == len(episodes)) and
        # Check the mapping covers all available chapters precisely
        (sum(mapping) == len(chapters)) and
        # Check each grouping of chapters has a valid duration
        all(
            duration_min <= sum(
                (chapter.duration for chapter in episode_chapters),
                timedelta()
            ) <= duration_max
            for episode_chapters in partition(chapters, mapping)
        )
    )

def calculate(chapters, episodes, duration_min, duration_max,
        mapping=None, solutions=None):
    "Recursive function for calculating mapping solutions"
    if mapping is None:
        mapping = []
    if solutions is None:
        solutions = []
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
            if valid(new_map, chapters, episodes, duration_min, duration_max):
                solutions.append(new_map)
            # Regardless of whether the current mapping is valid (it could be
            # the start of a valid mapping), recursively call ourselves with
            # the new group appended to the mapping
            calculate(
                chapters, episodes, duration_min, duration_max,
                new_map, solutions)
    if not mapping:
        return solutions


class MapError(Exception):
    "Base class for mapping errors"

class NoMappingError(MapError):
    "Exception raised when no title mapping is found"

class NoSolutionsError(MapError):
    "Exception raised when no solutions are found by automap"

class MultipleSolutionsError(MapError):
    "Exception raised when multiple solutions are found with no selection"

class EpisodeMap(dict):
    "Represents a mapping of episodes to titles/chapters"

    def __iter__(self):
        for episode in sorted(
                super(EpisodeMap, self).__iter__(), key=attrgetter('number')):
            yield episode

    def __setitem__(self, key, value):
        assert isinstance(key, Episode)
        try:
            start, finish = value
            assert isinstance(start, Chapter)
            assert isinstance(finish, Chapter)
        except (TypeError, ValueError):
            assert isinstance(value, Title)
        super(EpisodeMap, self).__setitem__(key, value)

    def keys(self):
        return [k for k in self]

    def iterkeys(self):
        for k in self:
            yield k

    def iteritems(self):
        for k in self:
            yield (k, self[k])

    def automap(self, titles, episodes, duration_min, duration_max,
            choose_mapping=None):
        "Automatically map unmapped titles to unripped episodes"
        try:
            self._automap_titles(
                titles, episodes, duration_min, duration_max)
        except NoMappingError:
            self._automap_chapters(
                titles, episodes, duration_min, duration_max, choose_mapping)

    def _automap_titles(self, titles, episodes, duration_min, duration_max):
        "Auto-mapping using a title-based algorithm"
        result = {}
        for title in titles:
            if duration_min <= title.duration <= duration_max:
                result[episodes.pop(0)] = title
                if not episodes:
                    break
            else:
                logging.debug(
                    'Title %d is not an episode (duration: %s)',
                    title.number, title.duration)
        if not result:
            raise NoMappingError('No mapping for any titles found')
        self.update(result)

    def _automap_chapters(self, titles, episodes, duration_min, duration_max,
            choose_mapping=None):
        "Auto-mapping with a chapter-based algorithm"
        longest_title = sorted(titles, key=attrgetter('duration'))[-1]
        logging.debug(
            'Longest title is %d (duration: %s), containing '
            '%d chapters',
            longest_title.number, longest_title.duration,
            len(longest_title.chapters))
        chapters = longest_title.chapters
        # XXX Remove trailing empty chapters
        solutions = calculate(chapters, episodes, duration_min, duration_max)
        logging.debug(
            'Found %d chapter mapping solution(s)' % len(solutions))
        if not solutions:
            raise NoSolutionsError('No chapter mappings found')
        elif len(solutions) == 1:
            solution = EpisodeMap(zip(episodes, partition_ends(chapters, solutions[0])))
        elif len(solutions) > 1:
            if not choose_mapping:
                raise MultipleSolutionsError(
                    'Multiple possible chapter mappings found')
            solution = choose_mapping([
                EpisodeMap(zip(episodes, partition_ends(chapters, solution)))
                for solution in solutions
                ])
        self.update(solution)

