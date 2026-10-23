# Copyright 2023 The CrossNow.inc Authors.
#

from .UnstructuredJoin import UnstructuredJoin


class ParallelGateway(UnstructuredJoin):
    """
    Task Spec for a bpmn:parallelGateway node. From the specification of BPMN
    (http://www.omg.org/spec/BPMN/2.0/PDF - document number:formal/2011-01-03):

        The Parallel Gateway is activated if there is at least one token on
        each incoming Sequence Flow.

        The Parallel Gateway consumes exactly one token from each incoming

        Sequence Flow and produces exactly one token at each outgoing
        Sequence Flow.

        TODO: Not implemented:
        If there are excess tokens at an incoming Sequence Flow, these tokens
        remain at this Sequence Flow after execution of the Gateway.

    Essentially, this means that we must wait until we have a completed parent
    task on each incoming sequence.
    """

    def _check_threshold_unstructured(self, my_task, force=False):
        completed_inputs, waiting_tasks = self._get_inputs_with_tokens(my_task)
        return force or len(completed_inputs) >= len(self.inputs), waiting_tasks

    @property
    def spec_type(self):
        return 'Parallel Gateway'
