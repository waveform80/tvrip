import re
import math

from docutils import core, nodes, io
from docutils.writers import Writer
from docutils.parsers.rst import roles
from rich import box
from rich.console import Console, NewLine
from rich.containers import Renderables
from rich.style import Style
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich.default_styles import DEFAULT_STYLES


class Stack(list):
    @property
    def top(self):
        return self[-1]

    def push(self, item):
        self.append(item)


class RichContext:
    """
    Instances represent the current context of the :class:`RichTranslator`
    class.

    The context includes the *console*, the current console *options*, and
    several optional keyword parameters. These all set their correspondingly
    named attributes on the context instance.

    :param rich.console.Console console:
        The console that will ultimately be used to print the :attr:`output`

    :param rich.console.ConsoleOptions options:
        The options dictating output width (amongst other things)

    :param rich.style.Style style:
        The style to apply to the :attr:`output` for this context

    :param str item_prefix:
        The format-string used to produce bullet-point or ordinal prefixes
        of list items (a blank string if the context is not within a list)

    :param int index:
        The ordinal number of the current list item (or 0 if the context does
        not apply to list items)

    :param rich.table.Table table:
        The table currently under construction (or :data:`None`)

    :param bool literal:
        If :data:`True`, the current context's output is literal and whitespace
        should not be collapsed

    :param int heading_level:
        The heading level under which the current context exists; incremented
        within the context of a new section

    :param str first_indent:
        The line prefix to apply to the first line of :attr:`output` for this
        context

    :param str subsequent_indent:
        The line prefix to apply to all but the first line of :attr:`output`
        for this context

    .. attribute:: console

        The :class:`rich.console.Console` instance that will ultimately be
        used for output.

    .. attribute:: output

        A :class:`list` containing all :mod:`rich` output objects generated
        for this context.

    .. attribute:: options

        A :class:`rich.console.ConsoleOptions` instance that dictates the
        minimum and maximum output widths (amongst other things).

    .. attribute:: style

        A :class:`rich.style.Style` instance to apply to all :attr:`output`
        for this context.

    .. attribute:: term_width

        An :class:`int` indicating the maximum width of the term in a
        definition list. Used when formatting definition lists in the
        "compact" style.

    .. attribute:: item_prefix

        A format :class:`str` that will be used to generate the prefix for
        all list items under this context.

    .. attribute:: index

        An :class:`int` indicating the ordinal position of the current list
        item (or 0 if the context is not under a list).

    .. attribute:: table

        The :class:`~rich.table.Table` currently being constructed, or
        :data:`None` if no table is under construction.

    .. attribute:: literal

        A :class:`bool` which, if :data:`True`, indicates that the
        :attr`output` of this context is literal and whitespace should not be
        collapsed.

    .. attribute:: heading_level

        An :class:`int` indicating the heading level under which the
        :attr:`output` of this context exists. Incremented under contexts
        associated with a new section.

    .. attribute:: first_indent

        A :class:`str` storing the prefix to be applied to the first line of
        :attr:`output` of this context.

    .. attribute:: subsequent_indent

        A :class:`str` storing the prefix to be applied to all but the first
        line of :attr:`output` of this context.
    """
    def __init__(self, console, options, *, style=None, term_width=0,
                 item_prefix='', index=0, table=None, literal=False,
                 heading_level=1, first_indent='', subsequent_indent=''):
        self.console = console
        self.options = options
        if style is None:
            style = Style.null()
        self.style = style
        # Always start output with a blank text string and the default style.
        # This works around an issue in rendering where the default style is
        # propagated when subsequent items are appended
        self.output = [Text('', style=style, end='')]
        self.term_width = term_width
        self.item_prefix = item_prefix
        self.index = index
        self.table = table
        self.literal = literal
        self.heading_level = heading_level
        self.first_indent = first_indent
        self.subsequent_indent = subsequent_indent

    def __repr__(self):
        return (
            f'RichContext({self.output!r}, term_width={self.term_width!r}, '
            f'item_prefix={self.item_prefix!r}, '
            f'index={self.index!r}, table={self.table!r}, '
            f'literal={self.literal!r}, heading_level={self.heading_level!r}, '
            f'first_indent={self.first_indent!r}, '
            f'subsequent_indent={self.subsequent_indent!r})'
        )

    def new(self, *, style=None, term_width=None, item_prefix=None, index=None,
            table=None, literal=None, heading_level=None, indent=None,
            first_indent=None, subsequent_indent=None, padding=None):
        """
        Return a new instance of :class:`RichContext` with the specified
        attributes overridden.

        If *style* is not :data:`None`, it will be combined with the current
        style in the new instance. All other attributes override their
        corresponding value in the new instance.

        If *padding* is not :data:`None`, it will reduce the maximum width of
        the associated console options by the specified amount.

        One convenience parameter, *indent*, sets both *first_indent* and
        *subsequent_indent* if they are otherwise unspecified.
        """
        indent_width = max(
            (len(s) for s in (indent, first_indent, subsequent_indent)
            if s is not None), default=0)
        padding = padding or 0
        if isinstance(style, str):
            style = self.console.get_style(style)
        return RichContext(
            self.console,
            self.options.update(
                width=self.options.max_width - indent_width - padding),
            style=self.style if style is None else self.style + style,
            term_width=
                self.term_width if term_width is None else term_width,
            item_prefix=
                self.item_prefix if item_prefix is None else item_prefix,
            index=self.index if index is None else index,
            table=self.table if table is None else table,
            literal=self.literal if literal is None else literal,
            heading_level=
                self.heading_level if heading_level is None else heading_level,
            first_indent=
                first_indent if first_indent is not None else
                indent if indent is not None else '',
            subsequent_indent=
                subsequent_indent if subsequent_indent is not None else
                indent if indent is not None else '',
        )

    def append(self, context):
        """
        Appends *context*, another instance of :class:`RichContext`, and
        typically a sub-context of this one, to the :attr:`output` of this
        context.

        This method takes care to combine :class:`~rich.text.Text` instances
        into a single instance to ensure that word-wrapping operates correctly
        during output.
        """
        if context.first_indent or context.subsequent_indent:
            for obj in context.render_lines():
                self.output.append(obj)
        else:
            for obj in context.output:
                if isinstance(obj, str):
                    obj = Text(obj, style=context.style, end='')
                if (
                    isinstance(obj, Text) and self.output and
                    isinstance(self.output[-1], Text)
                ):
                    self.output[-1].append(obj)
                else:
                    self.output.append(obj)

    def render_lines(self):
        """
        Renders the :attr:`output` stored in this context as a series of
        output lines, obeying the current console :attr:`options` and the
        indentation set in :attr:`first_indent` and :attr:`subsequent_indent`.
        """
        for index, line in enumerate(self.console.render_lines(
            Renderables(self.output), self.options, pad=False, new_lines=True,
        )):
            yield Text(self.first_indent if index == 0 else
                       self.subsequent_indent, end='')
            yield from line


class RichTranslator(nodes.NodeVisitor):
    """
    A docutils :class:`~docutils.nodes.NodeVisitor` which translates the
    given *document* for output on the specified *console*, with the given
    *options* (provided by rich's :ref:`console protocol`, specifically the
    ``__rich_console__`` method).

    Users should typically not need to use this class directly, though they
    may wish to sub-class it to customize its behaviour. Instead, use the
    :class:`RestructuredText` class, also in this module.
    """
    dl_compact_width = 8

    def __init__(self, document, console, options):
        super().__init__(document)
        self.console = console
        self.stack = Stack()
        self.stack.push(RichContext(console, options))

    @property
    def context(self):
        """
        Return the current :class:`RichContext` at the top of the
        :attr:`stack`.
        """
        return self.stack.top

    def append(self, obj):
        """
        Append *obj* (a :mod:`rich` renderable, or a :class:`str`) to the
        output of the current context at the top of the stack.
        """
        if isinstance(obj, str):
            obj = Text(obj, style=self.context.style, end='')
        if (
            isinstance(obj, Text) and self.context.output and
            isinstance(self.context.output[-1], Text)
        ):
            self.context.output[-1].append(obj)
        else:
            self.context.output.append(obj)

    def pop_context(self, node):
        """
        Pops the current top of the :attr:`stack` and appends all of its
        :attr:`~RichContext.output` to the new top of the stack. This is
        commonly called when departing a node that created a new context.
        """
        sub_context = self.stack.pop()
        self.context.append(sub_context)

    def do_nothing(self, node):
        """
        A no-op method that's typically aliased to various visit and depart
        methods that you wish to ignore (but not actively skip the children).
        """
        pass

    def skip_node(self, node):
        """
        A method which skips all child nodes. This is typically alised to visit
        methods that should be skipped entirely (e.g. comments).
        """
        raise nodes.SkipChildren()

    visit_document = do_nothing
    depart_document = do_nothing

    def visit_section(self, node):
        self.stack.push(self.context.new(
            heading_level=self.context.heading_level + 1))
    depart_section = pop_context

    def visit_title(self, node):
        self.stack.push(self.context.new(
            style=f'rest.h{self.context.heading_level}'))
    def depart_title(self, node):
        title_lens = [0]
        sub_context = self.stack.pop()
        for obj in sub_context.output:
            if isinstance(obj, NewLine):
                title_lens.append(0)
            title_lens[-1] += min(
                self.console.measure(obj).maximum, self.console.width)
            self.append(obj)
        self.append(NewLine())
        self.append(Text(
            '=~-'[self.context.heading_level - 1] * max(title_lens),
            style=sub_context.style))
        self.append(NewLine())

    def visit_paragraph(self, node):
        self.stack.push(self.context.new(style='rest.paragraph'))
    def depart_paragraph(self, node):
        self.pop_context(node)
        self.append(NewLine(2))

    def visit_emphasis(self, node):
        self.stack.push(self.context.new(style='rest.emph'))
    depart_emphasis = pop_context

    def visit_strong(self, node):
        self.stack.push(self.context.new(style='rest.strong'))
    depart_strong = pop_context

    def visit_literal(self, node):
        self.stack.push(self.context.new(style='rest.code', literal=True))
    depart_literal = pop_context

    def visit_literal_block(self, node):
        self.stack.push(self.context.new(
            style='rest.code_block', literal=True, indent='    '))
    def depart_literal_block(self, node):
        self.pop_context(node)
        self.append(NewLine(2))

    def visit_block_quote(self, node):
        self.styles.push(self.context.new(
            style='rest.block_quote', literal=True, indent='> '))
    def depart_block_quote(self, node):
        self.pop_context(node)
        self.append(NewLine(2))

    def visit_bullet_list(self, node):
        # TODO Handle "bullet" attribute for different styles, or use a fixed
        # list of styles for different levels?
        self.stack.push(self.context.new(index=1, item_prefix='• '))
    depart_bullet_list = pop_context

    def visit_enumerated_list(self, node):
        # TODO Handle enumtype other than "arabic"
        start = node.attributes.get('start', 1)
        num_width = int(math.log10(start + len(node.children) - 1)) + 1
        self.stack.push(self.context.new(
            index=start, item_prefix=f'{{:{num_width}d}}. '))
    depart_enumerated_list = pop_context

    def visit_list_item(self, node):
        prefix = self.context.item_prefix.format(self.context.index)
        self.stack.push(self.context.new(style='rest.item'))
        self.append(prefix)
        self.pop_context(node)
        self.stack.push(self.context.new(subsequent_indent=' ' * len(prefix)))
    def depart_list_item(self, node):
        self.pop_context(node)
        self.context.index += 1

    def visit_definition_list(self, node):
        term_width = max(
            len(term.astext())
            for term in node.traverse(condition=nodes.term))
        self.stack.push(self.context.new(index=1, term_width=term_width))
    depart_definition_list = pop_context

    visit_definition_list_item = do_nothing
    depart_definition_list_item = do_nothing

    def visit_term(self, node):
        self.stack.push(self.context.new())
    def depart_term(self, node):
        if self.context.term_width <= self.dl_compact_width:
            padding = self.context.term_width - len(node.astext()) + 2
            self.append(' ' * padding)
        else:
            self.append(NewLine())
        self.pop_context(node)

    def visit_definition(self, node):
        if self.context.term_width <= self.dl_compact_width:
            self.stack.push(self.context.new(
                subsequent_indent=' ' * (self.context.term_width + 2)))
        else:
            self.stack.push(self.context.new(indent='    '))
    depart_definition = pop_context

    def visit_table(self, node):
        self.stack.push(
            self.context.new(table=Table(box=box.ROUNDED, show_header=False)))
    def depart_table(self, node):
        sub_context = self.stack.pop()
        self.append(sub_context.table)
        self.append(NewLine())

    visit_tgroup = do_nothing
    depart_tgroup = do_nothing

    # TODO Do something with colspec's colwidth attribute?
    visit_colspec = do_nothing
    depart_colspec = do_nothing

    def _visit_tbody(self, node, style):
        self.stack.push(self.context.new(style=style))
    def _depart_tbody(self, node):
        # NOTE: We do not use pop_context here because depart_row has already
        # added our content to the current table, so we don't care about any
        # content in the sub-context
        self.stack.pop()

    def visit_thead(self, node):
        self._visit_tbody(node, style='rest.table.header')
    depart_thead = _depart_tbody

    def visit_tbody(self, node):
        self._visit_tbody(node, style='rest.table.cell')
    depart_tbody = _depart_tbody

    def visit_row(self, node):
        self.stack.push(self.context.new())
        # NOTE: Get rid of the null-styled hack in the output; we're only
        # interested in gathering the cell entries
        self.context.output = []
    def depart_row(self, node):
        sub_context = self.stack.pop()
        tbody = node.parent
        tgroup = tbody.parent
        table = tgroup.parent
        last_row_of_table = table.children[-1].children[-1].children[-1]
        last_row_of_body = tbody.children[-1]
        end_section = (
            isinstance(node.parent, nodes.thead) and
            (node is last_row_of_body) and
            (node is not last_row_of_table))
        self.context.table.add_row(*(
            cell[0] if len(cell) == 1 else Renderables(cell)
            for cell in sub_context.output
        ), end_section=end_section)

    def visit_entry(self, node):
        self.stack.push(self.context.new())
    def depart_entry(self, node):
        sub_context = self.stack.pop()
        while isinstance(sub_context.output[-1], NewLine):
            sub_context.output.pop()
        # NOTE: We temporarily leave each entry's output in its own list to
        # ensure adjacent cell's Text entries don't get amalgamated; depart_row
        # sorts converting these lists into valid rich renderables
        self.context.output.append(sub_context.output)

    def visit_reference(self, node):
        refuri = node.attributes.get('refuri')
        if refuri:
            self.append(Text.from_markup(
                f'[link={refuri}]{node.astext()}[/link]', style='rest.link'))
            raise nodes.SkipChildren()
    depart_reference = do_nothing

    visit_target = do_nothing
    depart_target = do_nothing

    def visit_Text(self, node):
        text = node.astext()
        if not self.context.literal:
            text = re.sub(r'\s+', ' ', text)
        self.append(text)
    depart_Text = do_nothing

    def visit_admonition(self, node):
        self.stack.push(self.context.new(padding=4))
    def depart_admonition(self, node, *, title='Admonition'):
        sub_context = self.stack.pop()
        while isinstance(sub_context.output[-1], NewLine):
            sub_context.output.pop()
        note = Panel(
            Renderables(sub_context.output),
            box=box.ROUNDED, title=title, title_align='left')
        self.append(note)
        self.append(NewLine())

    def _depart_admonition(title):
        return lambda self, node: self.depart_admonition(node, title=title)

    visit_attention = visit_admonition
    depart_attention = _depart_admonition('Attention')
    visit_caution = visit_admonition
    depart_caution = _depart_admonition('Caution')
    visit_danger = visit_admonition
    depart_danger = _depart_admonition('Danger')
    visit_error = visit_admonition
    depart_error = _depart_admonition('Error')
    visit_hint = visit_admonition
    depart_hint = _depart_admonition('Hint')
    visit_important = visit_admonition
    depart_important = _depart_admonition('Important')
    visit_note = visit_admonition
    depart_note = _depart_admonition('Note')
    visit_tip = visit_admonition
    depart_tip = _depart_admonition('Tip')
    visit_warning = visit_admonition
    depart_warning = _depart_admonition('Warning')
    visit_comment = skip_node
    depart_comment = do_nothing
    visit_system_message = skip_node
    depart_system_message = do_nothing

    del _depart_admonition

class RestructuredText:
    """
    A :mod:`rich` extension class which provides rendering of reStructuredText
    via a rich :class:`~rich.console.Console`.

    Use one of the class methods, :meth:`from_string`, :meth:`from_path`, or
    :meth:`from_file`, to construct an instance of the class. Then simply pass
    the instance to the console's :meth:`~rich.console.Console.print` method as
    usual.
    """
    def __init__(self, source, *, source_path, source_class,
                 reader=None, reader_name='standalone', parser=None,
                 parser_name='restructuredtext', settings=None,
                 settings_spec=None, settings_overrides=None):
        if settings_overrides is None:
            settings_overrides = {'input_encoding': 'unicode'}
        self.document = core.publish_doctree(
            source, source_path, source_class, reader, reader_name, parser,
            parser_name, settings, settings_spec, settings_overrides)
        #print(self.document.pformat())

    @classmethod
    def from_string(self, source):
        """
        Construct an instance from the specified *source* :class:`str` which
        must contain a valid reStructuredText document.

        :param str source:
            The reStructuredText source

        :rtype: RestructuredText
        """
        return RestructuredText(
            source, source_path=None, source_class=io.StringInput)

    @classmethod
    def from_path(self, source, encoding=None, errors=None):
        """
        Construct an instance from the specified *source*
        :class:`~pathlib.Path`, which must point to a file containing a valid
        reStructuredText document.

        The file will be opened in text-mode. If unspecified, the default
        *encoding* and *errors* used by :func:`open` will be used.

        :param pathlib.Path source:
            The reStructuredText source

        :rtype: RestructuredText
        """
        return RestructuredText(
            source.open('r'), source_path=str(source),
            source_class=io.FileInput)

    @classmethod
    def from_file(self, source, source_path=None):
        """
        Construct an instance from the specified *source* file-like object
        which must contain a valid reStructuredText document starting at the
        current file position.

        If *source_path* is specified, it will be used as the filename of
        the *source* for debugging purposes. If unspecified, the ``name``
        attribute of *source* will be queried for the filename instead.

        :param source:
            The file-like object containing the reStructuredText source

        :rtype: RestructuredText
        """
        return RestructuredText(
            source,
            source_path=source.name if source_path is None else source_path,
            source_class=io.FileInput)

    def __rich_console__(self, console, options):
        translator = RichTranslator(self.document, console, options)
        self.document.walkabout(translator)
        for line in console.render_lines(
            Renderables(translator.context.output), options,
            pad=False, new_lines=True
        ):
            yield from line


title_re = re.compile(r'^(.+?)\s*(?<!\x00)<(.*?)>$', re.DOTALL)
def doc_ref_role(
    role, rawtext, text, lineno, inliner, options=None, content=None
):
    matched = title_re.match(text)
    if matched:
        title = nodes.unescape(matched.group(1))
        target = nodes.unescape(matched.group(2))
    else:
        title = nodes.unescape(text)
        target = nodes.unescape(text)
    node = nodes.Text(title)
    return [node], []
roles.register_local_role('doc', doc_ref_role)


rest_theme = Theme(DEFAULT_STYLES.copy() | {
    'rest.emph': Style(italic=True),
    'rest.strong': Style(bold=True),
    'rest.paragraph': Style(),
    'rest.code': Style(bgcolor='black', color='yellow'),
    'rest.code_block': Style(bgcolor='black', color='yellow'),
    'rest.block_quote': Style(color='cyan'),
    'rest.h1': Style(bold=True),
    'rest.h2': Style(bold=True),
    'rest.h3': Style(bold=True),
    'rest.h4': Style(bold=True, dim=True),
    'rest.h5': Style(underline=True),
    'rest.h6': Style(italic=True),
    'rest.link': Style(color='bright_cyan'),
    'rest.item': Style(color='cyan'),
    'rest.item.bullet': Style(color='cyan'),
    'rest.item.number': Style(color='cyan'),
    'rest.table.header': Style(bold=True),
    'rest.table.cell': Style(),
})
