.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

===
map
===

::

    map [episode title[.start[-end]]]

The ``map`` command is used to define which title on the disc contains the
specified episode. This is used when constructing the filename of ripped
episodes. Note that multiple episodes can be mapped to a single title, to deal
with multi-part episodes being encoded as a single title.

For example::

    (tvrip) map 3 1
    (tvrip) map 7 4
    (tvrip) map 5 2.1-12

If no arguments are specified, the current episode map will be displayed. For
example::

    (tvrip) map
    Episode Mapping for The Boys season 2:

    ╭─────────┬───────────────────────────────────┬───────┬──────────┬────────╮
    │ Episode │ Name                              │ Title │ Duration │ Ripped │
    ├─────────┼───────────────────────────────────┼───────┼──────────┼────────┤
    │       7 │ Butcher, Baker, Candlestick Maker │     1 │  0:52:05 │        │
    │       8 │ What I Know                       │     2 │  1:04:30 │        │
    ╰─────────┴───────────────────────────────────┴───────┴──────────┴────────╯

See also :doc:`cmd_automap`, :doc:`cmd_unmap`
