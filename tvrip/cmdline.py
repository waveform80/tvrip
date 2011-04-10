# vim: set et sw=4 sts=4:

import os
import re
import readline
import sqlalchemy as sa
from itertools import izip, groupby
from operator import attrgetter, itemgetter
from cmd import Cmd
from textwrap import TextWrapper
from datetime import timedelta
from tvrip.const import ENCODING
from tvrip.termsize import terminal_size
from tvrip.ripper import Disc, Title, Chapter
from tvrip.database import init_session, Configuration, Program, Season, Episode, AudioLanguage, SubtitleLanguage

class CmdError(Exception):
    u"""Base class for non-fatal Cmd errors"""

class CmdSyntaxError(CmdError):
    u"""Exception raised when the user makes a syntax error"""


class RipCmd(Cmd):
    use_rawinput = True
    prompt = u'tvr> '

    def __init__(self, debug=False):
        Cmd.__init__(self)
        self.discs = {}
        self.map = {}
        self.wrapper = TextWrapper()
        self.session = init_session(debug=debug)
        # Read the configuration from the database
        try:
            self.config = self.session.query(Configuration).one()
        except sa.orm.exc.NoResultFound:
            self.config = Configuration()
            self.session.add(self.config)
            self.session.add(AudioLanguage(u'eng'))
            self.session.add(SubtitleLanguage(u'eng'))
            self.session.commit()

    def _get_disc(self):
        return self.discs.get(self.config.source, None)
    def _set_disc(self, value):
        if self.config.source is None:
            raise CmdError(u'No source has been specified')
        elif self.config.source in self.discs:
            # XXX assert that no background jobs are currently running
            pass
        self.discs[self.config.source] = value
    disc = property(_get_disc, _set_disc)

    def default(self, line):
        raise CmdSyntaxError(u'Syntax error: %s' % line)

    def emptyline(self):
        # Do not repeat commands when given an empty line
        pass

    def precmd(self, line):
        # Ensure input is given as unicode
        return line.decode(ENCODING)

    def onecmd(self, line):
        # Just catch and report CmdError's; don't terminate execution because
        # of them
        try:
            return Cmd.onecmd(self, line)
        except CmdError, e:
            self.pprint(str(e) + u'\n')

    whitespace_re = re.compile(ur'\s+$')
    def wrap(self, s, newline=True, wrap=True, initial_indent=u'',
            subsequent_indent=u''):
        suffix = u''
        if newline:
            suffix = u'\n'
        elif wrap:
            match = self.whitespace_re.search(s)
            if match:
                suffix = match.group()
        if wrap:
            w = self.wrapper
            w.width = terminal_size()[0] - 2
            w.initial_indent = initial_indent
            w.subsequent_indent = subsequent_indent
            s = w.fill(s)
        return s + suffix

    def input(self, prompt=u''):
        lines = self.wrap(prompt, newline=False).split(u'\n')
        prompt = lines[-1]
        s = u''.join(line + u'\n' for line in lines[:-1])
        if isinstance(s, unicode):
            s = s.encode(ENCODING)
        self.stdout.write(s)
        return raw_input(prompt).decode(ENCODING).strip()

    def pprint(self, s, newline=True, wrap=True,
            initial_indent=u'', subsequent_indent=u''):
        s = self.wrap(s, newline, wrap, initial_indent, subsequent_indent)
        if isinstance(s, unicode):
            s = s.encode(ENCODING)
        self.stdout.write(s)

    def parse_docstring(self, s):
        lines = [line.strip() for line in s.splitlines()]
        result = ['']
        for line in lines:
            if result:
                if line:
                    if line.startswith(u'tvr>'):
                        if result[-1]:
                            result.append(line)
                        else:
                            result[-1] = line
                    else:
                        if result[-1]:
                            result[-1] += ' ' + line
                        else:
                            result[-1] = line
                else:
                    result.append('')
        if not result[-1]:
            result = result[:-1]
        return result

    def do_help(self, arg):
        u"""Displays the available commands or help on a specified command.

        The 'help' command is used to display the help text for a command or,
        if no command is specified, it presents a list of all available
        commands along with a brief description of each.
        """
        if arg:
            extra_line = False
            paras = self.parse_docstring(getattr(self, u'do_%s' % arg).__doc__)
            for para in paras[1:]:
                if para.startswith(u'tvr>'):
                    self.pprint('  ' + para, wrap=False)
                else:
                    self.pprint(para)
                    self.pprint('')
            if paras[-1].startswith(u'tvr>'):
                self.pprint('')
        else:
            commands = [
                (method[3:], self.parse_docstring(getattr(self, method).__doc__)[0])
                for method in self.get_names()
                if method.startswith(u'do_')
                and method != u'do_EOF'
            ]
            # Size the column containing the method names, ensuring it is no
            # wider than one third of the terminal width
            maxlen = min(
                max(len(command) for (command, help) in commands) + 2,
                terminal_size()[0] / 3
            )
            indent = ' ' * maxlen
            for (command, help) in commands:
                if len(command) <= maxlen:
                    self.pprint(u'%-*s%s' % (maxlen, command, help),
                        subsequent_indent=indent)
                else:
                    self.pprint(command)
                    self.pprint(help, initial_indent=indent,
                        subsequent_indent=indent)

    def do_exit(self, arg):
        u"""Exits from the application.

        Syntax: exit

        The 'exit' command is used to terminate the application. You can also
        use the standard UNIX Ctrl+D end of file sequence to quit.
        """
        self.pprint(u'')
        self.session.commit()
        return True

    def do_config(self, arg):
        u"""Shows the current set of configuration options.

        Syntax: config

        The 'config' command simply outputs the current set of configuration
        options as set by the various other commands.
        """
        self.pprint(u'source          = %s' % self.config.source)
        self.pprint(u'target          = %s' % self.config.target)
        self.pprint(u'temp            = %s' % self.config.temp)
        self.pprint(u'duration        = %d-%d (mins)' % (self.config.duration_min.seconds / 60, self.config.duration_max.seconds / 60))
        self.pprint(u'program         = %s' % (self.config.program.name if self.config.program else '<none set>'))
        self.pprint(u'season          = %s' % (self.config.season.number if self.config.season else '<none set>'))
        self.pprint(u'template        = %s' % self.config.template)
        self.pprint(u'decomb          = %s' % self.config.decomb)
        self.pprint(u'audio_mix       = %s' % self.config.audio_mix)
        self.pprint(u'audio_tracks    = %s' % self.config.audio_tracks)
        self.pprint(u'audio_langs     = %s' % u' '.join(l.lang for l in self.config.audio_langs))
        self.pprint(u'subtitle_format = %s' % self.config.subtitle_format)
        self.pprint(u'subtitle_tracks = %s' % self.config.subtitle_tracks)
        self.pprint(u'subtitle_black  = %s' % self.config.subtitle_black)
        self.pprint(u'subtitle_langs  = %s' % u' '.join(l.lang for l in self.config.subtitle_langs))
        self.pprint(u'')
        self.pprint(u'Episode mapping (* indicates ripped):')
        for episode, mapping in sorted(self.map.iteritems(), key=lambda t: t[0].number):
            if isinstance(mapping, Title):
                mapping = '%.2d' % mapping.number
            else:
                chapter_start, chapter_end = mapping
                mapping = '%.2d.%.02d-%.02d' % (chapter_start.title.number, chapter_start.number, chapter_end.number)
            self.pprint(u'%2stitle %s -> episode %2d, "%s"' % (
                u'*' if episode.ripped else u' ',
                mapping,
                episode.number,
                episode.name
            ))

    def do_audio_langs(self, arg):
        u"""Sets the list of audio languages to rip.

        Syntax: audio_langs lang1 lang2...

        The 'audio_langs' command sets the list of languages for which audio
        tracks will be extracted and converted. Languages are specified as
        lowercase 3-character ISO639 codes. For example:

        tvr> audio_langs eng jpn
        tvr> audio_langs eng
        """
        arg = arg.lower().split(u' ')
        new_langs = set(arg)
        for lang in self.config.audio_langs:
            if lang.lang in new_langs:
                new_langs.remove(lang.lang)
            else:
                self.session.delete(lang)
        for lang in new_langs:
            self.session.add(AudioLanguage(lang))
        self.session.commit()

    def do_audio_mix(self, arg):
        u"""Sets the audio mixdown

        Syntax: audio_mix <mix-value>

        The 'audio_mix' command sets the audio mixdown used by the 'rip'
        command.  The valid mixes are 'mono', 'stereo', 'dpl1', and 'dpl2' with
        the latter two indicating Dolby Pro Logic I and II respectively. AC3 or
        DTS pass-thru cannot be configured at this time. For example:

        tvr> audio_mix stereo
        tvr> audio_mix dpl2
        """
        try:
            arg = {
                u'mono':     u'mono',
                u'm':        u'mono',
                u'1':        u'mono',
                u'stereo':   u'stereo',
                u's':        u'stereo',
                u'2':        u'stereo',
                u'dpl1':     u'dpl1',
                u'dpl2':     u'dpl2',
                u'surround': u'dpl2',
                u'prologic': u'dpl2',
            }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(u'Invalid audio mix %s' % arg)
        self.config.audio_mix = arg
        self.session.commit()

    def do_audio_tracks(self, arg):
        u"""Sets which audio tracks to extract

        Syntax: audio_tracks <best|all>

        The 'audio_tracks' command specifies whether, of the audio tracks which
        match the specified languages (see the 'audio_langs' command), only the
        best track should be extracted, or all matching tracks. For example:

        tvr> audio_tracks best
        tvr> audio_tracks all
        """
        try:
            arg = {
                u'best':  u'best',
                u'1':     u'best',
                u'all':   u'all',
                u'*':     u'all',
            }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(u'Invalid audio track selection %s' % arg)
        self.config.audio_tracks = arg
        self.session.commit()

    def do_subtitle_langs(self, arg):
        u"""Sets the list of subtitle languages to rip.

        Syntax: subtitle_langs lang1 lang2...

        The 'subtitle_langs' command sets the list of languages for which
        subtitle tracks will be extracted and converted. Languages are
        specified as lowercase 3-character ISO639 codes. For example:

        tvr> subtitle_langs eng jpn
        tvr> subtitle_langs eng
        """
        arg = arg.lower().split(u' ')
        new_langs = set(arg)
        for lang in self.config.subtitle_langs:
            if lang.lang in new_langs:
                new_langs.remove(lang.lang)
            else:
                self.session.delete(lang)
        for lang in new_langs:
            self.session.add(SubtitleLanguage(lang))
        self.session.commit()

    def do_subtitle_format(self, arg):
        u"""Sets the subtitle extraction mode

        Syntax: subtitle_format <format>

        The 'subtitle_format' command sets the subtitles extraction mode used
        by the 'rip' command. The valid formats are 'none' indicating that
        subtitles should not be extracted at all, 'vobsub' which causes
        subtitles to be extracted as timed image overlays, and 'subrip' which
        causes subtitles to be extracted and converted to a text-based subtitle
        format via OCR.  For example:

        tvr> subtitle_format subrip
        tvr> subtitle_format vobsub
        tvr> subtitle_format none
        """
        try:
            arg = {
                u'off':    u'none',
                u'none':   u'none',
                u'vob':    u'vobsub',
                u'vobsub': u'vobsub',
                u'srt':    u'subrip',
                u'subrip': u'subrip',
            }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(u'Invalid subtitle extraction mode %s' % arg)
        self.config.subtitle_format = arg
        self.session.commit()

    def do_subtitle_black(self, arg):
        u"""Sets the subtitle black color

        Syntax: subtitle_black <number>

        The 'subtitle_black' command specifies which of the four colors in the
        subtitle track is rendered as black. This is used when the subtitle
        extraction mode is 'subrip' and is only needed when the default (3)
        doesn't give good OCR results. In 'vobsub' mode the coloring specified
        by the DVD itself is used for extraction, but this is generally not
        suitable for OCR (as it typically includes grayscales for softer
        edges). The valid values for the number are 1 to 4. For example:

        tvr> subblack 3
        tvr> subblack 1

        After changing this value, test whether the results look right with the
        'subtest' command. The desired effect is to have the words of the
        subtitles rendered in solid black on a white background with no
        outline.
        """
        try:
            arg = int(arg.strip())
            if not 1 <= arg <= 4:
                raise ValueError()
        except ValueError:
            raise CmdSyntaxError('Invalid color %s - must be a number from 1 to 4' % arg)
        self.config.subtitle_black = arg
        self.session.commit()

    def do_subtitle_tracks(self, arg):
        u"""Sets which subtitle tracks to extract

        Syntax: subtitle_tracks <best|all>

        The 'subtitle_tracks' command specifies whether, of the subtitle tracks
        which match the specified languages (see the 'subtitle_langs' command),
        only the best matching track should be extracted, or all matching
        tracks. For example:

        tvr> subtitle_tracks best
        tvr> subtitle_tracks all
        """
        try:
            arg = {
                u'best':  u'best',
                u'1':     u'best',
                u'all':   u'all',
                u'*':     u'all',
            }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(u'Invalid subtitle track selection %s' % arg)
        self.config.subtitle_tracks = arg
        self.session.commit()

    def do_subresetdb(self, arg):
        u"""Resets the OCR database for the current program.

        Syntax: subresetdb

        The 'subresetdb' command is used to wipe the OCR database of the
        currently selected program. When the subtitle conversion mode is
        'subrip', the OCR application builds up a database mapping images to
        characters. Each database is specific to a program as different
        programs tend to use different subtitle styles on their DVDs. However,
        in some cases a program may change its subtitle style between seasons,
        or even within a season in some rare cases. This may lead to
        recognition problems in which case this command can be used to clear
        the database and allow it to start being built from scratch with the
        next ripped episode.
        """
        if self.config.program:
            self.config.program.reset_db()
            self.pprint(u'Reset OCR database in %s' % self.config.program.dbpath)
        else:
            raise CmdError(u'No program has been set')

    def do_decomb(self, arg):
        u"""Sets the decomb option for video conversion.

        Syntax: decomb <option>

        The 'decomb' command sets the decomb setting for the video converter.
        Valid settings are currently 'off', 'on', and 'auto'. For example:

        tvr> decomb off
        tvr> decomb on
        """
        try:
            arg = {
                u'off':   u'off',
                u'false': u'off',
                u'0':     u'off',
                u'on':    u'on',
                u'true':  u'on',
                u'1':     u'on',
                u'auto':  u'auto',
            }[arg.strip().lower()]
        except KeyError:
            raise CmdSyntaxError(u'Invalid decomb option %s' % arg)
        self.config.decomb = arg
        self.session.commit()

    def do_duration(self, arg):
        u"""Sets range of episode duration.

        Syntax: duration <min>-<max>

        The 'duration' command sets the minimum and maximum length (in minutes)
        that an episode is expected to be.  This is used when scanning a source
        device for titles which are likely to be episodes. For example:

        tvr> duration 40-50
        tvr> duration 25-35
        """
        try:
            self.config.duration_min, self.config.duration_max = (
                timedelta(minutes=int(i))
                for i in arg.split(u'-', 1)
            )
            self.session.commit()
        except (TypeError, ValueError):
            self.pprint(u'Invalid durations given: %s' % arg)

    def do_episode(self, arg):
        u"""Sets the name of a single episode.

        Syntax: episode <number> <name>

        The 'episode' command can be used to display the name of the
        specified episode or, if two arguments are given, will redefine the
        name of the specified episode.
        """
        if arg:
            (number, name) = arg.split(u' ', 1)
            try:
                number = int(number)
            except ValueError:
                raise CmdError(u'Episode number was not valid (%s specified)' % number)
            if number < 1:
                raise CmdError(u'An episode number must be 1 or higher (%d specified)' % number)
            if not self.config.season:
                raise CmdError(u'No season has been set')
            try:
                e = self.session.query(Episode).\
                    filter(Episode.season==self.config.season).\
                    filter(Episode.number==number).one()
            except sa.orm.exc.NoResultFound:
                e = Episode(self.config.season, number, name)
                self.pprint(u'Added episode %d of season %d of '
                    u'program %s' % (e.number, e.season.number, e.season.program.name))
            else:
                e.name = name
                self.pprint(u'Renamed episode %d of season %d of '
                    u'program %s' % (e.number, e.season.number, e.season.program.name))
            self.session.commit()
        else:
            raise CmdError(u'You must specify an episode number')

    def do_episodes(self, arg):
        u"""Gets or sets the episodes for the current season.

        Syntax: episodes [number]

        The 'episodes' command can be used to list the episodes of the
        currently selected season of the program. If an argument is given, the
        current episode list is deleted and you will be prompted to enter
        names for the specified number of episodes.

        If you simply wish to change the name of a single episode, see the
        'episode' command instead.
        """
        if arg:
            if not self.config.season:
                raise CmdError(u'No season has been set')
            start = 1
            count = int(arg)
            if count < 1:
                raise CmdSyntaxError(u'A season must contain at least 1 or more '
                    u'episodes (%d specified)' % count)
            elif count > 100:
                raise CmdSyntaxError(u'%d episodes in a single season? '
                    u'I don\'t believe you...' % count)
            else:
                self.pprint(u'Please enter the names of the episodes. Leave a '
                    u'name blank if you wish to terminate entry early:')
                self.session.begin(subtransactions=True)
                try:
                    for e in self.session.query(Episode).filter(Episode.season==self.config.season):
                        self.session.delete(e)
                    for number in range(start, count + start):
                        name = self.input(u'%2d: ' % number)
                        if not name:
                            self.pprint(u'Terminating episode name entry')
                            break
                        e = Episode(self.config.season, number, name)
                        self.session.add(e)
                except:
                    self.session.rollback()
                    raise
                else:
                    self.session.commit()
            self.map = {}
        elif self.config.season:
            self.pprint(u'Episodes for season %d of program %s (* indicates ripped):' % (self.config.season.number, self.config.program.name))
            for e in self.session.query(Episode).filter(Episode.season==self.config.season):
                self.pprint(u'%1s%2d: %s' % (u'*' if e.ripped else u'', e.number, e.name))
        else:
            raise CmdError(u'No season has been set')

    def do_season(self, arg):
        u"""Sets which season of the program the disc contains.

        Syntax: season <number>

        The 'season' command specifies the season the disc contains episodes
        for. This number is used when constructing the filename of ripped
        episodes.

        This command is also used to expand the episode database. If the number
        given does not exist, it will be entered into the database under the
        current program and you will be prompted for episode names.
        """
        if not self.config.program:
            raise CmdError(u'You must specify a program first')
        try:
            arg = int(arg)
        except ValueError:
            raise CmdSyntaxError(u'A season must be a valid number (%s specified)' % arg)
        if arg < 1:
            raise CmdSyntaxError(u'A season number must be 1 or higher (%d specified)' % arg)
        if not self.config.season or self.config.season.number != arg:
            try:
                self.config.season = self.session.query(Season).\
                    filter(Season.program==self.config.program).\
                    filter(Season.number==arg).one()
            except sa.orm.exc.NoResultFound:
                self.session.begin(subtransactions=True)
                try:
                    self.config.season = Season(self.config.program, arg)
                    self.session.add(self.config.season)
                    try:
                        count = int(self.input(u'Season %d of program %s '
                            u'is new. Please enter the number of episodes '
                            u'in this season (enter 0 if you do not wish '
                            u'to define episodes at this time) [0-n] ' % (
                            self.config.season.number, self.config.program.name)))
                    except ValueError:
                        while True:
                            try:
                                count = int(self.input(u'Invalid input. '
                                    u'Please enter a number [0-n] '))
                            except ValueError:
                                pass
                            else:
                                break
                    if count != 0:
                        self.onecmd(u'episodes %d' % count)
                except:
                    self.session.rollback()
                    raise
                else:
                    self.session.commit()
            self.map = {}

    def complete_season(self, text, line, start, finish):
        return [
            unicode(season.number) for season in
            self.session.query(Season).\
            filter(Season.program==self.config.program).\
            filter(u"SUBSTR(CAST(season AS TEXT), 1, :length) = :season").\
            params(length=len(text), season=text)
        ]

    def do_seasons(self, arg):
        u"""Shows the defined seasons of the current program.

        Syntax: seasons

        The 'seasons' command outputs the list of seasons defined for the
        current program, along with a summary of how many episodes are defined
        for each season.
        """
        if self.config.program:
            count = 0
            for season in self.session.query(Season).filter(Season.program==self.config.program).order_by(Season.number):
                self.pprint(u'Season %d has %d episode(s)' % (
                    season.number,
                    len(season.episodes),
                ))
                count += 1
            if not count:
                self.pprint(u'No seasons have been defined for program %s' % self.config.program.name)
        else:
            raise CmdError(u'No program has been set')

    def do_program(self, arg):
        u"""Sets the name of the program.

        Syntax: program <name>

        The 'program' command specifies the program the disc contains episodes
        for. This is used when constructing the filename of ripped episodes.

        This command is also used to expand the episode database. If the name
        given does not exist, it will be entered into the database and you will
        be prompted for season and episode information.
        """
        if self.config.program is None or self.config.program.name != arg:
            try:
                self.config.program = self.session.query(Program).\
                    filter(Program.name==arg).one()
            except sa.orm.exc.NoResultFound:
                self.session.begin(subtransactions=True)
                try:
                    self.config.program = Program(arg)
                    self.session.add(self.config.program)
                    try:
                        count = int(self.input(u'Program %s is new. How '
                            u'many seasons exist (enter 0 if you do not '
                            u'wish to define seasons and episodes at this '
                            u'time)? [0-n] ' % self.config.program.name))
                    except ValueError:
                        while True:
                            try:
                                count = int(self.input(u'Invalid input. '
                                    u'Please enter a number [0-n] '))
                            except ValueError:
                                pass
                            else:
                                break
                    for number in range(1, count + 1):
                        self.onecmd(u'season %d' % number)
                except:
                    self.session.rollback()
                    raise
                else:
                    self.session.commit()
            else:
                self.config.season = self.session.query(Season).\
                    filter(Season.program==self.config.program).\
                    order_by(Season.number).first()
            self.map = {}

    program_re = re.compile(ur'^program\s+')
    def complete_program(self, text, line, start, finish):
        match = self.program_re.match(line)
        name = line[match.end():]
        return [
            program.name[start - match.end():] for program in
            self.session.query(Program).filter(Program.name.startswith(name))
        ]

    def do_programs(self, arg):
        u"""Shows the defined programs.

        Syntax: programs

        The 'programs' command outputs the list of programs defined in the
        database, along with a summary of how many seasons and episodes are
        defined for each.
        """
        count = 0
        for (program, seasons, episodes) in self.session.query(
                    Program.name,
                    sa.func.count(Season.number.distinct()),
                    sa.func.count(Episode.number)
                ).outerjoin(Season).outerjoin(Episode).\
                group_by(Program.name).order_by(Program.name):
            self.pprint(u'Program %s has %d season(s) and %d episode(s)' % (program, seasons, episodes))
            count += 1
        if not count:
            self.pprint(u'No programs are defined')

    def do_scan(self, arg):
        u"""Scans the source device for episodes.

        Syntax: scan

        The 'scan' command scans the current source device to discover what
        titles, audio tracks, and subtitle tracks exist on the disc in the
        source device. Please note that scanning a disc erases the current
        episode mapping.
        """
        if not self.config.source:
            self.pprint(u'No source has been specified')
        elif not (self.config.duration_min and self.config.duration_max):
            self.pprint(u'No duration range has been specified')
        else:
            self.pprint(u'Scanning disc in %s' % self.config.source)
            self.map = {}
            self.disc = Disc()
            self.disc.scan(self.config.source)
            self.pprint(u'Disc serial: %s' % self.disc.serial)
            for title in self.disc.titles:
                self.pprint(u'Title %d (duration: %s)' % (
                    title.number,
                    title.duration,
                ))
                self.pprint(u'  %d chapters' % len(title.chapters))
                for chapter in title.chapters:
                    self.pprint(u'    %d: %s->%s (duration: %s)' % (
                        chapter.number,
                        chapter.start,
                        chapter.finish,
                        chapter.duration,
                    ))
                self.pprint(u'  %d audio tracks' % len(title.audio_tracks))
                for track in title.audio_tracks:
                    suffix = u''
                    if track.best and self.config.in_audio_langs(track.language):
                        suffix = u'[best]'
                    self.pprint(u'    %d: %s, %s %s %s %s' % (
                        track.number,
                        track.language,
                        track.name,
                        track.encoding,
                        track.channel_mix,
                        suffix
                    ))
                self.pprint(u'  %d subtitle tracks' % len(title.subtitle_tracks))
                for track in title.subtitle_tracks:
                    suffix = u''
                    if track.best and self.config.in_subtitle_langs(track.language):
                        suffix = u'[best]'
                    self.pprint(u'    %d: %s, %s %s' % (
                        track.number,
                        track.language,
                        track.name,
                        suffix
                    ))

    def do_map(self, arg):
        u"""Maps episodes to titles or chapter ranges.

        Syntax: map [<episode> <title>[.<start>-<end>]]

        The 'map' command is used to define which title on the disc contains
        the specified episode. This is used when constructing the filename of
        ripped episodes. For example:

        tvr> map 3 1
        tvr> map 7 4
        tvr> map 5 2.1-12

        If no arguments are specified, auto-mapping is attempted. This attempts
        to match titles to unripped episodes of the currently selected
        program's season based on the duration limits specified in the
        configuration. If direct title mapping fails, it attempts chapter-based
        mapping with the longest title on the disc.

        The current episode mapping can be viewed in the output of the 'config'
        command.
        """
        if not self.disc:
            raise CmdError(u'No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError(u'No titles found on the scanned disc')
        elif not self.config.program:
            raise CmdError(u'No program has been set')
        elif not self.config.season:
            raise CmdError(u'No season has been set')
        elif arg:
            try:
                episode, title = arg.split(u' ')
            except ValueError:
                raise CmdSyntaxError(u'You must specify two arguments')
            if u'.' in title:
                try:
                    title, chapters = title.split(u'.')
                    chapter_start, chapter_end = (int(i) for i in chapters.split(u'-'))
                except ValueError:
                    raise CmdSyntaxError(u'Unable to parse specified chapter range')
            else:
                chapter_start = chapter_end = None
            try:
                title = int(title)
                episode = int(episode)
            except ValueError:
                raise CmdSyntaxError(u'Titles, chapters, and episodes must be integer numbers')
            try:
                title = [t for t in self.disc.titles if t.number==title][0]
            except IndexError:
                raise CmdError(u'There is no title %d on the scanned disc' % title)
            if chapter_start:
                try:
                    chapter_start = [c for c in title.chapters if c.number==chapter_start][0]
                except IndexError:
                    raise CmdError(u'There is no chapter %d within title %d on the scanned disc' % (chapter_start, title.number))
            if chapter_end:
                try:
                    chapter_end = [c for c in title.chapters if c.number==chapter_end][0]
                except IndexError:
                    raise CmdError(u'There is no chapter %d within title %d on the scanned disc' % (chapter_end, title.number))
            try:
                episode = self.session.query(Episode).\
                    filter(Episode.season==self.config.season).\
                    filter(Episode.number==episode).one()
            except sa.orm.exc.NoResultFound:
                raise CmdError(u'There is no episode %d in the current season' % episode)
            if chapter_start:
                self.pprint(u'Mapping chapters %d-%d (duration %s) of title %d to episode %d, "%s"' % (
                    chapter_start.number,
                    chapter_end.number,
                    sum(
                        [c.duration for c in title.chapters if chapter_start.number <= c.number <= chapter_end.number],
                        timedelta()
                    ),
                    title.number,
                    episode.number,
                    episode.name
                ))
                self.map[episode] = (chapter_start, chapter_end)
            else:
                self.pprint(u'Mapping title %d (duration %s) to episode %d, "%s"' % (
                    title.number,
                    title.duration,
                    episode.number,
                    episode.name
                ))
                self.map[episode] = title
        else:
            self.map = {}
            # Map all the titles that have been previously ripped from this
            # disc
            unmapped = list(self.disc.titles)
            # XXX Note that there is a risk that this maps episodes from a
            # season or program other than those currently selected
            for episode in self.session.query(Episode).filter(Episode.disc_serial==self.disc.serial):
                try:
                    title = [t for t in self.disc.titles if t.number==episode.disc_title][0]
                except IndexError:
                    raise CmdError('Previously ripped title %d not found on the scanned disc (serial %s)' % (
                        episode.disc_title, episode.disc_serial))
                else:
                    if episode.start_chapter is not None:
                        self.do_map(u'%d %d.%d-%d' % (
                            episode.number,
                            title.number,
                            episode.start_chapter,
                            episode.end_chapter,
                        ))
                    else:
                        self.do_map(u'%d %d' % (episode.number, title.number))
                        unmapped.remove(title)
            # Attempt to map the remaining unmapped titles to unripped episodes
            # from the selected season
            unripped = [e for e in self.config.season.episodes if not e.disc_serial]
            # Bail out now if there's no unripped episodes left to be mapped
            if not unripped:
                return
            for title in list(unmapped):
                if self.config.duration_min <= title.duration <= self.config.duration_max:
                    self.do_map(u'%d %d' % (unripped.pop(0).number, title.number))
                    unmapped.remove(title)
                else:
                    self.pprint(u'Title %d is not an episode (duration: %s)' % (
                        title.number,
                        title.duration,
                    ))
            if len(self.disc.titles) == len(unmapped):
                self.pprint(u'Attempting to map chapters of longest title to episodes')
                # If we didn't manage to find a single title to map to an
                # episode it's possible we're dealing with one of those weird
                # discs where lots of episodes are in one title with chapters
                # delimiting the episodes. Firstly, find the longest title...
                for title in reversed(sorted(self.disc.titles, key=attrgetter('duration'))):
                    break
                self.pprint(u'Longest title is %d (duration: %s), containing %d chapters' % (
                    title.number,
                    title.duration,
                    len(title.chapters),
                ))
                # Now loop over the chapters of the longest title, attempting
                # to build up consecutive runs of chapters with a duration
                # between the required min and max
                episode_map = []
                current_duration = timedelta()
                current_episode = unripped.pop(0)
                for chapter in title.chapters:
                    episode_map.append(current_episode)
                    current_duration += chapter.duration
                    if self.config.duration_min <= current_duration <= self.config.duration_max:
                        # If got a run of chapters that fits the duration
                        # limit, get the next episode to try and match to some
                        # chapters
                        current_duration = timedelta()
                        if unripped:
                            current_episode = unripped.pop(0)
                        elif chapter is not title.chapters[-1]:
                            # If we've run out of unripped episodes, but we
                            # haven't run out of chapters consider the whole
                            # operation a bust and forget the whole mapping
                            self.pprint(u'Found more chapters than unripped episodes; aborting')
                            episode_map = []
                            break
                    elif current_duration > self.config.duration_max:
                        # Likewise, if at any point we wind up with a run of
                        # chapters that exceeds the maximum duration, quit in
                        # disgrace!
                        self.pprint(u'Exceeded maximum duration while aggregating chapters; aborting')
                        episode_map = []
                        break
                # If we've got stuff in episode_map it's guaranteed to be
                # exactly as long as title.chapters so zip 'em together and
                # group the result to map start and end chapters easily
                if episode_map:
                    for episode, chapters in groupby(izip(episode_map, title.chapters), key=itemgetter(0)):
                        chapters = [c for (e, c) in chapters]
                        self.do_map(u'%d %d.%d-%d' % (
                            episode.number,
                            chapters[0].title.number,
                            chapters[0].number,
                            chapters[-1].number, 
                        ))

    def do_unmap(self, arg):
        u"""Removes an episode mapping.

        Syntax: unmap <episode>

        The 'unmap' command is used to remove a title to episode mapping. For
        example, if the auto-mapping when scanning a disc makes an error, you
        can use the 'map' and 'unmap' commands to fix it. For example:

        tvr> unmap 3
        tvr> unmap 7
        """
        if not self.disc:
            raise CmdError(u'No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError(u'No titles found on the scanned disc')
        else:
            try:
                arg = int(arg)
            except ValueError:
                raise CmdSyntaxError(u'You must specify an integer title number')
            try:
                episode = [e for e in self.config.season.episodes if e.number==arg][0]
            except IndexError:
                raise CmdError(u'Episode %d does not exist within the selected season' % arg)
            self.pprint(u'Removing mapping for episode %d, %s' % (episode.number, episode.name))
            del self.map[episode]

    def do_rip(self, arg):
        u"""Starts the ripping and transcoding process.

        Syntax: rip

        The 'rip' command begins ripping the mapped titles from the current
        source device, converting them according to the current preferences,
        and storing the results in the target path. Only previously unripped
        episodes will be ripped. If you wish to re-rip an episode, use the
        'unrip' command to set it to unripped first.
        """
        if not self.disc:
            raise CmdError(u'No disc has been scanned yet')
        elif not self.disc.titles:
            raise CmdError(u'No titles found on the scanned disc')
        elif not self.map:
            raise CmdError(u'No titles have been mapped to episodes')
        elif arg.strip():
            raise CmdSyntaxError(u'You must not specify any arguments')
        for episode, mapping in sorted(self.map.iteritems(), key=lambda t: t[0].number):
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
                if self.config.audio_tracks == u'best':
                    audio_tracks = [t for t in audio_tracks if t.best]
                subtitle_tracks = [
                    t for t in title.subtitle_tracks
                    if self.config.in_subtitle_langs(t.language)
                ]
                if self.config.subtitle_tracks == u'best':
                    subtitle_tracks = [t for t in subtitle_tracks if t.best]
                self.pprint(u'Ripping episode %d, "%s"' % (
                    episode.number, episode.name))
                self.disc.rip(self.config, episode, title, audio_tracks, subtitle_tracks, chapter_start, chapter_end)
                episode.disc_serial = self.disc.serial
                episode.disc_title = title.number
                if chapter_start:
                    episode.start_chapter = chapter_start.number
                    episode.end_chapter = chapter_end.number
                else:
                    episode.start_chapter = None
                    episode.end_chapter = None
                self.session.commit()

    def do_unrip(self, arg):
        u"""Changes the status of the specified episode to unripped.

        Syntax: unrip <episode>

        The 'unrip' command is used to set the status of an episode to
        unripped. If you specify '*' as the episode, all episodes in the
        currently selected season will be set to unripped.

        Episodes are automatically set to ripped during the operation of the
        'rip' command.  Episodes marked as ripped will never be automatically
        mapped to titles by the 'map' command (although they can be mapped
        manually too). For example:

        tvr> unrip 3
        tvr> unrip 7
        """
        if not self.config.program:
            raise CmdError(u'No program has been set')
        elif not self.config.season:
            raise CmdError(u'No season has been set')
        else:
            if arg.strip() == u'*':
                for episode in self.config.season.episodes:
                    episode.disc_serial = None
                    episode.disc_title = None
                    episode.start_chapter = None
                    episode.end_chapter = None
            else:
                try:
                    arg = int(arg)
                except ValueError:
                    raise CmdSyntaxError(u'You must specify an integer episode number')
                try:
                    episode = self.session.query(Episode).\
                        filter(Episode.season==self.config.season).\
                        filter(Episode.number==arg).one()
                except sa.orm.exc.NoResultFound:
                    raise CmdError(u'Episode %d of %s season %d does not exist' % (
                        arg, self.config.program.name, self.config.season.number))
                episode.disc_serial = None
                episode.disc_title = None
                episode.start_chapter = None
                episode.end_chapter = None
            self.session.commit()

    def do_source(self, arg):
        u"""Sets the source device.

        Syntax: source <device>

        The 'source' command sets a new source device. The home directory
        shorthand (~) may be used in the specified path. For example:

        tvr> source /dev/dvd
        tvr> source /dev/sr0
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint(u'Path %s does not exist' % arg)
            return
        self.config.source = arg

    def complete_path(self, text, line, start, finish):
        dir, base = os.path.split(line)
        return [
            item
            for item in os.listdir(os.path.expanduser(dir))
            if item.startswith(text)
        ]

    source_re = re.compile(u'^source\s+')
    def complete_source(self, text, line, start, finish):
        return self.complete_path(text, self.source_re.sub('', line), start, finish)

    def do_target(self, arg):
        u"""Sets the target path.

        Syntax: target <path>

        The 'target' command sets a new target path. The home-directory
        shorthand (~) may be used in the specified path. For example:

        tvr> target ~/Videos
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint(u'Path %s does not exist' % arg)
            return
        if not os.path.isdir(arg):
            self.pprint(u'Path %s is not a directory' % arg)
            return
        self.config.target = arg

    target_re = re.compile(ur'^target\s+')
    def complete_target(self, text, line, start, finish):
        return self.complete_path(text, self.target_re.sub('', line), start, finish)

    def do_temp(self, arg):
        u"""Sets the temporary files path.

        Syntax: temp <path>

        The 'temp' command sets the path which will be used for temporary
        storage (actually a temporary directory under this path is used). The
        home-directory shorthand (~) may be used, but be aware that no spaces
        are permitted in the path name. For example:

        tvr> temp ~/tmp
        tvr> temp /var/tmp
        """
        arg = os.path.expanduser(arg)
        if not os.path.exists(arg):
            self.pprint(u'Path %s does not exist' % arg)
            return
        if not os.path.isdir(arg):
            self.pprint(u'Path %s is not a directory' % arg)
            return
        self.config.temp = arg

    temp_re = re.compile(ur'^temp\s+')
    def complete_temp(self, text, line, start, finish):
        return self.complete_path(text, self.temp_re.sub('', line), start, finish)

    def do_template(self, arg):
        u"""Sets the template used for filenames.

        Syntax: template <string>

        The 'template' command sets the new filename template. The template is
        specified as a Python format string including named subsitution markers
        (program, season, episode, and name). The format-string is specified
        without quotation marks.
        """
        try:
            testname = arg % {
                'program': 'Program Name',
                'season':  1,
                'episode': 10,
                'name':    'Foo Bar',
            }
        except KeyError, e:
            raise CmdError('The new template contains an invalid substitution key: %s' % e)
        self.config.template = arg

    do_EOF = do_exit


