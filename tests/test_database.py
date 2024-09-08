# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2021-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime as dt
from pathlib import Path
from unittest import mock

import pytest

from tvrip.database import *
from tvrip.ripper import Disc


@pytest.fixture()
def with_old_schema(request, db):
    old_schema = """\
CREATE TABLE programs (
        name VARCHAR(200) NOT NULL,
        PRIMARY KEY (name)
);
CREATE TABLE seasons (
        program_name VARCHAR(200) NOT NULL,
        number INTEGER NOT NULL CHECK (number >= 0),
        PRIMARY KEY (program_name, number),
        FOREIGN KEY(program_name) REFERENCES programs (name) ON DELETE cascade ON UPDATE cascade
);
CREATE TABLE episodes (
        program_name VARCHAR(200) NOT NULL,
        season_number INTEGER NOT NULL,
        number INTEGER NOT NULL CHECK (number >= 1),
        name VARCHAR(200) NOT NULL,
        disc_id VARCHAR(200),
        disc_title INTEGER,
        start_chapter INTEGER,
        end_chapter INTEGER,
        PRIMARY KEY (program_name, season_number, number),
        FOREIGN KEY(program_name, season_number) REFERENCES seasons (program_name, number) ON DELETE cascade ON UPDATE cascade,
        CHECK ((end_chapter is null and start_chapter is null) or (end_chapter >= start_chapter))
);
CREATE TABLE config (
        id INTEGER NOT NULL,
        source VARCHAR(300) NOT NULL,
        target VARCHAR(300) NOT NULL,
        "temp" VARCHAR(300) NOT NULL,
        template VARCHAR(300) NOT NULL,
        id_template VARCHAR(100) NOT NULL,
        duration_min INTEGER NOT NULL,
        duration_max INTEGER NOT NULL,
        program_name VARCHAR(200),
        season_number INTEGER,
        subtitle_format VARCHAR(6) NOT NULL CHECK (subtitle_format in ('none', 'vobsub', 'pgs', 'cc', 'any')),
        audio_mix VARCHAR(6) NOT NULL CHECK (audio_mix in ('mono', 'stereo', 'dpl1', 'dpl2')),
        decomb VARCHAR(4) NOT NULL CHECK (decomb in ('off', 'on', 'auto')),
        audio_all BOOLEAN NOT NULL,
        subtitle_all BOOLEAN NOT NULL,
        subtitle_default BOOLEAN NOT NULL,
        video_style VARCHAR(10) NOT NULL CHECK (video_style in ('tv', 'film', 'animation')),
        dvdnav BOOLEAN NOT NULL,
        duplicates VARCHAR(5) NOT NULL CHECK (duplicates in ('all', 'first', 'last')),
        api_key VARCHAR(128) NOT NULL,
        api_url VARCHAR(300) NOT NULL,
        output_format VARCHAR(3) NOT NULL CHECK (output_format in ('mp4', 'mkv')),
        width_max INTEGER NOT NULL,
        height_max INTEGER NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(program_name) REFERENCES programs (name) ON DELETE set null ON UPDATE cascade,
        FOREIGN KEY(program_name, season_number) REFERENCES seasons (program_name, number) ON DELETE set null ON UPDATE cascade
);
CREATE TABLE config_audio (
        config_id INTEGER NOT NULL,
        lang VARCHAR(3) NOT NULL,
        PRIMARY KEY (config_id, lang),
        FOREIGN KEY(config_id) REFERENCES config (id) ON DELETE cascade ON UPDATE cascade
);
CREATE TABLE config_subtitles (
        config_id INTEGER NOT NULL,
        lang VARCHAR(3) NOT NULL,
        PRIMARY KEY (config_id, lang),
        FOREIGN KEY(config_id) REFERENCES config (id) ON DELETE cascade ON UPDATE cascade
);
CREATE TABLE config_paths (
        config_id INTEGER NOT NULL,
        name VARCHAR(100) NOT NULL,
        path VARCHAR(300) NOT NULL,
        PRIMARY KEY (config_id, name),
        FOREIGN KEY(config_id) REFERENCES config (id) ON DELETE cascade ON UPDATE cascade
);
"""
    with db.transaction():
        for stmt in db._parse_script(old_schema):
            db._conn.execute(text(stmt))
    yield


def test_db_init_fail(tmp_path):
    filename = tmp_path / 'not-a-file'
    filename.mkdir()
    with pytest.raises(RuntimeError):
        Database(filename)


def test_db_uninitialized(db):
    assert db.get_version() == 0


def test_db_old_version(db, with_old_schema):
    assert db.get_version() == 1


def test_db_current_version(db, with_schema):
    assert db.get_version() == with_schema == 2


def test_db_migration(db, with_old_schema):
    assert db.get_version() == 1
    db.migrate()
    assert db.get_version() == db.latest_version
    # Ensure migrate is idempotent
    db.migrate()
    assert db.get_version() == db.latest_version


def test_db_migration_missing_script(db, with_old_schema):
    # NOTE: I doubt we'll ever reach schema version 10 ... but if we do, bump
    # this value ...
    with mock.patch('tvrip.database.Database.latest_version', 10):
        with pytest.raises(ValueError):
            db.migrate()


def test_db_parse_script(db):
    assert list(db._parse_script(
        '-- This is a comment\nDROP TABLE foo;'
    )) == ['DROP TABLE foo;']
    assert list(db._parse_script(
        "VALUES (-1, '- not a comment -')"
    )) == ["VALUES (-1, '- not a comment -')"]
    assert list(db._parse_script(
        'DROP TABLE bar;\nDROP TABLE foo\n'
    )) == ['DROP TABLE bar;', 'DROP TABLE foo']
    assert list(db._parse_script(
        "VALUES (';');"
    )) == ["VALUES (';');"]
    assert list(db._parse_script(
        'DROP TABLE "little;bobby;tables";'
    )) == ['DROP TABLE "little;bobby;tables";']


def test_db_check_rowcount(db, with_program):
    # Episode 10 must not exist
    with pytest.raises(RuntimeError):
        db.update_episode(10, 'Blah')


def test_db_config(db, with_config):
    with db.transaction():
        cfg = with_config
        cfg = db.set_config(cfg._replace(
            duration=[dt.timedelta(minutes=13), dt.timedelta(minutes=17)]))
        assert cfg.duration == [
            dt.timedelta(minutes=13), dt.timedelta(minutes=17)]


def test_programs(db, with_program):
    with db.transaction():
        assert with_program.program == 'Foo & Bar'
        assert db.get_program('Foo & Bar') == with_program.program
        assert db.get_program('Blah') is None
        assert list(db.get_programs()) == [
            (with_program.program, 2, 9, 0),
        ]


def test_seasons(db, with_program):
    with db.transaction():
        cfg = db.get_config()
        assert cfg.program == 'Foo & Bar'
        assert cfg.season == 1
        assert db.get_season(1) == 1
        assert db.get_season(10) is None
        assert list(db.get_seasons()) == [
            (1, 5, 0),
            (2, 4, 0),
        ]
        assert db.get_first_season(with_program.program) == 1


def test_episodes(db, with_program):
    with db.transaction():
        assert db.get_config().season == 1
        assert list(db.get_episodes()) == [
            (1, 'Foo', None, None, None, None),
            (2, 'Bar', None, None, None, None),
            (3, 'Baz', None, None, None, None),
            (4, 'Quux', None, None, None, None),
            (5, 'Xyzzy', None, None, None, None),
        ]
        db.clear_episodes()
        assert list(db.get_episodes()) == []


def test_episode(db, with_program):
    with db.transaction():
        ep = db.get_episode(1)
        assert isinstance(ep, Episode)
        assert ep.title == 'Foo'
        assert ep.disc_id is None
        assert ep.as_row == dict(
            episode=1,
            title='Foo',
            disc_id=None,
            disc_title=None,
            start_chapter=None,
            end_chapter=None,
        )
        db.update_episode(1, 'Foo Part 1')
        ep = db.get_episode(1)
        assert ep.title == 'Foo Part 1'
        assert db.get_episode(10) is None


def test_insert_episode(db, with_program):
    with db.transaction():
        assert db.get_episode(1).title == 'Foo'
        assert db.get_episode(4).title == 'Quux'
        db.insert_episode(4, 'Quacks')
        assert db.get_episode(1).title == 'Foo'
        assert db.get_episode(4).title == 'Quacks'
        assert db.get_episode(5).title == 'Quux'
        assert db.get_episode(6).title == 'Xyzzy'


def test_delete_episode(db, with_program):
    with db.transaction():
        assert db.get_episode(1).title == 'Foo'
        assert db.get_episode(4).title == 'Quux'
        db.delete_episode(4)
        assert db.get_episode(1).title == 'Foo'
        assert db.get_episode(4).title == 'Xyzzy'


def test_unripped(db, with_config, with_program, drive, foo_disc1):
    with db.transaction():
        drive.disc = foo_disc1
        d = Disc(with_config)
        assert len(list(db.get_unripped())) == 5


def test_ripped(db, with_config, with_program, drive, foo_disc1):
    with db.transaction():
        drive.disc = foo_disc1
        d = Disc(with_config)
        assert len(list(db.get_ripped(d))) == 0
        ep = db.get_episode(1)
        assert ep.disc_id is None
        ep = db.rip_episode(ep, d.titles[1])
        assert len(list(db.get_ripped(d))) == 1
        assert ep.disc_id is not None


def test_ripped_chapters(db, with_config, with_program, drive, foo_disc1):
    with db.transaction():
        drive.disc = foo_disc1
        d = Disc(with_config)
        assert len(list(db.get_ripped(d))) == 0
        ep = db.get_episode(1)
        assert ep.start_chapter is None
        assert ep.end_chapter is None
        ep = db.rip_episode(ep, (d.titles[0].chapters[0], d.titles[0].chapters[4]))
        assert len(list(db.get_ripped(d))) == 1
        assert ep.start_chapter is not None
        assert ep.end_chapter is not None


def test_ripped_unripped(db, with_config, with_program, drive, foo_disc1):
    with db.transaction():
        drive.disc = foo_disc1
        d = Disc(with_config)
        ep = db.get_episode(1)
        ep = db.rip_episode(ep, d.titles[1])
        assert ep.disc_id is not None
        assert len(list(db.get_ripped(d))) == 1
        ep = db.unrip_episode(ep)
        assert len(list(db.get_ripped(d))) == 0
        assert ep.disc_id is None

