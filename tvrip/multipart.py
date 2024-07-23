# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Functions for determining how many episodes comprise a multi-part episode, and
what the name of that multi-part episode should be.
"""


def prefix(episodes):
    """
    Given a sequence of *episodes*, return the number of multi-part episodes
    at the start of the sequence. If the episodes do not start with a
    multi-parter, the result is 1.
    """
    # A crude heuristic based on episode titles ending in " - Part n", "(n)",
    # or subsequent episode titles being simply '"' (ditto)
    first_name = episodes[0].title
    part = 1
    for part, episode in enumerate(episodes[1:], start=2):
        if episode.title == '"': # ditto (continuation of prior episode)
            continue
        if episode.title.endswith('Part %d' % part):
            if episode.title[:-6] == first_name[:-6]:
                continue
        elif episode.title.endswith('(%d)' % part):
            if episode.title[:-3] == first_name[:-3]:
                continue
        return part - 1
    return part


def name(episodes):
    """
    Given a sequence of multi-part *episodes*, return the episode title minus
    any part suffix.
    """
    if len(episodes) == 1:
        return episodes[0].title
    elif all(e.title == '"' for e in episodes[1:]):  # ditto
        return episodes[0].title
    elif episodes[0].title.endswith('(1)'):
        return episodes[0].title[:-3].rstrip(' -,:')
    elif episodes[0].title.endswith('Part 1'):
        return episodes[0].title[:-6].rstrip(' -,:')
    else:
        raise ValueError('unable to extract multipart episode name')
