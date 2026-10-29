"""The lookup of the translation context in the calling frames: the module, the cursor, the user and the language."""

from __future__ import annotations

import inspect
import logging
import typing
import odoo

if typing.TYPE_CHECKING:
    import types


_logger = logging.getLogger('odoo.tools.text.translate')


def _get_frame(stack_level: int = 0) -> types.FrameType | None:
    from odoo.tools.safe_eval.runtime import safe_call as wrapper_func  # noqa: PLC0415

    stack_level += 1  # +1 to skip this function
    frame = origin_frame = inspect.currentframe()

    while frame:
        if frame.f_code is not wrapper_func.__code__:
            if stack_level == 0:
                return frame
            stack_level -= 1
        frame = frame.f_back

    _logger.warning(
        'Impossible to retrieve frame for translation language, skipping translation %s',
        origin_frame, stack_info=True,
    )
    return None


def get_translated_module(arg: str | int | typing.Any) -> str:  # frame not represented as hint
    """Get the addons name.

    :param arg: can be any of the following:
                str ("name_of_module") returns itself;
                str (__name__) use to resolve module name;
                int is number of frames to go back to the caller;
                frame of the caller function
    """
    if isinstance(arg, str):
        if arg.startswith('odoo.addons.'):
            # get the name of the module
            return arg.split('.')[2]
        if '.' in arg or not arg:
            # module name is not in odoo.addons.
            return 'base'
        else:
            return arg
    else:
        if isinstance(arg, int):
            frame = _get_frame(arg)
        else:
            frame = arg
        if not frame:
            return 'base'
        if (module_name := frame.f_globals.get("__name__")) and module_name.startswith('odoo.addons.'):
            # just a quick lookup because `get_resource_from_path is slow compared to this`
            return module_name.split('.')[2]
        path = inspect.getfile(frame)
        from odoo.modules import get_resource_from_path  # noqa: PLC0415
        path_info = get_resource_from_path(path)
        return path_info[0] if path_info else 'base'


def _get_cr(frame):
    # try, in order: cr, cursor, self.env.cr, self.cr,
    # request.env.cr
    if 'cr' in frame.f_locals:
        return frame.f_locals['cr']
    if 'cursor' in frame.f_locals:
        return frame.f_locals['cursor']
    if (local_self := frame.f_locals.get('self')) is not None:
        if (local_env := getattr(local_self, 'env', None)) is not None:
            return local_env.cr
        if (cr := getattr(local_self, 'cr', None)) is not None:
            return cr
    if (req := odoo.http.request) and (env := req.env):
        return env.cr
    return None


def _get_uid(frame) -> int | None:
    # try, in order: uid, user, self.env.uid
    if 'uid' in frame.f_locals:
        return frame.f_locals['uid']
    if 'user' in frame.f_locals:
        return int(frame.f_locals['user'])      # user may be a record
    if (local_self := frame.f_locals.get('self')) is not None:
        if hasattr(local_self, 'env') and (uid := local_self.env.uid):
            return uid
    return None


def _get_lang(frame, default_lang='') -> str:
    # get from: context.get('lang'), kwargs['context'].get('lang'),
    if local_context := frame.f_locals.get('context'):
        if lang := local_context.get('lang'):
            return lang
    if (local_kwargs := frame.f_locals.get('kwargs')) and (local_context := local_kwargs.get('context')):
        if lang := local_context.get('lang'):
            return lang
    # get from self.env
    log_level = logging.WARNING
    local_self = frame.f_locals.get('self')
    local_env = local_self is not None and getattr(local_self, 'env', None)
    if local_env:
        if lang := local_env.lang:
            return lang
        # we found the env, in case we fail, just log in debug
        log_level = logging.DEBUG
    # get from request?
    if (req := odoo.http.request) and (env := req.env) and (lang := env.lang):
        return lang
    # Last resort: attempt to guess the language of the user
    # Pitfall: some operations are performed in sudo mode, and we
    #          don't know the original uid, so the language may
    #          be wrong when the admin language differs.
    cr = _get_cr(frame)
    uid = _get_uid(frame)
    if cr and uid:
        from odoo import api  # noqa: PLC0415
        env = api.Environment(cr, uid, {})
        if lang := env['res.users'].context_get().get('lang'):
            return lang
    # fallback
    if default_lang:
        _logger.debug('no translation language detected, fallback to %s', default_lang)
        return default_lang
    # give up
    _logger.log(log_level, 'no translation language detected, skipping translation %s', frame, stack_info=True)
    return ''


def _get_translation_source(stack_level: int, module: str = '', lang: str = '', default_lang: str = '') -> tuple[str, str]:
    if not (module and lang):
        frame = _get_frame(stack_level + 1)  # +1 to skip this function
        lang = lang or _get_lang(frame, default_lang)
    if lang and lang != 'en_US':
        return get_translated_module(module or frame), lang
    else:
        # we don't care about the module for 'en_US'
        return module or 'base', 'en_US'
