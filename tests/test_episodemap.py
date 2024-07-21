# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2021-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import timedelta

import pytest

from tvrip.ripper import Disc
from tvrip.episodemap import *


def test_episodemap_init(db, with_config, with_program, drive, foo_disc1):
    epmap = EpisodeMap()
    assert len(epmap) == 0

    drive.disc = foo_disc1
    disc = Disc(with_config)
    epmap = EpisodeMap({
        ep: title
        for ep, title in zip(with_program.seasons[0].episodes, disc.titles)
    })
    assert len(epmap) == len(with_program.seasons[0].episodes)

    epmap = EpisodeMap([
        (ep, title)
        for ep, title in zip(with_program.seasons[0].episodes, disc.titles)
    ])
    assert len(epmap) == len(with_program.seasons[0].episodes)
    assert repr(epmap) == """\
EpisodeMap({
<Episode('Foo & Bar', 1, 1, 'Foo')>: <Title(1)>,
<Episode('Foo & Bar', 1, 2, 'Bar')>: <Title(2)>,
<Episode('Foo & Bar', 1, 3, 'Baz')>: <Title(3)>,
<Episode('Foo & Bar', 1, 4, 'Quux')>: <Title(4)>,
<Episode('Foo & Bar', 1, 5, 'Xyzzy')>: <Title(5)>,
})"""


def test_episodemap_iter(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    # Initialize in reverse order
    epmap = EpisodeMap(reversed([
        (ep, title) for ep, title in zip(episodes, titles)
    ]))

    # Ensure iteration is always in episode ascending order
    assert list(epmap.items()) == [
        (ep, title)
        for ep, title in zip(episodes, titles)
    ]


def test_episodemap_oper(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap([(ep, title) for ep, title in zip(episodes, titles)])
    assert episodes[0] in epmap
    assert 'foo' not in epmap
    assert epmap[episodes[0]] is titles[0]
    del epmap[episodes[0]]
    assert episodes[0] not in epmap
    epmap[episodes[0]] = titles[0].chapters[0], titles[0].chapters[-2]

    with pytest.raises(ValueError):
        epmap['foo'] = 'bar'
    with pytest.raises(ValueError):
        epmap[episodes[0]] = titles[0].chapters[0]
    with pytest.raises(ValueError):
        epmap[episodes[0]] = 'bar'
    with pytest.raises(ValueError):
        epmap[episodes[0]] = 1, 2
    with pytest.raises(ValueError):
        epmap[episodes[0]] = titles[0].chapters[0], titles[1].chapters[0]
    with pytest.raises(ValueError):
        epmap[episodes[0]] = titles[0].chapters[-1], titles[0].chapters[1]


def test_automap_errors(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    with pytest.raises(ValueError):
        epmap.automap(episodes, titles, timedelta(minutes=31), timedelta(minutes=29))
    with pytest.raises(MapError):
        epmap.automap([], titles, timedelta(minutes=29), timedelta(minutes=31))


def test_automap_titles(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    epmap.automap(episodes, titles, timedelta(minutes=29), timedelta(minutes=31))
    assert list(epmap.items()) == [
        (episodes[0], titles[1]),
        (episodes[1], titles[2]),
        (episodes[2], titles[3]),
        (episodes[3], titles[4]),
        (episodes[4], titles[5]),
    ]


def test_automap_titles_partial(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    epmap.automap(episodes, [titles[i] for i in (1, 2, 4, 5, 8, 9, 10)],
                  timedelta(minutes=29), timedelta(minutes=32))
    assert list(epmap.items()) == [
        (episodes[0], titles[1]),
        (episodes[1], titles[2]),
        (episodes[2], titles[4]),
        (episodes[3], titles[5]),
        (episodes[4], titles[10]),
    ]


def test_automap_titles_strict(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    with pytest.raises(MapError):
        epmap.automap(episodes, titles[:5], timedelta(minutes=29),
                      timedelta(minutes=31), strict_mapping=True)


def test_automap_titles_multipart(db, with_config, with_program, drive, foo_disc2):
    drive.disc = foo_disc2
    disc = Disc(with_config)
    episodes = with_program.seasons[1].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    epmap.automap(episodes, titles[1:], timedelta(minutes=29), timedelta(minutes=32))
    assert list(epmap.items()) == [
        (episodes[0], titles[1]),
        (episodes[1], titles[1]),
        (episodes[2], titles[2]),
        (episodes[3], titles[3]),
    ]


def test_automap_chapters(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    epmap.automap(episodes, [titles[0]], timedelta(minutes=29), timedelta(minutes=32))
    assert list(epmap.items()) == [
        (episodes[0], (titles[0].chapters[0], titles[0].chapters[4])),
        (episodes[1], (titles[0].chapters[5], titles[0].chapters[9])),
        (episodes[2], (titles[0].chapters[10], titles[0].chapters[14])),
        (episodes[3], (titles[0].chapters[15], titles[0].chapters[18])),
        (episodes[4], (titles[0].chapters[19], titles[0].chapters[23])),
    ]


def test_automap_chapters_many_solutions(db, with_config, with_program, drive, foo_disc2):
    drive.disc = foo_disc2
    disc = Disc(with_config)
    episodes = with_program.seasons[1].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    with pytest.raises(MultipleSolutionsError):
        epmap.automap(episodes, [titles[0]], timedelta(minutes=29),
                      timedelta(minutes=32))


def test_automap_chapters_pick_solution(db, with_config, with_program, drive, foo_disc2):
    drive.disc = foo_disc2
    disc = Disc(with_config)
    episodes = with_program.seasons[1].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    def chapter_lengths(mapping):
        return tuple(
            end.number - start.number + 1
            for start, end in mapping.values()
        )
    def choose_mapping(all_mappings):
        for m in all_mappings:
            if chapter_lengths(m) == (4, 5, 5, 4):
                return m
        raise RuntimeError('no matching mapping found')
    epmap.automap(episodes, [titles[0]], timedelta(minutes=29),
                  timedelta(minutes=32), choose_mapping=choose_mapping)
    assert list(epmap.items()) == [
        (episodes[0], (titles[0].chapters[0], titles[0].chapters[3])),
        (episodes[1], (titles[0].chapters[4], titles[0].chapters[8])),
        (episodes[2], (titles[0].chapters[9], titles[0].chapters[13])),
        (episodes[3], (titles[0].chapters[14], titles[0].chapters[17])),
    ]


def test_automap_fail(db, with_config, with_program, drive, foo_disc1):
    drive.disc = foo_disc1
    disc = Disc(with_config)
    episodes = with_program.seasons[0].episodes
    titles = disc.titles

    epmap = EpisodeMap()
    with pytest.raises(NoSolutionsError):
        epmap.automap(episodes, [titles[0]], timedelta(minutes=29), timedelta(minutes=30))
