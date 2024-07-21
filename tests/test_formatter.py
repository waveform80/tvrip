# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2022-2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from unittest import mock
from collections import OrderedDict

import pytest

from tvrip.formatter import *


@pytest.fixture()
def table_data(request):
    return [
        ['Key', 'Value'],
        ['FOO', 'bar'],
        ['BAZ', 'A much longer value which can wrap over several lines'],
        ['QUUX', 'Just for completeness'],
    ]


@pytest.fixture()
def dict_data(request):
    return OrderedDict([
        ['FOO', 'bar'],
        ['BAZ', 'A much longer value which can wrap over several lines'],
        ['QUUX', 'Just for completeness'],
    ])


def test_table_wrap_basic(table_data):
    expected = [
        "Key  Value                                                ",
        "---- -----------------------------------------------------",
        "FOO  bar                                                  ",
        "BAZ  A much longer value which can wrap over several lines",
        "QUUX Just for completeness                                ",
    ]
    wrap = TableWrapper()
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_no_header(table_data):
    expected = [
        "Key  Value                                                ",
        "FOO  bar                                                  ",
        "BAZ  A much longer value which can wrap over several lines",
        "QUUX Just for completeness                                ",
    ]
    wrap = TableWrapper(header_rows=0)
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_thin(table_data):
    wrap = TableWrapper(width=40)
    expected = [
        "Key  Value                              ",
        "---- -----------------------------------",
        "FOO  bar                                ",
        "BAZ  A much longer value which can wrap ",
        "     over several lines                 ",
        "QUUX Just for completeness              ",
    ]
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_equal():
    wrap = TableWrapper(width=40)
    table_data = [
        ("aaaaa" + " aaaaa" * 4,) * 3
    ] * 4
    expected = [
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa        aaaaa         aaaaa        ',
        '------------ ------------- -------------',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa        aaaaa         aaaaa        ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa        aaaaa         aaaaa        ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa aaaaa  aaaaa aaaaa   aaaaa aaaaa  ',
        'aaaaa        aaaaa         aaaaa        ',
    ]
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_pretty_thin(table_data):
    wrap = TableWrapper(width=40, **pretty_table)
    expected = [
        "+------+-------------------------------+",
        "| Key  | Value                         |",
        "|------+-------------------------------|",
        "| FOO  | bar                           |",
        "| BAZ  | A much longer value which can |",
        "|      | wrap over several lines       |",
        "| QUUX | Just for completeness         |",
        "+------+-------------------------------+",
    ]
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_footer(table_data):
    wrap = TableWrapper(width=40, footer_rows=1, **pretty_table)
    expected = [
        "+------+-------------------------------+",
        "| Key  | Value                         |",
        "|------+-------------------------------|",
        "| FOO  | bar                           |",
        "| BAZ  | A much longer value which can |",
        "|      | wrap over several lines       |",
        "|------+-------------------------------|",
        "| QUUX | Just for completeness         |",
        "+------+-------------------------------+",
    ]
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_complex():
    table_data = [
        ['Model', 'RAM', 'Ethernet', 'Wifi', 'Bluetooth', 'Notes'],
        ['Raspberry Pi 0', '512Mb', 'No', 'No', 'No',
         'Lowest power draw, smallest form factor'],
        ['Raspberry Pi 0W', '512Mb', 'No', 'Yes', 'Yes',
         'Popular in drones'],
        ['Raspberry Pi 3B+', '1Gb', 'Yes', 'Yes (+5GHz)', 'Yes',
         'The most common Pi currently'],
        ['Raspberry Pi 3A+', '512Mb', 'No', 'Yes (+5GHz)', 'Yes',
         'Small form factor, low power variant of the 3B+'],
    ]
    expected = [
        "+---------------+-------+----------+-------------+-----------+----------------+",
        "| Model         | RAM   | Ethernet | Wifi        | Bluetooth | Notes          |",
        "|---------------+-------+----------+-------------+-----------+----------------|",
        "| Raspberry Pi  | 512Mb | No       | No          | No        | Lowest power   |",
        "| 0             |       |          |             |           | draw, smallest |",
        "|               |       |          |             |           | form factor    |",
        "| Raspberry Pi  | 512Mb | No       | Yes         | Yes       | Popular in     |",
        "| 0W            |       |          |             |           | drones         |",
        "| Raspberry Pi  | 1Gb   | Yes      | Yes (+5GHz) | Yes       | The most       |",
        "| 3B+           |       |          |             |           | common Pi      |",
        "|               |       |          |             |           | currently      |",
        "| Raspberry Pi  | 512Mb | No       | Yes (+5GHz) | Yes       | Small form     |",
        "| 3A+           |       |          |             |           | factor, low    |",
        "|               |       |          |             |           | power variant  |",
        "|               |       |          |             |           | of the 3B+     |",
        "+---------------+-------+----------+-------------+-----------+----------------+",
    ]
    wrap = TableWrapper(width=79, **pretty_table)
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)
    expected = [
        "+-----------+-------+----------+-----------+-----------+------------+",
        "| Model     | RAM   | Ethernet | Wifi      | Bluetooth | Notes      |",
        "|-----------+-------+----------+-----------+-----------+------------|",
        "| Raspberry | 512Mb | No       | No        | No        | Lowest     |",
        "| Pi 0      |       |          |           |           | power      |",
        "|           |       |          |           |           | draw,      |",
        "|           |       |          |           |           | smallest   |",
        "|           |       |          |           |           | form       |",
        "|           |       |          |           |           | factor     |",
        "| Raspberry | 512Mb | No       | Yes       | Yes       | Popular in |",
        "| Pi 0W     |       |          |           |           | drones     |",
        "| Raspberry | 1Gb   | Yes      | Yes       | Yes       | The most   |",
        "| Pi 3B+    |       |          | (+5GHz)   |           | common Pi  |",
        "|           |       |          |           |           | currently  |",
        "| Raspberry | 512Mb | No       | Yes       | Yes       | Small form |",
        "| Pi 3A+    |       |          | (+5GHz)   |           | factor,    |",
        "|           |       |          |           |           | low power  |",
        "|           |       |          |           |           | variant of |",
        "|           |       |          |           |           | the 3B+    |",
        "+-----------+-------+----------+-----------+-----------+------------+",
    ]
    wrap = TableWrapper(width=69, **pretty_table)
    assert wrap.wrap(table_data) == expected
    assert wrap.fill(table_data) == '\n'.join(expected)


def test_table_wrap_too_thin(table_data):
    expected = [
        "Key  Value                                                ",
        "---- -----------------------------------------------------",
        "FOO  bar                                                  ",
        "BAZ  A much longer value which can wrap over several lines",
        "QUUX Just for completeness                                ",
    ]
    wrap = TableWrapper(width=5, **pretty_table)
    with pytest.raises(ValueError):
        wrap.wrap(table_data)


def test_table_wrap_bad_init():
    with pytest.raises(ValueError):
        TableWrapper(borders='|')
    with pytest.raises(ValueError):
        TableWrapper(corners=',-')
    with pytest.raises(ValueError):
        TableWrapper(internal_borders='foo')


def test_table_wrap_align():
    data = [
        ('Key', 'Value'),
        ('foo', 1),
        ('bar', 2),
    ]
    expected = [
        "Key Value",
        "--- -----",
        "foo     1",
        "bar     2",
    ]
    wrap = TableWrapper(
        width=40,
        align=lambda y, x, data: '>' if isinstance(data, int) else '<')
    assert wrap.wrap(data) == expected
    assert wrap.fill(data) == '\n'.join(expected)


def test_table_wrap_format():
    data = [
        ('Key', 'Value'),
        ('foo', 1),
        ('bar', 2),
    ]
    expected = [
        "Key Value",
        "--- -----",
        "foo 001  ",
        "bar 002  ",
    ]
    wrap = TableWrapper(
        width=40,
        format=lambda y, x, data: '{:03d}'.format(data)
                                  if isinstance(data, int) else str(data))
    assert wrap.wrap(data) == expected
    assert wrap.fill(data) == '\n'.join(expected)
