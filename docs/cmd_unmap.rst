.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=====
unmap
=====

::

    unmap <episodes>

The ``unmap`` command is used to remove a title to episode mapping. For
example, if the auto-mapping when scanning a disc makes an error, you can use
the :doc:`cmd_map` and :doc:`cmd_unmap` commands to fix it. You can also
specify ``*`` to clear the mapping list completely. For example::

    (tvrip) unmap 3
    (tvrip) unmap 7
    (tvrip) unmap *

See also :doc:`cmd_map`, :doc:`cmd_automap`
