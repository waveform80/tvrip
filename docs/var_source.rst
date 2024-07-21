.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
source
=======

::

    set source /path/to/dev

Specifies the path of the DVD or Blu-ray drive containing the source disc. Any
value specified must be a valid block device. Defaults to "/dev/sr0". Example::

    (tvrip) set source /dev/sr1
