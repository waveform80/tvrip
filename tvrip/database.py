# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2011-2014 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Implements the data model for the tvrip application's database
"""

import os
import re
import json
import typing as t
from pathlib import Path
from datetime import timedelta
from importlib import resources
from contextlib import contextmanager

from sqlalchemy import create_engine, text, exc
from sqlalchemy.engine import Row, Result
from sqlalchemy.engine.url import URL

from .const import DATADIR
from .ripper import Disc, Title, Chapter


class Config(t.NamedTuple):
    program: t.Optional[str]
    season: t.Optional[int]
    paths: dict[str, Path] = {
        'vlc':           Path('/usr/bin/vlc'),
        'handbrake':     Path('/usr/bin/HandBrakeCLI'),
        'atomicparsley': Path('/usr/bin/AtomicParsley'),
        'mkvpropedit':   Path('/usr/bin/mkvpropedit'),
    }
    api: str = ''
    api_key: str = ''
    audio_all: bool = False
    audio_encoding: str = 'av_aac'
    audio_langs: list[str] = ['eng']
    audio_mix: str = 'dpl2'
    decomb: str = 'auto'
    duplicates: str = 'all'
    duration: tuple[timedelta, timedelta] = (
        timedelta(minutes=40), timedelta(minutes=50))
    dvdnav: bool = True
    id_template: str = '{season}x{episode:02d}'
    max_resolution: tuple[int, int] = (1920, 1080)
    output_format: str = 'mp4'
    source: Path = Path('/dev/dvd')
    subtitle_all: bool = False
    subtitle_default: bool = False
    subtitle_format: str = 'none'
    subtitle_langs: list[str] = ['eng']
    target: Path = Path('~/Videos')
    template: str = '{program} - {id} - {name}.{ext}'
    temp: Path = '/tmp'
    video_style: str = 'tv'

    @classmethod
    def from_row(cls, row):
        conf = json.loads(row.config)
        if isinstance(conf, dict):
            if 'duration' in conf:
                conf['duration'] = tuple(
                    timedelta(minutes=i) for i in conf['duration'])
            if 'max_resolution' in conf:
                conf['max_resolution'] = tuple(conf['max_resolution'])
            if 'paths' in conf:
                conf['paths'] = {
                    key: Path(path) for key, path in conf['paths'].items()}
            if 'source' in conf:
                conf['source'] = Path(conf['source'])
            if 'target' in conf:
                conf['target'] = Path(conf['target'])
            if 'temp' in conf:
                conf['temp'] = Path(conf['temp'])
            conf = {
                key: value
                for key, value in conf.items()
                if key in cls._fields
            }
        else:
            conf = {}
        return cls(
            program=row.program,
            season=row.season,
            **conf)

    @property
    def as_row(self):
        conf = self._asdict()
        del conf['program']
        del conf['season']
        conf['duration'] = [t.total_seconds() // 60 for t in conf['duration']]
        conf['max_resolution'] = list(conf['max_resolution'])
        conf['paths'] = {key: str(path) for key, path in conf['paths'].items()}
        conf['source'] = str(conf['source'])
        conf['target'] = str(conf['target'])
        conf['temp'] = str(conf['temp'])
        return {
            'program': self.program,
            'season': self.season,
            'config': json.dumps(conf)
        }


class Episode(t.NamedTuple):
    episode: int
    title: str
    disc_id: t.Optional[str]
    disc_title: t.Optional[int]
    start_chapter: t.Optional[int]
    end_chapter: t.Optional[int]

    def __repr__(self):
        return f'<Episode({self.episode}, {self.title!r})>'

    @property
    def ripped(self):
        return bool(self.disc_id)

    @classmethod
    def from_row(cls, row):
        return cls(*row)

    @property
    def as_row(self):
        return self._asdict()


class Database:
    # This is the version of the schema in sql/create_db.sql, i.e. the "latest"
    # version of the database which will be created in the event that no
    # database is found on disk, or the version that the existing database on
    # disk will be migrated to
    latest_version = 2

    def __init__(self, filename, debug=False):
        try:
            self._url = URL.create('sqlite', database=str(filename))
            self._engine = None
            self._conn = None
            self._open(debug=debug)
        except exc.OperationalError:
            raise RuntimeError(
                f"Cannot create or open database {self._url.database}")

    def _open(self, *, debug=False):
        self._engine = create_engine(self._url, echo=debug)
        self._conn = self._engine.connect()
        with self._conn.begin():
            self._conn.execute(text('PRAGMA foreign_keys = ON'))

    def close(self):
        """
        Close the database connection. This method is idempotent. After the
        initial call, any subsequent database operations attempted will
        necessarily fail.
        """
        if self._conn:
            self._conn.close()
            self._conn = None
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    @contextmanager
    def transaction(self):
        with self._conn.begin():
            yield

    def get_version(self):
        """
        Return the current version of the database schema. This is typically
        done by reading the contents of the ``version`` table, but before that
        was added we simply call it version 1. Returns :data:`None` if the
        database appears uninitialized, and raises :exc:`ValueError` is the
        version cannot be interpreted.
        """
        try:
            with self._conn.begin():
                db_version = int(self._conn.scalar(text(
                    "SELECT version FROM version")))
        except exc.OperationalError:
            with self._conn.begin():
                config_exists = bool(self._conn.scalar(text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE tbl_name = 'config' AND type = 'table'")))
                programs_exists = bool(self._conn.scalar(text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE tbl_name = 'programs' AND type = 'table'")))
            if programs_exists and config_exists:
                return 1
            else:
                # Database is uninitialized
                return 0
        else:
            return db_version

    def migrate(self):
        """
        Upgrade the database from its current version to the latest schema
        design. This method is idempotent; if the database is already the
        latest version, nothing is done.

        Any upgrade performed is done atomically; any failure will result in
        the original database being untouched.
        """
        migration_script = self._get_migration_script()
        if migration_script.strip():
            new_db = self._url.database + '.new'
            Path(new_db).unlink(missing_ok=True)
            with self._attach(new_db):
                with self._conn.begin():
                    for statement in self._parse_script(migration_script):
                        self._conn.execute(text(statement))
            debug = self._engine.echo
            self.close()
            Path(new_db).rename(Path(self._url.database))
            self._open(debug=debug)

    def _get_migration_script(self):
        """
        Generate the scripts necessary to migrate the database from its
        current version (determined by :meth:`get_version`) to the latest
        version. Returns a :class:`str` containing a series of SQL statements.
        """
        scripts = []
        version = self.get_version()
        if version < Database.latest_version:
            with resources.files('tvrip') as root:
                # Any migration (including setting up an entirely fresh
                # database) needs the create script first to set up the bare
                # structures in the "NEW" attached database
                scripts.append((root / 'sql/create_db.sql').read_text())
                if version > 0:
                    # Build the list of upgradable versions from the scripts in
                    # the sql/ directory
                    migrations = {}
                    ver_re = re.compile(
                        r'migrate_db_(?P<from>.*)_to_(?P<to>.*)\.sql$')
                    for script_path in (root / 'sql').iterdir():
                        matched = ver_re.match(script_path.name)
                        if matched:
                            migrations[int(matched.group('from'))] = (
                                int(matched.group('to')), script_path)
                    # Attempt to find a list of scripts which'll get us from
                    # the existing version to the desired one.
                    #
                    # NOTE: This is a stupid algorithm which won't attempt
                    # different branches or back-tracking so if you wind up
                    # with custom versions or downgrade scripts in the sql
                    # directory, things will probably break
                    this_version = version
                    try:
                        while this_version != Database.latest_version:
                            this_version, script_path = migrations[this_version]
                            scripts.append(script_path.read_text())
                    except KeyError:
                        raise ValueError(
                            f'Unable to find upgrade path from {version} to '
                            f'{self.latest_version}')
        return '\n'.join(scripts)

    @contextmanager
    def _attach(self, filename, schema='NEW'):
        """
        Attach the specified *filename* as a database under the given *schema*.

        This method is intended for use as a context manager. For the duration
        of the context, the given database will be available under *schema*.
        Once the context is exited the database will be detached.
        """
        with self._conn.begin():
            self._conn.execute(
                text(f"ATTACH :filename AS {schema}"),
                {'filename': str(filename)})
        try:
            yield
        finally:
            with self._conn.begin():
                self._conn.execute(text(f"DETACH {schema}"))

    @staticmethod
    def _parse_script(script):
        """
        This is an extremely crude statement splitter for SQLite's dialect of
        SQL. It understands ``--comments``, ``"quoted identifiers"``, and
        ``'string literals'`` and ``$delim$ extended strings $delim$``, but not
        ``/* C-style comments */``, or the compatibility ``[MS SQL Server
        quoting]`` or ``\\`MySQL quoting\\```. If you start using such things
        in the SQL scripts, you'll need to extend this function to accommodate
        them.

        It returns a generator which yields individiual statements from
        *script*, delimited by semi-colon terminators.
        """
        # pylint: disable=too-many-branches
        stmt = ''
        quote = None
        for char in script:
            if quote != '--':
                stmt += char
            if quote is None:
                if char == ';':
                    yield stmt.strip()
                    stmt = ''
                elif char == "'":
                    quote = "'"
                elif char == '"':
                    quote = '"'
                elif char == '-':
                    quote = '-'
            elif quote in ('"', "'"):
                if quote == char:
                    quote = None
            elif quote == '-':
                if char == '-':
                    quote = '--'
                    stmt = stmt[:-2]
                else:
                    quote = None
            elif quote == '--':
                if char == '\n':
                    quote = None
        stmt = stmt.strip()
        if stmt:
            yield stmt

    def _check_rowcount(self, result: Result, expected: int=1) -> None:
        if result.rowcount != expected:
            raise RuntimeError(f'failed to UPDATE {expected} row(s)')

    def get_config(self) -> Config:
        return Config.from_row(self._conn.execute(text(
            """
            SELECT
                program,
                season,
                config
            FROM config
            WHERE id = 'default'
            """)).one())

    def set_config(self, value: Config) -> None:
        self._check_rowcount(self._conn.execute(text(
            """
            UPDATE config SET
                program = :program,
                season = :season,
                config = json(:config)
            WHERE id = 'default'
            """), value.as_row))
        return value

    def get_episode(self, episode: int) -> t.Optional[Episode]:
        row = self._conn.execute(text(
            """
            SELECT
                e.episode,
                e.title,
                e.disc_id,
                e.disc_title,
                e.start_chapter,
                e.end_chapter
            FROM
                episodes e
                JOIN config c USING (program, season)
            WHERE episode = :episode
            """), {'episode': episode}).first()
        if row is None:
            return row
        else:
            return Episode.from_row(row)

    def get_episodes(self) -> t.Iterable[Episode]:
        return [
            Episode.from_row(row)
            for row in self._conn.execute(text(
                """
                SELECT
                    e.episode,
                    e.title,
                    e.disc_id,
                    e.disc_title,
                    e.start_chapter,
                    e.end_chapter
                FROM
                    episodes e
                    JOIN config c USING (program, season)
                ORDER BY e.episode
                """))
        ]

    def get_unripped(self) -> t.Iterable[Episode]:
        return [
            Episode.from_row(row)
            for row in self._conn.execute(text(
                """
                SELECT
                    e.episode,
                    e.title,
                    e.disc_id,
                    e.disc_title,
                    e.start_chapter,
                    e.end_chapter
                FROM
                    episodes e
                    JOIN config c USING (program, season)
                WHERE
                    e.disc_id IS NULL
                ORDER BY e.episode
                """))
        ]

    def get_ripped(self, disc: Disc) -> t.Iterable[Episode]:
        # The rather complex filter below deals with the different methods of
        # identifying discs. In the first version of tvrip, disc serial number
        # was used but was found to be insufficient (manufacturers sometimes
        # repeat serial numbers or simply leave them blank), so a new mechanism
        # involving a hash of disc details was introduced.
        return [
            Episode.from_row(row)
            for row in self._conn.execute(text(
                """
                SELECT
                    e.episode,
                    e.title,
                    e.disc_id,
                    e.disc_title,
                    e.start_chapter,
                    e.end_chapter
                FROM
                    episodes e
                    JOIN config c USING (program, season)
                WHERE (
                    SUBSTR(e.disc_id, 1, 4) = '$H1$'
                    AND e.disc_id = :ident
                ) OR (
                    SUBSTR(e.disc_id, 1, 4) <> '$H1$'
                    AND e.disc_id = :serial
                )
                """), {'serial': disc.serial, 'ident': disc.ident})
        ]

    def clear_episodes(self):
        self._conn.execute(text(
            """
            DELETE FROM episodes
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            """))

    def add_episode(self, episode: int, title: str) -> None:
        self._conn.execute(text(
            """
            INSERT INTO episodes (program, season, episode, title)
            SELECT
                program,
                season,
                :episode,
                :title
            FROM config
            WHERE id = 'default'
            """), {'episode': episode, 'title': title})

    def rip_episode(
        self, episode: int, target: t.Union[Title, tuple[Chapter, Chapter]]
    ) -> None:
        if isinstance(target, Title):
            title = target
            start_chapter = end_chapter = None
        else:
            start_chapter, end_chapter = target
            title = start_chapter.title
        disc = title.disc
        self._check_rowcount(self._conn.execute(text(
            """
            UPDATE episodes SET
                disc_id = :disc_id,
                disc_title = :disc_title,
                start_chapter = :start_chapter,
                end_chapter = :end_chapter
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            AND episode = :episode
            """), {
                'episode': episode,
                'disc_id': disc.ident,
                'disc_title': title.number,
                'start_chapter': start_chapter.number if start_chapter else None,
                'end_chapter': end_chapter.number if end_chapter else None,
            }))

    def unrip_episode(self, episode: int) -> None:
        self._check_rowcount(self._conn.execute(text(
            """
            UPDATE episodes SET
                disc_id = NULL,
                disc_title = NULL,
                start_chapter = NULL,
                end_chapter = NULL
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            AND episode = :episode
            """), {'episode': episode}))

    def insert_episode(self, episode: int, title: str) -> None:
        # Shift all later episodes along 1
        to_alter = [
            row.episode
            for row in self._conn.execute(text(
                """
                SELECT episode
                FROM episodes
                WHERE (program, season) = (
                    SELECT program, season
                    FROM config
                    WHERE id = 'default'
                )
                AND episode >= :episode
                ORDER BY episode DESC
                """), {'episode': episode})
        ]
        for move_episode in to_alter:
            self._check_rowcount(self._conn.execute(text(
                """
                UPDATE episodes
                SET episode = episode + 1
                WHERE (program, season) = (
                    SELECT program, season
                    FROM config
                    WHERE id = 'default'
                )
                AND episode = :episode
                """), {'episode': move_episode}))
        self.add_episode(episode, title)

    def update_episode(self, episode: int, title: str) -> None:
        self._check_rowcount(self._conn.execute(text(
                """
                UPDATE episodes
                SET title = :title
                WHERE (program, season) = (
                    SELECT program, season
                    FROM config
                    WHERE id = 'default'
                )
                AND episode = :episode
            """), {'episode': episode, 'title': title}))

    def delete_episode(self, episode: int) -> None:
        self._check_rowcount(self._conn.execute(text(
            """
            DELETE FROM episodes
            WHERE (program, season) = (
                SELECT program, season
                FROM config
                WHERE id = 'default'
            )
            AND episode = :episode
            """), {'episode': episode}))
        to_alter = [
            row.episode
            for row in self._conn.execute(text(
                """
                SELECT episode
                FROM episodes
                WHERE (program, season) = (
                    SELECT program, season
                    FROM config
                    WHERE id = 'default'
                )
                AND episode > :episode
                ORDER BY episode DESC
                """), {'episode': episode})
        ]
        # Shift all later episodes back 1
        for episode in to_alter:
            self._check_rowcount(self._conn.execute(text(
                """
                UPDATE episodes
                SET episode = episode - 1
                WHERE (program, season) = (
                    SELECT program, season
                    FROM config
                    WHERE id = 'default'
                )
                AND episode = :episode
                """), {'episode': episode}))

    def get_program(self, program: str) -> t.Optional[str]:
        return self._conn.execute(text(
            """
            SELECT program
            FROM programs
            WHERE program = :program
            """), {'program': program}).scalar_one_or_none()

    def get_first_season(self, program: str) -> t.Optional[int]:
        return self._conn.execute(text(
            """
            SELECT MIN(season)
            FROM seasons
            WHERE program = :program
            AND season > 0
            """), {'program': program}).scalar_one_or_none()

    # TODO get_first_unripped

    def get_programs(self) -> Result:
        return self._conn.execute(text(
            """
            SELECT
                p.program,
                COUNT(DISTINCT s.season) AS seasons,
                COUNT(e.episode) AS episodes,
                COUNT(e.disc_id) AS ripped
            FROM
                programs p
                LEFT JOIN seasons s USING (program)
                LEFT JOIN episodes e USING (program, season)
            GROUP BY
                p.program
            """))

    def add_program(self, program: str) -> None:
        self._conn.execute(text(
            """
            INSERT INTO programs (program)
            VALUES (:program)
            """), {'program': program})

    def get_season(self, season: int) -> t.Optional[int]:
        return self._conn.execute(text(
            """
            SELECT s.season
            FROM
                seasons s
                JOIN config c USING (program)
            WHERE s.season = :season
            """), {'season': season}).scalar_one_or_none()

    def get_seasons(self) -> Result:
        return self._conn.execute(text(
            """
            SELECT
                s.season,
                COUNT(e.episode) AS episodes,
                COUNT(e.disc_id) AS ripped
            FROM
                seasons s
                JOIN config c USING (program)
                LEFT JOIN episodes e USING (program, season)
            GROUP BY s.season
            ORDER BY s.season
            """))

    def add_season(self, season: int) -> None:
        self._conn.execute(text(
            """
            INSERT INTO seasons (program, season)
            SELECT
                program,
                :season
            FROM config
            WHERE id = 'default'
            """), {'season': season})
