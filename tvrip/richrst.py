import re
import math

from docutils import core, nodes, io
from docutils.writers import Writer
from docutils.parsers.rst import roles
from rich.console import Console, NewLine
from rich.containers import Renderables
from rich.style import Style
from rich.text import Text
from rich.panel import Panel
from rich.padding import Padding
from rich.table import Table
from rich.theme import Theme
from rich.default_styles import DEFAULT_STYLES


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
    node = nodes.Text(title, rawsource=rawtext)
    return [node], []
roles.register_local_role('doc', doc_ref_role)


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

    :param str bullet_format:
        The format-string used to produce bullet-point or ordinal prefixes
        of list items (a blank string if the context is not within a list)

    :param int index:
        The ordinal number of the current list item (or 0 if the context does
        not apply to list items)

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

    .. attribute:: bullet_format

        A format :class:`str` that will be used to generate the prefix for
        all list items under this context.

    .. attribute:: index

        An :class:`int` indicating the ordinal position of the current list
        item (or 0 if the context is not under a list).

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
    def __init__(self, console, options, *, style=None, bullet_format='',
                 index=0, literal=False, heading_level=1, first_indent='',
                 subsequent_indent=''):
        self.console = console
        self.output = []
        self.options = options
        if style is None:
            style = Style.null()
        self.style = style
        self.bullet_format = bullet_format
        self.index = index
        self.literal = literal
        self.heading_level = heading_level
        self.first_indent = first_indent
        self.subsequent_indent = subsequent_indent

    def __repr__(self):
        return (
            f'Context({self.output!r}, bullet_format={self.bullet_format!r}, '
            f'index={self.index!r}, literal={self.literal!r}, '
            f'heading_level={self.heading_level!r}, '
            f'first_indent={self.first_indent!r}, '
            f'subsequent_indent={self.subsequent_indent!r})'
        )

    def new(self, *, style=None, bullet_format=None, index=None, literal=None,
            heading_level=None, indent=None, first_indent=None,
            subsequent_indent=None):
        """
        Return a new instance of :class:`RichContext` with the specified
        attributes overridden.

        If *style* is not :data:`None`, it will be combined with the current
        style in the new instance. All other attributes override their
        corresponding value in the new instance.

        One convenience parameter, *indent*, sets both *first_indent* and
        *subsequent_indent* if they are otherwise unspecified.
        """
        indent_width = max(
            (len(s) for s in (indent, first_indent, subsequent_indent)
            if s is not None), default=0)
        if isinstance(style, str):
            style = self.console.get_style(style)
        return Context(
            self.console,
            self.options.update(width=self.options.max_width - indent_width),
            style=self.style if style is None else self.style + style,
            bullet_format=
                self.bullet_format if bullet_format is None else bullet_format,
            index=self.index if index is None else index,
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
            Renderables(self.output), self.options, style=self.style, pad=True,
            new_lines=True,
        )):
            yield Text(self.first_indent if index == 0 else
                       self.subsequent_indent, style=self.style, end='')
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
    def __init__(self, document, console, options):
        super().__init__(document)
        self.console = console
        self.stack = Stack()
        self.stack.push(RichContext(console, options))

    @property
    def context(self):
        return self.stack.top

    def append(self, obj):
        if isinstance(obj, str):
            obj = Text(obj, style=self.context.style, end='')
        if (
            isinstance(obj, Text) and self.context.output and
            isinstance(self.context.output[-1], Text)
        ):
            self.context.output[-1].append(obj)
        else:
            self.context.output.append(obj)

    #def dispatch_visit(self, node):
    #    return super().dispatch_visit(node)

    def visit_document(self, node):
        pass

    def depart_document(self, node):
        pass

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
        self.append(NewLine(2))

    def visit_section(self, node):
        self.stack.push(self.context.new(
            heading_level=self.context.heading_level + 1))

    def visit_paragraph(self, node):
        self.stack.push(self.context.new(style='rest.paragraph'))

    def depart_paragraph(self, node):
        self.pop_context(node)
        self.append(NewLine(2))

    def visit_emphasis(self, node):
        self.stack.push(self.context.new(style='rest.emph'))

    def visit_strong(self, node):
        self.stack.push(self.context.new(style='rest.strong'))

    def visit_literal(self, node):
        self.stack.push(self.context.new(style='rest.code', literal=True))

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
        self.stack.push(self.context.new(index=1, bullet_format='* '))

    def visit_enumerated_list(self, node):
        # TODO Handle enumtype other than "arabic"
        num_width = int(math.log10(len(node.children))) + 1
        self.stack.push(self.context.new(
            index=node.attributes.get('start', 1),
            bullet_format=f'{{:{num_width}d}}. '))

    def visit_list_item(self, node):
        bullet = self.context.bullet_format.format(self.context.index)
        self.stack.push(self.context.new(
            first_indent=bullet, subsequent_indent=' ' * len(bullet)))

    def depart_list_item(self, node):
        self.pop_context(node)
        self.context.index += 1

    def visit_Text(self, node):
        text = node.astext()
        if not self.context.literal:
            text = re.sub(r'\s+', ' ', text)
        self.append(text)

    def depart_Text(self, node):
        pass

    def pop_context(self, node):
        sub_context = self.stack.pop()
        self.context.append(sub_context)

    depart_section = pop_context
    depart_literal = pop_context
    depart_strong = pop_context
    depart_emphasis = pop_context
    depart_enumerated_list = pop_context
    depart_bullet_list = pop_context

    def skip_node(self, node):
        raise nodes.SkipChildren()

    visit_comment = skip_node
    depart_comment = skip_node
    visit_system_message = skip_node
    depart_system_message = skip_node


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
        print(self.document.pformat())

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
            pad=True, new_lines=True
        ):
            yield from line
