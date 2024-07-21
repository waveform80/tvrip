.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=========
program
=========

::

    program <name>

The ``program`` command specifies the program the disc contains episodes for.
This is used when constructing the filename of ripped episodes.

This command is also used to expand the episode database. If the name given
does not exist, it will be entered into the database and you will be prompted
for season and episode information.

See also :doc:`cmd_episodes`, :doc:`cmd_programs`
