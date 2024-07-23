# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2022-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from tvrip.multipart import *


def test_single_name(db, with_program):
    with db.transaction():
        episodes = list(db.get_episodes())[:1]
        assert prefix(episodes) == 1
        assert name(episodes) == 'Foo'


def test_ditto(db, with_program):
    with db.transaction():
        db.update_episode(2, '"') # ditto
        episodes = list(db.get_episodes())[:2]
        assert prefix(db.get_episodes()) == 2
        assert name(episodes) == 'Foo'


def test_name_parentheses(db, with_program):
    with db.transaction():
        db.update_episode(1, 'Foo: (1)')
        db.update_episode(2, 'Foo: (2)')
        db.update_episode(3, 'Foo: (3)')
        episodes = list(db.get_episodes())[:3]
        assert prefix(db.get_episodes()) == 3
        assert name(episodes) == 'Foo'
        db.update_episode(4, 'Bar: (4)')
        assert prefix(db.get_episodes()) == 3


def test_name_parts(db, with_program):
    with db.transaction():
        db.update_episode(1, 'Foo - Part 1')
        db.update_episode(2, 'Foo - Part 2')
        episodes = list(db.get_episodes())[:2]
        assert prefix(db.get_episodes()) == 2
        assert name(episodes) == 'Foo'
        db.update_episode(3, 'Bar - Part 3')
        assert prefix(db.get_episodes()) == 2


def test_name_not_multipart(db, with_program):
    with db.transaction():
        assert prefix(db.get_episodes()) == 1
        with pytest.raises(ValueError):
            assert name(db.get_episodes())
