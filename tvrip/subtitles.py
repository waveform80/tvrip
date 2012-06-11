# vim: set et sw=4 sts=4:

# Copyright 2012 Dave Hughes.
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

import os
import re
from operator import attrgetter
from datetime import date, time, datetime, timedelta
from itertools import izip, islice
from tvrip.const import DATADIR

class Error(Exception):
    u"""Base class for errors in parsing or generating subtitles"""

class ParseError(Error):
    u"""Class for errors which occur while parsing a sub-rip subtitle file"""

class RuleError(Error):
    u"""Base class for errors in the subtitles correction engine"""

class RuleSyntaxError(RuleError):
    u"""Exception raised when a syntax error in a rule is found"""


class Subtitle(object):
    u"""Represents a single subtitle in a sub-rip file"""

    def __init__(self, start=None, finish=None, text=u''):
        super(Subtitle, self).__init__()
        self.start = start
        self.finish = finish
        self.text = text

    def __eq__(self, other):
        if isinstance(other, Subtitle):
            return (
                self.start == other.start and
                self.finish == other.finish and
                self.text == other.text
            )
        else:
            return super(Subtitle, self).__eq__(other)

    def __ne__(self, other):
        if isinstance(other, Subtitle):
            return not self.__eq__(other)
        else:
            return super(Subtitle, self).__ne__(other)

    def __repr__(self):
        return u"<Subtitle(time(%s), time(%s), '%s'>" % (
            self.start, self.finish, self.text.replace("'", "''"))


class Subtitles(list):
    u"""Represents a subtitles file in sub-rip syntax"""

    index_re = re.compile(ur'^\d+$')
    duration_re = re.compile(ur'^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$')
    def __init__(self, *args, **kwargs):
        super(Subtitles, self).__init__(*args)
        if 'parsefile' in kwargs:
            (INDEX, DURATION, TEXT) = range(3)
            item = None
            state = INDEX
            # Simple state machine to parse the file
            for (linenum, line) in enumerate(kwargs['parsefile']):
                line = line.rstrip()
                if state == INDEX:
                    if line:
                        match = self.index_re.match(line)
                        if not match:
                            raise ParseError(u'Expected subtitle index on line %d but found "%s"' % (linenum + 1, line))
                        if item:
                            self.append(item)
                        item = Subtitle(None, None, [])
                        state = DURATION
                elif state == DURATION:
                    match = self.duration_re.match(line)
                    if not match:
                        raise ParseError(u'Expected subtitle duration on line %d but found "%s"' % (linenum + 1, line))
                    hour, min, sec, msec = (int(match.group(i)) for i in range(1, 5))
                    msec *= 1000
                    item.start = time(hour, min, sec, msec)
                    hour, min, sec, msec = (int(match.group(i)) for i in range(5, 9))
                    msec *= 1000
                    item.finish = time(hour, min, sec, msec)
                    state = TEXT
                elif state == TEXT:
                    if line:
                        item.text.append(line)
                    else:
                        state = INDEX
                else:
                    raise ParseError(u'Reached invalid state %d on line %d' % (state, linenum + 1))
            # Deal with the last item
            if item and item.text:
                self.append(item)
            # Convert all text attributes from lists to strings
            for item in self:
                item.text = u'\n'.join(item.text)

    def normalize(self):
        # Ensure entries are in order, merge overlapping entries with
        # equivalent text, separate overlapping entries with differing text (by
        # truncating the duration of the initial item)
        source = sorted(self, key=attrgetter('start'))
        result = []
        joined = False
        for (item1, item2) in izip(source, islice(source, 1, None)):
            if joined:
                joined = False
                continue
            if item1.finish > item2.start:
                if item1.text == item2.text:
                    # Overlapping items have the same text; combine them
                    joined = True
                    result.append(Subtitle(item1.start, item2.finish, item1.text))
                else:
                    # Overlapping items have different text. Compute a new
                    # finish time which is .1 seconds before the start of the
                    # next item, or equal to the start of the first item
                    d1 = datetime.combine(date.today(), item1.start)
                    d2 = datetime.combine(date.today(), item2.start)
                    newfinish = min(d2 - timedelta(microseconds=100000), d1)
                    result.append(Subtitle(item1.start, newfinish.time(), item1.text))
            else:
                result.append(item1)
        if not joined:
            result.append(item2)
        self[:] = result

    def __str__(self):
        return u'\n'.join(
u"""\
%d
%s,%03d --> %s,%03d
%s
""" %
            (
                index + 1,
                item.start.strftime(u'%H:%M:%S'), item.start.microsecond / 1000,
                item.finish.strftime(u'%H:%M:%S'), item.finish.microsecond / 1000,
                item.text
            ) for (index, item) in enumerate(self)
        )


class SubtitleCorrections(object):
    u"""Crude regex based engine for correcting subtitles"""

    def load_rules(self, language):
        rulesfile = os.path.join(DATADIR, u'tvrip.rules.%s' % language)
        if os.path.exists(rulesfile):
            self.rules =  [
                (line.strip(), num, self.parse_rule(num, line.strip()))
                for (num, line) in enumerate(open(rulesfile, u'rU').read().decode(u'UTF-8').splitlines())
                if line.strip() and not line.lstrip().startswith(u'#')
            ]
        else:
            self.rules = []

    def process(self, subtitles):
        skip = 0
        for (source, index, rule) in self.rules:
            if skip > 0:
                skip -= 1
                continue
            (subtitles, skip) = rule(subtitles)
            if skip < 0:
                raise RuleError(u'Rule %s on line %d returned a negative skip value (%d)' % (source, index, skip))
                skip = 0
        return subtitles

    def extract_parts(self, num, line, min_count=2, max_count=None):
        if max_count is None:
            max_count = min_count
        separator = line[1:2]
        if not separator:
            raise RuleSyntaxError(u'Incomplete rule "%s" on line %d' % (line, num))
        result = []
        escaped = False
        s = u''
        for c in line[2:]:
            if c == separator and not escaped:
                result.append(s)
                s = u''
            elif escaped:
                s += c
                escaped = False
            else:
                s += c
                escaped = c == u'\\'
        if len(result) < min_count:
            if min_count == max_count:
                raise RuleSyntaxError(u'Rule "%s" on line %d needs %d arguments but has %d' % (line, num, min_count, len(result)))
            else:
                raise RuleSyntaxError(u'Rule "%s" on line %d needs at least %d arguments but has %d' % (line, num, min_count, len(result)))
        elif len(result) > max_count:
            raise RuleSyntaxError(u'Rule "%s" on line %d needs up to %d arguments but has %d' % (line, num, max_count, len(result)))
        while len(result) < max_count:
            result.append(None)
        return result

    def parse_rule(self, num, line):
        if line[0] == u's':
            # Substitution rule
            (pattern, replacement, skip) = self.extract_parts(num, line, 2, 3)
            if skip is None:
                skip = 0
            else:
                skip = int(skip)
                if skip < 0:
                    raise RuleSyntaxError(u'Negative skip value given in rule %s on line %d' % (line, num))
            pattern = re.compile(pattern, re.UNICODE)
            def substitute(subtitles):
                result = Subtitles(
                    Subtitle(s.start, s.finish, u'\n'.join(
                        pattern.sub(replacement, line)
                        for line in s.text.splitlines()
                    ))
                    for s in subtitles
                )
                if result != subtitles:
                    return (result, skip)
                else:
                    return (subtitles, 0)
            return substitute
        elif line[0] == u'j':
            # Jump rule
            (pattern, skip) = self.extract_parts(num, line, 2, 2)
            skip = int(skip)
            if skip < 0:
                raise RuleSyntaxError(u'Negative skip value given in rule %s on line %d' % (line, num))
            pattern = re.compile(pattern)
            def jump(subtitles):
                if any(pattern.search(s.text) for s in subtitles):
                    return (subtitles, skip)
                else:
                    return (subtitles, 0)
            return jump
        elif line[0] == u'c':
            # Concatenation rule
            patterns = self.extract_parts(num, line, 1, 2)
            if len(patterns) == 1:
                patterns = [patterns[0], u'.*']
            patterns = [re.compile(pattern) for pattern in patterns]
            def concat(subtitles):
                for s in subtitles:
                    lines = s.text.splitlines()
                    if len(lines) <= 1:
                        continue
                    result = []
                    joined = False
                    for (line1, line2) in izip(lines, islice(lines, 1, None)):
                        if joined:
                            joined = False
                            continue
                        elif all(pattern.search(line) for (pattern, line) in izip(patterns, (line1, line2))):
                            result.append(u' '.join((line1, line2)))
                            joined = True
                        else:
                            result.append(line1)
                    if not joined:
                        result.append(line2)
                    s.text = u'\n'.join(result)
                return (subtitles, 0)
            return concat
        else:
            raise RuleSyntaxError(u'Unknown rule type %s on line %d' % (line[:1], num))


