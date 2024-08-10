.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
automap
=======

::

    automap [episodes [titles]]

The ``automap`` command is used to have the application attempt to figure out
which titles (or chapters of titles) contain the next set of unripped episodes.
If no episode numbers are specified, or ``*`` is specified all unripped
episodes are considered candidates. Otherwise, only those episodes specified
are considered.

If no title numbers are specified, all titles on the disc are considered
candidates. Otherwise, only the titles specified are considered.

The algorithm relies on the :doc:`var_duration` being correctly set. It
attempts to match unripped titles on the disc which fit within the duration
range to unripped episodes in the current season. If this "title mapping"
fails, "chapter mapping" is attempted instead. This finds the longest title on
the disc, and attempts to find sequences of chapters within that title which
match the specified duration range for the given episodes (all episodes by
default). This often results in an ambiguous set of solutions, in which case
you will be prompted to play certain chapters and answer if they correspond to
the start of an episode.

The current episode mapping can be viewed in the output of the :doc:`cmd_map`
command.

See also :doc:`cmd_map`, :doc:`cmd_unmap`, :doc:`cmd_season`, :doc:`var_duration`
