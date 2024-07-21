.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

======
target
======

::

    set target /path/to/videos

Specifies the directory under which output files will be written. Note that the
:doc:`var_template` may include additional sub-directories that will be created
under this. For example, to output to the "Videos" directory under your
home-directory::

    (tvrip) set target ~/Videos

See also :doc:`var_template`
