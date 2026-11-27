

import json
import uuid
from ..operators import Attrib
from .dict import DictionarySerializer

class JSONSerializer(DictionarySerializer):

    def serialize_workflow_spec(self, wf_spec, **kwargs):
        thedict = super(JSONSerializer, self).serialize_workflow_spec(wf_spec, **kwargs)
        return self._dumps(thedict)

    def deserialize_workflow_spec(self, s_state, **kwargs):
        thedict = self._loads(s_state)
        return super(JSONSerializer, self).deserialize_workflow_spec(thedict, **kwargs)

    def serialize_workflow(self, workflow, **kwargs):
        thedict = super(JSONSerializer, self).serialize_workflow(workflow, **kwargs)
        return self._dumps(thedict)

    def deserialize_workflow(self, s_state, **kwargs):
        thedict = self._loads(s_state)
        return super(JSONSerializer, self).deserialize_workflow(thedict, **kwargs)

    def _object_hook(self, dct):
        if '__uuid__' in dct:
            return uuid.UUID(dct['__uuid__'])

        if '__bytes__' in dct:
            return dct['__bytes__'].encode('ascii')

        if '__attrib__' in dct:
            return Attrib(dct['__attrib__'])

        return dct

    def _default(self, obj):
        if isinstance(obj, uuid.UUID):
            return {'__uuid__': obj.hex}

        if isinstance(obj, bytes):
            return {'__bytes__': obj.decode('ascii')}

        if isinstance(obj, Attrib):
            return {'__attrib__': obj.name}

        raise TypeError('%r is not JSON serializable' % obj)

    def _loads(self, text):
        return json.loads(text, object_hook=lambda o: self._object_hook(o))

    def _dumps(self, dct):
        return json.dumps(dct, sort_keys=True, default=lambda o:
                self._default(o))
