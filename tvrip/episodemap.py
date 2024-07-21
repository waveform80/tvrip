# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2012-2014 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
A custom mapping class for episodes and disc-titles.

The :class:`EpisodeMap` class defined in this module is a simple :class:`dict`
variant which includes some additional methods for automatically calculating a
mapping that meets certain criteria (duration-based).
"""

import logging
from datetime import timedelta
from operator import attrgetter
from collections.abc import MutableMapping

from tvrip.database import Episode
from tvrip.ripper import Title, Chapter
from . import multipart

__all__ = [
    'EpisodeMap',
    'MapError',
    'NoMappingError',
    'NoSolutionsError',
    'MultipleSolutionsError'
]


class MapError(Exception):
    "Base class for mapping errors"


class NoEpisodesError(MapError):
    "Exception raised when no episodes are available for mapping"


class NoMappingError(MapError):
    "Exception raised when no title mapping is found"


class NoSolutionsError(MapError):
    "Exception raised when no solutions are found by automap"


class MultipleSolutionsError(MapError):
    "Exception raised when multiple solutions are found with no selection"


class EpisodeMap(MutableMapping):
    """
    Instances of :class:`EpisodeMap` represent a mapping of episodes to titles
    (or chapters of titles) on a :class:`Disc`.

    As a :class:`dict` descendent, it can be treated much like a regular dict,
    but will only accept keys which are instance of :class:`Episode`, and
    values which are a :class:`Title`, or a 2-tuple of :class:`Chapter`
    (representing the start and end chapter of the episode).

    The only extra method defined (beyond the usual) is :meth:`automap` which
    can be used to populate the mapping automatically given the set of titles
    available on a disc, a range of episodes to cover, and a possible episode
    duration range.
    """
    def __init__(self, data=None):
        self._mapping = {}
        if data is not None:
            if isinstance(data, dict):
                data = data.items()
            for key, value in data:
                self[key] = value

    def __repr__(self):
        content='\n'.join(
            (
                f'{episode}: {title},' if isinstance(title, Title) else
                f'{episode}: {title[0].title}-{title[0]}..{title[1]},'
            )
            for episode, title in self.items()
        )
        return f'{self.__class__.__name__}({{\n{content}\n}})'

    def __len__(self):
        return len(self._mapping)

    def __iter__(self):
        # Ensures that iterating the map returns episodes in ascending order
        for episode in sorted(self._mapping, key=attrgetter('number')):
            yield episode

    def __contains__(self, key):
        return key in self._mapping

    def __getitem__(self, key):
        return self._mapping[key]

    def __setitem__(self, key, value):
        # Ensures values are either a Title or a (Chapter, Chapter) tuple.
        if not isinstance(key, Episode):
            raise ValueError('mapping key is not an Episode')
        try:
            start, finish = value
            if not (isinstance(start, Chapter) and isinstance(finish, Chapter)):
                raise ValueError('mapping values are not Chapters')
            if start.title is not finish.title:
                raise ValueError(
                    'start chapter is in different title to finish chapter')
            if finish.number < start.number:
                raise ValueError(
                    'start chapter is earlier than finish chapter')
        except (TypeError, ValueError):
            if not isinstance(value, Title):
                raise ValueError(
                    'mapping value is not a Title or two Chapters') from None
        self._mapping[key] = value

    def __delitem__(self, key):
        del self._mapping[key]

    def automap(
            self, episodes, titles, duration_min, duration_max, *,
            strict_mapping=False, permit_multipart=True, choose_mapping=None):
        """
        Attempt to automatically populate the mapping to cover the *episode*
        specified, given the available *titles* on the disc. Valid episodes
        must be between *duration_min* and *duration_max* (both
        :class:`timedelta` values) in length.

        If *strict_mapping* is :data:`False` (the default), the mapping may
        cover only the start of the *episodes* specified. If :data:`True`, then
        *all* episodes specified must be mapped.

        If *permit_multipart* is :data:`True` (the default), then the algorithm
        will consider mapping a single extra-long title as multiple episodes
        provided they have a recognized "Part N" or "(N)" suffix in their name.

        Various strategies to populate the map are attempted:

        * Firstly straight episode to title mapping is attempted, where only
          titles within the specified duration range are considered.

        * If this fails, the longest title on the disc is selected, and chapter
          mapping is attempted; this attempts to find a consecutive run of
          chapters fitting in the duration range for each specified episode.

        * If this fails, chapter mapping is attempted with *all* titles on the
          disc.

        During chapter mapping, it is common for multiple solutions to be found
        (e.g. intro / end credit sections which are sufficiently short that
        they might / might not form part of an episode without breaking the
        duration range).

        In this case, the optional *choose_mapping* function will be called
        with the sequence of possible mappings found. It must return the
        selected mapping (or raise an exception). Usually this involves some
        form of user interaction to determine the "real" start of an episode.
        """
        self.update(automap(
            episodes, titles, duration_min, duration_max,
            strict_mapping=strict_mapping, permit_multipart=permit_multipart,
            choose_mapping=choose_mapping))


def valid(mapping, chapters, episodes, duration_min, duration_max):
    """
    Checks whether a possible *mapping* of *chapters* to *episodes* is "valid".
    In other words, whether all *chapters* are included, that all chapters
    belong to the same title on the disc, that they cover all specified
    *episodes*, and that the sequences of *chapters* fit within the range of
    *duration_min* to *duration_max*.
    """
    return (
        # Check the mapping covers all the specified episodes
        (len(mapping) == len(episodes)) and
        # Check the mapping covers all available chapters precisely
        (sum(mapping) == len(chapters)) and
        # Check the title of each start+end chapter is equal (episodes don't
        # cross titles)
        all(
            start.title.number == end.title.number
            for (start, end) in partition_ends(chapters, mapping)
        ) and
        # Check each grouping of chapters has a valid duration
        all(
            duration_min <= sum(
                (chapter.duration for chapter in episode_chapters),
                timedelta()
            ) <= duration_max
            for episode_chapters in partition(chapters, mapping)
        )
    )


def automap(
        episodes, titles, duration_min, duration_max, *,
        strict_mapping=False, permit_multipart=True, choose_mapping=None):
    """
    Attempt (via various strategies) to map all *episodes* to some set of the
    specified *titles*, under the assumption that all episodes fit within the
    *duration_min* and *duration_max* (:class:`timedelta`) range.

    If *strict_mapping* is :data:`True`, all episodes must be mapped or an
    exception will be raised. Otherwise, only a prefix of episodes may be
    mapped.

    If *permit_multipart* is :data:`True`, an extra-long title may cover a
    multi-part episode (provided it fits within a multiple of the duration
    range).

    The *choose_mapping* parameter specifies a callable that, in the event
    chapter-based mapping finds multiple "solutions", will be called with a
    list of all valid mappings and which must return the one selected
    (presumably via some form of user-interaction).

    Returns the generated :class:`EpisodeMap`.
    """
    if not episodes:
        raise NoEpisodesError('No episodes available for mapping (new season?)')
    if duration_max < duration_min:
        raise ValueError('max duration must be at least min duration')
    try:
        logging.debug('Trying title-based mapping')
        return automap_titles(
            episodes, titles, duration_min, duration_max,
            permit_multipart=permit_multipart,
            strict_mapping=strict_mapping)
    except NoMappingError:
        try:
            logging.debug('Trying chapter-based algorithm with longest title')
            return automap_chapters_longest(
                episodes, titles, duration_min, duration_max,
                choose_mapping=choose_mapping)
        except NoSolutionsError:
            logging.debug('Trying chapter-based algorithm with all titles')
            return automap_chapters_all(
                episodes, titles, duration_min, duration_max,
                choose_mapping=choose_mapping)


def automap_titles(
        episodes, titles, duration_min, duration_max, *,
        strict_mapping=False, permit_multipart=True):
    "Auto-mapping using a title-based algorithm"
    result = EpisodeMap()
    episodes = list(episodes)
    for title in titles:
        if not episodes:
            logging.debug('Out of episodes for auto-mapping')
            break
        if duration_min <= title.duration <= duration_max:
            result[episodes.pop(0)] = title
        elif title.duration > duration_max and permit_multipart:
            parts = multipart.prefix(episodes)
            if parts > 1 and (
                    duration_min * parts <= title.duration <= duration_max * parts):
                while parts:
                    result[episodes.pop(0)] = title
                    parts -= 1
            else:
                logging.debug(
                    'Title %d is not an episode or multipart episode '
                    '(duration: %s)', title.number, title.duration)
        else:
            logging.debug(
                'Title %d is not an episode (duration: %s)',
                title.number, title.duration)
    if not result:
        raise NoMappingError('No mapping for any titles found')
    if strict_mapping and episodes:
        raise NoMappingError("Mapping doesn't cover all episodes")
    return result


def automap_chapters_longest(
        episodes, titles, duration_min, duration_max, *,
        choose_mapping=None):
    "Auto-mapping with chapters from the longest title in the selecteion"
    longest_title = sorted(titles, key=attrgetter('duration'))[-1]
    logging.debug(
        'Longest title is %d (duration: %s), containing '
        '%d chapters',
        longest_title.number, longest_title.duration,
        len(longest_title.chapters))
    return automap_chapters(
        episodes, longest_title.chapters, duration_min, duration_max,
        choose_mapping=choose_mapping)


def automap_chapters_all(
        episodes, titles, duration_min, duration_max, *,
        choose_mapping=None):
    "Auto-mapping with chapters from all titles in the selection"
    return automap_chapters(
        episodes, [chapter for title in titles for chapter in title.chapters],
        duration_min, duration_max, choose_mapping=choose_mapping)


def automap_chapters(
        episodes, chapters, duration_min, duration_max, *,
        choose_mapping=None):
    "Auto-mapping with a chapter-based algorithm"
    # XXX Remove trailing empty chapters
    solutions = calculate(episodes, chapters, duration_min, duration_max)
    logging.debug(
        'Found %d chapter mapping solution(s)', len(solutions))
    if not solutions:
        raise NoSolutionsError('No chapter mappings found')
    if len(solutions) == 1:
        return EpisodeMap(
            zip(episodes, partition_ends(chapters, solutions[0])))
    if not choose_mapping:
        raise MultipleSolutionsError(
            'Multiple possible chapter mappings found')
    return choose_mapping([
        EpisodeMap(zip(episodes, partition_ends(chapters, solution)))
        for solution in solutions
    ])


def calculate(
        episodes, chapters, duration_min, duration_max, *,
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
            # If we've exceeded the maximum duration, stop. We break here as
            # all further solutions down this branch would be invalid
            break
        if duration >= duration_min:
            new_map = mapping + [count + 1]
            # If the duration of the group of chapters is within range, check
            # whether the mapping as a whole is valid and add it to the
            # solutions list if so
            if valid(new_map, chapters, episodes, duration_min, duration_max):
                solutions.append(new_map)
            # Regardless of whether the current mapping is valid (it could be
            # the start of a valid mapping), recursively call ourselves with
            # the new group appended to the mapping
            calculate(
                episodes, chapters, duration_min, duration_max,
                mapping=new_map, solutions=solutions)
    if mapping:
        return None
    else:
        return solutions


def partition_ends(seq, counts):
    """
    A generator that yields the start and end of chunks of *seq* defined by
    *counts*. For example::

        >>> list(partition_ends(range(10), [3, 1, 2]))
        [(0, 2), (3, 3), (4, 5)]
        >>> list(partition_ends('ABCDEF', [1, 2, 3]))
        [('A', 'A'), ('B', 'C'), ('D', 'F')]
    """
    # partition_ends(range(10), [3, 1, 2]) --> [(0, 2), (3, 3), (4, 5)]
    for s in partition(seq, counts):
        yield (s[0], s[-1])


def partition(seq, counts):
    """
    A generator that yields *seq* in chunks of length found in *counts*.
    For example::

        >>> list(partition(list(range(10)), [3, 1, 2]))
        [[0, 1, 2], [3], [4, 5]]
        >>> list(partition(range(10), [3, 1, 2]))
        [range(0, 3), range(3, 4), range(4, 6)]
        >>> list(partition('ABCDEF', [1, 2, 3]))
        ['A', 'BC', 'DEF']
    """
    index = 0
    for count in counts:
        yield seq[index:index + count]
        index += count
