.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

===
rip
===

::

    rip [episodes]

The ``rip`` command begins ripping the mapped titles from the current source
device, converting them according to the current preferences, and storing the
results in the target path.

You can specify a list of episodes to rip a subset of the map. This is useful
to adjust ripping configurations between episodes. Note that already ripped
episodes will not be re-ripped even if manually specified. Use :doc:`cmd_unrip`
first.

If no episodes are specified, all unripped episodes in the map will be ripped.
Examples::

    (tvrip) rip
    (tvrip) rip 8,11-15

See also :doc:`cmd_unrip`, :doc:`cmd_map`, :doc:`cmd_automap`
