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
candidates. Otherwise, only the titles specified are considered. If title
mapping fails, chapter-based mapping is attempted instead.

The current episode mapping can be viewed in the output of the :doc:`cmd_map`
command.

See also :doc:`cmd_map`, :doc:`cmd_unmap`
