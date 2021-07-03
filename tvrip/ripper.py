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

import os
import re
import json
import shutil
import tempfile
import datetime as dt
import subprocess as proc
import hashlib
from fractions import Fraction
from operator import attrgetter
from itertools import groupby, chain
from weakref import ref
from pathlib import Path

from . import multipart


AUDIO_MIX_ORDER = [
    '5point1',
    '5.1(side)',
    'downmix',
    'stereo',
    'mono',
    ]
AUDIO_ENCODING_ORDER = {
    encoding: index
    for index, encoding in enumerate(['dts', 'ac3'])
}


class Disc():
    "Represents a DVD disc"

    error1_re = re.compile(
        r"libdvdread: Can't open .* for reading", re.UNICODE)
    error2_re = re.compile(
        r'libdvdnav: vm: failed to open/read the DVD', re.UNICODE)
    disc_name_re = re.compile(r'^libdvdnav: DVD Title: (?P<name>.*)$')
    disc_serial_re = re.compile(
        r'^libdvdnav: DVD Serial Number: (?P<serial>.*)$', re.UNICODE)

    def __init__(self, config, titles=None):
        super().__init__()
        self.match = None
        self.titles = []
        self.name = ''
        self.serial = ''
        self.ident = None
        if titles is None:
            titles = [0]
        for title in titles:
            self._scan_title(config, title)
        self.ident = self._generate_ident()
        self._mark_duplicates()
        self._mark_best()

    def _generate_ident(self):
        # Calculate a hash of disc serial, and track properties to form a
        # unique disc identifier, then replace disc-serial with this (#1)
        h = hashlib.sha1()
        h.update(self.serial.encode())
        h.update(str(len(self.titles)).encode())
        for title in self.titles:
            h.update(str(title.duration).encode())
            h.update(str(len(title.chapters)).encode())
            for chapter in title.chapters:
                h.update(str(chapter.start).encode())
                h.update(str(chapter.duration).encode())
        return '$H1$' + h.hexdigest()

    def _mark_duplicates(self):
        # Mark duplicate titles (adjacent titles with equal durations) as such;
        # the Title.duplicate property contains one of the following states:
        #
        # * no:    this title is not a duplicate
        # * first: this title is the first in a run of duplicates
        # * yes:   this title is in the middle of a run of duplicates
        # * last:  this title is the last in a run of duplicates
        previous = None
        for title in self.titles:
            if previous is not None:
                if previous.duration == title.duration:
                    if previous.duplicate == 'no':
                        previous.duplicate = 'first'
                    title.duplicate = 'yes'
                else:
                    if previous.duplicate == 'yes':
                        previous.duplicate = 'last'
            previous = title
        if title.duplicate == 'yes':
            title.duplicate = 'last'

    def _mark_best(self):
        # Mark "best" audio and subtitle tracks for each language; the "best"
        # audio track is determined by the global AUDIO_MIX_ORDER and
        # AUDIO_ENCODING_ORDER values which define the preference order for
        # these two properties
        for title in self.titles:
            for _, group in groupby(
                    sorted(title.audio_tracks, key=attrgetter('name')),
                    key=attrgetter('name')):
                group = sorted(group, key=lambda track: (
                    AUDIO_MIX_ORDER.index(track.channel_mix),
                    AUDIO_ENCODING_ORDER.get(track.encoding, len(AUDIO_ENCODING_ORDER))
                ))
                group[0].best = True
            for _, group in groupby(
                    sorted(title.subtitle_tracks, key=attrgetter('name')),
                    key=attrgetter('name')):
                group = list(group)
                group[0].best = True

    def __repr__(self):
        return '<Disc()>'

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
            '-i', config.source,      # specify the input device
            '-t', str(title),         # select the specified title
            '--min-duration', '300',  # only scan titles >5 minutes
            '--scan',                 # scan only
            '--json',                 # JSON output
            ]
        if not config.dvdnav:
            cmdline.append('--no-dvdnav')
        result = proc.run(cmdline, stdout=proc.PIPE, stderr=proc.PIPE,
                          check=True, encoding='utf-8', errors='replace')
        for line in result.stderr.splitlines():
            if _match(self.error1_re, line) or _match(self.error2_re, line):
                raise IOError(
                    'Unable to read disc in {}'.format(config.source))
            elif _match(self.disc_name_re, line):
                self.name = self.match.group('name')
            elif _match(self.disc_serial_re, line):
                self.serial = self.match.group('serial')
        try:
            json_start = result.stdout.rindex('JSON Title Set:')
        except ValueError:
            raise IOError('Unable to find JSON data in HandBrake output')
        json_disc = json.loads(
            result.stdout[json_start + len('JSON Title Set:'):])

        title = None
        for json_title in json_disc['TitleList']:
            title = Title(self)
            title.number = json_title['Index']
            title.duration = dt.timedelta(
                hours=json_title['Duration'].get('Hours', 0),
                minutes=json_title['Duration'].get('Minutes', 0),
                seconds=json_title['Duration'].get('Seconds', 0))
            title.size = (
                json_title['Geometry']['Width'],
                json_title['Geometry']['Height'])
            par = Fraction(json_title['Geometry']['PAR']['Num'],
                           json_title['Geometry']['PAR']['Den'])
            title.aspect_ratio = title.size[0] * par / title.size[1]
            title.frame_rate = Fraction(
                json_title['FrameRate']['Num'],
                json_title['FrameRate']['Den'])
            title.crop = tuple(json_title['Crop'])
            title.interlaced = json_title['InterlaceDetected']
            for json_ch in json_title['ChapterList']:
                chapter = Chapter(title)
                chapter.number = int(json_ch['Name'][len('Chapter '):])
                chapter.duration = dt.timedelta(
                    hours=json_ch['Duration'].get('Hours', 0),
                    minutes=json_ch['Duration'].get('Minutes', 0),
                    seconds=json_ch['Duration'].get('Seconds', 0))
            title.chapters = sorted(
                title.chapters, key=attrgetter('number'))
            for num, json_audio in enumerate(json_title['AudioList'], start=1):
                track = AudioTrack(title)
                track.number = num
                track.name = json_audio['Language']
                track.language = json_audio['LanguageCode'].lower()
                track.encoding = json_audio['CodecName'].lower()
                track.channel_mix = json_audio['ChannelLayoutName'].lower()
                track.sample_rate = json_audio['SampleRate']
                track.bit_rate = json_audio['BitRate']
            title.audio_tracks = sorted(
                title.audio_tracks, key=attrgetter('number'))
            for num, json_sub in enumerate(json_title['SubtitleList'], start=1):
                track = SubtitleTrack(title)
                track.number = num
                track.name = json_sub['Language']
                track.language = json_sub['LanguageCode'].lower()
                track.format = json_sub['SourceName'].lower()
            title.subtitle_tracks = sorted(
                title.subtitle_tracks, key=attrgetter('number'))

    def play(self, config, title_or_chapter=None):
        "Play the specified title or chapter"
        if title_or_chapter is None:
            mrl = 'dvd://{source}'.format(source=config.source)
        elif isinstance(title_or_chapter, Title):
            mrl = 'dvd://{source}#{title}'.format(
                source=config.source,
                title=title_or_chapter.number)
        elif isinstance(title_or_chapter, Chapter):
            mrl = 'dvd://{source}#{title}:{chapter}'.format(
                source=config.source,
                title=title_or_chapter.title.number,
                chapter=title_or_chapter.number)
        else:
            assert False
        cmdline = [config.get_path('vlc'), '--quiet', mrl]
        proc.check_call(cmdline, stdout=proc.DEVNULL, stderr=proc.DEVNULL)

    def rip(self, config, episodes, title, audio_tracks, subtitle_tracks,
            start_chapter=None, end_chapter=None):
        "Rip the specified title"
        for item in chain(audio_tracks, subtitle_tracks,
                          [start_chapter, end_chapter]):
            if item is not None and item.title is not title:
                raise ValueError(
                    '{item} does not belong to {title}'.format(
                        item=item, title=title))
        file_id = ' '.join(
            config.id_template.format(
                season=episode.season.number,
                episode=episode.number
            )
            for episode in sorted(episodes, key=attrgetter('number'))
        )
        filename = config.template.format(
            program=config.program.name,
            id=file_id,
            name=multipart.name(episodes),
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
            (track.number, track.name, track.best)
            for track in subtitle_tracks
        ]
        cmdline = [
            config.get_path('handbrake'),
            '-i', config.source,
            '-t', str(title.number),
            '-o', os.path.join(config.target, filename),
            '-f', 'av_mp4',  # output an MP4 container
            '-O',            # optimize for streaming
            '-m',            # include chapter markers
            '--encoder', 'x264',
            '--encoder-preset', 'medium',
            '--encoder-profile', 'high',
            '--encoder-level', '4.1',
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
            # audio encoding options (use 160kbps FDK-AAC plus whatever downmix
            # the user selected for the specified tracks)
            '-a', ','.join(str(num)  for (num, _, _)  in audio_defs),
            '-E', ','.join('fdk_aac' for ad           in audio_defs),
            '-B', ','.join('160'     for ad           in audio_defs),
            '-6', ','.join(mix       for (_, mix, _)  in audio_defs),
            '-A', ','.join(name      for (_, _, name) in audio_defs),
        ]
        cmdline.append('--quality')
        cmdline.append(str({
            'film':      21,
            'tv':        22,
            'animation': 23,
        }[config.video_style]))
        if config.video_style != 'tv':
            cmdline.append('--encoder-tune')
            cmdline.append(config.video_style)
        if not config.dvdnav:
            cmdline.append('--no-dvdnav')
        if start_chapter:
            cmdline.append('-c')
            if end_chapter:
                cmdline.append(
                    '{start}-{end}'.format(
                        start=start_chapter.number, end=end_chapter.number))
            else:
                end_chapter = start_chapter
                cmdline.append(str(start_chapter.number))
        if config.subtitle_format == 'vobsub' and subtitle_defs:
            cmdline.append('-s')
            cmdline.append(','.join(str(num) for (num, _, _) in subtitle_defs))
            if config.subtitle_default:
                for num, name, best in subtitle_defs:
                    if best:
                        cmdline.append('--subtitle-default')
                        cmdline.append(str(num))
                        break
        if config.decomb == 'on':
            cmdline.append('-d')
            cmdline.append('slow')
        elif config.decomb == 'auto':
            cmdline.append('-5')
        with (Path(config.temp) / 'tvrip.log').open('a') as log:
            proc.check_call(cmdline, stdout=log, stderr=log)
        # Tag the resulting file
        tmphandle, tmpfile = tempfile.mkstemp(dir=config.temp)
        try:
            cmdline = [
                config.get_path('atomicparsley'),
                os.path.join(config.target, filename),
                '-o', tmpfile,
                '--stik', 'TV Show',
                # set tags for TV shows
                '--TVShowName',   episodes[0].season.program.name,
                '--TVSeasonNum',  str(episodes[0].season.number),
                '--TVEpisodeNum', str(episodes[0].number),
                '--TVEpisode',    multipart.name(episodes),
                # also set tags for music files as these have wider support
                '--artist',       episodes[0].season.program.name,
                '--album',        'Season {}'.format(episodes[0].season.number),
                '--tracknum',     str(episodes[0].number),
                '--title',        multipart.name(episodes),
            ]
            with (Path(config.temp) / 'tvrip.log').open('a') as log:
                proc.check_call(cmdline, stdout=log, stderr=log)
            os.chmod(
                tmpfile,
                os.stat(os.path.join(config.target, filename)).st_mode)
            shutil.move(tmpfile, os.path.join(config.target, filename))
        finally:
            os.close(tmphandle)
        for episode in episodes:
            episode.disc_id = title.disc.ident
            episode.disc_title = title.number
            if start_chapter:
                episode.start_chapter = start_chapter.number
                episode.end_chapter = end_chapter.number
            else:
                episode.start_chapter = None
                episode.end_chapter = None


class Title():
    "Represents a title on a DVD"

    def __init__(self, disc):
        super().__init__()
        disc.titles.append(self)
        self._disc = ref(disc)
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
        self.duplicate = 'no'

    def __repr__(self):
        return '<Title({})>'.format(self.number)

    @property
    def disc(self):
        "Returns the owning :class:`Disc`"
        return self._disc()

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
        self._title = ref(title)
        self.number = 0
        self.duration = dt.timedelta(0)

    def __repr__(self):
        return '<Chapter({number}, {duration})>'.format(
            number=self.number, duration=self.duration)

    @property
    def title(self):
        "Returns the owning :class:`Title`"
        return self._title()

    @property
    def start(self):
        "Returns the start time of the chapter"
        return (
            dt.datetime(dt.MINYEAR, 1, 1) + sum((
                c.duration
                for c in self.title.chapters[:self.title.chapters.index(self)]
            ), dt.timedelta(0))
        ).time()

    @property
    def finish(self):
        "Returns the finish time of the chapter"
        return (
            dt.datetime.combine(dt.date(dt.MINYEAR, 1, 1), self.start) +
            self.duration
        ).time()

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

    def play(self, config):
        "Starts VLC playing at the chapter start"
        self.title.disc.play(config, self)


class AudioTrack():
    "Represents an audio track within a Title object"

    def __init__(self, title):
        super().__init__()
        title.audio_tracks.append(self)
        self._title = ref(title)
        self.name = ''
        self.number = 0
        self.language = ''
        self.encoding = ''
        self.channel_mix = ''
        self.sample_rate = 0
        self.bit_rate = 0
        self.best = False

    def __repr__(self):
        return '<AudioTrack({number}, {name!r})>'.format(
            number=self.number, name=self.name)

    @property
    def title(self):
        "Returns the owning title"
        return self._title()


class SubtitleTrack():
    "Represents a subtitle track within a Title object"

    def __init__(self, title):
        super().__init__()
        title.subtitle_tracks.append(self)
        self._title = ref(title)
        self.number = 0
        self.name = ''
        self.language = ''
        self.format = 'VOBSUB'
        self.best = False
        self.log = ''

    def __repr__(self):
        return '<SubtitleTrack({number}, {name!r})>'.format(
            number=self.number, name=self.name)

    @property
    def title(self):
        "Returns the owning title"
        return self._title()
