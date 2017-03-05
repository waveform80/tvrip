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

"Implements the disc scanner and ripper"

import sys
import os
import re
import shutil
import tempfile
import datetime as dt
import subprocess as proc
from hashlib import sha1
from operator import attrgetter
from itertools import groupby

AUDIO_MIX_ORDER = [
    '5.1 ch',
    '5.0 ch',
    'Dolby Surround',
    '3.1 ch',
    '2.0 ch',
    '1.0 ch',
    ]
AUDIO_ENCODING_ORDER = ['DTS', 'AC3']


class Disc():
    "Represents a DVD disc"

    def __init__(self):
        super().__init__()
        self.match = None
        self.titles = []
        self.name = ''
        self.serial = None
        self.ident = None

    def __repr__(self):
        return '<Disc()>'

    def scan(self, config, titles=None):
        "Scan the disc specified by config for rippable titles"
        if titles is None:
            titles = [0]
        for title in titles:
            self._scan_title(config, title)
        # Calculate a hash of disc serial, and track properties to form a
        # unique disc identifier, then replace disc-serial with this (#1)
        h = sha1()
        if self.serial:
            h.update(self.serial)
        h.update(str(len(self.titles)).encode())
        for title in self.titles:
            h.update(str(title.duration).encode())
            h.update(str(len(title.chapters)).encode())
            for chapter in title.chapters:
                h.update(str(chapter.start).encode())
                h.update(str(chapter.duration).encode())
        self.ident = '$H1$' + h.hexdigest()

    error1_re = re.compile(
        r"libdvdread: Can't open .* for reading", re.UNICODE)
    error2_re = re.compile(
        r'libdvdnav: vm: failed to open/read the DVD', re.UNICODE)
    disc_name_re = re.compile(r'^libdvdnav: DVD Title: (?P<name>.*)$')
    disc_serial_re = re.compile(
        r'^libdvdnav: DVD Serial Number: (?P<serial>.*)$', re.UNICODE)
    title_re = re.compile(
        r'^\+ title (?P<number>\d+):$', re.UNICODE)
    duration_re = re.compile(
        r'^  \+ duration: (?P<duration>.*)$', re.UNICODE)
    stats_re = re.compile(
        r'^  \+ size: (?P<size>.*), aspect: (?P<aspect_ratio>.*), '
        r'(?P<frame_rate>.*) fps$', re.UNICODE)
    crop_re = re.compile(r'^  \+ autocrop: (?P<crop>.*)$', re.UNICODE)
    comb_re = re.compile(r'^  \+ combing detected,.*$', re.UNICODE)
    chapters_re = re.compile(r'^  \+ chapters:$', re.UNICODE)
    chapter_re = re.compile(
        r'^    \+ (?P<number>\d+): cells \d+->\d+, \d+ blocks, '
        r'duration (?P<duration>.*)$', re.UNICODE)
    audio_tracks_re = re.compile(r'^  \+ audio tracks:$', re.UNICODE)
    audio_track_re = re.compile(
        r'^    \+ (?P<number>\d+), '
        r'(?P<name>[^(]*) \((?P<encoding>[^)]*)\)( \((?P<label>[^)]*)\))? '
        r'\((?P<channel_mix>\d+\.\d+ ch)\)( \(Dolby [^)]*\))? '
        r'\(iso639-2: (?P<language>[a-z]{2,3})\), '
        r'(?P<sample_rate>\d+)Hz, (?P<bit_rate>\d+)bps$', re.UNICODE)
    subtitle_tracks_re = re.compile(r'^  \+ subtitle tracks:$', re.UNICODE)
    subtitle_track_re = re.compile(
        r'^    \+ (?P<number>\d+), (?P<name>.*) '
        r'\(iso639-2: (?P<language>[a-z]{2,3})\)( \((?P<type>Text|Bitmap)\))?'
        r'\((?P<format>CC|VOBSUB)\)?$', re.UNICODE)
    def _scan_title(self, config, title):
        "Internal method for scanning (a) disc title(s)"

        # This is a simple utility method to make the pattern matching below a
        # bit simpler. It returns the result of the match as a bool and stores
        # the result as an instance attribute for later extraction of groups
        def _match(pattern, line):
            self.match = pattern.match(line)
            return bool(self.match)

        cmdline = [
            config.get_path('handbrake'),
            '-i', config.source,     # specify the input device
            '-t', str(title),        # select the specified title
            '--min-duration', '300', # only scan titles >5 minutes
            '--scan',                # scan only
            ]
        if not config.dvdnav:
            cmdline.append('--no-dvdnav')
        output = proc.check_output(cmdline, stderr=proc.STDOUT, universal_newlines=True)
        state = {'disc'}
        title = None
        # Parse the output into child objects
        for line in output.splitlines():
            if 'disc' in state and (
                    _match(self.error1_re, line) or
                    _match(self.error2_re, line)):
                raise IOError(
                    'Unable to read disc in {}'.format(config.source))
            if 'disc' in state and _match(self.disc_name_re, line):
                self.name = self.match.group('name')
            elif 'disc' in state and _match(self.disc_serial_re, line):
                self.serial = str(self.match.group('serial'))
            elif 'disc' in state and _match(self.title_re, line):
                if title:
                    title.chapters = sorted(
                        title.chapters, key=attrgetter('number'))
                    title.audio_tracks = sorted(
                        title.audio_tracks, key=attrgetter('number'))
                    title.subtitle_tracks = sorted(
                        title.subtitle_tracks, key=attrgetter('number'))
                state = {'disc', 'title'}
                title = Title(self)
                title.number = int(self.match.group('number'))
            elif 'title' in state and _match(self.duration_re, line):
                state = {'disc', 'title'}
                hours, minutes, seconds = (
                    int(i) for i in self.match.group('duration').split(':'))
                title.duration = dt.timedelta(
                    seconds=seconds, minutes=minutes, hours=hours)
            elif 'title' in state and _match(self.stats_re, line):
                state = {'disc', 'title'}
                title.size = (
                    int(i) for i in self.match.group('size').split('x'))
                title.aspect_ratio = float(self.match.group('aspect_ratio'))
                title.frame_rate = float(self.match.group('frame_rate'))
            elif 'title' in state and _match(self.crop_re, line):
                state = {'disc', 'title'}
                title.crop = (
                    int(i) for i in self.match.group('crop').split('/'))
            elif 'title' in state and _match(self.comb_re, line):
                title.interlaced = True
            elif 'title' in state and _match(self.chapters_re, line):
                state = {'disc', 'title', 'chapter'}
            elif 'chapter' in state and _match(self.chapter_re, line):
                chapter = Chapter(title)
                chapter.number = int(self.match.group('number'))
                hours, minutes, seconds = (
                    int(i) for i in self.match.group('duration').split(':'))
                chapter.duration = dt.timedelta(
                    seconds=seconds, minutes=minutes, hours=hours)
            elif 'title' in state and _match(self.audio_tracks_re, line):
                state = {'disc', 'title', 'audio'}
            elif 'audio' in state and _match(self.audio_track_re, line):
                track = AudioTrack(title)
                track.number = int(self.match.group('number'))
                if self.match.group('label'):
                    track.name = '{name} ({label})'.format(
                        name=self.match.group('name'),
                        label=self.match.group('label'))
                else:
                    track.name = self.match.group('name')
                track.language = str(self.match.group('language'))
                track.encoding = str(self.match.group('encoding'))
                track.channel_mix = str(self.match.group('channel_mix'))
                track.sample_rate = int(self.match.group('sample_rate'))
                track.bit_rate = int(self.match.group('bit_rate'))
            elif 'title' in state and _match(self.subtitle_tracks_re, line):
                state = {'disc', 'title', 'subtitle'}
            elif 'subtitle' in state and _match(self.subtitle_track_re, line):
                track = SubtitleTrack(title)
                track.number = int(self.match.group('number'))
                track.name = str(self.match.group('name'))
                track.language = str(self.match.group('language'))
                track.format = self.match.group('format').lower()
        self.titles = sorted(self.titles, key=attrgetter('number'))
        # Determine the best audio and subtitle tracks
        for title in self.titles:
            for _, group in groupby(
                    sorted(title.audio_tracks, key=attrgetter('name')),
                    key=attrgetter('name')):
                group = sorted(group, key=lambda track: (
                    AUDIO_MIX_ORDER.index(track.channel_mix),
                    AUDIO_ENCODING_ORDER.index(track.encoding)
                    ))
                if group:
                    group[0].best = True
            for _, group in groupby(
                    sorted(title.subtitle_tracks, key=attrgetter('name')),
                    key=attrgetter('name')):
                group = list(group)
                if group:
                    group[0].best = True

    def play(self, config, title_or_chapter):
        "Play the specified title or chapter"
        if isinstance(title_or_chapter, Title):
            mrl = 'dvd://{source}#{title}'.format(
                source=config.source,
                title=title_or_chapter.number)
        elif isinstance(title_or_chapter, Chapter):
            mrl = 'dvd://{source}#{title}:{chapter}'.format(
                source=config.source,
                title=title_or_chapter.title.number,
                chapter=title_or_chapter.number)
        cmdline = [config.get_path('vlc'), '--quiet', mrl]
        proc.check_call(cmdline, stdout=proc.DEVNULL, stderr=proc.DEVNULL)

    def rip(self, config, episode, title, audio_tracks, subtitle_tracks,
            start_chapter=None, end_chapter=None):
        "Rip the specified title"
        filename = config.template.format(
            program=config.program.name,
            season=config.season.number,
            episode=episode.number,
            name=episode.name,
            now=dt.datetime.now(),
            )
        # Replace invalid characters in the filename with -
        filename = re.sub(r'[\/:]', '-', filename)
        # Convert the video track
        audio_defs = [
            (track.number, config.audio_mix, track.name)
            for track in audio_tracks
            ]
        subtitle_defs = [
            (track.number, track.name)
            for track in subtitle_tracks
            ]
        cmdline = [
            config.get_path('handbrake'),
            '-i', config.source,
            '-t', str(title.number),
            '-o', os.path.join(config.target, filename),
            '-f', 'av_mp4', # output an MP4 container
            '-O',           # optimize for streaming
            '-m',           # include chapter markers
            '--encoder', 'x264',          # use x264 for encoding
            '--encoder-preset', 'medium', # use x264 medium preset
            '--encoder-profile', 'high',  # use x264 high profile
            '--encoder-level', '4.1',     # use x264 level 4.1
            '--quality', '23',            # video quality 23
            # advanced encoding options (mostly defaults from High Profile)
            '-x', 'psy-rd=1|0.15:vbv-bufsize=78125:vbv-maxrate=62500:me=umh:b-adapt=2',
            # disable cropping (otherwise vobsub subtitles screw up) but don't
            # sacrifice cropping for aligned storage
            '--crop', '0:0:0:0',
            '--loose-crop',
            # use efficient storage options (actually defaults but no harm in
            # explicitly specifying them)
            '--loose-anamorphic',
            '--modulus', '16',
            # audio encoding options (use 160kbps AAC with the decent FDK
            # encoder, plus whatever downmix the user selected for the
            # specified tracks)
            '-a', ','.join(str(num)  for (num, _, _)  in audio_defs),
            '-E', ','.join('fdk_aac' for ad           in audio_defs),
            '-B', ','.join('160'     for ad           in audio_defs),
            '-6', ','.join(mix       for (_, mix, _)  in audio_defs),
            '-A', ','.join(name      for (_, _, name) in audio_defs),
            ]
        if not config.dvdnav:
            cmdline.append('--no-dvdnav')
        if start_chapter:
            cmdline.append('-c')
            if end_chapter:
                cmdline.append(
                    '{start}-{end}'.format(
                        start=start_chapter.number, end=end_chapter.number))
            else:
                cmdline.append(str(start_chapter.number))
        if config.subtitle_format == 'vobsub':
            cmdline.append('-s')
            cmdline.append(','.join(str(num) for (num, _) in subtitle_defs))
        if config.decomb == 'on':
            cmdline.append('-d')
            cmdline.append('slow')
        elif config.decomb == 'auto':
            cmdline.append('-5')
        proc.check_call(cmdline)
        # Tag the resulting file
        tmphandle, tmpfile = tempfile.mkstemp(dir=config.temp)
        try:
            cmdline = [
                config.get_path('atomicparsley'),
                os.path.join(config.target, filename),
                '-o', tmpfile,
                '--stik', 'TV Show',
                # set tags for TV shows
                '--TVShowName',   episode.season.program.name,
                '--TVSeasonNum',  str(episode.season.number),
                '--TVEpisodeNum', str(episode.number),
                '--TVEpisode',    episode.name,
                # also set tags for music files as these have wider support
                '--artist',       episode.season.program.name,
                '--album',        'Season {}'.format(episode.season.number),
                '--tracknum',     str(episode.number),
                '--title',        episode.name,
                ]
            proc.check_call(cmdline)
            os.chmod(
                tmpfile,
                os.stat(os.path.join(config.target, filename)).st_mode)
            shutil.move(tmpfile, os.path.join(config.target, filename))
        finally:
            os.close(tmphandle)

class Title():
    "Represents a title on a DVD"

    def __init__(self, disc):
        super().__init__()
        disc.titles.append(self)
        self.disc = disc
        self.number = 0
        self.duration = dt.timedelta()
        self.size = (0, 0)
        self.aspect_ratio = 0
        self.frame_rate = 0
        self.crop = (0, 0, 0, 0)
        self.chapters = []
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.interlaced = False

    def __repr__(self):
        return '<Title({})>'.format(self.number)

    @property
    def duplicate(self):
        """
        Returns a string indicating the duplicate state of this title: 'no' if
        the title isn't a duplicate, 'first' if it's the first in a set of
        duplicates, 'last' if it's the last in a set of duplicates, and 'yes'
        otherwise (the title is in the middle of 3 or more duplicates).
        """
        if self.previous is None:
            if self.next is not None and self.next.duration == self.duration:
                return 'first'
            else:
                return 'no'
        elif self.next is None:
            if self.previous is not None and self.previous.duration == self.duration:
                return 'last'
            else:
                return 'no'
        else:
            if self.next.duration == self.duration:
                if self.previous.duration == self.duration:
                    return 'yes'
                else:
                    return 'first'
            else:
                if self.previous.duration == self.duration:
                    return 'last'
                else:
                    return 'no'

    @property
    def previous(self):
        "Returns the prior chapter within the disc or None"
        i = self.disc.titles.index(self)
        if i == 0:
            return None
        else:
            return self.disc.titles[i - 1]

    @property
    def next(self):
        "Returns the next title within the disc or None"
        try:
            return self.disc.titles[self.disc.titles.index(self) + 1]
        except IndexError:
            return None

    def play(self, config):
        "Starts VLC playing at the title start"
        self.disc.play(config, self)


class Chapter():
    "Represents a chapter marker within a Title object"

    def __init__(self, title):
        super().__init__()
        title.chapters.append(self)
        self.title = title
        self.number = 0
        self.duration = dt.timedelta(0)

    @property
    def start(self):
        "Returns the start time of the chapter"
        result = dt.datetime(dt.MINYEAR, 1, 1)
        for chapter in self.title.chapters:
            if chapter.number >= self.number:
                break
            result += chapter.duration
        return result.time()

    @property
    def finish(self):
        "Returns the finish time of the chapter"
        result = dt.datetime.combine(dt.date(dt.MINYEAR, 1, 1), self.start)
        return (result + self.duration).time()

    @property
    def previous(self):
        "Returns the prior chapter within the title or None"
        i = self.title.chapters.index(self)
        if i == 0:
            return None
        else:
            return self.title.chapters[i - 1]

    @property
    def next(self):
        "Returns the next chapter within the title or None"
        try:
            return self.title.chapters[self.title.chapters.index(self) + 1]
        except IndexError:
            return None

    def __repr__(self):
        return '<Chapter({number}, {duration})>'.format(
            number=self.number, duration=self.duration)

    def play(self, config):
        "Starts VLC playing at the chapter start"
        self.title.disc.play(config, self)


class AudioTrack():
    "Represents an audio track within a Title object"

    def __init__(self, title):
        super().__init__()
        title.audio_tracks.append(self)
        self.title = title
        self.name = ''
        self.number = 0
        self.language = ''
        self.encoding = ''
        self.channel_mix = ''
        self.sample_rate = 0
        self.bit_rate = 0
        self.best = False

    def __repr__(self):
        return "<AudioTrack({number}, '{name}')>".format(
            number=self.number, name=self.name)


class SubtitleTrack():
    "Represents a subtitle track within a Title object"

    def __init__(self, title):
        super().__init__()
        title.subtitle_tracks.append(self)
        self.title = title
        self.number = 0
        self.name = ''
        self.language = ''
        self.format = 'VOBSUB'
        self.best = False
        self.log = ''

    def __repr__(self):
        return "<SubtitleTrack({number}, '{name}')>".format(
            number=self.number, name=self.name)


