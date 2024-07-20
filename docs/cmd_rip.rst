===
rip
===

::

    rip [episodes]

The ``rip`` command begins ripping the mapped titles from the current source
device, converting them according to the current preferences, and storing the
results in the target path. Only previously unripped episodes will be ripped.
If you wish to re-rip an episode, use the :doc:`cmd_unrip` command to set it to
unripped first.

You can specify a list of episodes to rip only a subset of the map. This is
useful to adjust ripping configurations between episodes. Note that already
ripped episodes will not be re-ripped even if manually specified. Use
:doc:`cmd_unrip` first.

If no episodes are specified, all unripped episodes in the map will be ripped.
Examples::

    (tvrip) rip
    (tvrip) rip 8,11-15

See also :doc:`cmd_unrip`, :doc:`cmd_map`, :doc:`cmd_automap`
