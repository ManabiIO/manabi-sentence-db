"""Bounded HTML character-data trees; this module never fetches linked resources."""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from .serialization import DataError

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
        'param', 'source', 'track', 'wbr'}


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    duplicate_attrs: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self):
        return ''.join(child if isinstance(child, str) else
                       '\n' if child.tag == 'br' else child.text() for child in self.children)

    def as_dict(self):
        value = {'tag': self.tag, 'attrs': self.attrs,
                 'children': [c if isinstance(c, str) else c.as_dict() for c in self.children]}
        if self.duplicate_attrs:
            value['duplicate_attrs'] = self.duplicate_attrs
        return value


class Tree(HTMLParser):
    def __init__(self, data):
        super().__init__(convert_charrefs=True)
        self.root = Element('root')
        self.stack = [self.root]
        self.nodes = 0
        try:
            self.feed(data.decode('utf-8'))
            self.close()
        except UnicodeError as error:
            raise DataError('Invalid UTF-8 HTML') from error

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs))
        # Preserve invalid repeated attributes in pins, including WordPress media
        # and unrelated newsletter forms; do not silently discard their drift.
        if len(attrs) != len(dict(attrs)):
            node.duplicate_attrs = attrs
        self.nodes += 1
        if self.nodes > 100_000 or len(self.stack) > 100:
            raise DataError('HTML tree exceeds size/depth bound')
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def by_class(self, name):
        return [n for n in self.root.walk() if name in (n.attrs.get('class') or '').split()]
