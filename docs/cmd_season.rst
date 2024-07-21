.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
season
=======

::

    season <number>

The ``season`` command specifies the season the disc contains episodes for.
This number is used when constructing the filename of ripped episodes.

This command is also used to expand the episode database. If the number given
does not exist, it will be entered into the database under the current program
and you will be prompted for episode names.

See also :doc:`cmd_program`, :doc:`cmd_seasons`
