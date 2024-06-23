import pytest

from tvrip.multipart import *


def test_single_name(db, with_program):
    prog = with_program
    episodes = [prog.seasons[0].episodes[0]]
    assert prefix(episodes) == 1
    assert name(episodes) == 'Foo'


def test_ditto(db, with_program):
    s = with_program.seasons[0]
    s.episodes[1].name = '"'  # ditto
    episodes = [s.episodes[0], s.episodes[1]]
    assert prefix(s.episodes) == 2
    assert name(episodes) == 'Foo'


def test_name_parentheses(db, with_program):
    s = with_program.seasons[0]
    s.episodes[0].name = 'Foo: (1)'
    s.episodes[1].name = 'Foo: (2)'
    s.episodes[2].name = 'Foo: (3)'
    episodes = [s.episodes[0], s.episodes[1], s.episodes[2]]
    assert prefix(s.episodes) == 3
    assert name(episodes) == 'Foo'
    s.episodes[3].name = 'Bar: (4)'
    assert prefix(s.episodes) == 3


def test_name_parts(db, with_program):
    s = with_program.seasons[0]
    s.episodes[0].name = 'Foo - Part 1'
    s.episodes[1].name = 'Foo - Part 2'
    episodes = [s.episodes[0], s.episodes[1]]
    assert prefix(s.episodes) == 2
    assert name(episodes) == 'Foo'
    s.episodes[2].name = 'Bar - Part 3'
    assert prefix(s.episodes) == 2


def test_name_not_multipart(db, with_program):
    s = with_program.seasons[0]
    assert prefix(s.episodes) == 1
    with pytest.raises(ValueError):
        assert name(s.episodes)
