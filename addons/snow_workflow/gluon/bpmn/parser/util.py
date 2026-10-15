# Copyright 2023 The CrossNow.inc Authors.
#


BPMN_MODEL_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
DIAG_INTERCHANGE_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DIAG_COMMON_NS = "http://www.omg.org/spec/DD/20100524/DC"

DEFAULT_NSMAP = {
    'bpmn': BPMN_MODEL_NS,
    'dc': DIAG_COMMON_NS,
    'bpmndi': DIAG_INTERCHANGE_NS,
}

def one(nodes, or_none=False):
    """
    Assert that there is exactly one node in the give list, and return it.
    """
    if not nodes and or_none:
        return None
    assert len(
        nodes) == 1, 'Expected 1 result. Received %d results.' % (len(nodes))
    return nodes[0]


def first(nodes):
    """
    Return the first node in the given list, or None, if the list is empty.
    """
    if len(nodes) >= 1:
        return nodes[0]
    else:
        return None


def xpath_eval(node, extra_ns=None):
    """
    Returns an XPathEvaluator, with namespace prefixes 'bpmn' for
    http://www.omg.org/spec/BPMN/20100524/MODEL, and additional specified ones
    """
    namespaces = DEFAULT_NSMAP.copy()
    if extra_ns:
        namespaces.update(extra_ns)
    return lambda path: node.xpath(path, namespaces=namespaces)


def full_tag(tag):
    """
    Return the full tag name including namespace for the given BPMN tag. In
    other words, the name with namespace
    http://www.omg.org/spec/BPMN/20100524/MODEL
    """
    return '{%s}%s' % (BPMN_MODEL_NS, tag)
