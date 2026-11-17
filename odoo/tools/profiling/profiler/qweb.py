"""The collectors of the QWeb templates, which track the rendering of the templates."""

import threading
from odoo import tools

from .collectors import Collector
from .stack import real_time

class QwebTracker:

    def __init__(self, view_id, arch, cr):
        current_thread = threading.current_thread()  # don't store current_thread on self
        self.execution_context_enabled = getattr(current_thread, 'profiler_params', {}).get('execution_context_qweb')
        self.qweb_hooks = getattr(current_thread, 'qweb_hooks', ())
        self.context_stack = []
        self.cr = cr
        self.view_id = view_id
        for hook in self.qweb_hooks:
            hook('render', self.cr.sql_log_count, view_id=view_id, arch=arch)

    def enter_directive(self, directive, attrib, xpath):
        execution_context = None
        if self.execution_context_enabled:
            directive_info = {}
            if ('t-' + directive) in attrib:
                directive_info['t-' + directive] = repr(attrib['t-' + directive])
            if directive == 'set':
                if 't-value' in attrib:
                    directive_info['t-value'] = repr(attrib['t-value'])
                if 't-valuef' in attrib:
                    directive_info['t-valuef'] = repr(attrib['t-valuef'])

                for key in attrib:
                    if key.startswith('t-set-') or key.startswith('t-setf-'):
                        directive_info[key] = repr(attrib[key])
            elif directive == 'foreach':
                directive_info['t-as'] = repr(attrib['t-as'])
            elif directive == 'groups' and 'groups' in attrib and not directive_info.get('t-groups'):
                directive_info['t-groups'] = repr(attrib['groups'])
            elif directive == 'att':
                for key in attrib:
                    if key.startswith('t-att-') or key.startswith('t-attf-'):
                        directive_info[key] = repr(attrib[key])
            elif directive == 'options':
                for key in attrib:
                    if key.startswith('t-options-'):
                        directive_info[key] = repr(attrib[key])
            elif ('t-' + directive) not in attrib:
                directive_info['t-' + directive] = None

            execution_context = tools.profiling.profiler.ExecutionContext(**directive_info, xpath=xpath)
            execution_context.__enter__()
            self.context_stack.append(execution_context)

        for hook in self.qweb_hooks:
            hook('enter', self.cr.sql_log_count, view_id=self.view_id, xpath=xpath, directive=directive, attrib=attrib)

    def leave_directive(self, directive, attrib, xpath):
        if self.execution_context_enabled:
            self.context_stack.pop().__exit__()

        for hook in self.qweb_hooks:
            hook('leave', self.cr.sql_log_count, view_id=self.view_id, xpath=xpath, directive=directive, attrib=attrib)


class QwebCollector(Collector):
    """
    Record qweb execution with directive trace.
    """
    name = 'qweb'

    def __init__(self):
        super().__init__()
        self.events = []

        def hook(event, sql_log_count, **kwargs):
            self.events.append((event, kwargs, sql_log_count, real_time()))
        self.hook = hook

    def _get_directive_profiling_name(self, directive, attrib):
        expr = ''
        if directive == 'set':
            if 't-set' in attrib:
                expr = f"t-set={repr(attrib['t-set'])}"
                if 't-value' in attrib:
                    expr += f" t-value={repr(attrib['t-value'])}"
                if 't-valuef' in attrib:
                    expr += f" t-valuef={repr(attrib['t-valuef'])}"
            for key in attrib:
                if key.startswith('t-set-') or key.startswith('t-setf-'):
                    if expr:
                        expr += ' '
                    expr += f"{key}={repr(attrib[key])}"
        elif directive == 'foreach':
            expr = f"t-foreach={repr(attrib['t-foreach'])} t-as={repr(attrib['t-as'])}"
        elif directive == 'options':
            if attrib.get('t-options'):
                expr = f"t-options={repr(attrib['t-options'])}"
            for key in attrib:
                if key.startswith('t-options-'):
                    expr = f"{expr}  {key}={repr(attrib[key])}"
        elif directive == 'att':
            for key in attrib:
                if key == 't-att' or key.startswith('t-att-') or key.startswith('t-attf-'):
                    if expr:
                        expr += ' '
                    expr += f"{key}={repr(attrib[key])}"
        elif ('t-' + directive) in attrib:
            expr = f"t-{directive}={repr(attrib['t-' + directive])}"
        else:
            expr = f"t-{directive}"

        return expr

    def start(self):
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, 'qweb_hooks'):
            init_thread.qweb_hooks = []
        init_thread.qweb_hooks.append(self.hook)

    def stop(self):
        self.profiler.init_thread.qweb_hooks.remove(self.hook)

    def post_process(self):
        last_event_query = None
        last_event_time = None
        stack = []
        results = []
        archs = {}
        for event, kwargs, sql_count, time in self.events:
            if event == 'render':
                archs[kwargs['view_id']] = kwargs['arch']
                continue

            # update the active directive with the elapsed time and queries
            if stack:
                top = stack[-1]
                top['delay'] += time - last_event_time
                top['query'] += sql_count - last_event_query
            last_event_time = time
            last_event_query = sql_count

            directive = self._get_directive_profiling_name(kwargs['directive'], kwargs['attrib'])
            if directive:
                if event == 'enter':
                    data = {
                        'view_id': kwargs['view_id'],
                        'xpath': kwargs['xpath'],
                        'directive': directive,
                        'delay': 0,
                        'query': 0,
                    }
                    results.append(data)
                    stack.append(data)
                else:
                    assert event == "leave"
                    data = stack.pop()

        self.add({'results': {'archs': archs, 'data': results}}, check_limit=False)
        super().post_process()
