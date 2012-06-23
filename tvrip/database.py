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

"""Implements the data model for the tvrip application's database"""

from __future__ import (
    unicode_literals, print_function, absolute_import, division)

import os
import tempfile
from sqlalchemy import (
    Column, ForeignKeyConstraint, ForeignKey,
    CheckConstraint, create_engine
)
from sqlalchemy.types import Unicode, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, synonym, sessionmaker
from datetime import timedelta
from tvrip.const import DATADIR


Session = sessionmaker()
DeclarativeBase = declarative_base()


class Episode(DeclarativeBase):
    """Represents an episode of a season of a program"""

    __tablename__ = 'episodes'
    __table_args__ = (
        ForeignKeyConstraint(
            ['program_name', 'season_number'],
            ['seasons.program_name', 'seasons.number'],
            onupdate='cascade', ondelete='cascade'),
        CheckConstraint('(end_chapter is null and start_chapter is null) '
            'or (end_chapter >= start_chapter)'),
        {},
    )

    program_name = Column(Unicode(200), primary_key=True)
    season_number = Column(Integer, primary_key=True)
    number = Column(Integer, CheckConstraint('number >= 1'), primary_key=True)
    name = Column(Unicode(200), nullable=False)
    disc_id = Column(Unicode(200), nullable=True)
    disc_title = Column(Integer, nullable=True)
    start_chapter = Column(Integer, nullable=True)
    end_chapter = Column(Integer, nullable=True)

    @property
    def ripped(self):
        """Indicates whether the episode has been ripped yet"""
        return bool(self.disc_id)

    def __repr__(self):
        return "<Episode(%s, %d, %d, %s)>" % (
            repr(self.season.program.name),
            self.season.number,
            self.number,
            repr(self.name)
        )


class Season(DeclarativeBase):
    """Represents a season of a program"""

    __tablename__ = 'seasons'

    program_name = Column(Unicode(200), ForeignKey('programs.name',
        onupdate='cascade', ondelete='cascade'), primary_key=True)
    number = Column(Integer, CheckConstraint('number >= 1'), primary_key=True)
    episodes = relationship('Episode', backref='season',
        order_by=[Episode.number])
    selected = relationship('Configuration', backref='season', uselist=False)

    def __repr__(self):
        return "<Season(%s, %d)>" % (repr(self.program.name), self.number)


class Program(DeclarativeBase):
    """Represents a program (i.e. a TV series)"""

    __tablename__ = 'programs'

    name = Column(Unicode(200), primary_key=True)
    seasons = relationship('Season', backref='program', order_by=[Season.number])
    selected = relationship('Configuration', backref='program', uselist=False)

    def __repr__(self):
        return "<Program(%s)>" % repr(self.name)


class AudioLanguage(DeclarativeBase):
    """Represents an audio language in the stored configuration"""

    __tablename__ = 'config_audio'

    config_id = Column(Integer, ForeignKey('config.id',
        onupdate='cascade', ondelete='cascade'), default=1, primary_key=True)
    lang = Column(Unicode(3), primary_key=True)

    def __repr__(self):
        return "<AudioLanguage(%s)>" % repr(self.lang)


class SubtitleLanguage(DeclarativeBase):
    """Represents a subtitle language in the stored configuration"""

    __tablename__ = 'config_subtitles'

    config_id = Column(Integer, ForeignKey('config.id',
        onupdate='cascade', ondelete='cascade'), default=1, primary_key=True)
    lang = Column(Unicode(3), primary_key=True)

    def __repr__(self):
        return "<SubtitleLanguage(%s)>" % repr(self.lang)


class ConfigPath(DeclarativeBase):
    """Represents a path to an external utility in the stored configuration"""

    __tablename__ = 'config_paths'

    config_id = Column(Integer, ForeignKey('config.id',
        onupdate='cascade', ondelete='cascade'), default=1, primary_key=True)
    name = Column(Unicode(100), primary_key=True)
    path = Column(Unicode(300), nullable=False)

    def __repr__(self):
        return "<ConfigPath(%s, %s)>" % (repr(self.name), repr(self.path))


class Configuration(DeclarativeBase):
    """Represents a stored configuration for the application"""

    __tablename__  = 'config'
    __table_args__ = (
        ForeignKeyConstraint(
            ['program_name'],
            ['programs.name'],
            onupdate='cascade', ondelete='set null'),
        ForeignKeyConstraint(
            ['program_name', 'season_number'],
            ['seasons.program_name', 'seasons.number'],
            onupdate='cascade', ondelete='set null'),
        {}
    )

    id = Column(Integer, primary_key=True)
    source = Column(Unicode(300), nullable=False, default='/dev/dvd')
    target = Column(Unicode(300), nullable=False,
        default=os.path.expanduser('~/Videos'))
    temp = Column(Unicode(300), nullable=False,
        default=unicode(tempfile.gettempdir()))
    template = Column(Unicode(300), nullable=False,
        default='{program} - {season}x{episode:02d} - {name}.mp4')
    _duration_min = Column('duration_min', Integer, nullable=False, default=40)
    _duration_max = Column('duration_max', Integer, nullable=False, default=50)
    program_name = Column(Unicode(200))
    season_number = Column(Integer)
    subtitle_format = Column(Unicode(6),
        CheckConstraint("subtitle_format in ('none', 'vobsub')"),
        nullable=False, default='none')
    audio_mix = Column(Unicode(6),
        CheckConstraint("audio_mix in ('mono', 'stereo', 'dpl1', 'dpl2')"),
        nullable=False, default='dpl2')
    decomb = Column(Unicode(4),
        CheckConstraint("decomb in ('off', 'on', 'auto')"),
        nullable=False, default='off')
    audio_all = Column(Boolean, nullable=False, default=False)
    audio_langs = relationship('AudioLanguage', backref='config')
    subtitle_all = Column(Boolean, nullable=False, default=False)
    subtitle_langs = relationship('SubtitleLanguage', backref='config')
    paths = relationship('ConfigPath', backref='config')

    def _get_duration_min(self):
        return timedelta(minutes=self._duration_min)
    def _set_duration_min(self, value):
        self._duration_min = value.seconds / 60
    duration_min = synonym('_duration_min',
        descriptor=property(_get_duration_min, _set_duration_min))

    def _get_duration_max(self):
        return timedelta(minutes=self._duration_max)
    def _set_duration_max(self, value):
        self._duration_max = value.seconds / 60
    duration_max = synonym('_duration_max',
        descriptor=property(_get_duration_max, _set_duration_max))

    def in_audio_langs(self, lang):
        """Returns True if lang is a selected audio language"""
        return any(l.lang == lang for l in self.audio_langs)

    def in_subtitle_langs(self, lang):
        """Returns True if lang is a selected subtitle language"""
        return any(l.lang == lang for l in self.subtitle_langs)

    def get_path(self, name):
        """Returns the configured path of the specified utility"""
        session = Session.object_session(self)
        return session.query(ConfigPath).\
            filter(ConfigPath.config_id==self.id).\
            filter(ConfigPath.name==name).one().path

    def set_path(self, name, value):
        """Sets the configured path of the specified utility"""
        session = Session.object_session(self)
        session.query(ConfigPath).\
            filter(ConfigPath.config_id==self.id).\
            filter(ConfigPath.name==name).one().path = value
        session.commit()

    def __repr__(self):
        return "<Configuration(...)>"

SESSION = None
def init_session(url=None, debug=False):
    """Initializes the connection to the database and returns a new session

    This routine must be called once during the application to open the
    connection to the tvrip database and obtain a session object for
    manipulating that connection.
    """
    # The SESSION global is simply used to ensure this is a one-time call so
    # multiple simultaneous database connections don't get opened
    global SESSION
    assert SESSION is None

    if url is None:
        url = 'sqlite:///%s' % os.path.join(DATADIR, 'tvrip.db')
    engine = create_engine(url, echo=debug)
    SESSION = Session(bind=engine)
    DeclarativeBase.metadata.bind = engine
    DeclarativeBase.metadata.create_all()
    return SESSION
