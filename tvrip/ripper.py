# vim: set et sw=4 sts=4:

import sys
import os
import re
import shutil
import logging
import tempfile
from datetime import datetime, date, time, timedelta, MINYEAR
from operator import attrgetter
from itertools import groupby
from subprocess import Popen, PIPE, STDOUT
from tvrip.database import Configuration
from tvrip.subtitles import Subtitle, Subtitles, SubtitleCorrections

AUDIO_MIX_ORDER = [u'5.1 ch', u'5.0 ch', u'Dolby Surround', u'2.0 ch', u'1.0 ch']
AUDIO_ENCODING_ORDER = [u'DTS', u'AC3']


class Error(Exception):
    u"""Base class for ripper errors"""

class ProcessError(Error):
    u"""Class for errors returned by external processes"""


class Disc(object):
    u"""Represents a DVD disc"""

    def __init__(self):
        super(Disc, self).__init__()
        self.titles = []
        self.serial = None
        self.match = None

    def test(self, pattern, line):
        self.match = pattern.match(line)
        return self.match

    def __repr__(self):
        return u"<Disc()>"

    disc_serial_re = re.compile(ur'^libdvdnav: DVD Serial Number: (?P<serial>.*)$')
    title_re = re.compile(ur'^\+ title (?P<number>\d+):$')
    duration_re = re.compile(ur'^  \+ duration: (?P<duration>.*)$')
    stats_re = re.compile(ur'^  \+ size: (?P<size>.*), aspect: (?P<aspect_ratio>.*), (?P<frame_rate>.*) fps$')
    crop_re = re.compile(ur'^  \+ autocrop: (?P<crop>.*)$')
    comb_re = re.compile(ur'^  \+ combing detected,.*$')
    chapters_re = re.compile(ur'^  \+ chapters:$')
    chapter_re = re.compile(ur'^    \+ (?P<number>\d+): cells \d+->\d+, \d+ blocks, duration (?P<duration>.*)$')
    audio_tracks_re = re.compile(ur'^  \+ audio tracks:$')
    audio_track_re = re.compile(ur'^    \+ (?P<number>\d+), (?P<name>[^(]*) \((?P<encoding>[^)]*)\)( \((?P<label>[^)]*)\))? \((?P<channel_mix>[^)]*)\) \(iso639-2: (?P<language>[a-z]{2,3})\), (?P<sample_rate>\d+)Hz, (?P<bit_rate>\d+)bps$')
    subtitle_tracks_re = re.compile(ur'^  \+ subtitle tracks:$')
    subtitle_track_re = re.compile(ur'^    \+ (?P<number>\d+), (?P<name>.*) \(iso639-2: (?P<language>[a-z]{2,3})\)( \((?P<type>.*)\))?$')
    def scan(self, config):
        self.titles = []
        cmdline = [
            config.get_path('handbrake'),
            u'-i', config.source, # specify the input device
            u'-t', u'0'    # ask for a scan of the entire disc
        ]
        process = Popen(cmdline, stdout=PIPE, stderr=STDOUT)
        output = process.communicate()[0]
        state = set([u'disc'])
        title = None
        # Parse the output into child objects
        for line in output.splitlines():
            if u'disc' in state and self.test(self.disc_serial_re, line):
                self.serial = self.match.group(u'serial')
            elif u'disc' in state and self.test(self.title_re, line):
                if title:
                    title.chapters = sorted(title.chapters, key=attrgetter(u'number'))
                    title.audio_tracks = sorted(title.audio_tracks, key=attrgetter(u'number'))
                    title.subtitle_tracks = sorted(title.subtitle_tracks, key=attrgetter(u'number'))
                state = set([u'disc', u'title'])
                title = Title(self)
                title.number = int(self.match.group(u'number'))
            elif u'title' in state and self.test(self.duration_re, line):
                state = set([u'disc', u'title'])
                hours, minutes, seconds = (int(i) for i in self.match.group(u'duration').split(u':'))
                title.duration = timedelta(seconds=seconds, minutes=minutes, hours=hours)
            elif u'title' in state and self.test(self.stats_re, line):
                state = set([u'disc', u'title'])
                title.size = (int(i) for i in self.match.group(u'size').split(u'x'))
                title.aspect_ratio = float(self.match.group(u'aspect_ratio'))
                title.frame_rate = float(self.match.group(u'frame_rate'))
            elif u'title' in state and self.test(self.crop_re, line):
                state = set([u'disc', u'title'])
                title.crop = (int(i) for i in self.match.group(u'crop').split(u'/'))
            elif u'title' in state and self.test(self.comb_re, line):
                title.interlaced = True
            elif u'title' in state and self.test(self.chapters_re, line):
                state = set([u'disc', u'title', u'chapter'])
            elif u'chapter' in state and self.test(self.chapter_re, line):
                chapter = Chapter(title)
                chapter.number = int(self.match.group(u'number'))
                hours, minutes, seconds = (int(i) for i in self.match.group(u'duration').split(u':'))
                chapter.duration = timedelta(seconds=seconds, minutes=minutes, hours=hours)
            elif u'title' in state and self.test(self.audio_tracks_re, line):
                state = set([u'disc', u'title', u'audio'])
            elif u'audio' in state and self.test(self.audio_track_re, line):
                track = AudioTrack(title)
                track.number = int(self.match.group(u'number'))
                if self.match.group(u'label'):
                    track.name = '%s (%s)' % (
                        self.match.group(u'name'),
                        self.match.group(u'label'),
                    )
                else:
                    track.name = self.match.group(u'name')
                track.language = self.match.group(u'language')
                track.encoding = self.match.group(u'encoding')
                track.channel_mix = self.match.group(u'channel_mix')
                track.sample_rate = int(self.match.group(u'sample_rate'))
                track.bit_rate = int(self.match.group(u'bit_rate'))
            elif u'title' in state and self.test(self.subtitle_tracks_re, line):
                state = set([u'disc', u'title', u'subtitle'])
            elif u'subtitle' in state and self.test(self.subtitle_track_re, line):
                track = SubtitleTrack(title)
                track.number = int(self.match.group(u'number'))
                track.name = self.match.group(u'name')
                track.language = self.match.group(u'language')
                track.type = self.match.group(u'type')
        self.titles = sorted(self.titles, key=attrgetter(u'number'))
        # Determine the best audio and subtitle tracks
        for title in self.titles:
            for key, group in groupby(sorted(title.audio_tracks, key=attrgetter('name')), key=attrgetter('name')):
                group = sorted(group, key=lambda track: (
                    AUDIO_MIX_ORDER.index(track.channel_mix),
                    AUDIO_ENCODING_ORDER.index(track.encoding)
                ))
                if group:
                    group[0].best = True
            for key, group in groupby(sorted(title.subtitle_tracks, key=attrgetter('name')), key=attrgetter('name')):
                group = list(group)
                if group:
                    group[0].best = True

    def rip(self, config, episode, title, audio_tracks, subtitle_tracks, start_chapter=None, end_chapter=None):
        if not isinstance(config, Configuration):
            raise ValueError(u'config must a Configuration instance')
        filename = config.template % {
            u'program': config.program.name,
            u'season':  config.season.number,
            u'episode': episode.number,
            u'name':    episode.name,
        }
        # Convert the subtitle track(s) if required
        if config.subtitle_format == u'subrip':
            for track in subtitle_tracks:
                assert track.title is title
                track.convert(config, filename)
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
            config.get_path(u'handbrake'),
            u'-i', config.source,
            u'-t', unicode(title.number),
            u'-o', os.path.join(config.target, filename),
            u'-f', u'mp4',          # output an MP4 container
            u'-O',                  # optimize for streaming
            u'-m',                  # include chapter markers
            u'--strict-anamorphic', # store pixel aspect ratio
            u'-e', u'x264',         # use x264 for encoding
            u'-q', u'23',           # quality 23
            u'-x', u'b-adapt=2:rc-lookahead=50', # advanced encoding options (mostly defaults from High Profile)
            u'-a', u','.join(unicode(num) for (num, _, _)  in audio_defs),
            u'-6', u','.join(mix          for (_, mix, _)  in audio_defs),
            u'-A', u','.join(name         for (_, _, name) in audio_defs),
        ]
        if start_chapter:
            cmdline.append(u'-c')
            if end_chapter:
                cmdline.append(u'%d-%d' % (start_chapter.number, end_chapter.number))
            else:
                cmdline.append(unicode(start_chapter.number))
        if config.subtitle_format == u'vobsub':
            cmdline.append(u'-s')
            cmdline.append(u','.join(unicode(num) for (num, _) in subtitle_defs))
        if config.decomb == u'on':
            cmdline.append(u'-d')
            cmdline.append(u'slow')
        elif config.decomb == u'auto':
            cmdline.append(u'-5')
        p = Popen(cmdline, stdout=sys.stdout, stderr=sys.stderr)
        p.communicate()
        if p.returncode != 0:
            raise ValueError(u'Handbrake exited with non-zero return code %d' % p.returncode)
        # Tag the resulting file
        tmphandle, tmpfile = tempfile.mkstemp(dir=config.temp)
        try:
            cmdline = [
                config.get_path(u'atomicparsley'),
                os.path.join(config.target, filename),
                u'-o', tmpfile,
                u'--stik', u'TV Show',
                # set tags for TV shows
                u'--TVShowName',   episode.season.program.name,
                u'--TVSeasonNum',  unicode(episode.season.number),
                u'--TVEpisodeNum', unicode(episode.number),
                u'--TVEpisode',    episode.name,
                # also set tags for music files as these have wider support
                u'--artist',       episode.season.program.name,
                u'--album',        u'Season %d' % episode.season.number,
                u'--tracknum',     unicode(episode.number),
                u'--title',        episode.name
            ]
            p = Popen(cmdline, stdout=sys.stdout, stderr=sys.stderr)
            p.communicate()
            if p.returncode != 0:
                raise ValueError('AtomicParsley exited with non-zero return code %d' % p.returncode)
            os.rename(tmpfile, os.path.join(config.target, filename))
        finally:
            os.close(tmphandle)

class Title(object):
    u"""Represents a title on a DVD"""

    def __init__(self, disc):
        super(Title, self).__init__()
        disc.titles.append(self)
        self.disc = disc
        self.number = 0
        self.duration = timedelta()
        self.size = (0, 0)
        self.aspect_ratio = 0
        self.frame_rate = 0
        self.crop = (0, 0, 0, 0)
        self.chapters = []
        self.audio_tracks = []
        self.subtitle_tracks = []
        self.interlaced = False

    def __repr__(self):
        return u"<Title(%d)>" % self.number


class Chapter(object):
    u"""Represents a chapter marker within a Title object"""

    def __init__(self, title):
        super(Chapter, self).__init__()
        title.chapters.append(self)
        self.title = title
        self.number = 0
        self.duration = timedelta(0)

    @property
    def start(self):
        result = datetime(MINYEAR, 1, 1)
        for c in self.title.chapters:
            if c.number >= self.number:
                break
            result += c.duration
        return result.time()

    @property
    def finish(self):
        result = datetime.combine(date(MINYEAR, 1, 1), self.start)
        return (result + self.duration).time()

    def __repr__(self):
        return u"<Chapter(%d, %s)>" % (self.number, self.duration)


class AudioTrack(object):
    u"""Represents an audio track within a Title object"""

    def __init__(self, title):
        super(AudioTrack, self).__init__()
        title.audio_tracks.append(self)
        self.title = title
        self.name = u''
        self.number = 0
        self.language = u''
        self.encoding = u''
        self.channel_mix = u''
        self.sample_rate = 0
        self.bit_rate = 0
        self.best = False

    def __repr__(self):
        return u"<AudioTrack(%d, '%s')>" % (self.number, self.name)


class SubtitleTrack(object):
    u"""Represents a subtitle track within a Title object"""

    def __init__(self, title):
        super(SubtitleTrack, self).__init__()
        title.subtitle_tracks.append(self)
        self.title = title
        self.number = 0
        self.name = u''
        self.language = u''
        self.type = u''
        self.best = False
        self.log = u''
        self.corrections = SubtitleCorrections()

    def convert(self, config, filename):
        logging.info(u'Converting "%s" subtitle track' % self.name)
        self.tempdir = tempfile.mkdtemp(dir=config.temp)
        cat_cmdline = [
            config.get_path(u'tccat'),
            u'-i', config.source,
            # ,-1 means extract all chapters from specified title
            u'-T', u'%d,-1' % self.title.number,
        ]
        extract_cmdline = [
            config.get_path(u'tcextract'),
            # extract private stream (subtitles)
            u'-x', u'ps1',
            # type of input is a VOB
            u'-t', u'vob',
            # subtitle tracks are numbered starting at 0x20
            u'-a', unicode(hex(0x20 + self.number - 1)),
        ]
        convert_cmdline = [
            config.get_path(u'subtitle2pgm'),
            # use the specified color as black
            u'-c', ','.join(unicode(0 if i == config.subtitle_black else 255) for i in xrange(1, 5)),
            # trim borders from subtitle frames
            u'-C', u'1',
            # output to the temporary directory with a "sub" prefix
            u'-o', os.path.join(self.tempdir, u'sub'),
            # print progress messages
            u'-P',
        ]
        cat_proc = Popen(cat_cmdline, stdout=PIPE, stderr=sys.stderr)
        extract_proc = Popen(extract_cmdline, stdin=cat_proc.stdout, stdout=PIPE, stderr=sys.stderr)
        convert_proc = Popen(convert_cmdline, stdin=extract_proc.stdout, stdout=sys.stdout, stderr=sys.stderr)
        convert_proc.communicate()
        extract_proc.wait()
        cat_proc.wait()
        if cat_proc.returncode != 0:
            raise ProcessError(u'%s exited with non-zero return code: %s' % (config.get_path(u'tccat'), cat_proc.returncode))
        if extract_proc.returncode != 0:
            raise ProcessError(u'%s exited with non-zero return code: %s' % (config.get_path(u'tcextract'), extract_proc.returncode))
        if convert_proc.returncode != 0:
            raise ProcessError(u'%s exited with non-zero return code: %s' % (config.get_path(u'subtitle2pgm'), convert_proc.returncode))
        # Parse the .srtx file left in the temporary directory by extract(). In
        # this file each subtitle entry's text indicates the file containing
        # the subtitle image
        template_file = os.path.join(self.tempdir, u'sub.srtx')
        subrip_file = os.path.join(config.target, os.path.splitext(filename)[0] + u'.srt')
        subtitles = Subtitles(parsefile=open(template_file, u'rU'))
        # Run all the images through gocr to convert to text, replacing the
        # filename in the subtitle with the OCR'd text
        logging.info(u'Converting subtitle images to text')
        for subtitle in subtitles:
            # Remove the .txt suffix
            imagefile = subtitle.text[:-4]
            if not os.path.exists(imagefile):
                raise IOError(u'Image file "%s" referenced by "%s" does not exist' % (imagefile, srtxfile))
            cmdline = [
                config.get_path(u'gocr'),
                u'-i', imagefile,
                # path to database of learned characters (program specific)
                u'-p', self.title.episode.season.program.dbpath + '/',
                # output format
                u'-f', u'UTF8',
                # minimum number of pixels between words
                u'-s', u'9',
                # use and extend database, and perform zoning analysis
                u'-m', u'390',
            ]
            p = Popen(cmdline, stdin=sys.stdin, stdout=PIPE, stderr=sys.stderr)
            subtitle.text = p.communicate()[0].strip().decode('UTF-8')
            if p.returncode != 0:
                raise ProcessError(u'%s exited with non-zero return code %d' % (config.get_path(u'gocr'), p.returncode))
        # Apply language-specific correction rules if available, then
        # normalize, encode and write the output
        logging.info(u'Applying corrections to subtitle text')
        self.corrections.load_rules(self.language)
        subtitles = self.corrections.process(subtitles)
        subtitles.normalize()
        with open(subrip_file, u'w') as f:
            f.write(unicode(subtitles).encode(u'UTF-8'))
        # Remove the entire temporary path
        shutil.rmtree(self.tempdir)
        del self.tempdir

    def __repr__(self):
        return u"<SubtitleTrack(%d, '%s')>" % (self.number, self.name)


