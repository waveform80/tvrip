.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

========
Tutorial
========

This tutorial will walk you through the simple case of ripping the first disc
of Season 2 of `The Boys`_.

.. warning::

    "tvrip" is intended for ripping discs that *you own*; it is emphatically
    *not* intended for piracy. The *whole point* of the application is to
    enable those wishing to avoid the `enshittification`_ of services by
    *owning* their media.

    Why not just use the DVD? Because physical media is a pain to switch (this
    is something of which the streaming services have made the masses aware),
    and moreover tends not to last (particularly when young, grubby fingers are
    constantly messing with the DVDs of their favourite film!).

    Buy the disc, rip the disc, own the media.

Having installed "tvrip" and its pre-requisites, the first thing to do is start
it up and check the configuration (see :doc:`cmd_config`), and adjust any
settings that we want to correct.

.. code-block:: console

    $ tvrip
    (tvrip) config
    ╭──────────────────┬─────────────────────────────────╮
    │ Setting          │ Value                           │
    ├──────────────────┼─────────────────────────────────┤
    │ atomicparsley    │ AtomicParsley                   │
    │ handbrake        │ HandBrakeCLI                    │
    │ mkvpropedit      │ mkvpropedit                     │
    │ vlc              │ vlc                             │
    ├──────────────────┼─────────────────────────────────┤
    │ source           │ /dev/dvd                        │
    │ duration         │ 40.0-50.0 (mins)                │
    │ duplicates       │ all                             │
    ├──────────────────┼─────────────────────────────────┤
    │ target           │ /home/dave/Videos               │
    │ temp             │ /tmp                            │
    │ template         │ {program} - {id} - {name}.{ext} │
    │ id_template      │ {season}x{episode:02d}          │
    │ output_format    │ mp4                             │
    │ max_resolution   │ 1920x1080                       │
    │ decomb           │ off                             │
    │ audio_mix        │ dpl2                            │
    │ audio_all        │ off                             │
    │ audio_langs      │ eng                             │
    │ subtitle_format  │ none                            │
    │ subtitle_all     │ off                             │
    │ subtitle_default │ off                             │
    │ subtitle_langs   │ eng                             │
    │ video_style      │ tv                              │
    │ dvdnav           │ on                              │
    │ api_url          │ https://api.thetvdb.com/        │
    │ api_key          │                                 │
    ╰──────────────────┴─────────────────────────────────╯

In this case, we want to output the Matroska format, we want all the English
audio tracks (to capture any director's commentaries), we want "vobsub"
subtitles (this is the native subtitle format on DVDs), and all the English
subtitle tracks (in case of extras).

.. code-block:: console

    (tvrip) set output_format mkv
    (tvrip) set audio_all on
    (tvrip) set subtitle_format vobsub
    (tvrip) set subtitle_all on

We'll check the configuration now looks sensible.

.. code-block:: console

    (tvrip) config
    ╭──────────────────┬─────────────────────────────────╮
    │ Setting          │ Value                           │
    ├──────────────────┼─────────────────────────────────┤
    │ atomicparsley    │ AtomicParsley                   │
    │ handbrake        │ HandBrakeCLI                    │
    │ mkvpropedit      │ mkvpropedit                     │
    │ vlc              │ vlc                             │
    ├──────────────────┼─────────────────────────────────┤
    │ source           │ /dev/dvd                        │
    │ duration         │ 40.0-50.0 (mins)                │
    │ duplicates       │ all                             │
    ├──────────────────┼─────────────────────────────────┤
    │ target           │ /home/dave/Videos               │
    │ temp             │ /tmp                            │
    │ template         │ {program} - {id} - {name}.{ext} │
    │ id_template      │ {season}x{episode:02d}          │
    │ output_format    │ mkv                             │
    │ max_resolution   │ 1920x1080                       │
    │ decomb           │ off                             │
    │ audio_mix        │ dpl2                            │
    │ audio_all        │ on                              │
    │ audio_langs      │ eng                             │
    │ subtitle_format  │ vobsub                          │
    │ subtitle_all     │ on                              │
    │ subtitle_default │ off                             │
    │ subtitle_langs   │ eng                             │
    │ video_style      │ tv                              │
    │ dvdnav           │ on                              │
    │ api_url          │ https://api.thetvdb.com/        │
    │ api_key          │                                 │
    ╰──────────────────┴─────────────────────────────────╯

Next, we have a look at the programs list (with :doc:`cmd_programs`) to see if
tvrip knows about "The Boys".

.. code-block:: console

    (tvrip) programs
    ╭─────────┬─────────┬──────────┬────────╮
    │ Program │ Seasons │ Episodes │ Ripped │
    ├─────────┼─────────┼──────────┼────────┤
    ╰─────────┴─────────┴──────────┴────────╯

It does not (in fact it doesn't know about any programs at all), so we use
:doc:`cmd_program` to define it. At this point, tvrip will query the excellent
`TVDB`_ for any matching program names, and produce a (very long) list of
possible matches. The first match (unsurprisingly) is the correct one, so we
enter "1" and let tvrip request all the episode data.

.. code-block:: console

    (tvrip) program The Boys
    Searching the TVDB for The Boys
    Found the following matches on the TVDB:
    ╭────┬───────────────────────┬────────────┬────────────┬───────────────────────╮
    │ #  │ Title                 │ Aired      │ Status     │ Overview              │
    ├────┼───────────────────────┼────────────┼────────────┼───────────────────────┤
    │ 1  │ The Boys              │ 2019-07-26 │ Continuing │ In a world where      │
    │    │                       │            │            │ superheroes embrace   │
    │    │                       │            │            │ the darker side of    │
    │    │                       │            │            │ their massive         │
    │    │                       │            │            │ celebrity and fame, a │
    │    │                       │            │            │ group of vigilantes   │
    │    │                       │            │            │ known informally as   │
    │    │                       │            │            │ "The Boys" set out to │
    │    │                       │            │            │ take down corrupt     │
    │    │                       │            │            │ superheroes with no   │
    │    │                       │            │            │ more th…              │
    │ 2  │ The Boys Presents:    │ 2022-03-04 │ Ended      │ From some of the most │
    │    │ Diabolical            │            │            │ unhinged and maniacal │
    │    │                       │            │            │ minds in Hollywood    │
    │    │                       │            │            │ today comes           │
    │    │                       │            │            │ Diabolical, a         │
    │    │                       │            │            │ collection of eight   │
    │    │                       │            │            │ irreverent and        │
    │    │                       │            │            │ emotionally shocking  │
    │    │                       │            │            │ animated short films. │
    │    │                       │            │            │ Each episode plunges  │
    │    │                       │            │            │ elbow-deep …          │
    │ 3  │ Prime Rewind: Inside  │ 2020-08-28 │ Ended      │ A talk show about     │
    │    │ The Boys              │            │            │ Season 2 of the       │
    │    │                       │            │            │ Amazon Original       │
    │    │                       │            │            │ Series "The Boys",    │
    │    │                       │            │            │ hosted by Aisha Tyler │
    │    │                       │            │            │ and featuring the     │
    │    │                       │            │            │ creators and cast     │
    │    │                       │            │            │ from the series,      │
    │    │                       │            │            │ including Karl Urban  │
    │    │                       │            │            │ (Butcher), Jack Quaid │
    │    │                       │            │            │ (Hughie), An…         │
    │ 4  │ The Boys: VNN (Seven  │ 2021-07-07 │ Ended      │ A digital series      │
    │    │ on 7)                 │            │            │ bridges the events    │
    │    │                       │            │            │ that take place       │
    │    │                       │            │            │ between Season 2 and  │
    │    │                       │            │            │ Season 3 of The Boys' │
    │    │                       │            │            │ main series           │
    │    │                       │            │            │ narrative.            │
    ...
    Which entry matches the program you wish to rip (enter 0 if you wish to enter program information
    manually)? [0-88] 1
    Querying TVDB for season 0
    Querying TVDB for season 1
    Querying TVDB for season 2
    Querying TVDB for season 3
    Querying TVDB for season 4

At this point, tvrip will have set the current program to "The Boys", and the
current season to "1". We can take a look at the program data that tvrip has
retrieved with :doc:`cmd_programs`, :doc:`cmd_seasons`, and
:doc:`cmd_episodes`.

.. code-block::

    (tvrip) programs
    ╭──────────┬─────────┬──────────┬────────╮
    │ Program  │ Seasons │ Episodes │ Ripped │
    ├──────────┼─────────┼──────────┼────────┤
    │ The Boys │       5 │       89 │   0.0% │
    ╰──────────┴─────────┴──────────┴────────╯
    (tvrip) seasons
    Seasons for program The Boys

    ╭─────┬──────────┬────────╮
    │ Num │ Episodes │ Ripped │
    ├─────┼──────────┼────────┤
    │ 0   │       57 │   0.0% │
    │ 1   │        8 │   0.0% │
    │ 2   │        8 │   0.0% │
    │ 3   │        8 │   0.0% │
    │ 4   │        8 │   0.0% │
    ╰─────┴──────────┴────────╯
    (tvrip) episodes
    Episodes for season 1 of program The Boys

    ╭─────┬───────────────────────────────┬────────╮
    │ Num │ Title                         │ Ripped │
    ├─────┼───────────────────────────────┼────────┤
    │ 1   │ The Name of the Game          │        │
    │ 2   │ Cherry                        │        │
    │ 3   │ Get Some                      │        │
    │ 4   │ The Female of the Species     │        │
    │ 5   │ Good for the Soul             │        │
    │ 6   │ The Innocents                 │        │
    │ 7   │ The Self-Preservation Society │        │
    │ 8   │ You Found Me                  │        │
    ╰─────┴───────────────────────────────┴────────╯

This all looks reasonable, but it's season 2 we're interested in. We use
:doc:`cmd_season` to switch to season 2, and check the list of episodes once
more.

.. code-block:: console

    (tvrip) season 2
    (tvrip) episodes
    Episodes for season 2 of program The Boys

    ╭─────┬─────────────────────────────────────────────────┬────────╮
    │ Num │ Title                                           │ Ripped │
    ├─────┼─────────────────────────────────────────────────┼────────┤
    │ 1   │ The Big Ride                                    │        │
    │ 2   │ Proper Preparation and Planning                 │        │
    │ 3   │ Over the Hill with the Swords of a Thousand Men │        │
    │ 4   │ Nothing Like it in the World                    │        │
    │ 5   │ We Gotta Go Now                                 │        │
    │ 6   │ The Bloody Doors Off                            │        │
    │ 7   │ Butcher, Baker, Candlestick Maker               │        │
    │ 8   │ What I Know                                     │        │
    ╰─────┴─────────────────────────────────────────────────┴────────╯

At this point, we load the first disc of the set into the drive, set the source
drive correctly (the default of :file:`/dev/dvd` is almost certainly incorrect)
and tell tvrip to scan the disc (see :doc:`cmd_scan`). It does so, and reports
the titles found on the disc.

.. code-block::

    (tvrip) set source /dev/sr1
    (tvrip) scan
    Scanning disc in /dev/sr1
    Disc type:
    Disc identifier: $H1$8ee229fadd956e45341a85f6c24a445a3998bc27
    Disc serial:
    Disc name:
    Disc has 3 titles

    ╭───────┬──────────┬──────────┬─────┬───────╮
    │ Title │ Chapters │ Duration │ Dup │ Audio │
    ├───────┼──────────┼──────────┼─────┼───────┤
    │ 1     │        9 │  1:00:12 │     │ eng   │
    │ 2     │        9 │  0:56:49 │     │ eng   │
    │ 3     │        9 │  0:55:59 │     │ eng   │
    ╰───────┴──────────┴──────────┴─────┴───────╯

At this point it is probably worth going through some common concepts used
throughout tvrip:

programs
    This refers to TV shows, but "show" sounds a bit too much like a command so
    we use "program" instead.

seasons
    This refers to the set of episodes of a TV show, broadcast within a single
    year. Most of the time seasons are numbered from 1 but there are exceptions
    to this (e.g. classic `Tom and Jerry`_ use season numbers corresponding to
    the release decade of the cartoon).

episodes
    This refers to a single broadcast of a TV show. Like seasons, episodes are
    numbered but also have a name associated with them. We call this the
    episode name and not the title to avoid confusion with physical media (see
    below).

discs
    Physical media, such as `DVDs`_ or `Blurays`_.

titles
    The representation of a single TV show on a disc. If you remember CDs (or
    vinyl!), you might think of these as "tracks" but title is a bit more
    accurate as titles on a DVD or Bluray disc can actually share data. Besides
    which, track is also used for…

tracks
    Refers to individual audio or subtitle tracks within a title on a disc.

At this point we need to map the titles on the disc to the episodes in the
season. We can do this manually with the :doc:`cmd_map` command, but it's much
easier to do this automatically with :doc:`cmd_automap`. 

For this to work, tvrip needs to know how long an episode typically is. We know
(from watching the show!) that episodes are typically an hour-ish long. From
the output above we can see the three titles on the disc range from about 55
minutes to 1 hour long. This is fairly typical; broadcast TV shows are
typically a bit shorter than their "ideal" runtime with the different made up
with ads, spots, and the like.

Hence we tell tvrip episodes range from 55-65 minutes in length, and then run
:doc:`cmd_automap`.

.. code-block::

    (tvrip) set duration 55-65
    (tvrip) automap
    Performing auto-mapping
    Episode Mapping for The Boys season 2:

    ╭───────┬──────────┬────────┬─────────┬────────────────────────────────────────╮
    │ Title │ Duration │ Ripped │ Episode │ Name                                   │
    ├───────┼──────────┼────────┼─────────┼────────────────────────────────────────┤
    │ 1     │  1:00:12 │        │       1 │ The Big Ride                           │
    │ 2     │  0:56:49 │        │       2 │ Proper Preparation and Planning        │
    │ 3     │  0:55:59 │        │       3 │ Over the Hill with the Swords of a     │
    │       │          │        │         │ Thousand Men                           │
    ╰───────┴──────────┴────────┴─────────┴────────────────────────────────────────╯

This command simply maps the titles on the disc to unripped episodes in the
current season, in ascending order. Much of the time, the episodes for shows
appear in ascending order on their discs. However, this is not always the case
and you are strongly advised to check that titles correspond to their mapped
epsiode. You can do this with the :doc:`cmd_play` command which will launch VLC
with the specified title.

.. code-block::

    (tvrip) play 1

Once you know which episode being played, close VLC to return to tvrip (VLC is
not launched in the background; tvrip will be suspended whilst the disc is
playing).

Now we are satisfied that our episode mapping is correct, we proceed to ripping
the episodes. Files will be output in the directory configured by
:doc:`var_target`, in the format specified by :doc:`var_output_format`.

.. code-block::

    (tvrip) rip
    Ripping episode 1, "The Big Ride"
    Ripping episode 2, "Proper Preparation and Planning"
    Ripping episode 3, "Over the Hill with the Swords of a Thousand Men"

Once the rip is finished, we can query the episodes to see which ones remain.

.. code-block::

    (tvrip) episodes
    Episodes for season 2 of program The Boys

    ╭─────┬─────────────────────────────────────────────────┬────────╮
    │ Num │ Title                                           │ Ripped │
    ├─────┼─────────────────────────────────────────────────┼────────┤
    │ 1   │ The Big Ride                                    │   ✓    │
    │ 2   │ Proper Preparation and Planning                 │   ✓    │
    │ 3   │ Over the Hill with the Swords of a Thousand Men │   ✓    │
    │ 4   │ Nothing Like it in the World                    │        │
    │ 5   │ We Gotta Go Now                                 │        │
    │ 6   │ The Bloody Doors Off                            │        │
    │ 7   │ Butcher, Baker, Candlestick Maker               │        │
    │ 8   │ What I Know                                     │        │
    ╰─────┴─────────────────────────────────────────────────┴────────╯

Now switch to disc 2, :doc:`cmd_scan`, :doc:`cmd_automap`, and :doc:`cmd_rip`!

.. _The Boys: https://www.amazon.co.uk/Boys-Season-02-DVD/dp/B08YLGJWY3/
.. _enshittification: https://en.wikipedia.org/wiki/Enshittification
.. _TVDB: https://thetvdb.com/
.. _DVDs: https://en.wikipedia.org/wiki/DVD
.. _Blurays: https://en.wikipedia.org/wiki/Blu-ray
.. _Tom and Jerry: https://thetvdb.com/series/tom-and-jerry#seasons
