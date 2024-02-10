# vim: set et sw=4 sts=4:

# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
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

"Implements the command line processor for the tvrip application"

import os
import re
import subprocess as proc
from pathlib import Path
from datetime import timedelta, datetime

import requests
import sqlalchemy as sa

from .ripper import Disc, Title
from .database import (
    init_session, Configuration, Program, Season, Episode,
    AudioLanguage, SubtitleLanguage, ConfigPath
    )
from .episodemap import EpisodeMap, MapError
from .cmdline import Cmd, CmdError, CmdSyntaxError
from .const import DATADIR
from .tvdb import TVDB
from . import multipart


class RipCmd(Cmd):
    "Implementation of the TVRip command line"

    prompt = '(tvrip) '

    def __init__(self, session, *, color_prompt=True, stdin=None, stdout=None):
        super().__init__(color_prompt=color_prompt, stdin=stdin, stdout=stdout)
        self.discs = {}
        self.episode_map = EpisodeMap()
        self.session = session
        # Specify the history filename
        self.history_file = os.path.join(DATADIR, 'tvrip.history')
        # Read the configuration from the database
        try:
            self.config = self.session.query(Configuration).one()
        except sa.orm.exc.NoResultFound:
            self.config = Configuration()
            self.session.add(self.config)
            self.session.add(AudioLanguage(self.config, 'eng'))
            self.session.add(SubtitleLanguage(self.config, 'eng'))
            self.session.add(
                ConfigPath(self.config, 'handbrake', 'HandBrakeCLI'))
            self.session.add(
                ConfigPath(self.config, 'atomicparsley', 'AtomicParsley'))
            self.session.add(
                ConfigPath(self.config, 'mkvpropedit', 'mkvpropedit'))
            self.session.add(
                ConfigPath(self.config, 'vlc', 'vlc'))
            self.session.commit()
        self.set_api()
        self.config_handlers = {
            'api_key':          self.set_api_key,
            'api_url':          self.set_api_url,
            'atomicparsley':    self.set_executable,
            'audio_all':        self.set_bool,
            'audio_langs':      self.set_langs,
            'audio_mix':        self.set_audio_mix,
            'decomb':           self.set_decomb,
            'duplicates':       self.set_duplicates,
            'duration':         self.set_duration,
            'dvdnav':           self.set_bool,
            'handbrake':        self.set_executable,
            'id_template':      self.set_id_template,
            'max_resolution':   self.set_max_resolution,
            'mkvpropedit':      self.set_executable,
            'output_format':    self.set_output_format,
            'source':           self.set_device,
            'subtitle_all':     self.set_bool,
            'subtitle_default': self.set_bool,
            'subtitle_format':  self.set_subtitle_format,
            'subtitle_langs':   self.set_langs,
            'target':           self.set_directory,
            'template':         self.set_template,
            'temp':             self.set_directory,
            'video_style':      self.set_video_style,
            'vlc':              self.set_executable,
        }

    def onecmd(self, line):
        # Ensure that the current transaction is committed after a command, or
        # that everything the command did is rolled back in the case of an
        # exception
        try:
            result = super().onecmd(line)
        except:
            self.session.rollback()
            raise
        else:
            self.session.commit()
            return result

    def _get_disc(self):
        "Returns the Disc object for the current source"
        return self.discs.get(self.config.source, None)

    def _set_disc(self, value):
        "Set the Disc object for the current source"
        if self.config.source is None:
            raise CmdError('No source has been specified')
        elif self.config.source in self.discs:
            # XXX assert that no background jobs are currently running
            pass
        if value is None:
            self.discs.pop(self.config.source, None)
        else:
            self.discs[self.config.source] = value

    disc = property(_get_disc, _set_disc)

    def no_args(self, arg):
        if arg.strip():
            raise CmdSyntaxError('You must not specify any arguments')

    def parse_episode(self, episode, must_exist=True):
        """
        Parse a string containing an episode number.

        Given a string representing an episode number, this method returns the
        Episode object from the current program's season with the corresponding
        number, or throws an error if no such episode exists unless the
        optional must_exist flag is set to False.
        """
        if not self.config.program:
            raise CmdError('No program has been set')
        elif not self.config.season:
            raise CmdError('No season has been set')
        try:
            episode = int(episode)
        except ValueError:
            raise CmdSyntaxError(
                'Expected episode number but found "{}"'.format(episode))
        if episode < 1:
            raise CmdError(
                'Episode number {} is less than one'.format(episode))
        result = self.session.query(Episode).get(
            (self.config.program_name, self.config.season_number, episode))
        if result is None and must_exist:
            raise CmdError(
                'There is no episode {episode} in '
                'season {season} of {program}'.format(
                    episode=episode,
                    season=self.config.season.number,
                    program=self.config.program.name))
        return result

    def parse_episode_range(self, episodes, must_exist=True):
        """
        Parse a string containing an episode range.

        Given a string representing a range of episodes as two dash-separated
        numbers, this method returns the Episode objects at the start and end
        of the range or throws an error if no such episodes exist unless the
        optional must_exist flag is set to False.
        """
        if '-' not in episodes:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (
            self.parse_episode(i, must_exist)
            for i in self.parse_number_range(episodes)
            )
        return start, finish

    def parse_episode_list(self, episodes, must_exist=True):
        """
        Parse a string containing an episode list.

        Given a string representing a list of episodes as a comma-separated
        list of numbers and number-ranges, this method returns a sequence of
        Episode objects. If episodes within the list do not exist an error will
        be thrown unless the optional must_exist flag is set to False in which
        case None will be returned for them instead.
        """
        return [
            self.parse_episode(i, must_exist)
            for i in self.parse_number_list(episodes)
            ]

    def parse_title(self, title):
        """
        Parse a string containing a title number.

        Given a string representing a title number, this method returns the
        Title object from the current disc with the corresponding number, or
        throws an error if no such title exists.
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        try:
            title = int(title)
        except ValueError:
            raise CmdSyntaxError(
                'Expected title number but found "{}"'.format(title))
        if not 1 <= title <= 99:
            raise CmdError(
                'Title number {} is not between 1 and 99'.format(title))
        try:
            return [t for t in self.disc.titles if t.number == title][0]
        except IndexError:
            raise CmdError(
                'There is no title {} on the scanned disc'.format(title))

    def parse_title_range(self, titles):
        """
        Parse a string containing a title range.

        Given a string representing a range of titles as two dash-separated
        numbers, this method returns the Title objects at the start and end
        of the range or throws an error if no such titles exist.
        """
        if '-' not in titles:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (self.parse_title(i) for i in titles.split('-', 1))
        return start, finish

    def parse_title_list(self, titles):
        """
        Parse a string containing a title list.

        Given a string representing a list of titles as a comma-separated
        list of numbers and number-ranges, this method returns a sequence of
        Title objects. If titles within the list do not exist an error will
        be thrown.
        """
        return [self.parse_title(i) for i in self.parse_number_list(titles)]

    def parse_chapter(self, title, chapter):
        """
        Parse a string containing a chapter number.

        Given a string representing a chapter number, and the Title object that
        the chapter is presumed to exist within, this method returns the
        Chapter object with the corresponding number, or throws an error if no
        such chapter exists.
        """
        try:
            chapter = int(chapter)
        except ValueError:
            raise CmdSyntaxError(
                'Expected chapter number but found "{}"'.format(chapter))
        try:
            return [c for c in title.chapters if c.number == chapter][0]
        except IndexError:
            raise CmdError(
                'There is no chapter {chapter} within title {title}'.format(
                    chapter=chapter,
                    title=title.number))

    def parse_chapter_range(self, title, chapters):
        """
        Parse a string containing a chapter range.

        Given a string representing a range of chapters as two dash-separated
        numbers, this method returns the Chapter objects at the start and end
        of the range or throws an error if no such chapters exist.
        """
        if '-' not in chapters:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (
            self.parse_chapter(title, i)
            for i in chapters.split('-', 1)
            )
        return start, finish

    def parse_title_or_chapter(self, s):
        """
        Parse a string containing a title or a title.chapter specification.

        Given a string representing a title, or a string with a dot-separated
        title and chapter, this method returns the Title or Chapter object that
        the string represents.
        """
        if '.' in s:
            title, chapter = s.split('.', 1)
            return self.parse_chapter(self.parse_title(title), chapter)
        else:
            return self.parse_title(s)

    def parse_title_or_chapter_range(self, s):
        """
        Parse a string containing a title or a chapter-range specification.

        Given a string representing a title, a title.start chapter, a
        title.start-end chapter range, or a title.start-title.end range, this
        method returns a Title object or the (Chapter, Chapter) tuple that the
        string represents.
        """
        if '.' in s:
            title, chapters = s.split('.', 1)
            if '.' in chapters:
                start_title = title
                start_chapter, end_chapter = chapters.split('-', 1)
                end_title, end_chapter = end_chapter.split('.', 1)
                return (
                    self.parse_chapter(self.parse_title(start_title), start_chapter),
                    self.parse_chapter(self.parse_title(end_title), end_chapter)
                    )
            elif '-' in chapters:
                return self.parse_chapter_range(self.parse_title(title), chapters)
            else:
                chapter = self.parse_chapter(self.parse_title(title), chapters)
                return (chapter, chapter)
        else:
            return self.parse_title(s)

    def clear_episodes(self, season=None):
        "Removes all episodes from the specified season"
        if season is None:
            season = self.config.season
        for episode in self.session.query(Episode).filter((Episode.season == season)):
            self.session.delete(episode)

    def pprint_disc(self):
        "Prints the details of the currently scanned disc"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        self.pprint('Disc type: {}'.format(self.disc.type))
        self.pprint('Disc identifier: {}'.format(self.disc.ident))
        self.pprint('Disc serial: {}'.format(self.disc.serial))
        self.pprint('Disc name: {}'.format(self.disc.name))
        self.pprint('Disc has {} titles'.format(len(self.disc.titles)))
        self.pprint('')
        table = [('Title', 'Chapters', 'Duration', 'Dup', 'Audio')]
        for title in self.disc.titles:
            table.append((
                title.number,
                len(title.chapters),
                title.duration,
                {'first': '━┓', 'yes': ' ┃', 'last': '━┛', 'no': ''}[title.duplicate],
                ' '.join(track.language for track in title.audio_tracks)
                ))
        self.pprint_table(table)

    def pprint_title(self, title):
        "Prints the details of the specified disc title"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        self.pprint(
            'Title {title}, duration: {duration}, duplicate: {duplicate}'.format(
                title=title.number, duration=title.duration,
                duplicate=title.duplicate)
        )
        self.pprint('')
        table = [('Chapter', 'Start', 'Finish', 'Duration')]
        for chapter in title.chapters:
            table.append((
                chapter.number,
                chapter.start,
                chapter.finish,
                chapter.duration,
                ))
        self.pprint_table(table)
        self.pprint('')
        table = [('Audio', 'Lang', 'Name', 'Encoding', 'Mix', 'Best')]
        for track in title.audio_tracks:
            suffix = ''
            if track.best and self.config.in_audio_langs(track.language):
                suffix = '✓'
            table.append((
                track.number,
                track.language,
                track.name,
                track.encoding,
                track.channel_mix,
                suffix
                ))
        self.pprint_table(table)
        self.pprint('')
        table = [('Subtitle', 'Lang', 'Name', 'Format', 'Best')]
        for track in title.subtitle_tracks:
            suffix = ''
            if track.best and self.config.in_subtitle_langs(track.language):
                suffix = '✓'
            table.append((
                track.number,
                track.language,
                track.name,
                track.format,
                suffix
                ))
        self.pprint_table(table)

    def pprint_programs(self):
        "Prints the defined programs"
        table = [('Program', 'Seasons', 'Episodes', 'Ripped')]
        for (program, seasons, episodes, ripped) in self.session.query(
                    Program.name,
                    sa.func.count(Season.number.distinct()),
                    sa.func.count(Episode.number),
                    sa.func.count(Episode.disc_id)
                ).outerjoin(
                    Season, Season.program_name == Program.name
                ).outerjoin(
                    Episode
                ).group_by(
                    Program.name
                ).order_by(
                    Program.name
                ):
            table.append((
                program,
                seasons,
                episodes,
                '{:5.1f}%'.format(ripped * 100 / episodes) if episodes else '-'.rjust(6)
            ))
        self.pprint_table(table)

    def pprint_seasons(self, program=None):
        "Prints the seasons of the specified program"
        if program is None:
            if not self.config.program:
                raise CmdError('No program has been set')
            program = self.config.program
        self.pprint('Seasons for program {}'.format(program.name))
        self.pprint('')
        table = [('Num', 'Episodes', 'Ripped')]
        for (season, episodes, ripped) in self.session.query(
                    Season.number,
                    sa.func.count(Episode.number),
                    sa.func.count(Episode.disc_id)
                ).filter(
                    (Season.program == program)
                ).outerjoin(
                    Episode
                ).group_by(
                    Season.number
                ).order_by(
                    Season.number
                ):
            table.append((
                season,
                episodes,
                '{:5.1f}%'.format(ripped * 100 / episodes) if episodes else '-'.rjust(6)
            ))
        self.pprint_table(table)

    def pprint_episodes(self, season=None):
        "Prints the episodes of the specified season"
        if season is None:
            if not self.config.season:
                raise CmdError('No season has been set')
            season = self.config.season
        self.pprint(
            'Episodes for season {season} of program {program}'.format(
                season=season.number, program=season.program.name))
        self.pprint('')
        table = [('Num', 'Title', 'Ripped')]
        for episode in self.session.query(Episode).filter((Episode.season == season)):
            table.append((
                episode.number,
                episode.name,
                '✓' if episode.ripped else '',
            ))
        self.pprint_table(table)

    def do_config(self, arg=''):
        """
        Shows the current set of configuration options.

        Syntax: config

        The 'config' command simply outputs the current set of configuration
        options as set by the various other commands.
        """
        self.no_args(arg)
        self.pprint('External Utility Paths:')
        self.pprint('')
        for path in self.config.paths:
            self.pprint('{name:<16} = {value}'.format(
                name=path.name, value=path.path))
        self.pprint('')
        self.pprint('Scanning Configuration:')
        self.pprint('')
        self.pprint('source           = {}'.format(self.config.source))
        self.pprint('duration         = {min}-{max} (mins)'.format(
            min=self.config.duration_min.total_seconds() / 60,
            max=self.config.duration_max.total_seconds() / 60))
        self.pprint('duplicates       = {}'.format(self.config.duplicates))
        self.pprint('')
        self.pprint('Ripping Configuration:')
        self.pprint('')
        self.pprint('target           = {}'.format(self.config.target))
        self.pprint('temp             = {}'.format(self.config.temp))
        self.pprint('template         = {}'.format(self.config.template))
        self.pprint('id_template      = {}'.format(self.config.id_template))
        self.pprint('output_format    = {}'.format(self.config.output_format))
        self.pprint('max_resolution   = {width}x{height}'.format(
            width=self.config.width_max,
            height=self.config.height_max))
        self.pprint('decomb           = {}'.format(self.config.decomb))
        self.pprint('audio_mix        = {}'.format(self.config.audio_mix))
        self.pprint('audio_all        = {}'.format(
            ['off', 'on'][self.config.audio_all]))
        self.pprint('audio_langs      = {}'.format(' '.join(
            l.lang for l in self.config.audio_langs)))
        self.pprint('subtitle_format  = {}'.format(
            self.config.subtitle_format))
        self.pprint('subtitle_all     = {}'.format(
            ['off', 'on'][self.config.subtitle_all]))
        self.pprint('subtitle_default = {}'.format(
            ['off', 'on'][self.config.subtitle_default]))
        self.pprint('subtitle_langs   = {}'.format(
            ' '.join(l.lang for l in self.config.subtitle_langs)))
        self.pprint('video_style      = {}'.format(self.config.video_style))
        self.pprint('dvdnav           = {}'.format(
            ['no', 'yes'][self.config.dvdnav]))
        self.pprint('api_url          = {}'.format(self.config.api_url))
        self.pprint('api_key          = {}'.format(self.config.api_key))

    def do_set(self, arg):
        """
        Sets a configuration option.

        Syntax: set <variable> <value>

        The 'set' command is used to alter the value of one of the
        configuration settings listed by the 'config' command.
        """
        try:
            (var, value) = arg.split(' ', 1)
        except (TypeError, ValueError):
            raise CmdSyntaxError('You must specify a variable and a value')
        var = var.strip().lower()
        value = value.strip()
        try:
            self.config_handlers[var](var, value)
        except KeyError:
            raise CmdSyntaxError(
                'Invalid configuration variable: {}'.format(var))

    set_re = re.compile(r'^set\s+')
    set_var_re = re.compile(r'^set\s+([a-z_]+)\s+')

    def complete_set(self, text, line, start, finish):
        "Auto-completer for set command"
        match = self.set_var_re.match(line)
        if match:
            var = match.group(1)
            try:
                handler = self.config_handlers[var]
            except KeyError:
                return None
            else:
                try:
                    return handler.complete(self, text, line, start, finish)
                except AttributeError:
                    return None
        else:
            match = self.set_re.match(line)
            var = line[match.end():]
            return [
                name[start - match.end():]
                for name in self.config_handlers
                if name.startswith(var)
            ]

    def do_help(self, arg):
        """
        Displays the available commands or help on a specified command or
        configuration setting.

        The 'help' command is used to display the help text for a command or,
        if no command is specified, it presents a list of all available
        commands along with a brief description of each.
        """
        try:
            super().do_help(arg)
        except CmdError as exc:
            try:
                doc = self.config_handlers[arg].__doc__
            except KeyError:
                raise exc
            else:
                for para in self.parse_docstring(doc):
                    self.pprint(para)
                    self.pprint('')

    def set_complete_one(self, line, start, valid):
        match = self.set_var_re.match(line)
        value = line[match.end():]
        return [
            name[start - match.end():]
            for name in valid
            if name.startswith(value)
        ]

    def set_complete_path(self, line, start, is_dir=False, is_exec=False,
                          is_block_device=False):
        match = self.set_var_re.match(line)
        value = line[match.end():]
        if value.endswith('/'):
            path = Path(value)
        else:
            path = Path(value).parent
        for item in path.iterdir():
            if str(item).startswith(value):
                if item.is_dir():
                    yield f'/{item.name}/'
                elif not is_dir:
                    if is_exec and not os.access(item, os.X_OK):
                        continue
                    elif is_block_device and not item.is_block_device():
                        continue
                    yield f'/{item.name}'

    def set_executable(self, var, value):
        """
        This configuration option takes the path of an executable, e.g.
        "/usr/bin/vlc".
        """
        value = Path(value).expanduser()
        if not value.exists():
            raise CmdError('Path {} does not exist'.format(value))
        if not os.access(str(value), os.X_OK, effective_ids=True):
            raise CmdError('Path {} is not executable'.format(value))
        self.config.set_path(var, str(value))

    def set_complete_executable(self, text, line, start, finish):
        return list(self.set_complete_path(line, start, is_exec=True))

    set_executable.complete = set_complete_executable

    def set_directory(self, var, value):
        """
        This configuration option takes the path of a directory, e.g.
        "/home/me/Videos".
        """
        value = Path(value).expanduser()
        if not value.exists():
            raise CmdError('Path {} does not exist'.format(value))
        if not value.is_dir():
            raise CmdError('Path {} is not a directory'.format(value))
        setattr(self.config, var, str(value))

    def set_complete_directory(self, text, line, start, finish):
        return list(self.set_complete_path(line, start, is_dir=True))

    set_directory.complete = set_complete_directory

    def set_device(self, var, value):
        """
        This configuration option takes the path of a device, e.g.
        "/dev/sr0".
        """
        value = Path(value).expanduser()
        if not value.exists():
            raise CmdError('Path {} does not exist'.format(value))
        if not value.is_block_device():
            raise CmdError('Path {} is not a block device'.format(value))
        setattr(self.config, var, str(value))

    def set_complete_device(self, text, line, start, finish):
        return list(self.set_complete_path(line, start, is_block_device=True))

    set_device.complete = set_complete_device

    def set_bool(self, var, value):
        """
        This configuration option is either "on" or "off".
        """
        try:
            setattr(self.config, var, self.parse_bool(value))
        except ValueError:
            raise CmdError(f'Value {value} must be on/off/no/yes')

    def set_complete_bool(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {'false', 'true', 'off', 'on', 'no', 'yes'})

    set_bool.complete = set_complete_bool

    def set_duplicates(self, var, value):
        """
        This configuration option can be set to "all", "first", or "last". When
        "all", duplicate titles will be treated individually and will all be
        considered for auto-mapping. When "first" only the first of a set of
        duplicates will be considered for auto-mapping, and conversely when
        "last" only the last of a set of duplicates will be used.
        """
        assert var == 'duplicates'
        if value not in ('all', 'first', 'last'):
            raise CmdSyntaxError(
                '"{}" is not a valid option for duplicates'.format(value))
        self.config.duplicates = value

    def set_complete_duplicates(self, text, line, start, finish):
        return self.set_complete_one(line, start, {'all', 'first', 'last'})

    set_duplicates.complete = set_complete_duplicates

    def set_duration(self, var, value):
        """
        This configuration option sets the minimum and maximum length (in
        minutes) that an episode is expected to be. This is used when scanning
        a source device for titles which are likely to be episodes, and when
        auto-mapping titles to episodes.
        """
        assert var == 'duration'
        self.config.duration_min, self.config.duration_max = (
            timedelta(minutes=i)
            for i in self.parse_number_range(value))

    def set_video_style(self, var, value):
        """
        This configuration option can be set to "tv", "film", or "animation".
        It influences the video encoder during ripping.
        """
        assert var == 'video_style'
        try:
            value = {
                'tv':         'tv',
                'television': 'tv',
                'film':       'film',
                'anim':       'animation',
                'animation':  'animation',
                }[value]
        except KeyError:
            raise CmdSyntaxError('Invalid video style {}'.format(value))
        self.config.video_style = value

    def set_complete_video_style(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {'tv', 'television', 'film', 'animation'})

    set_video_style.complete = set_complete_video_style

    def set_langs(self, var, value):
        """
        This configuration option accepts a space-separated list of languages
        to use when extracting audio or subtitle from an episode. Languages are
        specified as 3-character ISO639 codes, e.g. "eng jpn".
        """
        value = value.lower().split(' ')
        new_langs = set(value)
        try:
            lang_cls = {
                'audio_langs':    AudioLanguage,
                'subtitle_langs': SubtitleLanguage,
            }[var]
        except KeyError:
            assert False
        for lang in getattr(self.config, var):
            if lang.lang in new_langs:
                new_langs.remove(lang.lang)
            else:
                self.session.delete(lang)
        for lang in new_langs:
            self.session.add(lang_cls(self.config, lang=lang))

    def set_complete_langs(self, text, line, start, finish):
        langs = {
            'aar', 'abk', 'ace', 'ach', 'ada', 'ady', 'afr', 'ain', 'aka',
            'alb', 'ale', 'alt', 'amh', 'anp', 'ara', 'arg', 'arm', 'arn',
            'arp', 'arw', 'asm', 'ast', 'ava', 'awa', 'aym', 'aze', 'bak',
            'bal', 'bam', 'ban', 'baq', 'bas', 'bej', 'bel', 'bem', 'ben',
            'bho', 'bik', 'bin', 'bis', 'bla', 'bod', 'bos', 'bra', 'bre',
            'bua', 'bug', 'bul', 'bur', 'byn', 'cad', 'car', 'cat', 'ceb',
            'ces', 'cha', 'che', 'chi', 'chk', 'chm', 'chn', 'cho', 'chp',
            'chr', 'chv', 'chy', 'cnr', 'cor', 'cos', 'cre', 'crh', 'csb',
            'cym', 'cze', 'dak', 'dan', 'dar', 'del', 'den', 'deu', 'dgr',
            'din', 'div', 'doi', 'dsb', 'dua', 'dut', 'dyu', 'dzo', 'efi',
            'eka', 'ell', 'eng', 'est', 'eus', 'ewe', 'ewo', 'fan', 'fao',
            'fas', 'fat', 'fij', 'fil', 'fin', 'fon', 'fra', 'fre', 'frr',
            'frs', 'fry', 'ful', 'fur', 'gaa', 'gay', 'gba', 'geo', 'ger',
            'gil', 'gla', 'gle', 'glg', 'glv', 'gon', 'gor', 'grb', 'gre',
            'grn', 'gsw', 'guj', 'gwi', 'hai', 'hat', 'hau', 'haw', 'heb',
            'her', 'hil', 'hin', 'hmn', 'hmo', 'hrv', 'hsb', 'hun', 'hup',
            'hye', 'iba', 'ibo', 'ice', 'iii', 'iku', 'ilo', 'ind', 'inh',
            'ipk', 'isl', 'ita', 'jav', 'jpn', 'jpr', 'jrb', 'kaa', 'kab',
            'kac', 'kal', 'kam', 'kan', 'kas', 'kat', 'kau', 'kaz', 'kbd',
            'kha', 'khm', 'kik', 'kin', 'kir', 'kmb', 'kok', 'kom', 'kon',
            'kor', 'kos', 'kpe', 'krc', 'krl', 'kru', 'kua', 'kum', 'kur',
            'kut', 'lad', 'lah', 'lam', 'lao', 'lav', 'lez', 'lim', 'lin',
            'lit', 'lol', 'loz', 'ltz', 'lua', 'lub', 'lug', 'lun', 'luo',
            'lus', 'mac', 'mad', 'mag', 'mah', 'mai', 'mak', 'mal', 'man',
            'mao', 'mar', 'mas', 'may', 'mdf', 'mdr', 'men', 'mic', 'min',
            'mkd', 'mlg', 'mlt', 'mnc', 'mni', 'moh', 'mon', 'mos', 'mri',
            'msa', 'mus', 'mwl', 'mwr', 'mya', 'myv', 'nap', 'nau', 'nav',
            'nbl', 'nde', 'ndo', 'nds', 'nep', 'new', 'nia', 'niu', 'nld',
            'nno', 'nob', 'nog', 'nor', 'nqo', 'nso', 'nya', 'nym', 'nyn',
            'nyo', 'nzi', 'oci', 'oji', 'ori', 'orm', 'osa', 'oss', 'pag',
            'pam', 'pan', 'pap', 'pau', 'per', 'pol', 'pon', 'por', 'pus',
            'que', 'raj', 'rap', 'rar', 'roh', 'rom', 'ron', 'rum', 'run',
            'rup', 'rus', 'sad', 'sag', 'sah', 'sas', 'sat', 'scn', 'sco',
            'sel', 'shn', 'sid', 'sin', 'slo', 'slk', 'slv', 'sma', 'sme',
            'smj', 'smn', 'smo', 'sms', 'sna', 'snd', 'snk', 'som', 'sot',
            'spa', 'sqi', 'srd', 'srn', 'srp', 'srr', 'ssw', 'suk', 'sun',
            'sus', 'swa', 'swe', 'syr', 'tah', 'tam', 'tat', 'tel', 'tem',
            'ter', 'tet', 'tgk', 'tgl', 'tha', 'tib', 'tig', 'tir', 'tiv',
            'tkl', 'tli', 'tmh', 'tog', 'ton', 'tpi', 'tsi', 'tsn', 'tso',
            'tuk', 'tum', 'tur', 'tvl', 'twi', 'tyv', 'udm', 'uig', 'ukr',
            'umb', 'urd', 'uzb', 'vai', 'ven', 'vie', 'vot', 'wal', 'war',
            'was', 'wel', 'wln', 'wol', 'xal', 'xho', 'yao', 'yap', 'yid',
            'yor', 'zap', 'zen', 'zgh', 'zha', 'zho', 'zul', 'zun', 'zza',
        }
        return [lang for lang in langs if lang.startswith(text)]

    set_langs.complete = set_complete_langs

    def set_audio_mix(self, var, value):
        """
        This configuration option specifies an audio mix. Valid values are
        "mono", "stereo", "dpl1", and "dpl2". AC3 or DTS are not currently
        supported.
        """
        assert var == 'audio_mix'
        try:
            value = {
                'mono':     'mono',
                'm':        'mono',
                '1':        'mono',
                'stereo':   'stereo',
                's':        'stereo',
                '2':        'stereo',
                'dpl1':     'dpl1',
                'dpl2':     'dpl2',
                'surround': 'dpl2',
                'prologic': 'dpl2',
                }[value]
        except KeyError:
            raise CmdSyntaxError('Invalid audio mix {}'.format(value))
        self.config.audio_mix = value

    def set_complete_audio_mix(self, text, line, start, finish):
        return self.set_complete_one(
            line, start,
            {'mono', 'stereo', 'dpl1', 'dpl2', 'surround', 'prologic'})

    set_audio_mix.complete = set_complete_audio_mix

    def set_subtitle_format(self, var, value):
        """
        This configuration option specifies a subtitle format. Valid values
        are "none", "vobsub", "pgs", "cc", and "all". Typically, you want
        "vobsub" for DVDs and "pgs" for Blu-rays.
        """
        assert var == 'subtitle_format'
        try:
            value = {
                'off':    'none',
                'none':   'none',
                'vob':    'vobsub',
                'vobsub': 'vobsub',
                'bmp':    'vobsub',
                'bitmap': 'vobsub',
                'pgs':    'pgs',
                'cc':     'cc',
                'text':   'cc',
                'any':    'any',
                'all':    'any',
                'both':   'any',
                }[value]
        except KeyError:
            raise CmdSyntaxError(
                'Invalid subtitle extraction mode {}'.format(value))
        self.config.subtitle_format = value

    def set_complete_subtitle_format(self, text, line, start, finish):
        return self.set_complete_one(
            line, start,
            {'off', 'none', 'vobsub', 'pgs', 'bitmap', 'cc', 'text', 'all',
             'both'})

    set_subtitle_format.complete = set_complete_subtitle_format

    def set_decomb(self, var, value):
        """
        This configuration option specifies a decomb mode. Valid values are
        "off", "on", and "auto".
        """
        assert var == 'decomb'
        try:
            self.config.decomb = ['off', 'on'][self.parse_bool(value)]
        except ValueError:
            if value == 'auto':
                self.config.decomb = 'auto'
            else:
                raise CmdError(f'{value} must be off/on/auto')

    def set_complete_decomb(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {'false', 'true', 'off', 'on', 'no', 'yes', 'auto'})

    set_decomb.complete = set_complete_decomb

    def set_template(self, var, value):
        assert var == 'template'
        try:
            value.format(
                program='Program Name',
                id='1x01',
                name='Foo Bar',
                now=datetime.now(),
                ext='mp4',
                )
        except KeyError as exc:
            raise CmdError(
                'The new template contains an '
                'invalid substitution key: {}'.format(exc))
        except ValueError as exc:
            raise CmdError(
                'The new template contains an error: {}'.format(exc))
        self.config.template = value

    def set_id_template(self, var, value):
        assert var == 'id_template'
        try:
            value.format(
                season=1,
                episode=10,
                )
        except KeyError as exc:
            raise CmdError(
                'The new id_template contains an '
                'invalid substitution key: {}'.format(exc))
        except ValueError as exc:
            raise CmdError(
                'The new id_template contains an error: {}'.format(exc))
        self.config.id_template = value

    def set_max_resolution(self, var, value):
        """
        The maximum resolution of the output file. Smaller sources will be
        unaffected; larger sources will be scaled with their aspect ratio
        respected.
        """
        assert var == 'max_resolution'
        try:
            width, height = (int(i) for i in value.split('x', 1))
        except (TypeError, ValueError):
            raise CmdError(
                'The new resolution must be specified as WxH')
        else:
            if width < 32 or height < 32:
                raise CmdError('The new resolution is too small')
        self.config.width_max = width
        self.config.height_max = height

    def set_complete_max_resolution(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {
                '640x480',   # NTSC
                '768x576',   # PAL
                '854x480',   # NTSC DVD (anamorphic)
                '1024x576',  # PAL DVD (anamorphic)
                '1280x720',  # HD 720p
                '1920x1080', # "Full" HD 1080p
                '2560x1440', # 2K QHD
                '3840x2160', # 4K UHD
                '5120x2880', # 5K UHD
                '7680x4320', # 8K UHD
            })

    set_max_resolution.complete = set_complete_max_resolution

    def set_output_format(self, var, value):
        """
        This configuration option specifies the video output format. Valid
        values are "mp4" and "mkv". "mp4" is more widely supported, but "mkv"
        is the more advanced format, and is the only format to support things
        like PGS subtitle pass-through on Blu-ray.

        The output format affects the {ext} substitution in the template.
        """
        assert var == 'output_format'
        valid = ('mp4', 'mkv')
        if value not in valid:
            raise CmdError('The new output_format must be one of {}'.format(
                ', '.join(valid)))
        self.config.output_format = value

    def set_complete_output_format(self, text, line, start, finish):
        return self.set_complete_one(line, start, {'mp4', 'mkv'})

    set_output_format.complete = set_complete_output_format

    def set_api_key(self, var, value):
        assert var == 'api_key'
        if set(value) - set('0123456789abcdef'):
            raise CmdSyntaxError('API key contains non-hex digits')
        if len(value) not in (0, 32):
            raise CmdSyntaxError('API key must be blank or 32 hex-digits')
        self.config.api_key = value
        self.set_api()

    def set_api_url(self, var, value):
        assert var == 'api_url'
        self.config.api_url = value
        self.set_api()

    def set_api(self):
        if self.config.api_url and self.config.api_key:
            self.api = TVDB(self.config.api_key, self.config.api_url)
        else:
            self.api = None

    def do_duplicate(self, arg):
        """
        Manually specifies duplicated titles on a disc.

        Syntax: duplicate <title>[-<title>]

        The 'duplicate' command is used to override the duplicate setting on
        disc titles. Usually duplicate titles are automatically detected during
        'scan' based on identical title lengths. However, some discs have
        duplicate titles with different lengths. In this case, it is necessary
        to manually specify such duplicates.

        If a single title number is given, that title is marked as not being a
        duplicate. If a range of title numbers is given, then all titles in
        that range will be marked as being duplicates of each other (and titles
        immediately adjacent to the range which were formally marked as
        duplicates will be marked as not duplicating titles within the range).
        Examples:

        (tvrip) duplicate 5
        (tvrip) duplicate 1-3
        """
        arg = arg.strip()
        try:
            start, finish = self.parse_title_range(arg)
        except CmdError:
            start = finish = self.parse_title(arg)
        if start == finish:
            start.duplicate = 'no'
        else:
            start.duplicate = 'first'
            title = start.next
            while title != finish:
                title.duplicate = 'yes'
                title = title.next
            finish.duplicate = 'last'
        # Adjust adjacent tracks, if required
        if start.previous is not None:
            try:
                start.previous.duplicate = {
                    'yes':   'last',
                    'first': 'no',
                    }[start.previous.duplicate]
            except KeyError:
                pass
        if finish.next is not None:
            try:
                finish.next.duplicate = {
                    'yes':  'first',
                    'last': 'no',
                    }[finish.next.duplicate]
            except KeyError:
                pass

    def do_episode(self, arg):
        """
        Modifies a single episode in the current season.

        Syntax: episode <insert|update|delete> <number> [name]

        The 'episode' command is used to modify the details of a single episode
        in the current season. If the first parameter is "insert", then the
        episode will be inserted at the specified position, shifting any
        existing, and all subsequent episodes up (numerically). If the first
        parameter is "update", then the numbered episode is renamed. Finally,
        if the first parameter is "delete", then the numbered episode is
        removed, shifting all subsequent episodes down (numerically). In this
        case, name does not need to be specified.

        See also: season, episodes
        """
        if not self.config.season:
            raise CmdError('No season has been set')
        season = self.config.season
        try:
            (op, number) = arg.split(' ', 1)
        except (TypeError, ValueError):
            raise CmdSyntaxError(
                'You must specify an operation and an episode number')
        op = op.strip().lower()[:3]
        if op in ('ins', 'upd'):
            try:
                (_, number, name) = arg.split(' ', 2)
            except (TypeError, ValueError):
                raise CmdSyntaxError(
                    'You must specify an episode number and name for insert/update')
        elif op == 'del':
            name = ''
        else:
            raise CmdSyntaxError(
                'Episode operation must be one of insert/update/delete')
        try:
            number = int(number)
        except ValueError:
            raise CmdSyntaxError(
                '{} is not a valid episode number'.format(number))

        {
            'ins': self.insert_episode,
            'upd': self.update_episode,
            'del': self.delete_episode,
        }[op](season, number, name)

    def insert_episode(self, season, number, name):
        # Shift all later episodes along 1
        for episode in self.session.query(
                    Episode
                ).filter(
                    (Episode.season == season) &
                    (Episode.number >= number)
                ).order_by(
                    Episode.number.desc()
                ):
            episode.number += 1
            self.session.flush()
        episode = Episode(season, number, name)
        self.session.add(episode)
        self.pprint(
            'Inserted episode {episode} to season {season} '
            'of {program}'.format(
                episode=episode.number,
                season=episode.season.number,
                program=episode.season.program.name))

    def update_episode(self, season, number, name):
        episode = self.parse_episode(number)
        episode.name = name
        self.pprint(
            'Renamed episode {episode} of season {season} '
            'of {program}'.format(
                episode=episode.number,
                season=episode.season.number,
                program=episode.season.program.name))

    def delete_episode(self, season, number, name=None):
        # Shift all later episodes down 1
        episode = self.parse_episode(number)
        self.session.delete(episode)
        for episode in self.session.query(
                    Episode
                ).filter(
                    (Episode.season == season) &
                    (Episode.number > number)
                ).order_by(
                    Episode.number
                ):
            episode.number -= 1
            self.session.flush()
        self.pprint(
            'Deleted episode {episode} to season {season} '
            'of {program}'.format(
                episode=number,
                season=season.number,
                program=season.program.name))

    def do_episodes(self, arg):
        """
        Gets or sets the episodes for the current season.

        Syntax: episodes [number]

        The 'episodes' command can be used to list the episodes of the
        currently selected season of the program. If an argument is given, the
        current episode list is deleted and you will be prompted to enter
        names for the specified number of episodes.

        If you simply wish to change the name of a single episode, see the
        'episode' command instead.

        See also: season, episode
        """
        if not self.config.season:
            raise CmdError('No season has been set')
        if arg:
            try:
                count = int(arg)
            except ValueError:
                raise CmdSyntaxError(
                    '{} is not a valid episode count'.format(arg))
            if count < 1:
                raise CmdSyntaxError(
                    'A season must contain at least 1 or more '
                    'episodes ({} specified)'.format(count))
            elif count > 100:
                raise CmdSyntaxError(
                    '{} episodes in a single season? '
                    'I don\'t believe you...'.format(count))
            self.create_episodes(count)
            self.episode_map.clear()
        else:
            self.pprint_episodes()

    def create_episodes(self, count):
        "Creates the specified number of episodes in the current season"
        self.pprint('Please enter the names of the episodes. Leave a '
                    'name blank if you wish to terminate entry early:')
        self.clear_episodes()
        for number in range(1, count + 1):
            name = self.input('{:2d}: '.format(number))
            if not name:
                self.pprint('Terminating episode name entry')
                break
            episode = Episode(self.config.season, number, name)
            self.session.add(episode)

    def do_season(self, arg, program_id=None):
        """
        Sets which season of the program the disc contains.

        Syntax: season <number>

        The 'season' command specifies the season the disc contains episodes
        for. This number is used when constructing the filename of ripped
        episodes.

        This command is also used to expand the episode database. If the number
        given does not exist, it will be entered into the database under the
        current program and you will be prompted for episode names.

        See also: program, seasons
        """
        if not self.config.program:
            raise CmdError('You must specify a program first')
        try:
            arg = int(arg)
        except ValueError:
            raise CmdSyntaxError(
                'A season must be a valid number '
                '({} specified)'.format(arg))
        if arg < 0:
            raise CmdSyntaxError(
                'A season number must be 0 or higher '
                '({} specified)'.format(arg))
        self.config.season = self.session.query(Season).get(
            (self.config.program.name, arg))
        if self.config.season is None:
            try:
                new_season = self.find_season(arg)
            except CmdError:
                new_season = self.new_season(arg)
            self.config.season = new_season
        self.episode_map.clear()
        self.map_ripped()

    def complete_season(self, text, line, start, finish):
        "Auto-completer for season command"
        return [
            str(season.number) for season in
            self.session.query(
                    Season
                ).filter(
                    (Season.program == self.config.program) &
                    sa.sql.text(
                        "SUBSTR(CAST(seasons.number AS TEXT), 1, :length) = :season")
                ).params(
                    length=len(text),
                    season=text
                )
            ]

    def find_season(self, number):
        entry = self.find_program_entry(self.config.program.name)
        if not number in self.api.seasons(entry.id):
            raise CmdError('Season {} not found on TVDB'.format(number))
        new_season = Season(self.config.program, number)
        for episode, title in self.api.episodes(entry.id, number):
            self.session.add(Episode(new_season, episode, title))
        return new_season

    def new_season(self, number):
        new_season = Season(self.config.program, number)
        self.session.add(new_season)
        count = self.input_number(
            range(100),
            'Season {season} of program {program} is new. Please enter '
            'the number of episodes in this season (enter 0 if you do '
            'not wish to define episodes at this time)'
            ''.format(season=new_season.number,
                      program=self.config.program.name))
        self.config.season = new_season
        if count != 0:
            self.do_episodes(count)
        return new_season

    def do_seasons(self, arg=''):
        """
        Shows the defined seasons of the current program.

        Syntax: seasons

        The 'seasons' command outputs the list of seasons defined for the
        current program, along with a summary of how many episodes are defined
        for each season.

        See also: programs, season
        """
        self.no_args(arg)
        self.pprint_seasons()

    def do_program(self, arg):
        """
        Sets the name of the program.

        Syntax: program <name>

        The 'program' command specifies the program the disc contains episodes
        for. This is used when constructing the filename of ripped episodes.

        This command is also used to expand the episode database. If the name
        given does not exist, it will be entered into the database and you will
        be prompted for season and episode information.

        See also: episodes, programs
        """
        if not arg:
            raise CmdSyntaxError('You must specify a program name')
        new_program = self.session.query(Program).get((arg,))
        if new_program is None:
            try:
                new_program = self.find_program(arg)
            except CmdError:
                new_program = self.new_program(arg)
        # This is necessary to workaround a tricky transition; e.g. current
        # configuration is for season 3 of something but we're transitioning
        # to a program which doesn't have 3 seasons
        self.config.season = None
        self.config.program = new_program
        self.config.season = self.session.query(
                Season
            ).filter(
                Season.program == new_program,
                Season.number > 0
            ).order_by(
                Season.number
            ).first()
        self.episode_map.clear()
        self.map_ripped()

    program_re = re.compile(r'^program\s+')

    def complete_program(self, text, line, start, finish):
        "Auto-completer for program command"
        match = self.program_re.match(line)
        name = line[match.end():]
        return [
            program.name[start - match.end():] for program in
            self.session.query(Program).filter(Program.name.startswith(name))
            ]

    def find_program_entry(self, name):

        def format_overview(s):
            s = (s.splitlines() or [''])[0]
            if len(s) > 200:
                s = s[:197] + '...'
            return s

        if not self.api:
            raise CmdError('api_key or api_url not configured')
        self.pprint('Searching the TVDB for {}'.format(name))
        data = self.api.search(name)
        if not data:
            self.pprint('No results found for {}'.format(name))
            raise CmdError('no results found for {}'.format(name))
        self.pprint('Found the following matches on the TVDB:')
        self.pprint('')
        table = [('#', 'Title', 'Aired', 'Status', 'Overview')]
        for num, entry in enumerate(data, start=1):
            table.append((
                num,
                entry.title,
                str(entry.aired) if entry.aired else '-',
                entry.status,
                format_overview(entry.overview),
            ))
        self.pprint_table(table)
        self.pprint('')
        index = self.input_number(
            range(len(data) + 1),
            'Which entry matches the program you wish to rip (enter '
            '0 if you wish to enter program information manually)?')
        if index == 0:
            raise CmdError('user opted for manual entry')
        return data[index - 1]

    def find_program(self, name):
        entry = self.find_program_entry(name)
        new_program = Program(entry.title)
        self.session.add(new_program)
        for season in self.api.seasons(entry.id):
            self.pprint('Querying TVDB for season {}'.format(season))
            new_season = Season(new_program, season)
            self.session.add(new_season)
            for episode, title in self.api.episodes(entry.id, season):
                self.session.add(Episode(new_season, episode, title))
        return new_program

    def new_program(self, name):
        new_program = Program(name=name)
        self.session.add(new_program)
        count = self.input_number(
            range(100),
            'Program {} is new. How many seasons exist (enter 0 if you do '
            'not wish to define seasons and episodes at this time)?'
            ''.format(name))
        self.config.program = new_program
        self.config.season = None
        for number in range(1, count + 1):
            self.do_season(number)
        return new_program

    def do_programs(self, arg=''):
        """
        Shows the defined programs.

        Syntax: programs

        The 'programs' command outputs the list of programs defined in the
        database, along with a summary of how many seasons and episodes are
        defined for each.

        See also: program
        """
        self.no_args(arg)
        self.pprint_programs()

    def do_disc(self, arg=''):
        """
        Displays information about the last scanned disc.

        Syntax: disc

        The 'disc' command re-displays the top-level information that was
        discovered during the last 'scan' command. It shows the disc's
        identifier and serial number, along with a summary of title
        information.

        See also: scan, title
        """
        self.no_args(arg)
        self.pprint_disc()

    def do_title(self, arg):
        """
        Displays information about the specified title(s).

        Syntax: title <titles>

        The 'title' command displays detailed information about the specified
        titles including chapter starts and durations, audio tracks, and
        subtitle tracks.

        See also: scan, disc
        """
        if not arg:
            raise CmdSyntaxError('You must specify a title')
        for title in self.parse_title_list(arg):
            self.pprint_title(title)

    def do_play(self, arg):
        """
        Plays the specified episode.

        Syntax: play [title[.chapter]]

        The 'play' command plays the specified title (and optionally chapter)
        of the currently scanned disc. Note that a disc must be scanned before
        this command can be used. VLC will be started at the specified location
        and must be quit before the command prompt will return.

        See also: scan, disc
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        try:
            if not arg:
                self.disc.play(self.config)
            else:
                self.parse_title_or_chapter(arg).play(self.config)
        except proc.CalledProcessError as e:
            raise CmdError('VLC exited with code {}'.format(e.returncode))

    def do_scan(self, arg):
        """
        Scans the source device for episodes.

        Syntax: scan [titles]

        The 'scan' command scans the current source device to discover what
        titles, audio tracks, and subtitle tracks exist on the disc in the
        source device. Please note that scanning a disc erases the current
        episode mapping.

        See also: automap, rip
        """
        if not self.config.source:
            raise CmdError('No source has been specified')
        elif not (self.config.duration_min and self.config.duration_max):
            raise CmdError('No duration range has been specified')
        elif arg:
            titles = self.parse_number_list(arg)
        else:
            titles = None
        self.pprint('Scanning disc in {}'.format(self.config.source))
        self.episode_map.clear()
        try:
            self.disc = Disc(self.config, titles)
        except (IOError, proc.CalledProcessError) as exc:
            self.disc = None
            raise CmdError(exc)
        self.map_ripped()
        self.do_disc()

    def map_ripped(self):
        "Adds titles/chapters which were previously ripped to the episode map"
        if not self.disc:
            return
        # The rather complex filter below deals with the different methods of
        # identifying discs. In the first version of tvrip, disc serial number
        # was used but was found to be insufficient (manufacturers sometimes
        # repeat serial numbers or simply leave them blank), so a new mechanism
        # involving a hash of disc details was introduced.
        for episode in self.session.query(
                    Episode
                ).filter(
                    (Episode.season == self.config.season) &
                    (
                        (
                            (Episode.disc_id.startswith('$H1$')) &
                            (Episode.disc_id == self.disc.ident)
                        ) |
                        (
                            (~Episode.disc_id.startswith('$H1$')) &
                            (Episode.disc_id == self.disc.serial)
                        )
                    )
                ):
            try:
                title = [
                    t for t in self.disc.titles
                    if t.number == episode.disc_title
                    ][0]
            except IndexError:
                self.pprint(
                    'Warning: previously ripped title {title} not found '
                    'on the scanned disc (id {id})'.format(
                        title=episode.disc_title,
                        id=episode.disc_id))
            else:
                if episode.start_chapter is None:
                    self.episode_map[episode] = title
                else:
                    try:
                        start_chapter = [
                            c for c in title.chapters
                            if c.number == episode.start_chapter
                            ][0]
                        end_chapter = [
                            c for c in title.chapters
                            if c.number == episode.end_chapter
                            ][0]
                    except IndexError:
                        self.pprint(
                            'Warning: previously ripped chapters '
                            '{start_chapter}, {end_chapter} not '
                            'found in title {title} on the scanned disc '
                            '(id {id})'.format(
                                start_chapter=episode.start_chapter,
                                end_chapter=episode.end_chapter,
                                title=title.number,
                                id=episode.disc_id))
                    else:
                        self.episode_map[episode] = (start_chapter, end_chapter)

    def do_automap(self, arg):
        """
        Maps episodes to titles or chapter ranges automatically.

        Syntax: automap [episodes [titles]]

        The 'automap' command is used to have the application attempt to figure
        out which titles (or chapters of titles) contain the next set of
        unripped episodes. If no episode numbers are specified, or * is
        specified all unripped episodes are considered candidates. Otherwise,
        only those episodes specified are considered.

        If no title numbers are specified, all titles on the disc are
        considered candidates. Otherwise, only the titles specified are
        considered. If title mapping fails, chapter-based mapping is attempted
        instead.

        The current episode mapping can be viewed in the output of the 'map'
        command.

        See also: map, unmap
        """
        self.pprint('Performing auto-mapping')
        # Generate the list of titles, either specified or implied in the
        # arguments
        if ' ' in arg:
            episodes, titles = arg.split(' ', 1)
        elif arg:
            episodes = arg
            titles = '*'
        else:
            episodes = titles = '*'
        strict_mapping = episodes != '*'
        if strict_mapping:
            episodes = self.parse_episode_list(episodes)
        else:
            episodes = self.session.query(
                    Episode
                ).filter(
                    (Episode.season == self.config.season) &
                    (Episode.disc_id == None)
                ).order_by(
                    Episode.number
                ).all()
        if titles == '*':
            titles = [
                title for title in self.disc.titles
                if title not in self.episode_map.values()
            ]
        else:
            titles = self.parse_title_list(titles)
        self.map_ripped()
        # Re-filter episode and title list to exclude titles that map_ripped()
        # has dealt with
        episodes = [
            episode for episode in episodes
            if episode not in self.episode_map
        ]
        titles = [
            title for title in titles
            if title not in self.episode_map.values()
        ]
        # Filter out duplicate titles on the disc
        titles = [
            title for title in titles
            if title.duplicate == 'no' or
            self.config.duplicates == 'all' or
            self.config.duplicates == title.duplicate
        ]
        try:
            self.episode_map.automap(
                episodes, titles, self.config.duration_min,
                self.config.duration_max,
                strict_mapping=strict_mapping,
                choose_mapping=self.choose_mapping)
        except MapError as exc:
            raise CmdError(str(exc))
        self.do_map()

    def choose_mapping(self, mappings):
        self.pprint('{} possible chapter-based mappings found'.format(len(mappings)))
        # Iterate over the episodes and ask the user in each case whether the
        # first chapter is accurate by playing a clip with vlc
        for episode in list(mappings[0].keys()):
            chapters = set(mapping[episode][0] for mapping in mappings)
            self.pprint(
                'Episode {episode} has {count} potential starting '
                'chapters: {chapters}'.format(
                    episode=episode.number,
                    count=len(chapters),
                    chapters=','.join(
                        '{title}.{chapter:02d}'.format(
                            title=chapter.title.number, chapter=chapter.number)
                        for chapter in chapters)))
            while len(chapters) > 1:
                chapter = chapters.pop()
                while True:
                    chapter.play(self.config)
                    while True:
                        response = self.input(
                            'Is chapter {title}.{chapter:02d} the start of episode '
                            '{episode}? [y/n/r] '.format(
                                title=chapter.title.number,
                                chapter=chapter.number,
                                episode=episode.number))
                        response = response.lower()[:1]
                        if response in ('y', 'n', 'r'):
                            break
                        else:
                            self.pprint('Invalid response')
                    if response == 'y':
                        chapters = {chapter}
                        break
                    elif response == 'n':
                        break
            assert len(chapters) == 1
            chapter = chapters.pop()
            mappings = [
                mapping for mapping in mappings
                if mapping[episode][0] == chapter
            ]
        assert len(mappings) == 1
        return mappings[0]

    def do_map(self, arg=''):
        """
        Maps episodes to titles or chapter ranges.

        Syntax: map [episode title[.start[-end]]]

        The 'map' command is used to define which title on the disc contains
        the specified episode. This is used when constructing the filename of
        ripped episodes. Note that multiple episodes can be mapped to a single
        title, to deal with multi-part episodes being encoded as a single
        title.

        For example:

        (tvrip) map 3 1
        (tvrip) map 7 4
        (tvrip) map 5 2.1-12

        If no arguments are specified, the current episode map will be
        displayed.

        See also: automap, unmap
        """
        if arg:
            self.set_map(arg)
        else:
            self.get_map()

    def set_map(self, arg):
        try:
            episode, target = arg.split(' ')
        except ValueError:
            raise CmdSyntaxError('You must specify two arguments')
        episode = self.parse_episode(episode)
        target = self.parse_title_or_chapter_range(target)
        if isinstance(target, Title):
            target_label = 'title {title.number} (duration {title.duration})'.format(
                title=target)
        else:
            start, end = target
            if start.title == end.title:
                index = (
                    '{start.title.number}.{start.number:02d}-'
                    '{end.number:02d}'.format(
                        start=start, end=end))
            else:
                index = (
                    '{start.title.number}.{start.number:02d}-'
                    '{end.title.number}.{end.number:02d}'.format(
                        start=start, end=end))
            target_label = 'chapters {index} (duration {duration})'.format(
                index=index,
                duration=sum((
                    chapter.duration
                    for title in start.title.disc.titles
                    for chapter in title.chapters
                    if (
                        (start.title.number, start.number) <=
                        (title.number, chapter.number) <=
                        (end.title.number, end.number))
                    ), timedelta()))
        self.pprint(
            'Mapping {target_label} to {episode.number} "{episode.name}"'.format(
                episode=episode, target_label=target_label))
        self.episode_map[episode] = target

    def get_map(self):
        if self.config.program is None:
            raise CmdError('No program has been set')
        if self.config.season is None:
            raise CmdError('No season has been set')
        program = self.config.program
        season = self.config.season
        self.pprint('Episode Mapping for {} season {}:'.format(
            program.name, season.number))
        self.pprint('')
        if self.episode_map:
            table = [('Title', 'Duration', 'Ripped', 'Episode', 'Name')]
            for episode, mapping in self.episode_map.items():
                if isinstance(mapping, Title):
                    index = '{}'.format(mapping.number)
                    duration = mapping.duration
                else:
                    start, end = mapping
                    if start.title == end.title:
                        index = (
                            '{title}.{start:02d}-{end:02d}'.format(
                                title=start.title.number,
                                start=start.number,
                                end=end.number
                            )
                        )
                    else:
                        index = (
                            '{st}.{sc:02d}-{et}.{ec:02d}'.format(
                                st=start.title.number,
                                sc=start.number,
                                et=end.title.number,
                                ec=end.number
                            )
                        )
                    duration = sum((
                        chapter.duration
                        for title in start.title.disc.titles
                        for chapter in title.chapters
                        if (
                            (start.title.number, start.number) <=
                            (title.number, chapter.number) <=
                            (end.title.number, end.number))
                        ), timedelta())
                table.append(
                    (index, duration, '✓' if episode.ripped else '',
                     episode.number, episode.name))
            self.pprint_table(table)
        else:
            self.pprint('Episode map is currently empty')

    def do_unmap(self, arg):
        """
        Removes an episode mapping.

        Syntax: unmap <episodes>

        The 'unmap' command is used to remove a title to episode mapping. For
        example, if the auto-mapping when scanning a disc makes an error, you
        can use the 'map' and 'unmap' commands to fix it. You can also specify
        '*' to clear the mapping list completely. For example:

        (tvrip) unmap 3
        (tvrip) unmap 7
        (tvrip) unmap *

        See also: map, automap
        """
        if not arg:
            raise CmdSyntaxError(
                'You must specify a list of episodes to remove from the mapping')
        episodes = arg
        if episodes == '*':
            episodes = list(self.episode_map.keys())
        else:
            episodes = self.parse_episode_list(episodes)
        for episode in episodes:
            self.pprint(
                'Removing mapping for episode {episode.number}, '
                '{episode.name}'.format(episode=episode))
            try:
                del self.episode_map[episode]
            except KeyError:
                self.pprint(
                    'Episode {episode.number}, {episode.name} was not in the '
                    'map'.format(episode=episode))

    def do_rip(self, arg=''):
        """
        Starts the ripping and transcoding process.

        Syntax: rip [episodes]

        The 'rip' command begins ripping the mapped titles from the current
        source device, converting them according to the current preferences,
        and storing the results in the target path. Only previously unripped
        episodes will be ripped. If you wish to re-rip an episode, use the
        'unrip' command to set it to unripped first.

        You can specify a list of episodes to rip only a subset of the map.
        This is useful to adjust ripping configurations between episodes. Note
        that already ripped episodes will not be re-ripped even if manually
        specified. Use 'unrip' first.

        If no episodes are specified, all unripped episodes in the map will be
        ripped. Examples:

        (tvrip) rip
        (tvrip) rip 8,11-15

        See also: unrip, map, automap
        """
        if not self.episode_map:
            raise CmdError('No titles have been mapped to episodes')
        arg = arg.strip()
        if arg:
            episodes = self.parse_episode_list(arg, must_exist=False)
        else:
            episodes = self.episode_map.keys()
        for episode in episodes:
            if not episode.ripped:
                self._rip_episode(episode)

    def _rip_episode(self, episode):
        mapping = self.episode_map[episode]
        if isinstance(mapping, Title):
            chapter_start = chapter_end = None
            title = mapping
            episodes = [e for e, t in self.episode_map.items() if t is title]
        else:
            chapter_start, chapter_end = mapping
            assert chapter_start.title is chapter_end.title
            title = chapter_start.title
            episodes = [episode]
        audio_tracks = [
            t for t in title.audio_tracks
            if self.config.in_audio_langs(t.language)
            ]
        if not self.config.audio_all:
            audio_tracks = [t for t in audio_tracks if t.best]
        subtitle_tracks = [
            t for t in title.subtitle_tracks
            if self.config.in_subtitle_langs(t.language) and (
                t.format == self.config.subtitle_format or
                self.config.subtitle_format == 'any'
            )
        ]
        if not self.config.subtitle_all:
            subtitle_tracks = [t for t in subtitle_tracks if t.best]
        if len(episodes) == 1:
            self.pprint(
                'Ripping episode {episode.number}, '
                '"{episode.name}"'.format(episode=episode)
            )
        else:
            self.pprint(
                'Ripping episodes {numbers}, {title}'.format(
                    numbers=' '.join(str(e.number) for e in episodes),
                    title=multipart.name(episodes)
                )
            )
        try:
            self.disc.rip(self.config, episodes, title, audio_tracks,
                          subtitle_tracks, chapter_start, chapter_end)
        except proc.CalledProcessError as e:
            raise CmdError('process failed with code {}'.format(e.returncode))

    def do_unrip(self, arg):
        """
        Changes the status of the specified episode to unripped.

        Syntax: unrip <episodes>

        The 'unrip' command is used to set the status of an episode or episodes
        to unripped. Episodes may be specified as a range (1-5) or as a comma
        separated list (4,2,1) or some combination (1,3-5), or '*' to indicate
        all episodes in the currently selected season.

        Episodes are automatically set to ripped during the operation of the
        'rip' command.  Episodes marked as ripped will be automatically mapped
        to titles by the 'map' command when the disc they were ripped from is
        scanned (they can be mapped manually too). For example:

        (tvrip) unrip 3
        (tvrip) unrip 7

        See also: rip, map
        """
        if not arg:
            raise CmdSyntaxError(
                'You must specify a list of episodes to mark as unripped')
        episodes = arg
        if episodes == '*':
            episodes = self.session.query(
                    Episode
                ).filter(
                    (Episode.season == self.config.season) &
                    (Episode.disc_id != None)
                )
        else:
            episodes = self.parse_episode_list(episodes, must_exist=False)
        for episode in episodes:
            if episode:
                episode.disc_id = None
                episode.disc_title = None
                episode.start_chapter = None
                episode.end_chapter = None

