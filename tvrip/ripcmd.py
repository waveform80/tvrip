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
from datetime import timedelta, datetime

import sqlalchemy as sa

from tvrip.ripper import Disc, Title
from tvrip.database import (
    init_session, Configuration, Program, Season, Episode,
    AudioLanguage, SubtitleLanguage, ConfigPath
    )
from tvrip.episodemap import EpisodeMap, MapError
from tvrip.cmdline import Cmd, CmdError, CmdSyntaxError
from tvrip.const import DATADIR
from . import multipart


class RipCmd(Cmd):
    "Implementation of the TVRip command line"

    prompt = '(tvrip) '

    def __init__(self, debug=False):
        super().__init__()
        self.discs = {}
        self.episode_map = EpisodeMap()
        self.session = init_session(debug=debug)
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
                ConfigPath(self.config, 'vlc', 'vlc'))
            self.session.commit()

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
            del self.discs[self.config.source]
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
        if not '-' in episodes:
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
        if not '-' in titles:
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
        if not '-' in chapters:
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

        Given a string representing a title, a title.start-end chapter range,
        or a title.start-title.end range, this method returns a Title object or
        the (Chapter, Chapter) tuple that the string represents.
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
            else:
                return self.parse_chapter_range(self.parse_title(title), chapters)
        else:
            return self.parse_title(s)

    def clear_seasons(self, program=None):
        "Removes all seasons from the specified program"
        if program is None:
            program = self.config.program
        for season in self.session.query(
                Season
            ).filter(
                (Season.program == program)
            ):
            self.session.delete(season)

    def clear_episodes(self, season=None):
        "Removes all episodes from the specified season"
        if season is None:
            season = self.config.season
        for episode in self.session.query(
                Episode
            ).filter(
                (Episode.season == season)
            ):
            self.session.delete(episode)

    def pprint_disc(self):
        "Prints the details of the currently scanned disc"
        if not self.disc:
            raise CmdError('No disc has been scanned yet')
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
                {'first': ' ┐', 'yes': ' │', 'last': ' ┘', 'no': ''}[title.duplicate],
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
            duplicate=title.duplicate))
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
        table = [('Subtitle', 'Lang', 'Name', 'Format', 'Best')]
        for track in title.subtitle_tracks:
            suffix = ''
            if track.best and self.config.in_subtitle_langs(track.language):
                suffix = 'x'
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
                    Season
                ).outerjoin(
                    Episode
                ).group_by(
                    Program.name
                ).order_by(
                    Program.name
                ):
            table.append((program, seasons, episodes,
                '{:5.1f}%'.format(ripped * 100 / episodes) if episodes else '-'.rjust(6)))
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
            table.append((season, episodes,
                '{:5.1f}%'.format(ripped * 100 / episodes) if episodes else '-'.rjust(6)))
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
        for episode in self.session.query(
                Episode
            ).filter(
                (Episode.season == season)
            ):
            table.append((
                episode.number,
                episode.name,
                ['', 'x'][episode.ripped]
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
            min=self.config.duration_min.seconds / 60,
            max=self.config.duration_max.seconds / 60))
        self.pprint('duplicates       = {}'.format(self.config.duplicates))
        self.pprint('program          = {}'.format(
            self.config.program.name if self.config.program else '<none set>'
        ))
        self.pprint('season           = {}'.format(
            self.config.season.number if self.config.season else '<none set>'
        ))
        self.pprint('')
        self.pprint('Ripping Configuration:')
        self.pprint('')
        self.pprint('target           = {}'.format(self.config.target))
        self.pprint('temp             = {}'.format(self.config.temp))
        self.pprint('template         = {}'.format(self.config.template))
        self.pprint('id_template      = {}'.format(self.config.id_template))
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
        self.pprint('dvdnav           = {}'.format(
            ['no', 'yes'][self.config.dvdnav]))

    def do_dvdnav(self, arg):
        """
        Sets whether libdvdnav or libdvdread are used by HandBrake.

        Syntax: dvdnav <off|on>

        The 'dvdnav' command is used to configure the library HandBrake will
        use for reading DVDs. The default is 'on' meaning that libdvdnav will
        be used; if 'off' is specified, libdvdread will be used instead. For
        example:

        (tvrip) dvdnav off
        (tvrip) dvdnav on
        """
        self.config.dvdnav = self.parse_bool(arg)

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
        except CmdError as e:
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

    def do_duplicates(self, arg):
        """
        Sets how duplicate titles on a disc are handled.

        Syntax: duplicates <all|first|last>

        The 'duplicates' command is used to configure how tvrip should handle
        duplicate titles on a disc. Duplicate titles are defined as consecutive
        titles with precisely the same length (these are commonly found in some
        collections, e.g. where separate titles have been defined simply for
        audio commentaries).

        The default is 'all' which means duplicate titles should be treated
        normally and included along with all other titles for auto-mapping.
        When set to 'first', only the first title of a duplicate set will be
        considered for auto-mapping. Likewise, 'last' includes only the last
        title of a duplicate set on the disc. Duplicates can still be manually
        mapped and ripped; this option only affects auto-mapping. Examples:

        (tvrip) duplicates first
        (tvrip) duplicates all
        """
        arg = arg.strip().lower()
        if arg not in ('all', 'first', 'last'):
            raise CmdSyntaxError(
                '"{}" is not a valid option for duplicates'.format(arg))
        self.config.duplicates = arg

    def do_path(self, arg):
        """
        Sets a path to an external utility.

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
        """
        Sets the list of audio languages to rip.

        Syntax: audio_langs <lang>...

        The 'audio_langs' command sets the list of languages for which audio
        tracks will be extracted and converted. Languages are specified as
        space separated lowercase 3-character ISO639 codes. For example:

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
            self.session.add(AudioLanguage(self.config, lang=lang))

    def do_audio_mix(self, arg):
        """
        Sets the audio mixdown

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
        """
        Sets whether to extract all language-matched audio tracks

        Syntax: audio_all <off|on>

        The 'audio_all' command specifies whether, of the audio tracks which
        match the specified languages (see the 'audio_langs' command), only the
        best track should be extracted, or all matching tracks. For example:

        (tvrip) audio_tracks off
        (tvrip) audio_tracks on
        """
        self.config.audio_all = self.parse_bool(arg)

    def do_subtitle_langs(self, arg):
        """
        Sets the list of subtitle languages to rip.

        Syntax: subtitle_langs <lang>...

        The 'subtitle_langs' command sets the list of languages for which
        subtitle tracks will be extracted and converted. Languages are
        specified as space separated lowercase 3-character ISO639 codes. For
        example:

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
            self.session.add(SubtitleLanguage(self.config, lang=lang))

    def do_subtitle_format(self, arg):
        """
        Sets the subtitle extraction mode

        Syntax: subtitle_format <format>

        The 'subtitle_format' command sets the subtitles extraction mode used
        by the 'rip' command. The valid formats are 'none' indicating that
        subtitles should not be extracted at all, 'vobsub' which causes
        subtitles to be extracted as timed image overlays, 'cc' which causes
        text-based closed captions to be embedded in the resulting MP4, or
        'any' which indicates any format of subtitle should be accepted.  Be
        aware that text-based closed captions do not work with several players.
        For example:

        (tvrip) subtitle_format vobsub
        (tvrip) subtitle_format none
        """
        try:
            arg = {
                'off':    'none',
                'none':   'none',
                'vob':    'vobsub',
                'vobsub': 'vobsub',
                'bmp':    'vobsub',
                'bitmap': 'vobsub',
                'cc':     'cc',
                'text':   'cc',
                'any':    'any',
                'all':    'any',
                'both':   'any',
                }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(
                'Invalid subtitle extraction mode {}'.format(arg))
        self.config.subtitle_format = arg

    def do_subtitle_all(self, arg):
        """
        Sets whether to extract all language-matched subtitles

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
        """
        Sets the decomb option for video conversion.

        Syntax: decomb <off|on|auto>

        The 'decomb' command sets the decomb setting for the video converter.
        Valid settings are currently 'off', 'on', and 'auto'. For example:

        (tvrip) decomb off
        (tvrip) decomb on
        """
        try:
            self.config.decomb = ['off', 'on'][self.parse_bool(arg)]
        except ValueError:
            if arg.strip().lower() == 'auto':
                self.config.decomb = 'auto'
            else:
                raise

    def do_duration(self, arg):
        """
        Sets range of episode duration.

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
        elif op != 'del':
            raise CmdSyntaxError(
                'Episode operation must be one of insert/update/delete')
        try:
            number = int(number)
        except ValueError:
            raise CmdSyntaxError(
                '{} is not a valid episode number'.format(number))

        if op == 'ins':
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
        elif op == 'upd':
            episode = self.parse_episode(number)
            episode.name = name
            self.pprint(
                'Renamed episode {episode} of season {season} '
                'of {program}'.format(
                    episode=episode.number,
                    season=episode.season.number,
                    program=episode.season.program.name))
        elif op == 'del':
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
        else:
            assert False

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
            episode = Episode(season, number, name)
            self.session.add(episode)

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

    def do_season(self, arg):
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
        if arg < 1:
            raise CmdSyntaxError(
                'A season number must be 1 or higher '
                '({} specified)'.format(arg))
        self.config.season = self.session.query(Season).get(
            (self.config.program.name, arg))
        if self.config.season is None:
            self.config.season = Season(self.config.program, arg)
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
            str(season.number) for season in
            self.session.query(
                    Season
                ).filter(
                    (Season.program==self.config.program) &
                    ("SUBSTR(CAST(season AS TEXT), 1, :length) = :season")
                ).params(
                    length=len(text),
                    season=text
                )
            ]

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
            new_program = Program(name=arg)
            self.session.add(new_program)
            try:
                count = int(self.input(
                    'Program {} is new. How many seasons exist (enter '
                    '0 if you do not wish to define seasons and episodes '
                    'at this time)? [0-n] '.format(
                        new_program.name)))
            except ValueError:
                while True:
                    try:
                        count = int(self.input(
                            'Invalid input. Please enter a number [0-n] '))
                    except ValueError:
                        pass
                    else:
                        break
            self.config.program = new_program
            self.config.season = None
            for number in range(1, count + 1):
                self.do_season(number)
        self.config.season = self.session.query(
                Season
            ).filter(
                (Season.program==new_program)
            ).order_by(
                Season.number
            ).first()
        self.config.program = new_program
        self.episode_map.clear()
        self.map_ripped()

    program_re = re.compile(r'^program\s+')
    def complete_program(self, text, line, start, finish):
        "Auto-completer for program command"
        match = self.program_re.match(line)
        name = str(line[match.end():])
        return [
            program.name[start - match.end():] for program in
            self.session.query(Program).filter(Program.name.startswith(name))
            ]

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

        Syntax: play <title[.chapter]>

        The 'play' command plays the specified title (and optionally chapter)
        of the currently scanned disc. Note that a disc must be scanned before
        this command can be used. VLC will be started at the specified location
        and must be quit before the command prompt will return.

        See also: scan, disc
        """
        if not arg:
            raise CmdSyntaxError('You must specify something to play')
        try:
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
            if title.duplicate == 'no'
            or self.config.duplicates == 'all'
            or self.config.duplicates == title.duplicate
            ]
        try:
            self.episode_map.automap(
                titles, episodes, self.config.duration_min,
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

        Syntax: map [episode title[.start-end]]

        The 'map' command is used to define which title on the disc contains
        the specified episode. This is used when constructing the filename of
        ripped episodes. For example:

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
            title = target
            self.pprint(
                'Mapping title {title} (duration {duration}) to episode '
                '{episode_num}, "{episode_title}"'.format(
                    title=title.number,
                    duration=title.duration,
                    episode_num=episode.number,
                    episode_title=episode.name))
            self.episode_map[episode] = title
        else:
            start, end = target
            if start.title == end.title:
                index = (
                    '{title}.{start:02d}-{end:02d}'.format(
                    title=start.title.number,
                    start=start.number,
                    end=end.number))
            else:
                index = (
                    '{st}.{sc:02d}-{et}.{ec:02d}'.format(
                    st=start.title.number,
                    sc=start.number,
                    et=end.title.number,
                    ec=end.number))
            self.pprint(
                'Mapping chapters {index} (duration {duration}) '
                'to episode {episode_num}, "{episode_title}"'.format(
                    index=index,
                    duration=sum((
                        chapter.duration
                        for title in start.title.disc.titles
                        for chapter in title.chapters
                        if (
                            (start.title.number, start.number) <=
                            (title.number, chapter.number) <=
                            (end.title.number, end.number))
                        ), timedelta()),
                    episode_num=episode.number,
                    episode_title=episode.name))
            self.episode_map[episode] = (start, end)

    def get_map(self):
        self.pprint('Episode Mapping (* indicates ripped):')
        self.pprint('')
        if self.episode_map:
            for episode, mapping in self.episode_map.items():
                if isinstance(mapping, Title):
                    index = '{}'.format(mapping.number)
                    duration = str(mapping.duration)
                else:
                    start, end = mapping
                    if start.title == end.title:
                        index = (
                            '{title}.{start:02d}-{end:02d}'.format(
                            title=start.title.number,
                            start=start.number,
                            end=end.number))
                    else:
                        index = (
                            '{st}.{sc:02d}-{et}.{ec:02d}'.format(
                            st=start.title.number,
                            sc=start.number,
                            et=end.title.number,
                            ec=end.number))
                    duration = sum((
                        chapter.duration
                        for title in start.title.disc.titles
                        for chapter in title.chapters
                        if (
                            (start.title.number, start.number) <=
                            (title.number, chapter.number) <=
                            (end.title.number, end.number))
                        ), timedelta())
                self.pprint(
                    '{ripped:2s}title {title:<11s} ({duration}) = '
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
            if self.config.in_subtitle_langs(t.language)
            and (
                t.format == self.config.subtitle_format
                or self.config.subtitle_format == 'any'
                )
            ]
        if not self.config.subtitle_all:
            subtitle_tracks = [t for t in subtitle_tracks if t.best]
        if len(episodes) == 1:
            self.pprint(
                'Ripping episode {episode.number}, '
                '"{episode.name}"'.format(episode=episode))
        else:
            self.pprint(
                'Ripping episodes {numbers}, {title}'.format(
                    numbers=' '.join(str(e.number) for e in episodes),
                    title=multipart.name(episodes)))
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

    def do_source(self, arg):
        """
        Sets the source device.

        Syntax: source <device>

        The 'source' command sets a new source device. The home directory
        shorthand (~) may be used in the specified path. For example:

        (tvrip) source /dev/dvd
        (tvrip) source /dev/sr0

        See also: target, temp
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
        """
        Sets the target path.

        Syntax: target <path>

        The 'target' command sets a new target path. The home-directory
        shorthand (~) may be used in the specified path. For example:

        (tvrip) target ~/Videos

        See also: source, temp
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            raise CmdError('Path {} does not exist'.format(arg))
        if not os.path.isdir(arg):
            raise CmdError('Path {} is not a directory'.format(arg))
        self.config.target = arg

    target_re = re.compile(r'^target\s+')
    def complete_target(self, text, line, start, finish):
        return self.complete_path(text, self.target_re.sub('', line),
                start, finish)

    def do_temp(self, arg):
        """
        Sets the temporary files path.

        Syntax: temp <path>

        The 'temp' command sets the path which will be used for temporary
        storage (actually a temporary directory under this path is used). The
        home-directory shorthand (~) may be used, but be aware that no spaces
        are permitted in the path name. For example:

        (tvrip) temp ~/tmp
        (tvrip) temp /var/tmp

        See also: source, target
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            raise CmdError('Path {} does not exist'.format(arg))
        if not os.path.isdir(arg):
            raise CmdError('Path {} is not a directory'.format(arg))
        self.config.temp = arg

    temp_re = re.compile(r'^temp\s+')
    def complete_temp(self, text, line, start, finish):
        return self.complete_path(text, self.temp_re.sub('', line),
                start, finish)

    def do_template(self, arg):
        """
        Sets the template used for filenames.

        Syntax: template <string>

        The 'template' command sets the new filename template. The template is
        specified as a Python format string including named subsitution markers
        (program, id, and name). The format-string is specified
        without quotation marks. For example:

        (tvrip) template {program} - {id} - {name}.mp4
        (tvrip) template {id}_{name}.mp4

        See also: id_template
        """
        try:
            arg.format(
                program='Program Name',
                id='1x01',
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

    def do_id_template(self, arg):
        """
        Sets the template used for the {id} component of filenames.

        Syntax: id_template <string>

        The 'id_template' command sets the new template used to form the {id}
        component in the filename template. The template is specified as a
        Python format string include named substitution markers (season, and
        episode). The format-string is specified without quotation marks. For
        example:

        (tvrip) id_template {season}x{episode:02d}
        (tvrip) id_template S{season:02d}E{episode02d}

        See also: template
        """
        try:
            arg.format(
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
        self.config.id_template = arg
