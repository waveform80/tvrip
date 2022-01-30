# vim: set et sw=4 sts=4:

# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
#
# This file is part of tvrip.
#
# tvrip is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# tvrip.  If not, see <http://www.gnu.org/licenses/>.

from bisect import bisect
from textwrap import dedent, TextWrapper
from itertools import islice, zip_longest, chain, tee


class TableWrapper:
    """
    Similar to :class:`~textwrap.TextWrapper`, this class provides facilities
    for wrapping text to a particular width, but with a focus on table-based
    output.

    The constructor takes numerous arguments, but typically you don't need to
    specify them all (or at all). A series of dictionaries are provided with
    "common" configurations: :data:`pretty_table`, :data:`curvy_table`,
    :data:`unicode_table`, and :data:`curvy_unicode_table`. For example::

        >>> from formatter import *
        >>> wrapper = TableWrapper(width=80, **curvy_table)
        >>> data = [
        ... ('Name', 'Length', 'Position'),
        ... ('foo', 3, 1),
        ... ('bar', 3, 2),
        ... ('baz', 3, 3),
        ... ('quux', 4, 4)]
        >>> print(wrapper.fill(data))
        ,------+--------+----------.
        | Name | Length | Position |
        |------+--------+----------|
        | foo  | 3      | 1        |
        | bar  | 3      | 2        |
        | baz  | 3      | 3        |
        | quux | 4      | 4        |
        `------+--------+----------'

    The :class:`TableWrapper` instance attributes (and keyword arguments to
    the constructor) are as follows:

    .. attribute:: width

        (default 70) The maximum number of characters that the table can take
        up horizontally. :class:`TableWrapper` guarantees that no output line
        will be longer than :attr:`width` characters.

    .. attribute:: header_rows

        (default 1) The number of rows at the top of the table that will be
        separated from the following rows by a horizontal border
        (:attr:`internal_line`).

    .. attribute:: footer_rows

        (default 0) The number of rows at the bottom of the table that will be
        separated from the preceding rows by a horizontal border
        (:attr:`internal_line`).

    .. attribute:: cell_separator

        (default ``' '``) The string used to separate columns of cells.

    .. attribute:: internal_line

        (default ``'-'``) The string used to draw horizontal lines inside the
        table for :attr:`header_rows` and :attr:`footer_rows`.

    .. attribute:: internal_separator

        (default ``' '``) The string used within runs of :attr:`internal_line`
        to separate columns.

    .. attribute:: borders

        (default ``('', '', '', '')``) A 4-tuple of strings which specify the
        characters used to create the left, top, right, and bottom borders of
        the table respectively.

    .. attribute:: corners

        (default ``('', '', '', '')``) A 4-tuple of strings which specify the
        characters used for the top-left, top-right, bottom-right, and
        bottom-left corners of the table respectively.

    .. attribute:: internal_borders

        (default ``('', '', '', '')``) A 4-tuple of strings which specify the
        characters used to interrupt runs of the :attr:`borders` characters
        to draw row and column separators. Like :attr:`borders` these are the
        left, top, right, and bottom characters respectively.

    .. attribute:: align

        A callable accepting three parameters: 0-based row index, 0-based
        column index, and the cell data. The callable must return a character
        indicating the intended alignment of data within the cell. "<" for
        left justification, "^" for centered alignment, and ">" for right
        justification (as in :meth:`str.format`). The default is to left align
        everything.

    .. attribute:: format

        A callable accepting three parameters: 0-based row index, 0-based
        column index, and the cell data. The callable must return the desired
        string representation of the cell data. The default simply calls
        :class:`str` on everything.

    :class:`TableWrapper` also provides similar public methods to
    :class:`~textwrap.TextWrapper`:

    .. automethod:: wrap

    .. automethod:: fill
    """

    def __init__(self, width=70, header_rows=1, footer_rows=0,
                 cell_separator=' ', internal_line='-', internal_separator=' ',
                 borders=('', '', '', ''), corners=('', '', '', ''),
                 internal_borders=('', '', '', ''), align=None, format=None):
        if len(borders) != 4:
            raise ValueError('borders must be a 4-tuple of strings')
        if len(corners) != 4:
            raise ValueError('corners must be a 4-tuple of strings')
        if len(internal_borders) != 4:
            raise ValueError('internal_borders must be a 4-tuple of strings')
        self.width = width
        self.header_rows = header_rows
        self.footer_rows = footer_rows
        self.internal_line = internal_line
        self.cell_separator = cell_separator
        self.internal_separator = internal_separator
        self.internal_borders = internal_borders
        self.borders = tuple(borders)
        self.corners = tuple(corners)
        self.internal_borders = tuple(internal_borders)
        if align is None:
            align = lambda row, col, data: '<'
        self.align = align
        if format is None:
            format = lambda row, col, data: str(data)
        self.format = format

    def fit_widths(self, widths):
        """
        Internal method which, given the sequence of *widths* (the calculated
        maximum width of each column), reduces those widths until they fit in
        the specified :attr:`width` limit, taking into account the implied
        width of column separators, borders, etc.
        """
        min_width = sum((
            len(self.borders[0]),
            len(self.borders[2]),
            len(self.cell_separator) * (len(widths) - 1)
        ))
        # Minimum width of each column is 1
        if min_width + len(widths) > self.width:
            raise ValueError('width is too thin to accommodate the table')
        total_width = sum(widths) + min_width
        # Reduce column widths until they fit in the available space. First, we
        # sort by the current column widths then by index so the widest columns
        # form a left-to-right ordered suffix of the list
        widths = sorted((w, i) for i, w in enumerate(widths))
        while total_width > self.width:
            # Find the insertion point before the suffix
            suffix = bisect(widths, (widths[-1][0] - 1, -1))
            suffix_len = len(widths) - suffix
            # Calculate the amount of width we still need to shed
            reduce_by = total_width - self.width
            if suffix > 0:
                # Limit this by the amount that can be removed evenly from the
                # suffix columns before the suffix needs to expand to encompass
                # more columns (requiring another loop)
                reduce_by = min(
                    reduce_by,
                    (widths[suffix][0] - widths[suffix - 1][0]) * suffix_len
                )
            # Distribute the reduction evenly across the columns of the suffix
            widths[suffix:] = [
                (w - reduce_by // suffix_len, i)
                for w, i in widths[suffix:]
            ]
            # Subtract the remainder from the left-most columns of the suffix
            for i in range(suffix, suffix + reduce_by % suffix_len):
                widths[i] = (widths[i][0] - 1, widths[i][1])
            total_width -= reduce_by
        return [w for i, w in sorted((i, w) for w, i in widths)]

    def wrap_lines(self, data, widths):
        """
        Internal method responsible for wrapping the contents of each cell in
        each row in *data* to the specified column *widths*.
        """
        # Construct wrappers for each column width
        wrappers = [TextWrapper(width=width) for width in widths]
        for y, row in enumerate(data):
            aligns = [self.align(y, x, cell) for x, cell in enumerate(row)]
            # Construct a list of wrapped lines for each cell in the row; these
            # are not necessarily of equal length (hence zip_longest below)
            cols = [
                wrapper.wrap(self.format(y, x, cell))
                for x, (cell, wrapper) in enumerate(zip(row, wrappers))
            ]
            for line in zip_longest(*cols, fillvalue=''):
                yield (
                    self.borders[0] +
                    self.cell_separator.join(
                        '{cell:{align}{width}}'.format(
                            cell=cell, align=align, width=width)
                        for align, width, cell in zip(aligns, widths, line)) +
                    self.borders[2]
                )

    def generate_lines(self, data):
        """
        Internal method which, given a sequence of rows of tuples in *data*,
        uses :meth:`fit_widths` to calculate the maximum possible column
        widths, and :meth:`wrap_lines` to wrap the text in *data* to the
        calculated widths, yielding rows of strings to the caller.
        """
        widths = [
            max(1, max(len(
                self.format(y, x, item)) for x, item in enumerate(row)))
            for y, row in enumerate(zip(*data))  # transpose
        ]
        widths = self.fit_widths(widths)
        lines = iter(data)
        if self.borders[1]:
            yield (
                self.corners[0] +
                self.internal_borders[1].join(
                    self.borders[1] * width for width in widths) +
                self.corners[1]
            )
        if self.header_rows > 0:
            yield from self.wrap_lines(islice(lines, self.header_rows), widths)
            yield (
                self.internal_borders[0] +
                self.internal_separator.join(
                    self.internal_line * w for w in widths) +
                self.internal_borders[2]
            )
        yield from self.wrap_lines(
            islice(lines, len(data) - self.header_rows - self.footer_rows),
            widths)
        if self.footer_rows > 0:
            yield (
                self.internal_borders[0] +
                self.internal_separator.join(
                    self.internal_line * w for w in widths) +
                self.internal_borders[2]
            )
        yield from self.wrap_lines(lines, widths)
        if self.borders[3]:
            yield (
                self.corners[3] +
                self.internal_borders[3].join(
                    self.borders[3] * width for width in widths) +
                self.corners[2]
            )

    def wrap(self, data):
        """
        Wraps the table *data* returning a list of output lines without final
        newlines. *data* must be a sequence of row tuples, each of which is
        assumed to be the same length.

        If the current :attr:`width` does not permit at least a single
        character per column (after taking account of the width of borders,
        internal separators, etc.) then :exc:`ValueError` will be raised.
        """
        return list(self.generate_lines(data))

    def fill(self, data):
        """
        Wraps the table *data* returning a string containing the wrapped
        output.
        """
        return '\n'.join(self.wrap(data))


# Some prettier defaults for TableWrapper
pretty_table = {
    'cell_separator': ' | ',
    'internal_line': '-',
    'internal_separator': '-+-',
    'borders': ('| ', '-', ' |', '-'),
    'corners': ('+-', '-+', '-+', '+-'),
    'internal_borders': ('|-', '-+-', '-|', '-+-'),
}

curvy_table = pretty_table.copy()
curvy_table['corners'] = (',-', '-.', "-'", '`-')

unicode_table = {
    'cell_separator': ' │ ',
    'internal_line': '─',
    'internal_separator': '─┼─',
    'borders': ('│ ', '─', ' │', '─'),
    'corners': ('┌─', '─┐', '─┘', '└─'),
    'internal_borders': ('├─', '─┬─', '─┤', '─┴─'),
}

curvy_unicode_table = unicode_table.copy()
curvy_unicode_table['corners'] = ('╭─', '─╮', '─╯', '╰─')
