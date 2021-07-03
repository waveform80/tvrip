from datetime import time

import pytest

from tvrip.ripper import *


class Cmdline(list):
    def __contains__(self, item):
        if isinstance(item, list):
            l = len(item)
            for i in range(len(self) - l + 1):
                if item == self[i:i + l]:
                    return True
            return False
        else:
            return super().__contains__(item)


def test_disc(db, with_config, with_proc):
    disc = Disc(with_config)
    assert repr(disc) == '<Disc()>'
    assert len(disc.titles) == 10


def test_titles(db, with_config, with_proc):
    disc = Disc(with_config)
    assert repr(disc.titles[0]) == '<Title(1)>'
    assert isinstance(disc.titles[0], Title)
    assert disc.titles[0].number == 1
    assert disc.titles[0].next is disc.titles[1]
    assert disc.titles[1].previous is disc.titles[0]
    assert disc.titles[0].previous is None
    assert disc.titles[-1].next is None


def test_chapters(db, with_config, with_proc):
    disc = Disc(with_config)
    assert len(disc.titles[0].chapters) == sum(
        1 for t in disc.titles[1:8] for c in t.chapters)
    title = disc.titles[0]
    assert isinstance(title.chapters[0], Chapter)
    assert repr(title.chapters[0]) == '<Chapter(1, 0:07:11.564626)>'
    assert title.chapters[0].start == time(0, 0, 0)
    assert title.chapters[1].start == time(0, 7, 11, 564626)
    assert title.chapters[0].finish == title.chapters[1].start
    assert title.chapters[0].next is title.chapters[1]
    assert title.chapters[0].previous is None
    assert title.chapters[1].previous is title.chapters[0]
    assert title.chapters[-1].next is None


def test_subtracks(db, with_config, with_proc):
    disc = Disc(with_config)
    title = disc.titles[0]
    assert repr(title.audio_tracks[0]) == "<AudioTrack(1, 'English')>"
    assert repr(title.subtitle_tracks[0]) == "<SubtitleTrack(1, 'English (16:9) [VOBSUB]')>"


def test_scan_whole_disc(db, with_config, with_all_episodes, with_proc):
    disc = Disc(with_config)
    assert repr(disc) == '<Disc()>'
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$a065599e1270c1b99a6f74a4693b829b2f58edbe'
    assert len(disc.titles) == 10


def test_scan_one_title(db, with_config, with_all_episodes, with_proc):
    disc = Disc(with_config, titles=[1, 2, 3])
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$e52567c41d3e8503c7fa5496ddd0c67d67d78b6d'
    assert len(disc.titles) == 3
    cmdline = with_proc.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' not in cmdline


def test_scan_with_dvdread(db, with_config, with_all_episodes, with_proc):
    with_config.dvdnav = False
    disc = Disc(with_config, titles=[1, 2, 3])
    assert disc.name == 'FOO AND BAR'
    assert disc.serial == '123456789'
    assert disc.ident == '$H1$e52567c41d3e8503c7fa5496ddd0c67d67d78b6d'
    assert len(disc.titles) == 3
    cmdline = with_proc.run.call_args.args[0]
    assert cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in cmdline


def test_scan_wrong_source(db, with_config, with_proc):
    with_config.source = '/dev/badsource'
    with pytest.raises(IOError):
        disc = Disc(with_config)


def test_scan_bad_handbrake(db, with_config, with_proc):
    with_config.source = '/dev/badjson'
    with pytest.raises(IOError):
        disc = Disc(with_config)


def test_play_disc(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config)
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd' in cmdline


def test_play_disc_with_title(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config, disc.titles[0])
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1' in cmdline


def test_play_disc_with_chapter(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.play(with_config, disc.titles[0].chapters[0])
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1:1' in cmdline


def test_play_first_title(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.titles[0].play(with_config)
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1' in cmdline


def test_play_first_title_first_chapter(db, with_config, with_proc):
    disc = Disc(with_config)
    disc.titles[0].chapters[0].play(with_config)
    cmdline = with_proc.check_call.call_args.args[0]
    assert cmdline[0] == 'vlc'
    assert 'dvd:///dev/dvd#1:1' in cmdline


def test_rip_bad_args(db, with_config, with_episode, with_proc):
    disc = Disc(with_config)
    with pytest.raises(ValueError):
        disc.rip(with_config, [with_episode], disc.titles[0],
                 [disc.titles[1].audio_tracks[0]], [])


def test_rip_with_defaults(db, with_config, with_episode, with_proc):
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        [disc.titles[1].audio_tracks[0]], [])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '2'] in hb_cmdline
    assert ['-d', 'slow'] not in hb_cmdline
    assert '-5' not in hb_cmdline
    assert '-s' not in hb_cmdline
    assert '-c' not in hb_cmdline
    assert '--no-dvdnav' not in hb_cmdline
    assert ap_cmdline[0] == 'AtomicParsley'
    assert ['--TVShowName', 'Foo & Bar'] in ap_cmdline
    assert ['--TVEpisodeNum', '1'] in ap_cmdline


def test_rip_with_deinterlace(db, with_config, with_episode, with_proc):
    with_config.decomb = 'on'
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        [disc.titles[1].audio_tracks[0]], [])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-d', 'slow'] in hb_cmdline


def test_rip_with_decomb(db, with_config, with_episode, with_proc):
    with_config.decomb = 'auto'
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        [disc.titles[1].audio_tracks[0]], [])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert '-5' in hb_cmdline


def test_rip_with_subtitles(db, with_config, with_episode, with_proc):
    with_config.subtitle_format = 'vobsub'
    with_config.subtitle_default = False
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        disc.titles[1].audio_tracks, disc.titles[1].subtitle_tracks)
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in hb_cmdline
    assert '--subtitle-default' not in hb_cmdline


def test_rip_with_default_subtitles(db, with_config, with_episode, with_proc):
    with_config.subtitle_format = 'vobsub'
    with_config.subtitle_default = True
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        disc.titles[1].audio_tracks, disc.titles[1].subtitle_tracks)
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-s', '1,2,3'] in hb_cmdline
    assert ['--subtitle-default', '1'] in hb_cmdline


def test_rip_animation(db, with_config, with_episode, with_proc):
    with_config.video_style = 'animation'
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        disc.titles[1].audio_tracks, [])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['--encoder-tune', 'animation'] in hb_cmdline


def test_rip_with_dvdread(db, with_config, with_episode, with_proc):
    with_config.dvdnav = False
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[1],
        [disc.titles[1].audio_tracks[0]], [])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert '--no-dvdnav' in hb_cmdline


def test_rip_chapter(db, with_config, with_episode, with_proc):
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[0],
        [disc.titles[0].audio_tracks[0]], [],
        start_chapter=disc.titles[0].chapters[0])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '1'] in hb_cmdline
    assert ['-c', '1'] in hb_cmdline


def test_rip_chapters(db, with_config, with_episode, with_proc):
    disc = Disc(with_config)
    disc.rip(
        with_config, [with_episode], disc.titles[0],
        [disc.titles[0].audio_tracks[0]], [],
        start_chapter=disc.titles[0].chapters[0],
        end_chapter=disc.titles[0].chapters[4])
    assert len(with_proc.check_call.call_args_list) == 2
    hb_cmdline = Cmdline(with_proc.check_call.call_args_list[0].args[0])
    ap_cmdline = Cmdline(with_proc.check_call.call_args_list[1].args[0])
    assert hb_cmdline[0] == 'HandBrakeCLI'
    assert ['-i', '/dev/dvd'] in hb_cmdline
    assert ['-t', '1'] in hb_cmdline
    assert ['-c', '1-5'] in hb_cmdline
