"""Types of the database driver: the conversion of the decimals to floats."""

from __future__ import annotations

import typing
import psycopg2.errorcodes  # noqa: F401
import psycopg2.extensions

if typing.TYPE_CHECKING:

    # when type checking, the Cursor exposes methods of the psycopg cursor
    _CursorProtocol = psycopg2.extensions.cursor
else:
    _CursorProtocol = object




def undecimalize(value, cr) -> float | None:
    if value is None:
        return None
    return float(value)


DECIMAL_TO_FLOAT_TYPE = psycopg2.extensions.new_type((1700,), 'float', undecimalize)


psycopg2.extensions.register_type(DECIMAL_TO_FLOAT_TYPE)


psycopg2.extensions.register_type(psycopg2.extensions.new_array_type((1231,), 'float[]', DECIMAL_TO_FLOAT_TYPE))


class PsycoConnection(psycopg2.extensions.connection):
    _pool_last_used: float = 0

    def lobject(*args, **kwargs):
        pass

    if hasattr(psycopg2.extensions, 'ConnectionInfo'):
        @property
        def info(self):
            class PsycoConnectionInfo(psycopg2.extensions.ConnectionInfo):
                @property
                def password(self):
                    pass
            return PsycoConnectionInfo(self)

    def give_back(self, keep_in_pool=True):
        raise RuntimeError('not bound to a pool')
