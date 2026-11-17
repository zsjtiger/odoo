"""The templates of the views: the cache of the templates, their preloading and their rendering."""

from __future__ import annotations

from collections.abc import Sequence
from odoo import models
from odoo.exceptions import MissingError
from odoo.fields import Domain
from odoo.tools import partition


def _get_cached_template_prefetched_keys(self):
    return ['id', 'key', 'active', 'type']


def _get_template_minimal_cache_keys(self):
    return (bool(self.env.context.get('active_test', True)),)


def _get_cached_template_info(self, id_or_xmlid: int | str, *, _view: models.BaseModel | None = None):
    """Return cached template data for ``id_or_xmlid``.

        ``_view`` may be provided as a shortcut to avoid resolving
        ``id_or_xmlid`` again. Passing an empty recordset means the template is
        known to be missing and results in ``info['error']`` being a
        :class:`odoo.exceptions.MissingError`.

        ``_view`` is intentionally not part of the cache key: when provided and
        correct, it is equivalent to the view resolved from ``id_or_xmlid`` and
        does not change the result.
        """
    view = self.browse()
    error = False
    if _view is not None:
        view = _view
    elif isinstance(id_or_xmlid, int):
        view = self.env['ir.ui.view'].sudo().browse(id_or_xmlid)
        try:
            view.key
        except MissingError:
            view = self.browse()
    else:
        preload = self.sudo()._preload_views([id_or_xmlid])
        if id_or_xmlid in preload:
            info = preload[id_or_xmlid]
            view = info['view']
            error = info['error']
        else:
            error = SyntaxError('Error compiling template')
    info = {
        f: view[f] if view else None
        for f in self._get_cached_template_prefetched_keys()
    }
    if not view and not error:
        error = MissingError(self.env._("Template not found: '%s'", id_or_xmlid))
    info['error'] = error
    return info


def _get_template_view(self, id_or_xmlid: int | str, raise_if_not_found=True) -> models.BaseModel:
    info = self._get_cached_template_info(id_or_xmlid)
    if info['error'] and raise_if_not_found:
        raise info['error']
    return self.env['ir.ui.view'].browse(info['id'])


def _get_template_domain(self, xmlids: list[str]) -> Domain:
    return Domain('key', 'in', xmlids)


def _get_template_order(self) -> str:
    return "priority, id"


def _fetch_template_views(self, ids_or_xmlids: Sequence[int | str]) -> dict[int | str, models.BaseModel | Exception]:
    """ Return the view corresponding to ``template``, which may be a
            view ID or an XML ID. Note that this method may be overridden for other
            kinds of template values.
        """
    IrUiView = self.env['ir.ui.view'].sudo().with_context(load_all_views=True, raise_if_not_found=True)

    ids, xmlids = partition(lambda v: isinstance(v, int), ids_or_xmlids)

    # search view in ir.ui.view
    view_by_id = {}
    field_names = [f.name for f in IrUiView._fields.values() if f.prefetch is True]
    if xmlids:
        domain = Domain('id', 'in', ids) | Domain(self._get_template_domain(xmlids))
        views = IrUiView.search_fetch(domain, field_names, order=self._get_template_order())
    else:
        views = IrUiView.browse(ids)

    for view in views:
        try:
            if view.key in view_by_id:
                # keeps views according to their priority order
                continue
        except MissingError:
            continue
        view_by_id[view.id] = view
        if view.key:
            view_by_id[view.key] = view

    # search missing view from xmlid in ir.model.data
    missing_xmlid_views = [xmlid for xmlid in xmlids if '.' in xmlid and xmlid not in view_by_id]
    if missing_xmlid_views:
        domain = Domain.OR(
            Domain('model', '=', 'ir.ui.view') & Domain('module', '=', res[0]) & Domain('name', '=', res[1])
            for xmlid in missing_xmlid_views
            if (res := xmlid.split('.', 1))
        )

        for model_data in self.env['ir.model.data'].sudo().search(domain):
            view = IrUiView.browse(model_data.res_id)
            if view.exists():
                view_by_id[view.id] = view
                xmlid = f"{model_data.module}.{model_data.name}"
                view_by_id[xmlid] = view
                if view.key:
                    view_by_id[view.key] = view

    for key, view in view_by_id.items():
        # push information in cache
        self._get_cached_template_info(key, _view=view)

    # create data and errors
    for id_or_xmlid in ids_or_xmlids:
        if id_or_xmlid not in view_by_id:
            # push information in cache for missing records
            info = self._get_cached_template_info(id_or_xmlid, _view=self.browse())
            view_by_id[id_or_xmlid] = info['error']
    return view_by_id


def _clear_preload_views_cache_if_needed(self):
    """ Invalidate the local cache when the orm cache is cleared
        """
    self.env.cr.cache.pop('_compile_batch_', None)


def _preload_views(self, refs: Sequence[int | str]) -> dict[int | str, dict]:
    """
        Return self's arch combined with its inherited views archs.

        :param refs: list of id or xmlid
        :return: dictionary of preloaded information {id or xmlid: {xmlid, ref, view, error}}
        """
    self._clear_preload_views_cache_if_needed()

    context = {k: self.env.context.get(k) for k in self.env['ir.qweb']._get_template_cache_keys()}
    cache_key = tuple(context.values())

    compile_batch = self.env.cr.cache.setdefault('_compile_batch_', {}).setdefault(cache_key, {})

    refs = [int(ref) if isinstance(ref, int) or ref.isdigit() else ref for ref in refs]
    missing_refs = [ref for ref in refs if ref and ref not in compile_batch]
    if not missing_refs:
        return compile_batch

    unknown_views = self._fetch_template_views(missing_refs)

    # add in cache
    for id_or_xmlid, view in unknown_views.items():
        if isinstance(view, models.BaseModel):
            compile_batch[view.id] = compile_batch[id_or_xmlid] = {
                'xmlid': view.key or id_or_xmlid,
                'ref': view.id,
                'view': view,
                'error': False,
            }
        else:
            compile_batch[id_or_xmlid] = {
                'xmlid': id_or_xmlid,
                'view': None,
                'ref': None,
                'error': view,  # MissingError
            }

    return compile_batch


def _read_template_keys(self):
    """ Return the list of context keys to use for caching ``_read_template``. """
    return ['lang', 'inherit_branding', 'edit_translations']


def _get_view_etrees(self):
    if not self:
        return []
    arch_trees = self._get_combined_archs()
    for arch_tree in arch_trees:
        self.distribute_branding(arch_tree)
    return arch_trees


def _render_template(self, template, values=None):
    return self.env['ir.qweb']._render(template, values)
