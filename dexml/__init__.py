"""

  dexml:  xml processing for people who hate processing xml

"""

from xml.dom import minidom
from dexml import fields

class Error(Exception):
    pass

class ParseError(Error):
    pass

class RenderError(Error):
    pass

class XmlError(Error):
    pass


class PARSE_DONE:
    pass
class PARSE_MORE:
    pass
class PARSE_SKIP:
    pass


class Meta:
    """Class holding meta-information about a class."""

    def __init__(self,name,meta):
        self.namespace = getattr(meta,"namespace",None)
        self.namespace_prefix = getattr(meta,"namespace_prefix",None)
        self.tagname = getattr(meta,"tagname",name)


class BaseMetaclass(type):
    """Metaclass for dexml.Base and subclasses."""

    instances = {}

    def __new__(mcls,name,bases,attrs):
        super_new = super(BaseMetaclass,mcls).__new__
        cls = super_new(mcls,name,bases,attrs)
        #  Don't do anything if it's not a subclass of Base
        parents = [b for b in bases if isinstance(b, BaseMetaclass)]
        if not parents:
            return cls
        #  Set up the _meta object, inheriting from base classes
        cls._meta = Meta(name,attrs.get("meta"))
        for base in bases:
            if not isinstance(b,BaseMetaclass):
                continue
            if not hasattr(b,"_meta"):
                continue
            for attr in dir(base._meta):
                if attr.startswith("__"):
                    continue
                if getattr(cls._meta,attr) is None:
                    val = getattr(base._meta,attr)
                    if val is not None:
                        setattr(cls._meta,attr,val)
        #  Create ordered list of field objects, telling each about their
        #  name and containing class.
        cls._fields = []
        for (name,value) in attrs.iteritems():
            if isinstance(value,fields.Field):
                value.field_name = name
                value.field_class = cls
                cls._fields.append(value)
        cls._fields.sort(key=lambda f: f._order_counter)
        #  Register the new class so we can find it by name later on
        mcls.instances[(cls._meta.namespace,cls._meta.tagname)] = cls
        return cls

    @classmethod
    def find_class(mcls,tagname,namespace=None):
        return mcls.instances.get((namespace,tagname))


class Base(object):
    """Base class for dexml objects."""

    __metaclass__ = BaseMetaclass

    ignore_unknown_elements = True

    def __init__(self,**kwds):
        for f in self._fields:
            val = kwds.get(f.field_name)
            setattr(self,f.field_name,val)

    @classmethod
    def parse(cls,xml):
        """Produce an instance of this object from some xml.

        The passed-in xml can be a string, a readable file-like object, or
        a DOM node; we might add support for more types in the future.
        """
        self = cls()
        node = self._make_xml_node(xml)
        self.validate_xml_node(node)
        #  Keep track of fields that have successfully parsed something
        fields_found = []
        #  Try to consume all the node attributes
        attrs = node.attributes.values()
        for field in self._fields:
            unused_attrs = field.parse_attributes(self,attrs)
            if len(unused_attrs) < len(attrs):
                fields_found.append(field)
            attrs = unused_attrs
        if attrs and not self.ignore_unknown_elements:
            for attr in attrs:
                if not attr.nodeName.startswith("xml"):
                    err = "unknown attribute: %s" % (attr.name,)
                    raise ParseError(err)
        #  Try to consume all child nodes
        cur_field_idx = 0 
        for child in node.childNodes:
            idx = cur_field_idx
            while idx < len(self._fields):
                field = self._fields[idx]
                res = field.parse_child_node(self,child)
                if res is PARSE_DONE:
                    if field not in fields_found:
                        fields_found.append(field)
                    cur_field_idx = idx + 1
                    break
                elif res is PARSE_MORE:
                    if field not in fields_found:
                        fields_found.append(field)
                    cur_field_idx = idx
                    break
                else:
                    idx += 1
            else:
                if not self.ignore_unknown_elements:
                    if child.nodeType == child.ELEMENT_NODE:
                        err = "unknown element: %s" % (child.nodeName,)
                        raise ParseError(err)
                    elif child.nodeType == child.TEXT_NODE:
                        if child.nodeValue.strip():
                            err = "unparsed text node: %s" % (child.nodeValue,)
                            raise ParseError(err)
        #  Check that all required fields have been found
        for field in self._fields:
            if field.required and field not in fields_found:
                err = "required field not found: '%s'" % (field.field_name,)
                raise ParseError(err)
            field.parse_done(self)
        #  All done, return the instance so created
        return self

    def render(self,encoding=None,fragment=False,nsmap=None):
        """Produce xml from this object's instance data.

        A unicode string will be returned if any of the objects contain
        unicode values; specifying the 'encoding' argument forces generation
        of an ASCII string.

        By default a complete XML document is produced, including the
        leading "<?xml>" declaration.  To generate an XML fragment set
        the 'fragment' argument to True.

        TODO: explain the 'nsmap' argument
        """
        if nsmap is None:
            nsmap = {}
        data = []
        if not fragment:
            if encoding:
                s = '<?xml version="1.0" encoding="%s" ?>' % (encoding,)
                data.append(s)
            else:
                data.append('<?xml version="1.0" ?>')
        data.extend(self._render(nsmap))
        xml = "".join(data)
        if encoding:
            xml = xml.encode(encoding)
        return xml

    def _render(self,nsmap):
        #  Determine opening and closing tags
        pushed_ns = False
        if self._meta.namespace:
            namespace = self._meta.namespace
            prefix = self._meta.namespace_prefix
            try:
                cur_ns = nsmap[prefix]
            except KeyError:
                cur_ns = []
                nsmap[prefix] = cur_ns
            if prefix:
                tagname = "%s:%s" % (prefix,self._meta.tagname)
                open_tag_contents = [tagname]
                if not cur_ns or cur_ns[0] != namespace:
                    cur_ns.insert(0,namespace)
                    pushed_ns = True
                    open_tag_contents.append('xmlns:%s="%s"'%(prefix,namespace))
                close_tag_contents = tagname
            else:
                open_tag_contents = [self._meta.tagname]
                if not cur_ns or cur_ns[0] != namespace:
                    cur_ns.insert(0,namespace)
                    pushed_ns = True
                    open_tag_contents.append('xmlns="%s"'%(namespace,))
                close_tag_contents = self._meta.tagname
        else:
            open_tag_contents = [self._meta.tagname] 
            close_tag_contents = self._meta.tagname
        # Find the attributes and child nodes
        attrs = []
        children = []
        num = 0
        for f in self._fields:
            val = getattr(self,f.field_name)
            attrs.extend(f.render_attributes(self,val))
            children.extend(f.render_children(self,val,nsmap))
            if len(attrs) + len(children) == num and f.required:
                raise RenderError("Field '%s' is missing" % (f.field_name,))
        #  Actually construct the XML
        if pushed_ns:
            nsmap[prefix].pop(0)
        open_tag_contents.extend(attrs)
        if children:
            yield "<%s>" % (" ".join(open_tag_contents),)
            for chld in children:
                yield chld
            yield "</%s>" % (close_tag_contents,)
        else:
            yield "<%s />" % (" ".join(open_tag_contents),)

    @staticmethod
    def _make_xml_node(xml):
        """Transform a variety of input formats to an XML DOM node."""
        try:
            ntype = xml.nodeType
        except AttributeError:
            if isinstance(xml,basestring):
                try:
                    xml = minidom.parseString(xml)
                except Exception, e:
                    raise XmlError(e)
            elif hasattr(xml,"read"):
                try:
                    xml = minidom.parse(xml)
                except Exception, e:
                    raise XmlError(e)
            else:
                raise ValueError("Can't convert that to an XML DOM node")
            node = xml.documentElement
        else:
            if ntype == xml.DOCUMENT_NODE:
                node = xml.documentElement
            else:
                node = xml
        return node

    @classmethod
    def validate_xml_node(cls,node):
        """Check that the given xml node is valid for this object.

        Here 'valid' means that it is the right tag, in the right
        namespace.  We might add more eventually...
        """
        if node.nodeType != node.ELEMENT_NODE:
            err = "Class '%s' got a non-element node"
            err = err % (cls.__name__,)
            raise ParseError(err)
        if node.localName != cls._meta.tagname:
            err = "Class '%s' got tag '%s' (expected '%s')"
            err = err % (cls.__name__,node.localName,
                         cls._meta.tagname)
            raise ParseError(err)
        if cls._meta.namespace:
            if node.namespaceURI != cls._meta.namespace:
                err = "Class '%s' got namespace '%s' (expected '%s')"
                err = err % (cls.__name__,node.namespaceURI,
                             cls._meta.namespace)
                raise ParseError(err)
        else:
            if node.namespaceURI:
                err = "Class '%s' got namespace '%s' (expected no namespace)"
                err = err % (cls.__name__,node.namespaceURI,)
                raise ParseError(err)


def FilterNodes(nodes):
    for node in nodes:
        if node.nodeType == node.ELEMENT_NODE:
            yield node
        elif node.nodeType == node.TEXT_NODE:
            if node.nodeValue.strip():
                yield node
 
