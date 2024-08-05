# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2012-2014 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"Implements the command line processor for the tvrip application"

import os
import re
import subprocess as proc
from pathlib import Path
from datetime import timedelta, datetime
from importlib import resources

import requests
import sqlalchemy as sa
from rich import box
from rich.table import Table, Column

from .richrst import RestructuredText
from .ripper import Disc, Title
from .episodemap import EpisodeMap, MapError
from .cmdline import Cmd, CmdError, CmdSyntaxError
from .const import DATADIR
from .tvdb import TVDBv3, TVDBv4
from . import multipart


class RipCmd(Cmd):
    "Implementation of the TVRip command line"

    prompt = '[green](tvrip)[/green] '

    def __init__(self, db, *, stdin=None, stdout=None):
        super().__init__(stdin=stdin, stdout=stdout)
        self.discs = {}
        self.episode_map = EpisodeMap()
        self.db = db
        db_version = self.db.get_version()
        if self.db.get_version() < self.db.latest_version:
            self.console.print(
                f'Migrating database from version {db_version} to '
                f'{self.db.latest_version}')
            self.db.migrate()
        # Specify the history filename
        self.history_file = os.path.join(DATADIR, 'tvrip.history')
        # Read the configuration from the database
        with self.db.transaction():
            self.config = self.db.get_config()
        self.get_api()
        self.config_handlers = {
            'api':              self.set_api,
            'api_key':          self.set_api_key,
            'atomicparsley':    self.set_executable,
            'audio_all':        self.set_bool,
            'audio_encoding':   self.set_audio_encoding,
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

    def get_api(self):
        try:
            self.api = {
                'tvdb3': TVDBv3,
                'tvdb4': TVDBv4,
            }[self.config.api](self.config.api_key)
        except (KeyError, ValueError):
            self.api = None

    def cmdcontext(self):
        # Add a transaction to the context stack to ensure that everything a
        # command does is rolled back in the event of error
        stack = super().cmdcontext()
        stack.enter_context(self.db.transaction())
        return stack

    def _get_disc(self):
        "Returns the Disc object for the current source"
        return self.discs.get(self.config.source, None)

    def _set_disc(self, value):
        "Set the Disc object for the current source"
        assert self.config.source
        if self.config.source in self.discs:
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
        if self.config.program is None:
            raise CmdError('No program has been set')
        elif self.config.season is None:
            raise CmdError('No season has been set')
        try:
            episode = int(episode)
        except ValueError:
            raise CmdSyntaxError(
                f'Expected episode number but found "{episode}"')
        if episode < 1:
            raise CmdError(f'Episode number {episode} is less than one')
        result = self.db.get_episode(episode)
        if result is None and must_exist:
            raise CmdError(
                f'There is no episode {episode} in season '
                f'{self.config.season} of {self.config.program}')
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
            raise CmdSyntaxError(f'Expected title number but found "{title}"')
        if not 1 <= title <= 99:
            raise CmdError(f'Title number {title} is not between 1 and 99')
        try:
            return [t for t in self.disc.titles if t.number == title][0]
        except IndexError:
            raise CmdError(f'There is no title {title} on the scanned disc')

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
                f'Expected chapter number but found "{chapter}"')
        try:
            return [c for c in title.chapters if c.number == chapter][0]
        except IndexError:
            raise CmdError(
                f'There is no chapter {chapter} within title {title.number}')

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

    def print_disc(self):
        "Prints the details of the currently scanned disc"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        table = Table(box=box.ROUNDED)
        table.add_column('Title', no_wrap=True)
        table.add_column('Chapters', no_wrap=True, justify='right')
        table.add_column('Duration', no_wrap=True, justify='right')
        table.add_column('Dup', no_wrap=True)
        table.add_column('Audio')
        for title in self.disc.titles:
            table.add_row(
                str(title.number),
                str(len(title.chapters)),
                str(title.duration),
                {'first': '━┓', 'yes': ' ┃', 'last': '━┛', 'no': ''}[title.duplicate],
                ' '.join(track.language for track in title.audio_tracks)
                )
        self.console.print(
            f'[green]Disc type:[/green] {self.disc.type}',
            f'[green]Disc identifier:[/green] {self.disc.ident}',
            f'[green]Disc serial:[/green] {self.disc.serial}',
            f'[green]Disc name:[/green] {self.disc.name}',
            f'Disc has {len(self.disc.titles)} titles',
            '', table,
            sep='\n')

    def print_title(self, title):
        "Prints the details of the specified disc title"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        info = (
            f'Title {title.number}, duration: {title.duration}, '
            f'duplicate: {title.duplicate}')
        chapters_tbl = Table(box=box.ROUNDED)
        chapters_tbl.add_column('Chapter', no_wrap=True)
        chapters_tbl.add_column('Start', no_wrap=True, justify='right')
        chapters_tbl.add_column('Finish', no_wrap=True, justify='right')
        chapters_tbl.add_column('Duration', no_wrap=True, justify='right')
        for chapter in title.chapters:
            chapters_tbl.add_row(
                str(chapter.number),
                str(chapter.start),
                str(chapter.finish),
                str(chapter.duration),
                )
        audio_tbl = Table(box=box.ROUNDED)
        audio_tbl.add_column('Audio', no_wrap=True)
        audio_tbl.add_column('Lang', no_wrap=True)
        audio_tbl.add_column('Name')
        audio_tbl.add_column('Encoding', no_wrap=True)
        audio_tbl.add_column('Mix', no_wrap=True)
        audio_tbl.add_column('Best', no_wrap=True, justify='center')
        for track in title.audio_tracks:
            suffix = ''
            if track.best and track.language in self.config.audio_langs:
                suffix = '✓'
            audio_tbl.add_row(
                str(track.number),
                track.language,
                track.name,
                track.encoding,
                track.channel_mix,
                suffix
                )
        subtitle_tbl = Table(box=box.ROUNDED)
        subtitle_tbl.add_column('Subtitle', no_wrap=True)
        subtitle_tbl.add_column('Lang', no_wrap=True)
        subtitle_tbl.add_column('Name')
        subtitle_tbl.add_column('Format', no_wrap=True)
        subtitle_tbl.add_column('Best', no_wrap=True, justify='center')
        for track in title.subtitle_tracks:
            suffix = ''
            if track.best and track.language in self.config.subtitle_langs:
                suffix = '✓'
            subtitle_tbl.add_row(
                str(track.number),
                track.language,
                track.name,
                track.format,
                suffix
                )
        self.console.print(
            info, '', chapters_tbl, '', audio_tbl, '', subtitle_tbl,
            sep='\n')

    def print_programs(self):
        "Prints the defined programs"
        table = Table(box=box.ROUNDED)
        table.add_column('Program')
        table.add_column('Seasons', no_wrap=True, justify='right')
        table.add_column('Episodes', no_wrap=True, justify='right')
        table.add_column('Ripped', no_wrap=True, justify='right')
        for (program, seasons, episodes, ripped) in self.db.get_programs():
            table.add_row(
                program,
                str(seasons),
                str(episodes),
                f'{ripped * 100 / episodes:5.1f}%' if episodes else '-'
            )
        self.console.print(table)

    def print_seasons(self):
        "Prints the seasons of the specified program"
        if self.config.program is None:
            raise CmdError('No program has been set')
        table = Table(box=box.ROUNDED)
        table.add_column('Num', no_wrap=True)
        table.add_column('Episodes', no_wrap=True, justify='right')
        table.add_column('Ripped', no_wrap=True, justify='right')
        for (season, episodes, ripped) in self.db.get_seasons():
            table.add_row(
                str(season),
                str(episodes),
                f'{ripped * 100 / episodes:5.1f}%' if episodes else '-'
            )
        self.console.print(
            f'Seasons for program {self.config.program}', '', table,
            sep='\n')

    def print_episodes(self):
        "Prints the episodes of the specified season"
        if self.config.program is None:
            raise CmdError('No program has been set')
        if self.config.season is None:
            raise CmdError('No season has been set')
        table = Table(box=box.ROUNDED)
        table.add_column('Num', no_wrap=True)
        table.add_column('Title')
        table.add_column('Ripped', no_wrap=True, justify='center')
        for episode in self.db.get_episodes():
            table.add_row(
                str(episode.episode),
                episode.title,
                '✓' if episode.disc_id is not None else '',
            )
        self.console.print(
            f'Episodes for season {self.config.season} of program '
            f'{self.config.program}', '', table,
            sep='\n')

    def do_config(self, arg=''):
        "Shows the current set of configuration options"
        self.no_args(arg)

        bool_str = ('off', 'on')
        table = Table(box=box.ROUNDED)
        table.add_column('Setting', no_wrap=True)
        table.add_column('Value')

        for index, (key, path) in enumerate(sorted(self.config.paths.items())):
            last_row = index == len(self.config.paths) - 1
            table.add_row(key, str(path), end_section=last_row)
        table.add_row('source', str(self.config.source))
        table.add_row(
            'duration',
            f'{self.config.duration[0].total_seconds() // 60}-'
            f'{self.config.duration[1].total_seconds() // 60} (mins)')
        table.add_row('duplicates', self.config.duplicates, end_section=True)
        table.add_row('target', str(self.config.target))
        table.add_row('temp', str(self.config.temp))
        table.add_row('template', self.config.template)
        table.add_row('id_template', self.config.id_template)
        table.add_row('output_format', self.config.output_format)
        table.add_row(
            'max_resolution',
            f'{self.config.max_resolution[0]}x{self.config.max_resolution[1]}')
        table.add_row('decomb', self.config.decomb)
        table.add_row('audio_mix', self.config.audio_mix)
        table.add_row('audio_all', bool_str[self.config.audio_all])
        table.add_row('audio_encoding', self.config.audio_encoding)
        table.add_row('audio_langs', ' '.join(self.config.audio_langs))
        table.add_row('subtitle_format', self.config.subtitle_format)
        table.add_row('subtitle_all', bool_str[self.config.subtitle_all])
        table.add_row('subtitle_default', bool_str[self.config.subtitle_default])
        table.add_row('subtitle_langs', ' '.join(self.config.subtitle_langs))
        table.add_row('video_style', self.config.video_style)
        table.add_row('dvdnav', bool_str[self.config.dvdnav])
        table.add_row('api', self.config.api)
        table.add_row('api_key', self.config.api_key)

        self.console.print(table)

    def do_set(self, arg):
        "Sets a configuration option"
        try:
            (var, value) = arg.split(' ', 1)
        except (TypeError, ValueError):
            raise CmdSyntaxError('You must specify a variable and a value')
        var = var.strip().lower()
        value = value.strip()
        try:
            var, value = self.config_handlers[var](var, value)
        except KeyError:
            raise CmdSyntaxError(f'Invalid configuration variable: {var}')
        else:
            self.config = self.db.set_config(self.config._replace(
                **{var: value}))
            if var in ('api', 'api_key'):
                self.get_api()

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
        configuration setting
        """
        try:
            super().do_help(arg)
        except CmdError as exc:
            if arg not in self.config_handlers:
                raise
            with resources.files('tvrip') as root:
                source = RestructuredText.from_path(
                    root / 'docs' / f'var_{arg}.rst')
                self.console.print(source)

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
        Sets the path of an executable, e.g. "/usr/bin/vlc".
        """
        value = Path(value).expanduser()
        if not value.exists():
            raise CmdError(f'Path {value} does not exist')
        if not os.access(str(value), os.X_OK, effective_ids=True):
            raise CmdError(f'Path {value} is not executable')
        paths = self.config.paths.copy()
        paths[var] = value
        return 'paths', paths

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
            raise CmdError(f'Path {value} does not exist')
        if not value.is_dir():
            raise CmdError(f'Path {value} is not a directory')
        return var, value

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
            raise CmdError(f'Path {value} does not exist')
        if not value.is_block_device():
            raise CmdError(f'Path {value} is not a block device')
        return var, value

    def set_complete_device(self, text, line, start, finish):
        return list(self.set_complete_path(line, start, is_block_device=True))

    set_device.complete = set_complete_device

    def set_bool(self, var, value):
        """
        This configuration option is either "on" or "off".
        """
        try:
            return var, self.parse_bool(value)
        except ValueError:
            raise CmdError(f'Value {value} must be on/off/no/yes')

    def set_complete_bool(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {'false', 'true', 'off', 'on', 'no', 'yes'})

    set_bool.complete = set_complete_bool

    def set_duplicates(self, var, value):
        """
        Specifies whether "all", "first", or the "last" of duplicate titles
        should be mapped for ripping.
        """
        assert var == 'duplicates'
        if value in ('all', 'first', 'last'):
            return var, value
        else:
            raise CmdSyntaxError(
                f'"{value}" is not a valid option for duplicates')

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
        return var, tuple(
            timedelta(minutes=i) for i in self.parse_number_range(value))

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
            raise CmdSyntaxError(f'Invalid video style {value}')
        else:
            return var, value

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
        value = set(value.lower().split(' '))
        for lang in value:
            if not re.match(r'[a-z]{3}$', lang):
                raise CmdSyntaxError(
                    f'"{lang}" is not a valid option for {var}')
        # Convert back to a list because JSON can't handle sets
        return var, list(value)

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
                '5.1':      'dpl2',
                }[value]
        except KeyError:
            raise CmdSyntaxError(f'Invalid audio mix {value}')
        else:
            return var, value

    def set_complete_audio_mix(self, text, line, start, finish):
        return self.set_complete_one(
            line, start,
            {'mono', 'stereo', 'dpl1', 'dpl2', 'surround', 'prologic'})

    set_audio_mix.complete = set_complete_audio_mix

    def set_audio_encoding(self, var, value):
        """
        This configuration option specifies the audio encoder. Validd values
        are "av_aac", "fdk_aac", "fdk_haac", "mp3", "vorbis", "opus", "flac16",
        "flac24", "ac3", and "eac3"
        """
        assert var == 'audio_encoding'
        try:
            value = {
                'av-aac':   'av_aac',
                'av_aac':   'av_aac',
                'fdk-aac':  'fdk_aac',
                'fdk_aac':  'fdk_aac',
                'fdk-haac': 'fdk_haac',
                'fdk_haac': 'fdk_haac',
                'mp3':      'mp3',
                'lame':     'mp3',
                'vorbis':   'vorbis',
                'opus':     'opus',
                'flac':     'flac16',
                'flac16':   'flac16',
                'flac24':   'flac24',
                'ac3':      'ac3',
                'eac3':     'eac3',
            }[value]
        except KeyError:
            raise CmdSyntaxError(f'Invalid audio encoding {value}')
        else:
            return var, value

    def set_complete_audio_encoding(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {
                'av-aac', 'av_aac', 'fdk-aac', 'fdk_aac', 'fdk-haac',
                'fdk_haac', 'mp3', 'lame', 'vorbis', 'opus', 'flac', 'flac16',
                'flac24', 'ac3', 'eac3'})

    set_audio_encoding.complete = set_complete_audio_encoding

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
            raise CmdSyntaxError(f'Invalid subtitle extraction mode {value}')
        else:
            return var, value

    def set_complete_subtitle_format(self, text, line, start, finish):
        return self.set_complete_one(
            line, start,
            {'off', 'none', 'vobsub', 'pgs', 'bitmap', 'cc', 'text', 'all',
             'both'})

    set_subtitle_format.complete = set_complete_subtitle_format

    def set_decomb(self, var, value):
        """
        Set decomb mode to "off", "on", or "auto".
        """
        assert var == 'decomb'
        try:
            value = ['off', 'on'][self.parse_bool(value)]
        except ValueError:
            if value != 'auto':
                raise CmdError(f'{value} must be off/on/auto')
        return var, value

    def set_complete_decomb(self, text, line, start, finish):
        return self.set_complete_one(
            line, start, {'false', 'true', 'off', 'on', 'no', 'yes', 'auto'})

    set_decomb.complete = set_complete_decomb

    def set_template(self, var, value):
        assert var == 'template'
        try:
            value.format(
                program='Program Name',
                season=1,
                id='1x01',
                name='Foo Bar',
                now=datetime.now(),
                ext='mp4',
                )
        except KeyError as exc:
            raise CmdError(
                f'The template contains an invalid substitution key: {exc}')
        except ValueError as exc:
            raise CmdError(f'The template contains an error: {exc}')
        return var, value

    def set_id_template(self, var, value):
        assert var == 'id_template'
        try:
            value.format(
                season=1,
                episode=10,
                )
        except KeyError as exc:
            raise CmdError(
                f'The id_template contains an invalid substitution key: {exc}')
        except ValueError as exc:
            raise CmdError(
                f'The id_template contains an error: {exc}')
        return var, value

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
                'The new resolution must be specified as WIDTHxHEIGHT')
        else:
            if width < 32 or height < 32:
                raise CmdError('The new resolution is too small')
        return var, (width, height)

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
            raise CmdError(
                f'The new output_format must be one of {", ".join(valid)}')
        return var, value

    def set_complete_output_format(self, text, line, start, finish):
        return self.set_complete_one(line, start, {'mp4', 'mkv'})

    set_output_format.complete = set_complete_output_format

    def set_api_key(self, var, value):
        "Sets the API key for use with TVDB"
        assert var == 'api_key'
        if value == '-':
            value = ''
        if set(value) - set('0123456789abcdef'):
            raise CmdSyntaxError('API key contains non-hex digits')
        if len(value) not in (0, 32):
            raise CmdSyntaxError('API key must be blank or 32 hex-digits')
        return var, value

    def set_api(self, var, value):
        "Selects the API to use when looking up episodes"
        assert var == 'api'
        try:
            value = {
                'tvdb3':  'tvdb3',
                'tvdbv3': 'tvdb3',
                'tvdb':   'tvdb4',
                'tvdb4':  'tvdb4',
                'tvdbv4': 'tvdb4',
            }[value.strip().lower()]
        except KeyError:
            raise CmdSyntaxError('{value} is not a valid API')
        # TODO: Check if endpoint can be reached?
        return var, value

    def do_duplicate(self, arg):
        "Manually specifies duplicated titles on a disc"
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
        "Modifies a single episode in the current season"
        if self.config.season is None:
            raise CmdError('No season has been set')
        try:
            (op, episode) = arg.split(' ', 1)
        except (TypeError, ValueError):
            raise CmdSyntaxError(
                'You must specify an operation and an episode number')
        op = op.strip().lower()[:3]
        if op in ('ins', 'upd'):
            try:
                (_, episode, title) = arg.split(' ', 2)
            except (TypeError, ValueError):
                raise CmdSyntaxError(
                    'You must specify an episode number and name for '
                    'insert/update')
        elif op == 'del':
            title = ''
        else:
            raise CmdSyntaxError(
                'Episode operation must be one of insert/update/delete')
        try:
            episode = int(episode)
        except ValueError:
            raise CmdSyntaxError(f'{episode} is not a valid episode number')

        {
            'ins': self.insert_episode,
            'upd': self.update_episode,
            'del': self.delete_episode,
        }[op](episode, title)

    def insert_episode(self, episode, title):
        self.db.insert_episode(episode, title)
        self.console.print(
            f'Inserted episode {episode} to season {self.config.season} of '
            f'{self.config.program}')

    def update_episode(self, episode, title):
        self.parse_episode(episode)
        self.db.update_episode(episode, title)
        self.console.print(
            f'Renamed episode {episode} of season {self.config.season} of '
            f'{self.config.program}')

    def delete_episode(self, episode, title=None):
        self.parse_episode(episode)
        self.db.delete_episode(episode)
        self.console.print(
            f'Deleted episode {episode} of season {self.config.season} of '
            f'{self.config.program}')

    def do_episodes(self, arg):
        "Gets or sets the episodes for the current season"
        if self.config.season is None:
            raise CmdError('No season has been set')
        if arg:
            try:
                count = int(arg)
            except ValueError:
                raise CmdSyntaxError(f'{arg} is not a valid episode count')
            if count < 1:
                raise CmdSyntaxError(
                    f'A season must contain at least 1 or more '
                    f'episodes ({count} specified)')
            elif count > 100:
                raise CmdSyntaxError(
                    f'{count} episodes in a single season? '
                    f"I don't believe you...")
            self.create_episodes(count)
            self.episode_map.clear()
        else:
            self.print_episodes()

    def create_episodes(self, count):
        "Creates the specified number of episodes in the current season"
        self.console.print(
            'Please enter the titles of the episodes. Leave a title blank if '
            'you wish to terminate entry early:')
        titles = []
        for episode in range(1, count + 1):
            title = self.input(f'{episode:2d}: ')
            if title:
                titles.append(title)
            else:
                self.console.print('Terminating episode title entry')
                break
        self.db.clear_episodes()
        for episode, title in enumerate(titles, start=1):
            self.db.add_episode(episode, title)

    def do_season(self, arg):
        "Sets which season of the program the disc contains"
        if self.config.program is None:
            raise CmdError('You must specify a program first')
        try:
            arg = int(arg)
        except ValueError:
            raise CmdSyntaxError(
                f'A season must be a valid number ({arg} specified)')
        if arg < 0:
            raise CmdSyntaxError(
                f'A season number must be 0 or higher ({arg} specified)')
        new_season = self.db.get_season(arg)
        if new_season is None:
            try:
                self.find_season(arg)
            except CmdError:
                self.new_season(arg)
        else:
            self.config = self.db.set_config(self.config._replace(
                season=new_season))
        self.episode_map.clear()
        self.map_ripped()

    def complete_season(self, text, line, start, finish):
        "Auto-completer for season command"
        with self.db.transaction():
            return [
                str(season.season)
                for season in self.db.get_seasons()
                if str(season.season).startswith(text)
            ]

    def find_season(self, season):
        entry = self.find_program_entry(self.config.program)
        if not season in self.api.seasons(entry.id):
            raise CmdError(f'Season {season} not found on TVDB')
        self.db.add_season(season)
        self.config = self.db.set_config(self.config._replace(season=season))
        for episode, title in self.api.episodes(entry.id, season):
            self.db.add_episode(episode, title)

    def new_season(self, season):
        count = self.input_number(
            range(100),
            f'Season {season} of program {self.config.program} is new. '
            f'Please enter the number of episodes in this season (enter 0 if '
            f'you do not wish to define episodes at this time)')
        self.db.add_season(season)
        self.config = self.db.set_config(self.config._replace(season=season))
        if count != 0:
            self.do_episodes(count)

    def do_seasons(self, arg=''):
        "Shows the defined seasons of the current program"
        self.no_args(arg)
        self.print_seasons()

    def do_program(self, arg):
        "Sets the name of the program"
        if not arg:
            raise CmdSyntaxError('You must specify a program name')
        new_program = self.db.get_program(arg)
        if new_program is None:
            try:
                self.find_program(arg)
            except CmdError:
                self.new_program(arg)
            first_season = self.db.get_first_season(arg)
            self.config = self.db.set_config(self.config._replace(
                season=first_season))
        else:
            # TODO This should be get_first_unripped
            first_season = self.db.get_first_season(new_program)
            self.config = self.db.set_config(self.config._replace(
                program=new_program, season=first_season))
        self.episode_map.clear()
        self.map_ripped()

    program_re = re.compile(r'^program\s+')

    def complete_program(self, text, line, start, finish):
        "Auto-completer for program command"
        #import sys
        #print(repr(text), repr(line), start, finish, file=sys.stderr, flush=True)
        matched = self.program_re.match(line)
        name = line[matched.end():]
        with self.db.transaction():
            return [
                program.program[start - matched.end():]
                for program in self.db.get_programs()
                if program.program.startswith(name)
            ]

    def find_program_entry(self, program):

        def format_overview(s):
            s = (s.splitlines() or [''])[0]
            if len(s) > 200:
                s = s[:199] + '…'
            return s

        if not self.api:
            raise CmdError('api_key or api_url not configured')
        self.console.print(f'Searching the TVDB for {program}')
        data = self.api.search(program)
        if not data:
            raise CmdError(f'no results found for {program}')
        table = Table(box=box.ROUNDED)
        table.add_column('#', no_wrap=True)
        table.add_column('Title')
        table.add_column('Aired', no_wrap=True)
        table.add_column('Status', no_wrap=True)
        table.add_column('Overview')
        for num, entry in enumerate(data, start=1):
            table.add_row(
                str(num),
                entry.title,
                f'{entry.aired:%Y-%m-%d}' if entry.aired else '-',
                entry.status,
                format_overview(entry.overview),
            )
        self.console.print(
            'Found the following matches on the TVDB:', '', table,
            sep='\n')
        index = self.input_number(
            range(len(data) + 1),
            'Which entry matches the program you wish to rip (enter '
            '0 if you wish to enter program information manually)?')
        if index == 0:
            raise CmdError('user opted for manual entry')
        return data[index - 1]

    def find_program(self, program):
        entry = self.find_program_entry(program)
        self.db.add_program(program)
        self.config = self.db.set_config(self.config._replace(
            program=program, season=None))
        for season in self.api.seasons(entry.id):
            self.console.print(f'Querying TVDB for season {season}')
            self.db.add_season(season)
            self.config = self.db.set_config(self.config._replace(
                season=season))
            for episode, title in self.api.episodes(entry.id, season):
                self.db.add_episode(episode, title)

    def new_program(self, program):
        count = self.input_number(
            range(100),
            f'Program {program} is new. How many seasons exist (enter 0 if '
            f'you do not wish to define seasons and episodes at this time)?')
        self.db.add_program(program)
        self.config = self.db.set_config(self.config._replace(
            program=program, season=None))
        for season in range(1, count + 1):
            self.do_season(season)

    def do_programs(self, arg=''):
        "Shows the defined programs"
        self.no_args(arg)
        self.print_programs()

    def do_disc(self, arg=''):
        "Displays information about the last scanned disc"
        self.no_args(arg)
        self.print_disc()

    def do_title(self, arg):
        "Displays information about the specified title(s)"
        if not arg:
            raise CmdSyntaxError('You must specify a title')
        for title in self.parse_title_list(arg):
            self.print_title(title)

    def do_play(self, arg):
        "Plays the specified episode"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        try:
            if not arg:
                self.disc.play(self.config)
            else:
                self.parse_title_or_chapter(arg).play(self.config)
        except proc.CalledProcessError as exc:
            raise CmdError(f'VLC exited with code {exc.returncode}')

    def do_scan(self, arg):
        "Scans the source device for episodes"
        if arg:
            titles = self.parse_number_list(arg)
        else:
            titles = None
        self.console.print(f'Scanning disc in {self.config.source}')
        self.episode_map.clear()
        try:
            self.disc = Disc(self.config, titles)
        except (OSError, proc.CalledProcessError) as exc:
            self.disc = None
            raise CmdError(exc)
        self.map_ripped()
        self.do_disc()

    def map_ripped(self):
        "Adds titles/chapters which were previously ripped to the episode map"
        if not self.disc:
            return
        for episode in self.db.get_ripped(self.disc):
            try:
                title = [
                    t for t in self.disc.titles
                    if t.number == episode.disc_title
                    ][0]
            except IndexError:
                self.console.print(
                    f'Warning: previously ripped title {episode.disc_title} '
                    f'not found on the scanned disc (id {episode.disc_id})')
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
                        self.console.print(
                            f'Warning: previously ripped chapters '
                            f'{episode.start_chapter}, {episode.end_chapter} '
                            f'not found in title {title.number} on the '
                            f'scanned disc (id {episode.disc_id})')
                    else:
                        self.episode_map[episode] = (start_chapter, end_chapter)

    def do_automap(self, arg):
        "Maps episodes to titles or chapter ranges automatically"
        self.console.print('Performing auto-mapping')
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
            episodes = self.db.get_unripped()
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
                episodes, titles, self.config.duration,
                strict_mapping=strict_mapping,
                choose_mapping=self.choose_mapping)
        except MapError as exc:
            raise CmdError(str(exc))
        self.do_map()

    def choose_mapping(self, mappings):
        self.console.print(
            f'{len(mappings)} possible chapter-based mappings found')
        # Iterate over the episodes and ask the user in each case whether the
        # first chapter is accurate by playing a clip with vlc
        for episode in list(mappings[0].keys()):
            chapters = set(mapping[episode][0] for mapping in mappings)
            chapters_str = ','.join(
                f'{chapter.title.number}.{chapter.number:02d}'
                for chapter in chapters)
            self.console.print(
                f'Episode {episode.episode} has {len(chapters)} potential '
                f'starting chapters: {chapters_str}')
            while len(chapters) > 1:
                chapter = chapters.pop()
                while True:
                    chapter.play(self.config)
                    while True:
                        response = self.input(
                            f'Is chapter {chapter.title.number}.'
                            f'{chapter.number:02d} the start of episode '
                            f'{episode.episode}? [y/n/r/q] ')
                        response = response.lower()[:1]
                        if response in ('y', 'n', 'r', 'q'):
                            break
                        else:
                            self.console.print('Invalid response')
                    if response == 'y':
                        chapters = {chapter}
                        break
                    elif response == 'n':
                        break
                    elif response == 'q':
                        raise MapError('Abandoned automap at user request')
            assert len(chapters) == 1
            chapter = chapters.pop()
            mappings = [
                mapping for mapping in mappings
                if mapping[episode][0] == chapter
            ]
        assert len(mappings) == 1
        return mappings[0]

    def do_map(self, arg=''):
        "Maps episodes to titles or chapter ranges"
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
            target_label = f'title {target.number} (duration {target.duration})'
        else:
            start, end = target
            assert start.title == end.title
            index = (
                f'{start.title.number}.{start.number:02d}-'
                f'{end.number:02d}')
            duration=sum((
                chapter.duration
                for title in start.title.disc.titles
                for chapter in title.chapters
                if (
                    (start.title.number, start.number) <=
                    (title.number, chapter.number) <=
                    (end.title.number, end.number))
                ), timedelta())
            target_label = (
                f'chapters {start.title.number}.{start.number:02d}-'
                f'{end.number:02d} (duration {duration})')
        self.console.print(
            f'Mapping {target_label} to {episode.episode} "{episode.title}"')
        self.episode_map[episode] = target

    def get_map(self):
        if self.config.program is None:
            raise CmdError('No program has been set')
        if self.config.season is None:
            raise CmdError('No season has been set')
        program = self.config.program
        season = self.config.season
        if self.episode_map:
            table = Table(box=box.ROUNDED)
            table.add_column('Title', no_wrap=True)
            table.add_column('Duration', no_wrap=True, justify='right')
            table.add_column('Ripped', no_wrap=True, justify='center')
            table.add_column('Episode', no_wrap=True, justify='right')
            table.add_column('Name')
            for episode, mapping in self.episode_map.items():
                if isinstance(mapping, Title):
                    index = str(mapping.number)
                    duration = mapping.duration
                else:
                    start, end = mapping
                    assert start.title == end.title
                    index = (
                        f'{start.title.number}.'
                        f'{start.number:02d}-{end.number:02d}')
                    duration = sum((
                        chapter.duration
                        for title in start.title.disc.titles
                        for chapter in title.chapters
                        if (
                            (start.title.number, start.number) <=
                            (title.number, chapter.number) <=
                            (end.title.number, end.number))
                        ), timedelta())
                table.add_row(
                    str(index),
                    str(duration),
                    '✓' if episode.ripped else '',
                    str(episode.episode),
                    episode.title)
            self.console.print(
                f'Episode Mapping for {program} season {season}:', '', table,
                sep='\n')
        else:
            self.console.print('Episode map is currently empty')

    def do_unmap(self, arg):
        "Removes an episode mapping"
        if not arg:
            raise CmdSyntaxError(
                'You must specify a list of episodes to remove from the mapping')
        episodes = arg
        if episodes == '*':
            episodes = list(self.episode_map.keys())
        else:
            episodes = self.parse_episode_list(episodes)
        for episode in episodes:
            self.console.print(
                f'Removing mapping for episode {episode.episode}, '
                f'{episode.title}')
            try:
                del self.episode_map[episode]
            except KeyError:
                raise CmdError(
                    f'Episode {episode.episode}, {episode.title} was not in '
                    f'the map')

    def do_rip(self, arg=''):
        "Starts the ripping and transcoding process"
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
            if t.language in self.config.audio_langs
            ]
        if not self.config.audio_all:
            audio_tracks = [t for t in audio_tracks if t.best]
        subtitle_tracks = [
            t for t in title.subtitle_tracks
            if t.language in self.config.subtitle_langs and (
                t.format == self.config.subtitle_format or
                self.config.subtitle_format == 'any'
            )
        ]
        if not self.config.subtitle_all:
            subtitle_tracks = [t for t in subtitle_tracks if t.best]
        if len(episodes) == 1:
            self.console.print(
                f'Ripping episode {episode.episode}, "{episode.title}"')
        else:
            numbers = ' '.join(str(e.episode) for e in episodes)
            self.console.print(
                f'Ripping episodes {numbers}, {multipart.name(episodes)}')
        try:
            self.disc.rip(self.config, episodes, title, audio_tracks,
                          subtitle_tracks, chapter_start, chapter_end)
        except proc.CalledProcessError as exc:
            raise CmdError(f'process failed with code {exc.returncode}')
        else:
            for episode in episodes:
                if chapter_start is None:
                    self.db.rip_episode(episode.episode, title)
                else:
                    self.db.rip_episode(
                        episode.episode, (chapter_start, chapter_end))

    def do_unrip(self, arg):
        "Changes the status of the specified episode to unripped"
        if not arg:
            raise CmdSyntaxError(
                'You must specify a list of episodes to mark as unripped')
        episodes = arg
        if episodes == '*':
            episodes = self.db.get_episodes()
        else:
            episodes = self.parse_episode_list(episodes, must_exist=False)
        for episode in episodes:
            if episode is not None:
                self.db.unrip_episode(episode.episode)
