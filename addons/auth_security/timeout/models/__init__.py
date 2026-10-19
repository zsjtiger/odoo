# auth_security.device is defined by totp; import it first so the extension below can inherit it
from ...totp import models as totp_models  # noqa: F401

from . import auth_totp_device
from . import ir_http
from . import ir_websocket
from . import res_groups
from . import res_users
