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

"""Implements the command line processor for the tvrip application"""

from __future__ import (
    unicode_literals,
    print_function,
    absolute_import,
    division,
    )

import os
import re
import sqlalchemy as sa
from datetime import timedelta, datetime
from tvrip.ripper import Disc, Title
from tvrip.database import (
    init_session, Configuration, Program, Season, Episode,
    AudioLanguage, SubtitleLanguage, ConfigPath
    )
from tvrip.episodemap import EpisodeMap
from tvrip.cmdline import Cmd, CmdError, CmdSyntaxError


class RipCmd(Cmd):
    "Implementation of the TVRip command line"

    prompt = '(tvrip) '

    def __init__(self, debug=False):
        Cmd.__init__(self)
        self.discs = {}
        self.episode_map = EpisodeMap()
        self.session = init_session(debug=debug)
        # Read the configuration from the database
        try:
            self.config = self.session.query(Configuration).one()
        except sa.orm.exc.NoResultFound:
            self.config = Configuration()
            self.session.add(self.config)
            self.session.add(AudioLanguage(lang='eng'))
            self.session.add(SubtitleLanguage(lang='eng'))
            self.session.add(ConfigPath(name='handbrake',
                path='/usr/bin/HandBrakeCLI'))
            self.session.add(ConfigPath(name='atomicparsley',
                path='/usr/bin/AtomicParsley'))
            self.session.add(ConfigPath(name='vlc',
                path='/usr/bin/vlc'))
            self.session.commit()

    def onecmd(self, line):
        # Ensure that the current transaction is committed after a command, or
        # that everything the command did is rolled back in the case of an
        # exception
        try:
            result = Cmd.onecmd(self, line)
            self.session.commit()
            return result
        except:
            self.session.rollback()
            raise

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
            del self.discs[self.config.source]
        else:
            self.discs[self.config.source] = value
    disc = property(_get_disc, _set_disc)

    def parse_episode(self, episode, must_exist=True):
        """Parse a string containing an episode number.

        Given a string representing an episode number, this method returns the
        Episode object from the current program's season with the corresponding
        number, or throws an error if no such episode exists unless the optional
        must_exist flag is set to False.
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
        try:
            return self.session.query(Episode).\
                filter(Episode.season==self.config.season).\
                filter(Episode.number==episode).one()
        except sa.orm.exc.NoResultFound:
            if must_exist:
                raise CmdError(
                    'There is no episode {episode} in '
                    'season {season} of {program}'.format(
                        episode=episode,
                        season=self.config.season.number,
                        program=self.config.program.name))
            else:
                return None

    def parse_episode_range(self, episodes, must_exist=True):
        """Parse a string containing an episode range.

        Given a string representing a range of episodes as two dash-separated
        numbers, this method returns the Episode objects at the start and end
        of the range or throws an error if no such episodes exist unless the
        optional must_exist flag is set to False.
        """
        if not '-' in episodes:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (
            self.parse_episode(i, must_exist)
            for i in self.parse_number_range(episodes)
            )
        return start, finish

    def parse_episode_list(self, episodes, must_exist=True):
        """Parse a string containing an episode list.

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
        """Parse a string containing a title number.

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
        """Parse a string containing a title range.

        Given a string representing a range of titles as two dash-separated
        numbers, this method returns the Title objects at the start and end
        of the range or throws an error if no such titles exist.
        """
        if not '-' in titles:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (self.parse_title(i) for i in titles.split('-', 1))
        return start, finish

    def parse_title_list(self, titles):
        """Parse a string containing a title list.

        Given a string representing a list of titles as a comma-separated
        list of numbers and number-ranges, this method returns a sequence of
        Title objects. If titles within the list do not exist an error will
        be thrown.
        """
        return [self.parse_title(i) for i in self.parse_number_list(titles)]

    def parse_chapter(self, title, chapter):
        """Parse a string containing a chapter number.

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
        """Parse a string containing a chapter range.

        Given a string representing a range of chapters as two dash-separated
        numbers, this method returns the Chapter objects at the start and end
        of the range or throws an error if no such chapters exist.
        """
        if not '-' in chapters:
            raise CmdSyntaxError('Expected two dash-separated numbers')
        start, finish = (
            self.parse_chapter(title, i)
            for i in chapters.split('-', 1)
            )
        return start, finish

    def clear_seasons(self, program=None):
        "Removes all seasons from the specified program"
        if program is None:
            program = self.config.program
        for season in self.session.query(Season).\
                filter(Season.program==program):
            self.session.delete(season)

    def clear_episodes(self, season=None):
        "Removes all episodes from the specified season"
        if season is None:
            season = self.config.season
        for episode in self.session.query(Episode).\
                filter(Episode.season==season):
            self.session.delete(episode)

    def pprint_disc(self):
        "Prints the details of the currently scanned disc"
        self.pprint('Disc identifier: {}'.format(self.disc.ident))
        self.pprint('Disc serial: {}'.format(self.disc.serial))
        self.pprint('Disc name: {}'.format(self.disc.name))
        self.pprint('Disc has {} titles'.format(len(self.disc.titles)))
        self.pprint('')
        table = [('Title', 'Chapters', 'Duration', 'Audio')]
        for title in self.disc.titles:
            table.append((
                title.number,
                len(title.chapters),
                title.duration,
                ' '.join(track.language for track in title.audio_tracks)
                ))
        self.pprint_table(table)

    def pprint_title(self, title):
        "Prints the details of the specified disc title"
        self.pprint('Title {title} (duration: {duration})'.format(
            title=title.number, duration=title.duration))
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
                suffix = 'x'
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
        table = [('Subtitle', 'Lang', 'Name', 'Best')]
        for track in title.subtitle_tracks:
            suffix = ''
            if track.best and self.config.in_subtitle_langs(track.language):
                suffix = 'x'
            table.append((
                track.number,
                track.language,
                track.name,
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
                ).outerjoin(Season).outerjoin(Episode).\
                group_by(Program.name).order_by(Program.name):
            table.append((program, seasons, episodes,
                '{:.1f}%'.format(ripped * 100 / episodes)))
        self.pprint_table(table)

    def pprint_seasons(self, program=None):
        "Prints the seasons of the specified program"
        if program is None:
            program = self.config.program
        self.pprint('Seasons for program {}'.format(program.name))
        self.pprint('')
        table = [('Num', 'Episodes', 'Ripped')]
        for (season, episodes, ripped) in self.session.query(
                    Season.number,
                    sa.func.count(Episode.number),
                    sa.func.count(Episode.disc_id)
                ).filter(Season.program==program).\
                outerjoin(Episode).\
                group_by(Season.number).\
                order_by(Season.number):
            table.append((season, episodes,
                '{:.1f}%'.format(ripped * 100 / episodes)))
        self.pprint_table(table)

    def pprint_episodes(self, season=None):
        "Prints the episodes of the specified season"
        if season is None:
            season = self.config.season
        self.pprint(
            'Episodes for season {season} of program {program}'.format(
                season=season.number, program=season.program.name))
        self.pprint('')
        table = [('Num', 'Title', 'Ripped')]
        for episode in self.session.query(Episode).\
                filter(Episode.season==season):
            table.append((
                episode.number,
                episode.name,
                ['', 'x'][episode.ripped]
                ))
        self.pprint_table(table)

    def do_config(self, arg):
        """Shows the current set of configuration options.

        Syntax: config

        The 'config' command simply outputs the current set of configuration
        options as set by the various other commands.
        """
        if arg:
            raise CmdSyntaxError('Unknown argument {}'.format(arg))
        self.pprint('External Utility Paths:')
        self.pprint('')
        for path in self.config.paths:
            self.pprint('{name:<16} = {value}'.format(
                name=path.name, value=path.path))
        self.pprint('')
        self.pprint('Ripping Configuration:')
        self.pprint('')
        self.pprint('source           = {}'.format(self.config.source))
        self.pprint('target           = {}'.format(self.config.target))
        self.pprint('temp             = {}'.format(self.config.temp))
        self.pprint('duration         = {min}-{max} (mins)'.format(
            min=self.config.duration_min.seconds / 60,
            max=self.config.duration_max.seconds / 60))
        self.pprint('program          = {}'.format(
            self.config.program.name if self.config.program else '<none set>'
        ))
        self.pprint('season           = {}'.format(
            self.config.season.number if self.config.season else '<none set>'
        ))
        self.pprint('template         = {}'.format(self.config.template))
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
        self.pprint('subtitle_langs   = {}'.format(
            ' '.join(l.lang for l in self.config.subtitle_langs)))

    def do_path(self, arg):
        """Sets a path to an external utility.

        Syntax: path <name> <value>

        The 'path' command is used to alter the path of one of the external
        utilities used by TVRip. Specify the name of the path (which you can
        find from the 'config' command) and the new path to the utility. For
        example:

        (tvrip) path handbrake /usr/bin/HandBrakeCLI
        (tvrip) path atomicparsley /usr/bin/AtomicParsley
        """
        name, path = arg.split(' ', 1)
        if not os.path.exists(path):
            self.pprint("Warning: path '{}' does not exist".format(path))
        if not os.access(path, os.X_OK):
            self.pprint("Warning: path '{}' is not executable".format(path))
        try:
            self.config.set_path(name, path)
        except sa.orm.exc.NoResultFound:
            raise CmdError(
                'Path name "{}" is invalid, please see "config" '
                'for valid options'.format(name))

    def do_audio_langs(self, arg):
        """Sets the list of audio languages to rip.

        Syntax: audio_langs <lang>...

        The 'audio_langs' command sets the list of languages for which audio
        tracks will be extracted and converted. Languages are specified as
        lowercase 3-character ISO639 codes. For example:

        (tvrip) audio_langs eng jpn
        (tvrip) audio_langs eng
        """
        arg = arg.lower().split(' ')
        new_langs = set(arg)
        for lang in self.config.audio_langs:
            if lang.lang in new_langs:
                new_langs.remove(lang.lang)
            else:
                self.session.delete(lang)
        for lang in new_langs:
            self.session.add(AudioLanguage(lang=lang))

    def do_audio_mix(self, arg):
        """Sets the audio mixdown

        Syntax: audio_mix <mix-value>

        The 'audio_mix' command sets the audio mixdown used by the 'rip'
        command.  The valid mixes are 'mono', 'stereo', 'dpl1', and 'dpl2' with
        the latter two indicating Dolby Pro Logic I and II respectively. AC3 or
        DTS pass-thru cannot be configured at this time. For example:

        (tvrip) audio_mix stereo
        (tvrip) audio_mix dpl2
        """
        try:
            arg = {
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
                }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError('Invalid audio mix {}'.format(arg))
        self.config.audio_mix = arg

    def do_audio_all(self, arg):
        """Sets whether to extract all language-matched audio tracks

        Syntax: audio_all <off|on>

        The 'audio_all' command specifies whether, of the audio tracks which
        match the specified languages (see the 'audio_langs' command), only the
        best track should be extracted, or all matching tracks. For example:

        (tvrip) audio_tracks off
        (tvrip) audio_tracks on
        """
        self.config.audio_all = self.parse_bool(arg)

    def do_subtitle_langs(self, arg):
        """Sets the list of subtitle languages to rip.

        Syntax: subtitle_langs <lang>...

        The 'subtitle_langs' command sets the list of languages for which
        subtitle tracks will be extracted and converted. Languages are
        specified as lowercase 3-character ISO639 codes. For example:

        (tvrip) subtitle_langs eng jpn
        (tvrip) subtitle_langs eng
        """
        arg = arg.lower().split(' ')
        new_langs = set(arg)
        for lang in self.config.subtitle_langs:
            if lang.lang in new_langs:
                new_langs.remove(lang.lang)
            else:
                self.session.delete(lang)
        for lang in new_langs:
            self.session.add(SubtitleLanguage(lang=lang))

    def do_subtitle_format(self, arg):
        """Sets the subtitle extraction mode

        Syntax: subtitle_format <format>

        The 'subtitle_format' command sets the subtitles extraction mode used
        by the 'rip' command. The valid formats are 'none' indicating that
        subtitles should not be extracted at all, and 'vobsub' which causes
        subtitles to be extracted as timed image overlays. For example:

        (tvrip) subtitle_format vobsub
        (tvrip) subtitle_format none
        """
        try:
            arg = {
                'off':    'none',
                'none':   'none',
                'vob':    'vobsub',
                'vobsub': 'vobsub',
                }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(
                'Invalid subtitle extraction mode {}'.format(arg))
        self.config.subtitle_format = arg

    def do_subtitle_all(self, arg):
        """Sets whether to extract all language-matched subtitles

        Syntax: subtitle_all <off|on>

        The 'subtitle_all' command specifies whether, of the subtitle tracks
        which match the specified languages (see the 'subtitle_langs' command),
        only the best matching track should be extracted, or all matching
        tracks. For example:

        (tvrip) subtitle_all off
        (tvrip) subtitle_all on
        """
        self.config.subtitle_all = self.parse_bool(arg)

    def do_decomb(self, arg):
        """Sets the decomb option for video conversion.

        Syntax: decomb <option>

        The 'decomb' command sets the decomb setting for the video converter.
        Valid settings are currently 'off', 'on', and 'auto'. For example:

        (tvrip) decomb off
        (tvrip) decomb on
        """
        try:
            self.config.decomb = ['off', 'on'][self.parse_bool(arg)]
        except CmdSyntaxError:
            if arg.strip().lower() == 'auto':
                self.config.decomb = 'auto'
            else:
                raise

    def do_duration(self, arg):
        """Sets range of episode duration.

        Syntax: duration <min>-<max>

        The 'duration' command sets the minimum and maximum length (in minutes)
        that an episode is expected to be.  This is used when scanning a source
        device for titles which are likely to be episodes. For example:

        (tvrip) duration 40-50
        (tvrip) duration 25-35
        """
        if not arg:
            raise CmdSyntaxError('You must specify a new duration')
        self.config.duration_min, self.config.duration_max = (
            timedelta(minutes=i)
            for i in self.parse_number_range(arg)
            )

    def do_episode(self, arg):
        """Sets the name of a single episode.

        Syntax: episode <number> <name>

        The 'episode' command can be used to display the name of the
        specified episode or, if two arguments are given, will redefine the
        name of the specified episode.
        """
        if not arg:
            raise CmdSyntaxError('You must specify an episode number and name')
        (number, name) = arg.split(' ', 1)
        episode = self.parse_episode(number, must_exist=False)
        if episode is None:
            episode = Episode(
                season=self.config.season, number=number, name=name)
            self.session.add(episode)
            self.pprint(
                'Added episode {episode} to season {season} '
                'of {program}'.format(
                    episode=episode.number,
                    season=episode.season.number,
                    program=episode.season.program.name))
        else:
            episode.name = name
            self.pprint(
                'Renamed episode {episode} of season {season} '
                'of {program}'.format(
                    episode=episode.number,
                    season=episode.season.number,
                    program=episode.season.program.name))

    def create_episodes(self, count, season=None):
        "Creates the specified number of episodes in the current season"
        if season is None:
            season = self.config.season
        self.pprint('Please enter the names of the episodes. Leave a '
            'name blank if you wish to terminate entry early:')
        self.clear_episodes()
        for number in range(1, count + 1):
            name = self.input('{:2d}: '.format(number))
            if not name:
                self.pprint('Terminating episode name entry')
                break
            episode = Episode(season=season, number=number, name=name)
            self.session.add(episode)

    def do_episodes(self, arg):
        """Gets or sets the episodes for the current season.

        Syntax: episodes [number]

        The 'episodes' command can be used to list the episodes of the
        currently selected season of the program. If an argument is given, the
        current episode list is deleted and you will be prompted to enter
        names for the specified number of episodes.

        If you simply wish to change the name of a single episode, see the
        'episode' command instead.
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

    def do_season(self, arg):
        """Sets which season of the program the disc contains.

        Syntax: season <number>

        The 'season' command specifies the season the disc contains episodes
        for. This number is used when constructing the filename of ripped
        episodes.

        This command is also used to expand the episode database. If the number
        given does not exist, it will be entered into the database under the
        current program and you will be prompted for episode names.
        """
        if not self.config.program:
            raise CmdError('You must specify a program first')
        try:
            arg = int(arg)
        except ValueError:
            raise CmdSyntaxError(
                'A season must be a valid number '
                '({} specified)'.format(arg))
        if arg < 1:
            raise CmdSyntaxError(
                'A season number must be 1 or higher '
                '({} specified)'.format(arg))
        try:
            self.config.season = self.session.query(Season).\
                filter(Season.program==self.config.program).\
                filter(Season.number==arg).one()
        except sa.orm.exc.NoResultFound:
            self.config.season = Season(
                program=self.config.program, number=arg)
            self.session.add(self.config.season)
            try:
                count = int(self.input(
                    'Season {season} of program {program} is new. Please '
                    'enter the number of episodes in this season (enter 0 if '
                    'you do not wish to define episodes at this time) '
                    '[0-n] '.format(
                        season=self.config.season.number,
                        program=self.config.program.name)))
            except ValueError:
                while True:
                    try:
                        count = int(self.input(
                            'Invalid input. Please enter a number [0-n] '))
                    except ValueError:
                        pass
                    else:
                        break
            if count != 0:
                self.do_episodes(count)
        self.episode_map.clear()
        self.map_ripped()

    def complete_season(self, text, line, start, finish):
        "Auto-completer for season command"
        return [
            unicode(season.number) for season in
            self.session.query(Season).\
            filter(Season.program==self.config.program).\
            filter("SUBSTR(CAST(season AS TEXT), 1, :length) = :season").\
            params(length=len(text), season=text)
            ]

    def do_seasons(self, arg):
        """Shows the defined seasons of the current program.

        Syntax: seasons

        The 'seasons' command outputs the list of seasons defined for the
        current program, along with a summary of how many episodes are defined
        for each season.
        """
        if arg:
            raise CmdSyntaxError('Invalid argument {}'.format(arg))
        if not self.config.program:
            raise CmdError('No program has been set')
        self.pprint_seasons()

    def do_program(self, arg):
        """Sets the name of the program.

        Syntax: program <name>

        The 'program' command specifies the program the disc contains episodes
        for. This is used when constructing the filename of ripped episodes.

        This command is also used to expand the episode database. If the name
        given does not exist, it will be entered into the database and you will
        be prompted for season and episode information.
        """
        if not arg:
            raise CmdSyntaxError('You must specify a program name')
        try:
            self.config.program = self.session.query(Program).\
                filter(Program.name==arg).one()
        except sa.orm.exc.NoResultFound:
            self.config.program = Program(name=arg)
            self.session.add(self.config.program)
            try:
                count = int(self.input(
                    'Program {} is new. How many seasons exist (enter '
                    '0 if you do not wish to define seasons and episodes '
                    'at this time)? [0-n] '.format(
                        self.config.program.name)))
            except ValueError:
                while True:
                    try:
                        count = int(self.input(
                            'Invalid input. Please enter a number [0-n] '))
                    except ValueError:
                        pass
                    else:
                        break
            self.config.season = None
            for number in range(1, count + 1):
                self.do_season(number)
        self.config.season = self.session.query(Season).\
            filter(Season.program==self.config.program).\
            order_by(Season.number).first()
        self.episode_map.clear()
        self.map_ripped()

    program_re = re.compile(ur'^program\s+')
    def complete_program(self, text, line, start, finish):
        "Auto-completer for program command"
        match = self.program_re.match(line)
        name = unicode(line[match.end():])
        return [
            program.name[start - match.end():] for program in
            self.session.query(Program).filter(Program.name.startswith(name))
            ]

    def do_programs(self, arg):
        """Shows the defined programs.

        Syntax: programs

        The 'programs' command outputs the list of programs defined in the
        database, along with a summary of how many seasons and episodes are
        defined for each.
        """
        if arg:
            raise CmdSyntaxError('Invalid argument {}'.format(arg))
        self.pprint_programs()

    def do_disc(self, arg=''):
        """Displays information about the last scanned disc.

        Syntax: disc

        The 'disc' command re-displays the top-level information that was
        discovered during the last 'scan' command. It shows the disc's
        identifier and serial number, along with a summary of title
        information.
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        self.pprint_disc()

    def do_title(self, arg):
        """Displays information about the specified title(s).

        Syntax: title <titles>

        The 'title' command displays detailed information about the specified
        titles including chapter starts and durations, audio tracks, and
        subtitle tracks.
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        elif not arg:
            raise CmdSyntaxError('You must specify a title')
        for number in self.parse_number_list(arg):
            try:
                title = [
                    t for t in self.disc.titles
                    if t.number == number
                    ][0]
            except IndexError:
                # If the user specifies an invalid title number, ignore it
                # (useful with large ranges of titles)
                pass
            else:
                self.pprint_title(title)

    def do_scan(self, arg):
        """Scans the source device for episodes.

        Syntax: scan [titles]

        The 'scan' command scans the current source device to discover what
        titles, audio tracks, and subtitle tracks exist on the disc in the
        source device. Please note that scanning a disc erases the current
        episode mapping.
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
        self.disc = Disc()
        try:
            self.disc.scan(self.config, titles)
        except IOError as exc:
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
        for episode in self.session.query(Episode).\
                filter(Episode.season==self.config.season).\
                filter(
                    sa.or_(
                        sa.and_(
                            Episode.disc_id.startswith('$H1$'),
                            Episode.disc_id==self.disc.ident
                        ),
                        sa.and_(
                            ~Episode.disc_id.startswith('$H1$'),
                            Episode.disc_id==self.disc.serial
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
                    self.episode_map[episode] = (
                        title.chapters[episode.start_chapter],
                        title.chapters[episode.end_chapter]
                        )

    def do_automap(self, arg):
        """Maps episodes to titles or chapter ranges automatically.

        Syntax: automap [episodes [titles]]

        The 'automap' command is used to have the application attempt to figure
        out which titles (or chapters of titles) contain the next set of
        unripped episodes. If no title numbers are specified, all titles are
        considered candidates. Otherwise, only those titles specified are
        considered. If direct title mapping fails, chapter-based mapping is
        attempted instead.

        The current episode mapping can be viewed in the output of the 'map'
        command.
        """
        self.pprint('Performing auto-mapping')
        # Generate the list of titles, either specified or implied in the
        # arguments
        if ' ' in arg:
            episodes, titles = arg.split(' ', 1)
            episodes = self.parse_episode_list(episodes)
            titles = self.parse_title_list(titles)
        elif arg:
            episodes = self.parse_episode_list(arg)
            titles = list(self.disc.titles)
        else:
            episodes = self.session.query(Episode).\
                filter(Episode.season==self.config.season).\
                filter(Episode.disc_id==None).\
                order_by(Episode.number).all()
            titles = list(self.disc.titles)
        self.episode_map.automap(
            titles, episodes, self.config.duration_min,
            self.config.duration_max, self.choose_mapping)
        self.do_map()

    def choose_mapping(self, mappings):
        # Obtain a sorted list of all episodes that the possible mappings cover
        # (all possible mappings cover all episodes so just use the first for
        # this). No need for an explicit sort as an EpisodeMap instance always
        # returns episodes in order
        episodes = mappings[0].keys()
        # Iterate over the episodes and ask the user in each case whether the
        # first chapter is accurate by playing a clip with vlc
        for episode in episodes:
            self.pprint(
                '{} possible mappings remaining'.format(len(mappings)))
            chapters = set(mapping[episode][0] for mapping in mappings)
            self.pprint(
                'Episode {episode} has {count} potential starting '
                'chapters: {chapters}'.format(
                    episode=episode.number,
                    count=len(chapters),
                    chapters=','.join(
                        unicode(chapter.number) for chapter in chapters)))
            while len(chapters) > 1:
                chapter = chapters.pop()
                while True:
                    self.pprint('Playing chapter {}'.format(chapter.number))
                    chapter.play(self.config)
                    while True:
                        response = self.input(
                            'Is chapter {chapter} the start of episode '
                            '{episode}? [y/n/r] '.format(
                                chapter=chapter.number,
                                episode=episode.number))
                        response = response.lower()[:1]
                        if response in ('y', 'n', 'r'):
                            break
                        else:
                            self.pprint('Invalid response')
                    if response == 'y':
                        chapter = [chapters]
                        break
                    elif response == 'n':
                        break
            assert len(chapters) == 1
            chapter = chapters.pop()
            mappings = [
                mapping for mapping in mappings
                if mapping[episode][0] == chapter
                ]
        if len(mappings) == 1:
            self.pprint('Solution found!')
            return mappings[0]
        else:
            self.pprint('Something has gone horribly wrong...')
            for mapping in mappings:
                print(mapping)
                print('-------------------------------------------')

    def do_map(self, arg=''):
        """Maps episodes to titles or chapter ranges.

        Syntax: map [episode title[.start-end]]

        The 'map' command is used to define which title on the disc contains
        the specified episode. This is used when constructing the filename of
        ripped episodes. For example:

        (tvrip) map 3 1
        (tvrip) map 7 4
        (tvrip) map 5 2.1-12

        If no arguments are specified, the current episode map will be
        displayed.
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        elif not self.config.program:
            raise CmdError('No program has been set')
        elif not self.config.season:
            raise CmdError('No season has been set')
        elif not arg:
            self.pprint('Episode Mapping (* indicates ripped):')
            self.pprint('')
            if self.episode_map:
                for episode, mapping in self.episode_map.iteritems():
                    if isinstance(mapping, Title):
                        index = '{:2d}'.format(mapping.number)
                        duration = str(mapping.duration)
                    else:
                        chapter_start, chapter_end = mapping
                        index = (
                            '{title:2d}.{chapter_start:02d}-'
                            '{chapter_end:02d}'.format(
                            title=chapter_start.title.number,
                            chapter_start=chapter_start.number,
                            chapter_end=chapter_end.number))
                        duration = '%s' % sum(
                            (c.duration for c in chapter_start.title.chapters
                            if chapter_start.number <= c.number <= chapter_end.number
                            ), timedelta())
                    self.pprint(
                        '{ripped:2s}title {title} ({duration}) = '
                        'episode {episode_num:2d}, '
                        '"{episode_title}"'.format(
                            ripped='*' if episode.ripped else ' ',
                            title=index,
                            duration=duration,
                            episode_num=episode.number,
                            episode_title=episode.name
                            ))
            else:
                self.pprint('Episode map is currently empty')
            return
        try:
            episode, title = arg.split(' ')
        except ValueError:
            raise CmdSyntaxError('You must specify two arguments')
        if '.' in title:
            try:
                title, chapters = title.split('.')
                chapter_start, chapter_end = (
                    int(i) for i in chapters.split('-'))
            except ValueError:
                raise CmdSyntaxError('Unable to parse specified chapter range')
        else:
            chapter_start = chapter_end = None
        try:
            title = int(title)
            episode = int(episode)
        except ValueError:
            raise CmdSyntaxError('Titles, chapters, and episodes must be '
                'integer numbers')
        try:
            title = [t for t in self.disc.titles if t.number == title][0]
        except IndexError:
            raise CmdError(
                'There is no title {} on the scanned disc'.format(title))
        if chapter_start:
            try:
                chapter_start = [
                    c for c in title.chapters
                    if c.number == chapter_start
                    ][0]
            except IndexError:
                raise CmdError(
                    'There is no chapter {chapter} within title {title} on '
                    'the scanned disc'.format(
                        chapter=chapter_start,
                        title=title.number))
        if chapter_end:
            try:
                chapter_end = [
                    c for c in title.chapters
                    if c.number == chapter_end
                    ][0]
            except IndexError:
                raise CmdError(
                    'There is no chapter {chapter} within title {title} on '
                    'the scanned disc'.format(
                        chapter=chapter_end,
                        title=title.number))
        try:
            episode = self.session.query(Episode).\
                filter(Episode.season==self.config.season).\
                filter(Episode.number==episode).one()
        except sa.orm.exc.NoResultFound:
            raise CmdError(
                'There is no episode {} in the current '
                'season'.format(episode))
        if chapter_start:
            self.pprint(
                'Mapping chapters {chapter_start}-{chapter_end} (duration '
                '{duration}) of title {title} to episode {episode_num}, '
                '"{episode_title}"'.format(
                    chapter_start=chapter_start.number,
                    chapter_end=chapter_end.number,
                    duration=sum(
                        [c.duration for c in title.chapters
                        if chapter_start.number <= c.number <= chapter_end.number
                        ], timedelta()),
                    title=title.number,
                    episode_num=episode.number,
                    episode_title=episode.name))
            self.episode_map[episode] = (chapter_start, chapter_end)
        else:
            self.pprint(
                'Mapping title {title} (duration {duration}) to episode '
                '{episode_num}, "{episode_title}"'.format(
                    title=title.number,
                    duration=title.duration,
                    episode_num=episode.number,
                    episode_title=episode.name))
            self.episode_map[episode] = title

    def do_unmap(self, arg):
        """Removes an episode mapping.

        Syntax: unmap <episodes>

        The 'unmap' command is used to remove a title to episode mapping. For
        example, if the auto-mapping when scanning a disc makes an error, you
        can use the 'map' and 'unmap' commands to fix it. For example:

        (tvrip) unmap 3
        (tvrip) unmap 7
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        try:
            arg = int(arg)
        except ValueError:
            raise CmdSyntaxError('You must specify an integer title number')
        for episode in self.parse_episode_list(arg):
            self.pprint(
                'Removing mapping for episode {episode.number}, '
                '{episode.name}'.format(episode=episode))
            del self.episode_map[episode]

    def do_rip(self, arg):
        """Starts the ripping and transcoding process.

        Syntax: rip

        The 'rip' command begins ripping the mapped titles from the current
        source device, converting them according to the current preferences,
        and storing the results in the target path. Only previously unripped
        episodes will be ripped. If you wish to re-rip an episode, use the
        'unrip' command to set it to unripped first.
        """
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError('No titles found on the scanned disc')
        elif not self.episode_map:
            raise CmdError('No titles have been mapped to episodes')
        elif arg.strip():
            raise CmdSyntaxError('You must not specify any arguments')
        for episode, mapping in sorted(self.episode_map.iteritems(),
                key=lambda t: t[0].number):
            if not episode.ripped:
                if isinstance(mapping, Title):
                    chapter_start = chapter_end = None
                    title = mapping
                else:
                    chapter_start, chapter_end = mapping
                    assert chapter_start.title is chapter_end.title
                    title = chapter_start.title
                audio_tracks = [
                    t for t in title.audio_tracks
                    if self.config.in_audio_langs(t.language)
                    ]
                if not self.config.audio_all:
                    audio_tracks = [t for t in audio_tracks if t.best]
                subtitle_tracks = [
                    t for t in title.subtitle_tracks
                    if self.config.in_subtitle_langs(t.language)
                    ]
                if not self.config.subtitle_all:
                    subtitle_tracks = [t for t in subtitle_tracks if t.best]
                self.pprint(
                    'Ripping episode {episode.number}, '
                    '"{episode.name}"'.format(episode=episode))
                self.disc.rip(self.config, episode, title, audio_tracks,
                    subtitle_tracks, chapter_start, chapter_end)
                episode.disc_id = self.disc.ident
                episode.disc_title = title.number
                if chapter_start:
                    episode.start_chapter = chapter_start.number
                    episode.end_chapter = chapter_end.number
                else:
                    episode.start_chapter = None
                    episode.end_chapter = None

    def do_unrip(self, arg):
        """Changes the status of the specified episode to unripped.

        Syntax: unrip <episodes>

        The 'unrip' command is used to set the status of an episode or episodes
        to unripped. Episodes may be specified as a range (1-5) or as a comma
        separated list (4,2,1) or some combination (1,3-5).

        Episodes are automatically set to ripped during the operation of the
        'rip' command.  Episodes marked as ripped will be automatically mapped
        to titles by the 'map' command when the disc they were ripped from is
        scanned (they can be mapped manually too). For example:

        (tvrip) unrip 3
        (tvrip) unrip 7
        """
        for episode in self.parse_episode_list(arg, must_exist=False):
            if episode:
                episode.disc_id = None
                episode.disc_title = None
                episode.start_chapter = None
                episode.end_chapter = None

    def do_source(self, arg):
        """Sets the source device.

        Syntax: source <device>

        The 'source' command sets a new source device. The home directory
        shorthand (~) may be used in the specified path. For example:

        (tvrip) source /dev/dvd
        (tvrip) source /dev/sr0
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint('Path {} does not exist'.format(arg))
            return
        self.config.source = arg

    source_re = re.compile('^source\s+')
    def complete_source(self, text, line, start, finish):
        return self.complete_path(text, self.source_re.sub('', line),
                start, finish)

    def do_target(self, arg):
        """Sets the target path.

        Syntax: target <path>

        The 'target' command sets a new target path. The home-directory
        shorthand (~) may be used in the specified path. For example:

        (tvrip) target ~/Videos
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint('Path {} does not exist'.format(arg))
            return
        if not os.path.isdir(arg):
            self.pprint('Path {} is not a directory'.format(arg))
            return
        self.config.target = arg

    target_re = re.compile(ur'^target\s+')
    def complete_target(self, text, line, start, finish):
        return self.complete_path(text, self.target_re.sub('', line),
                start, finish)

    def do_temp(self, arg):
        """Sets the temporary files path.

        Syntax: temp <path>

        The 'temp' command sets the path which will be used for temporary
        storage (actually a temporary directory under this path is used). The
        home-directory shorthand (~) may be used, but be aware that no spaces
        are permitted in the path name. For example:

        (tvrip) temp ~/tmp
        (tvrip) temp /var/tmp
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint('Path {} does not exist'.format(arg))
            return
        if not os.path.isdir(arg):
            self.pprint('Path {} is not a directory'.format(arg))
            return
        self.config.temp = arg

    temp_re = re.compile(ur'^temp\s+')
    def complete_temp(self, text, line, start, finish):
        return self.complete_path(text, self.temp_re.sub('', line),
                start, finish)

    def do_template(self, arg):
        """Sets the template used for filenames.

        Syntax: template <string>

        The 'template' command sets the new filename template. The template is
        specified as a Python format string including named subsitution markers
        (program, season, episode, and name). The format-string is specified
        without quotation marks. For example:

        (tvrip) template {program} - {season}x{episode:02d} - {name}.mp4
        (tvrip) template S{season:02d}E{episode02d}_{name}.mp4
        """
        try:
            arg.format(
                program='Program Name',
                season=1,
                episode=10,
                name='Foo Bar',
                now=datetime.now(),
                )
        except KeyError as exc:
            raise CmdError(
                'The new template contains an '
                'invalid substitution key: {}'.format(exc))
        except ValueError as exc:
            raise CmdError(
                'The new template contains an error: {}'.format(exc))
        self.config.template = arg

