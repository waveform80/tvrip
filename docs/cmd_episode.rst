.. tvrip: extract and transcode DVDs of TV series
..
.. Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
..
.. SPDX-License-Identifier: GPL-3.0-or-later

=======
episode
=======

::

    episode insert|update|delete <number> [name]

The ``episode`` command is used to modify the details of a single episode in
the current season. The operation depends on the first parameter:

``insert``
    The episode will be inserted at the specified position, shifting any
    existing, and all subsequent episodes up (numerically)

``update``
    The numbered episode is renamed

``delete``
    The numbered episode is removed, shifting all subsequent episodes down
    (numerically). In this case, ``name`` does not need to be specified.

See also :doc:`cmd_season`, :doc:`cmd_episodes`
