========
duration
========

::

    set duration <min>-<max>

This setting configures the minimum and maximum length (in minutes) that an
episode is expected to be. This is used when the :doc:`cmd_automap` command is
mapping titles to episodes, to determine which titles on the disc are likely to
be episodes.

Typically, if episodes are expected to be half an hour long (for example), you
may find that they are actually somewhere in the region of 28 to 30 minutes
where the slack time was filled in broadcasts by advertising or filler
segments. Occasionally (for special episodes, such as finalés) episodes may be
a few minutes *longer* than the expected runtime. Thus, when setting the
duration, you usually want to err a couple of minutes either side of the
expected runtime.

Example::

    (tvrip) set duration 28-32

See also :doc:`cmd_automap`
