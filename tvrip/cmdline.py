# vim: set et sw=4 sts=4:

import os
import re
import readline
import sqlalchemy as sa
from cmd import Cmd
from textwrap import TextWrapper
from datetime import timedelta
from tvrip.const import ENCODING
from tvrip.termsize import terminal_size
from tvrip.ripper import Disc
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

    def do_languages(self, arg):
        u"""Gets/sets the list of audio/subtitle languages to rip.

        Syntax: languages [<audio|subtitle|both> lang1 lang2 ...]

        The 'languages' command with no arguments prints the current list of
        languages for which audio and subtitle tracks will be extracted and
        converted. With one or more arguments it sets the list of languages for
        which audio or subtitle tracks will be extracted, replacing the
        originally configured set. Languages are specified as lowercase
        3-character ISO639 codes. The first argument specifies whether audio,
        subtitle or both languages sets are being configured. For example:

        tvr> languages audio eng jpn
        tvr> languages subtitle eng
        """
        if arg:
            arg = arg.lower().split(u' ')
            try:
                mode = {
                    u'audio':    u'audio',
                    u'sound':    u'audio',
                    u'subtitle': u'subtitle',
                    u'sub':      u'subtitle',
                    u'both':     u'both',
                    u'all':      u'both',
                }[arg[0]]
            except KeyError:
                raise CmdSyntaxError(u'Invalid language mode %s' % arg[0])
            if mode in (u'audio', u'both'):
                new_langs = set(arg[1:])
                for lang in self.config.audio_langs:
                    if lang.lang in new_langs:
                        new_langs.remove(lang.lang)
                    else:
                        self.session.delete(lang)
                for lang in new_langs:
                    self.session.add(AudioLanguage(lang))
            if mode in (u'subtitle', u'both'):
                new_langs = set(arg[1:])
                for lang in self.config.subtitle_langs:
                    if lang.lang in new_langs:
                        new_langs.remove(lang.lang)
                    else:
                        self.session.delete(lang)
                for lang in new_langs:
                    self.session.add(SubtitleLanguage(lang))
            self.session.commit()
        else:
            self.pprint(u'Current audio languages:')
            for lang in self.config.audio_langs:
                self.pprint(lang.lang)
            self.pprint(u'Current subtitle languages:')
            for lang in self.config.subtitle_langs:
                self.pprint(lang.lang)

    def do_audio(self, arg):
        u"""Gets/sets the audio mixdown

        Syntax: audio [mix]

        The 'audio' command can be used to query the current audio mixdown used
        by the 'rip' command. If an argument is given it will become the new
        audio mixdown.

        The valid mixes are 'mono', 'stereo', 'dpl1', and 'dpl2' with the
        latter two indicating Dolby Pro Logic I and II respectively. AC3 or DTS
        pass-thru cannot be configured at this time. For example:

        tvr> audio stereo
        tvr> audio dpl2
        """
        if arg:
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
        else:
            self.pprint(u'Audio mix: %s (%s)' % (
                self.config.audio_mix,
                {
                    u'mono':   u'1 channel',
                    u'stereo': u'2 channel',
                    u'dpl1':   u'Dolby Pro Logic I',
                    u'dpl2':   u'Dolby Pro Logic II',
                }[self.config.audio_mix]
            ))

    def do_subtitles(self, arg):
        u"""Gets/sets the subtitle extraction mode

        Syntax: subtitles [format]

        The 'subtitles' command can be used to query the current subtitles
        extraction mode used by the 'rip' command. If an argument is given it
        will become the new subtitles extract mode.
        
        The valid formats are 'none' indicating that subtitles should not be
        extracted at all, 'vobsub' which causes subtitles to be extracted as
        timed image overlays, and 'subrip' which causes subtitles to be
        extracted and converted to a text-based subtitle format via OCR. For
        example:

        tvr> subtitles subrip
        tvr> subtitles vobsub
        tvr> subtitles none
        """
        if arg:
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
        else:
            self.pprint(u'Subtitle extraction mode: %s (%s)' % (
                self.config.subtitle_format,
                {
                    u'none':   u'no subtitles',
                    u'vobsub': u'image-based',
                    u'subrip': u'text-based',
                }[self.config.subtitle_format]
            ))

    def do_subblack(self, arg):
        u"""Gets/sets the subtitle black color

        Syntax: subblack [number]

        The 'subblack' command specifies which of the four colors in the
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
        if arg:
            try:
                arg = int(arg.strip())
                if not 1 <= arg <= 4:
                    raise ValueError()
            except ValueError:
                raise CmdSyntaxError('Invalid color %s - must be a number from 1 to 4' % arg)
            self.config.subtitle_black = arg
            self.session.commit()
        else:
            self.pprint(u'Subtitle black color index is %d' % self.config.subtitle_black)

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
        u"""Gets/sets the decomb option for video conversion.

        Syntax: decomb [option]

        The 'decomb' command without any arguments returns the current
        decomb setting for the video converter. If an argument is given
        it becomes the new decomb setting. Valid settings are currently
        'off', 'on', and 'auto'. For example:

        tvr> decomb off
        tvr> decomb on
        """
        if arg:
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
        else:
            self.pprint(u'Decomb setting: %s' % self.config.decomb)

    def do_duration(self, arg):
        u"""Gets/sets range of episode duration.

        Syntax: duration [<min> <max>]

        The 'duration' command without any arguments returns the current
        minimum and maximum length (in minutes) that an episode is expected to
        be. With two arguments it is used to specify a new minimum and maximum.
        This is used when scanning a source device for titles which are likely
        to be episodes. For example:

        tvr> duration 40 50
        tvr> duration 25 35
        """
        if arg:
            try:
                self.config.duration_min, self.config.duration_max = (
                    timedelta(minutes=int(i))
                    for i in arg.split(u' ')
                )
                self.session.commit()
            except (TypeError, ValueError):
                self.pprint(u'Invalid durations given: %s' % arg)
        else:
            self.pprint(u'Track between %d and %d minutes long will be '
                u'treated as episodes' % (
                    self.config.duration_min.seconds / 60,
                    self.config.duration_max.seconds / 60
                )
            )

    def do_episode(self, arg):
        u"""Gets/sets the name of a single episode.

        Syntax: episode <number> [name]

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
            if name:
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
                try:
                    e = self.session.query(Episode).\
                            filter(Episode.season==self.config.season).\
                            filter(Episode.number==number).one()
                except sa.orm.exc.NoResultFound:
                    raise CmdError(u'Episode %d of season %d of program %s '
                        u'does not exist' % (number, self.config.season.number, self.config.program.name))
                else:
                    self.pprint(u'Episode %d of season %d of program %s '
                        u'is named %s' % (e.number, e.season.number, e.season.program.name, e.name))
        else:
            raise CmdError(u'You must specify an episode number')

    def do_episodes(self, arg):
        u"""Gets/sets the episodes for the current season.

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
        elif self.config.season:
            self.pprint(u'Episodes for season %d of program %s (* indicates ripped status):' % (self.config.season.number, self.config.program.name))
            for e in self.session.query(Episode).filter(Episode.season==self.config.season):
                self.pprint(u'%2d%1s: %s' % (e.number, u'*' if e.disc_serial else u'', e.name))
        else:
            raise CmdError(u'No season has been set')

    def do_season(self, arg):
        u"""Gets/sets which season of the program the disc contains.

        Syntax: season [number]

        The 'season' command can be used to determine what season of the
        program the disc is expected to contain episodes for. If an argument is
        given it specifies the season the disc contains episodes for. This
        number is used when constructing the filename of ripped episodes.

        This command is also used to expand the episode database. If the number
        given does not exist, it will be entered into the database under the
        current program and you will be prompted for episode names.
        """
        if arg:
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
                else:
                    self.onecmd(u'season')
        elif self.config.season:
            self.pprint(u'Season %d of program %s' % (
                self.config.season.number,
                self.config.season.program.name,
            ))
        else:
            self.pprint(u'No season has been set')

    def complete_season(self, text, line, start, finish):
        return [
            unicode(season.number) for season in
            self.session.query(Season).\
            filter(Season.program==self.config.program).\
            filter(u"SUBSTR(CAST(season AS TEXT), 1, :length) = :season").\
            params(length=len(text), season=text).all()
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
        u"""Gets/sets the name of the program.

        Syntax: program [name]

        The 'program' command can be used to determine what program the disc is
        expected to contain episodes for. If an argument is given it specifies
        the program the disc contains episodes for. This is used when
        constructing the filename of ripped episodes.

        This command is also used to expand the episode database. If the name
        given does not exist, it will be entered into the database and you will
        be prompted for season and episode information.
        """
        if arg:
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
                    if self.config.season is None:
                        self.onecmd(u'program')
                    else:
                        self.onecmd(u'season')
        elif self.config.program:
            self.pprint(u'Program %s' % self.config.program.name)
        else:
            self.pprint(u'No program has been set')

    program_re = re.compile(ur'^program\s+')
    def complete_program(self, text, line, start, finish):
        line = self.program_re.sub('', line)
        return [
            program.name for program in
            self.session.query(Program).filter(Program.name.startswith(line)).all()
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

        The 'scan' command scans the current source device for titles likely to
        contain episodes.
        """
        if not self.config.source:
            self.pprint(u'No source has been specified')
        elif not (self.config.duration_min and self.config.duration_max):
            self.pprint(u'No duration range has been specified')
        else:
            self.pprint(u'Scanning disc in %s' % self.config.source)
            if self.config.season:
                unripped = [e for e in self.config.season.episodes if not e.disc_serial]
            else:
                unripped = []
            self.disc = Disc()
            self.disc.scan(self.config.source)
            self.pprint(u'Disc serial: %s' % self.disc.serial)
            for title in self.disc.titles:
                if self.config.duration_min <= title.duration <= self.config.duration_max:
                    self.pprint(u'Title %d is a potential episode (duration: %02d:%02d:%02d)' % (
                        title.number,
                        title.duration.seconds / 3600,
                        title.duration.seconds / 60 % 60,
                        title.duration.seconds % 60
                    ))
                    self.pprint(u'  %d chapters' % len(title.chapters))
                    for chapter in title.chapters:
                        self.pprint(u'    %d: %s->%s' % (
                            chapter.number,
                            chapter.start,
                            chapter.finish
                        ))
                    self.pprint(u'  %d audio tracks' % len(title.audio_tracks))
                    for track in title.audio_tracks:
                        suffix = u''
                        if track.preferred and self.config.in_audio_langs(track.language):
                            suffix = u'[selected]'
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
                        if track.preferred and self.config.in_subtitle_langs(track.language):
                            suffix = u'[selected]'
                        self.pprint(u'    %d: %s, %s %s' % (
                            track.number,
                            track.language,
                            track.name,
                            suffix
                        ))
                    # Attempt to map the title to an episode. If it's been
                    # previously ripped, perform a mapping based on the
                    # recorded serial number and title. Otherwise pick the
                    # first unripped episode from the current season
                    episode = self.session.query(Episode).\
                        filter(Episode.season==self.config.season).\
                        filter(Episode.disc_serial==title.disc.serial).\
                        filter(Episode.disc_title==title.number).first()
                    if episode:
                        self.do_map(u'%d %d' % (title.number, episode.number))
                    elif unripped:
                        self.do_map(u'%d %d' % (title.number, unripped.pop(0).number))
                else:
                    self.pprint(u'Title %d is not an episode (duration: %02d:%02d:%02d)' % (
                        title.number,
                        title.duration.seconds / 3600,
                        title.duration.seconds / 60 % 60,
                        title.duration.seconds % 60
                    ))

    def do_map(self, arg):
        u"""Maps titles to episodes.

        Syntax: map [<title> <episode>]

        The 'map' command is used to define which title on the disc contains
        the specified episode. This is used when constructing the filename of
        ripped episodes. For example:

        tvr> map 3 1
        tvr> map 7 4

        The scan command can be used to perform auto-mapping (see its help page
        for more information). Use the map command with no arguments to see the
        current title to episode mapping.
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
                title, episode = (int(i) for i in arg.split(u' '))
            except ValueError:
                raise CmdSyntaxError(u'You must specify two integer values')
            try:
                title = [t for t in self.disc.titles if t.number==title][0]
            except IndexError:
                raise CmdError(u'There is no title %d on the scanned disc' % title)
            try:
                episode = self.session.query(Episode).\
                    filter(Episode.season==self.config.season).\
                    filter(Episode.number==episode).one()
            except sa.orm.exc.NoResultFound:
                raise CmdError(u'There is no episode %d in the current season' % episode)
            self.pprint(u'Mapping title %d to episode %d, "%s"' % (title.number, episode.number, episode.name))
            title.episode = episode
        else:
            for title in self.disc.titles:
                if title.episode and title.episode.disc_serial:
                    self.pprint(u'Title %d is ripped episode %d, "%s"' % (title.number, title.episode.number, title.episode.name))
                elif title.episode:
                    self.pprint(u'Title %d is episode %d, "%s"' % (title.number, title.episode.number, title.episode.name))
                else:
                    self.pprint(u'Title %d is not mapped to an episode' % title.number)

    def do_unmap(self, arg):
        u"""Removes a title to episode mapping

        Syntax: unmap <title>

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
                title = [t for t in self.disc.titles if t.number==arg][0]
            except IndexError:
                raise CmdError(u'Title %d does not exist on the scanned disc' % arg)
            if not title.episode:
                raise CmdError(u'Title %d has no mapped episode' % title.number)
            else:
                self.pprint(u'Removing mapping for title %d' % title.number)
                title.episode = None

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
        elif not any(title.episode for title in self.disc.titles):
            raise CmdError(u'No titles have been mapped to episodes')
        elif arg.strip():
            raise CmdSyntaxError(u'You must not specify any arguments')
        failed = []
        for title in self.disc.titles:
            if title.episode and not title.episode.disc_serial:
                self.pprint(u'Ripping episode %d, "%s"' % (
                    title.episode.number, title.episode.name))
                title.rip(self.config)
                title.episode.disc_serial = self.disc.serial
                title.episode.disc_title = title.number
                self.session.commit()

    def do_unrip(self, arg):
        u"""Changes the status of the specified episode to unripped.

        Syntax: unrip <episode>

        The 'unrip' command is used to set the status of an episode to
        unripped. Episodes are automatically set to ripped during the operation
        of the 'rip' command. Episodes marked as ripped will never be
        automatically mapped to titles by the 'scan' command (although they can
        be mapped manually with the 'map' command). For example:

        tvr> unrip 3
        tvr> unrip 7
        """
        if not self.config.program:
            raise CmdError(u'No program has been set')
        elif not self.config.season:
            raise CmdError(u'No season has been set')
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
            self.session.commit()

    def do_source(self, arg):
        u"""Gets/sets the source device.

        Syntax: source [device]

        The 'source' command can be used to query the current source device
        to read when using the 'scan' and 'rip' commands. If an argument
        is given it will become the new source device. The home directory
        shorthand (~) may be used in the specified path. For example:

        tvr> source /dev/dvd
        tvr> source /dev/sr0
        """
        if arg:
            arg = os.path.expanduser(arg)
            if not os.path.exists(arg):
                self.pprint(u'Path %s does not exist' % arg)
                return
            self.config.source = arg
        elif not self.config.source:
            self.pprint(u'No source has been specified')
        else:
            self.pprint(u'Source device: %s' % self.config.source)

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
        u"""Gets/sets the target path.

        Syntax: target [path]

        The 'target' command can be used to query the current path into which
        ripped and converted episodes will be written. If an argument is given
        it will become the new target path. The home-directory shorthand (~)
        may be used in the specified path. For example:

        tvr> target ~/Videos
        """
        if arg:
            arg = os.path.expanduser(arg)
            if not os.path.exists(arg):
                self.pprint(u'Path %s does not exist' % arg)
                return
            if not os.path.isdir(arg):
                self.pprint(u'Path %s is not a directory' % arg)
                return
            self.config.target = arg
        elif not self.config.target:
            self.pprint(u'No target has been specified')
        else:
            self.pprint(u'Target path: %s' % self.config.target)

    target_re = re.compile(ur'^target\s+')
    def complete_target(self, text, line, start, finish):
        return self.complete_path(text, self.target_re.sub('', line), start, finish)

    def do_temp(self, arg):
        u"""Gets/sets the temporary files path.

        Syntax: temp [path]

        The 'temp' command can be used to query the current path which will
        be used for temporary storage (actually a temporary directory under
        this path is used). The home-directory shorthand (~) may be used, but
        be aware that no spaces are permitted in the path name. For example:

        tvr> temp ~/tmp
        tvr> temp /var/tmp
        """
        if arg:
            arg = os.path.expanduser(arg)
            if not os.path.exists(arg):
                self.pprint(u'Path %s does not exist' % arg)
                return
            if not os.path.isdir(arg):
                self.pprint(u'Path %s is not a directory' % arg)
                return
            self.config.temp = arg
        elif not self.config.temp:
            self.pprint(u'No temporary path has been specified')
        else:
            self.pprint(u'Temporary path: %s' % self.config.temp)

    temp_re = re.compile(ur'^temp\s+')
    def complete_temp(self, text, line, start, finish):
        return self.complete_path(text, self.temp_re.sub('', line), start, finish)

    def do_template(self, arg):
        u"""Gets/sets the template used for filenames.

        Syntax: template [format-string]

        The 'template' command can be used to query the string formatting
        template which generates the filenames of ripped and converted
        episodes. If an argument is given it will be used as the new filename
        template. The template is specified as a Python format string including
        named subsitution markers (program, season, episode, and name). The
        format-string is specified without quotation marks.
        """
        if arg:
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
        else:
            self.pprint(u'Filename template: %s' % self.config.template)

    do_EOF = do_exit


