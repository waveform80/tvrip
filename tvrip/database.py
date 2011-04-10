# vim: set et sw=4 sts=4:

import os
import tempfile
import shutil
import sqlalchemy as sa
import sqlalchemy.orm
from datetime import timedelta
from tvrip.const import DATADIR


class Program(object):
    u"""Represents a program (i.e. a TV series)"""

    def __init__(self, name, dbpath=None):
        self.name = name
        if dbpath is None:
            dbpath = tempfile.mkdtemp(prefix='ocr', dir=DATADIR)
        elif not os.path.isdir(dbpath):
            raise ValueError('%s is not a directory or does not exist' % dbpath)
        self.dbpath = dbpath
        # Ensure db.lst exists in the OCR database path
        filename = os.path.join(dbpath, 'db.lst')
        if not os.path.exists(filename):
            open(filename, 'w').close()

    def reset_db(self):
        # Remove all image files referenced by the database
        database = os.path.join(self.dbpath, 'db.lst')
        for line in open(database, 'rU'):
            filename, chars = line.split(' ', 1)
            filename = os.path.join(self.dbpath, filename)
            if os.path.exists(filename):
                os.unlink(filename)
        # Recreate the database as a blank file
        open(database, 'w').close()

    def __repr__(self):
        return u"<Program('%s')>" % self.name


class Season(object):
    u"""Represents a season of a program"""

    def __init__(self, program, number):
        self.program = program
        self.number = number

    def __repr__(self):
        return u"<Season('%s - %d')>" % (self.program.name, self.number)


class Episode(object):
    u"""Represents an episode of a season of a program"""

    def __init__(self, season, number, name, disc_serial=None, disc_title=None, start_chapter=None, end_chapter=None):
        self.season = season
        self.number = number
        self.name = name
        self.disc_serial = disc_serial
        self.disc_title = disc_title
        self.start_chapter = start_chapter
        self.end_chapter = end_chapter

    @property
    def ripped(self):
        return bool(self.disc_serial)

    def __repr__(self):
        return u"<Episode('%s - %dx%02d - %s')>" % (
            self.season.program.name,
            self.season.number,
            self.number,
            self.name
        )


class AudioLanguage(object):
    u"""Represents an audio language in the stored configuration"""

    def __init__(self, lang):
        self.id = 1
        self.lang = lang

    def __repr__(self):
        return u"<AudioLanguage('%s')>" % self.lang


class SubtitleLanguage(object):
    u"""Represents a subtitle language in the stored configuration"""

    def __init__(self, lang):
        self.id = 1
        self.lang = lang

    def __repr__(self):
        return u"<SubtitleLanguage('%s')>" % self.lang


class Configuration(object):
    u"""Represents a stored configuration for the application"""

    def __init__(self):
        # This is only ever called when creating a new configuration hence the
        # lack of parameters and the default settings below
        self.id = 1 # just because there needs to be a key
        self.source = u'/dev/dvd'
        self.target = os.path.expanduser(u'~/Videos')
        self.temp = tempfile.gettempdir()
        self.template = u'%(program)s - %(season)dx%(episode)02d - %(name)s.mp4'
        self._duration_min = 40
        self._duration_max = 50
        self.program = None
        self.season = None
        self.subtitle_format = u'none'
        self.subtitle_black = 3
        self.subtitle_tracks = u'first'
        self.audio_mix = u'dpl2'
        self.audio_tracks = u'first'
        self.decomb = u'off'

    def _get_duration_min(self):
        return timedelta(minutes=self._duration_min)
    def _set_duration_min(self, value):
        self._duration_min = value.seconds / 60
    duration_min = property(_get_duration_min, _set_duration_min)

    def _get_duration_max(self):
        return timedelta(minutes=self._duration_max)
    def _set_duration_max(self, value):
        self._duration_max = value.seconds / 60
    duration_max = property(_get_duration_max, _set_duration_max)

    def in_audio_langs(self, lang):
        return any(l.lang == lang for l in self.audio_langs)

    def in_subtitle_langs(self, lang):
        return any(l.lang == lang for l in self.subtitle_langs)

    def __repr__(self):
        return u"<Configuration(...)>"


def init_session(url=None, debug=False):
    if url is None:
        url = u'sqlite:///%s' % os.path.join(DATADIR, u'tvrip.db')
    engine = sa.create_engine(url, echo=debug)
    session = sa.orm.sessionmaker(bind=engine)()
    metadata = sa.MetaData()

    # Configure SQLAlchemy tables
    programs_table = sa.Table('programs', metadata,
        sa.Column('program', sa.Text, primary_key=True),
        sa.Column('dbpath', sa.Text)
    )
    seasons_table = sa.Table('seasons', metadata,
        sa.Column('program', sa.Text, primary_key=True),
        sa.Column('season', sa.Integer, primary_key=True),
        sa.ForeignKeyConstraint(['program'], ['programs.program'],
            onupdate='cascade', ondelete='cascade', name='program_fk'),
        sa.CheckConstraint('season >= 1', name='season_ck')
    )
    episodes_table = sa.Table('episodes', metadata,
        sa.Column('program', sa.Text, primary_key=True),
        sa.Column('season', sa.Integer, primary_key=True),
        sa.Column('episode', sa.Integer, primary_key=True),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('disc_serial', sa.Text, nullable=True),
        sa.Column('disc_title', sa.Integer, nullable=True),
        sa.Column('start_chapter', sa.Integer, nullable=True),
        sa.Column('end_chapter', sa.Integer, nullable=True),
        sa.ForeignKeyConstraint(['program', 'season'], ['seasons.program', 'seasons.season'],
            onupdate='cascade', ondelete='cascade', name='season_fk'),
        sa.CheckConstraint('episode >= 1', name='episode_ck'),
        sa.CheckConstraint('(end_chapter is null and start_chapter is null) or (end_chapter >= start_chapter)')
    )
    config_table = sa.Table('config', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('source', sa.Text),
        sa.Column('target', sa.Text),
        sa.Column('temp', sa.Text),
        sa.Column('template', sa.Text),
        sa.Column('duration_min', sa.Integer),
        sa.Column('duration_max', sa.Integer),
        sa.Column('program', sa.Text),
        sa.Column('season', sa.Integer),
        sa.Column('subtitle_format', sa.Text),
        sa.Column('subtitle_black', sa.Integer),
        sa.Column('audio_mix', sa.Text),
        sa.Column('decomb', sa.Text),
        sa.Column('audio_tracks', sa.Text),
        sa.Column('subtitle_tracks', sa.Text),
        sa.ForeignKeyConstraint(['program'], ['programs.program'],
            onupdate='cascade', ondelete='set null', name='program_fk'),
        sa.ForeignKeyConstraint(['program', 'season'], ['seasons.program', 'seasons.season'],
            onupdate='cascade', ondelete='set null', name='season_fk'),
        sa.CheckConstraint("decomb in ('off', 'on', 'auto')", name='decomb_ck'),
        sa.CheckConstraint("audio_tracks in ('first', 'all')", name='audio_tracks_ck'),
        sa.CheckConstraint("subtitle_tracks in ('first', 'all')", name='subtitle_tracks_ck'),
        sa.CheckConstraint('subtitle_black between 1 and 4', name='subtitle_black_ck')
    )
    config_audio_table = sa.Table('config_audio', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('lang', sa.Text, primary_key=True),
        sa.ForeignKeyConstraint(['id'], ['config.id'],
            onupdate='cascade', ondelete='cascade', name='config_fk')
    )
    config_subtitles_table = sa.Table('config_subtitles', metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('lang', sa.Text, primary_key=True),
        sa.ForeignKeyConstraint(['id'], ['config.id'],
            onupdate='cascade', ondelete='cascade', name='config_fk')
    )

    # Map the tables to classes
    sa.orm.mapper(Episode, episodes_table, properties={
        '_program':        episodes_table.c.program,
        '_season':         episodes_table.c.season,
        'number':          episodes_table.c.episode,
    })
    sa.orm.mapper(Season, seasons_table, properties={
        '_program':        seasons_table.c.program,
        'number':          seasons_table.c.season,
        'episodes':        sa.orm.relation(Episode, order_by=Episode.number, backref='season'),
        'selected':        sa.orm.relation(Configuration, uselist=False, backref='season'),
    })
    sa.orm.mapper(Program, programs_table, properties={
        'name':            programs_table.c.program,
        'seasons':         sa.orm.relation(Season, order_by=Season.number, backref='program'),
        'selected':        sa.orm.relation(Configuration, uselist=False, backref='program'),
    })
    sa.orm.mapper(AudioLanguage, config_audio_table)
    sa.orm.mapper(SubtitleLanguage, config_subtitles_table)
    sa.orm.mapper(Configuration, config_table, properties={
        '_program':        config_table.c.program,
        '_season':         config_table.c.season,
        'audio_langs':     sa.orm.relation(AudioLanguage),
        'subtitle_langs':  sa.orm.relation(SubtitleLanguage),
        'duration_min':    sa.orm.synonym('_duration_min', map_column=True),
        'duration_max':    sa.orm.synonym('_duration_max', map_column=True),
    })

    # Connect to the database and create all the tables if required, then
    # return the session (the caller can retrieve everything else required via
    # the session)
    metadata.create_all(engine)
    return session
