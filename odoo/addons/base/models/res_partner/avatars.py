# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The avatars of the partners: the images of the several sizes and the placeholders."""

from __future__ import annotations

import typing
from odoo import tools

if typing.TYPE_CHECKING:
    pass

from .partner import ResPartner

def _compute_avatar_1920(self):
    super(ResPartner, self)._compute_avatar_1920()


def _compute_avatar_1024(self):
    super(ResPartner, self)._compute_avatar_1024()


def _compute_avatar_512(self):
    super(ResPartner, self)._compute_avatar_512()


def _compute_avatar_256(self):
    super(ResPartner, self)._compute_avatar_256()


def _compute_avatar_128(self):
    super(ResPartner, self)._compute_avatar_128()


def _compute_avatar(self, avatar_field, image_field):
    partners_with_internal_user = self.filtered(
        lambda partner: partner.type == 'contact' or any(not u.share for u in partner.user_ids))
    super(ResPartner, partners_with_internal_user)._compute_avatar(avatar_field, image_field)
    partners_without_image = (self - partners_with_internal_user).filtered(lambda p: not p[image_field])
    for _, group in tools.groupby(partners_without_image, key=lambda p: p._avatar_get_placeholder_path()):
        group_partners = self.env['res.partner'].concat(group)
        group_partners[avatar_field] = group_partners[0]._avatar_get_placeholder()

    for partner in self - partners_with_internal_user - partners_without_image:
        partner[avatar_field] = partner[image_field]


def _avatar_get_placeholder_path(self):
    if self.is_company:
        return "base/static/img/avatar_placeholder_company.png"
    if self.type == 'delivery':
        return "base/static/img/avatar_placeholder_delivery.png"
    if self.type == 'invoice':
        return "base/static/img/avatar_placeholder_invoice.png"
    if self.type == 'other':
        return "base/static/img/avatar_placeholder_other.png"
    return super(ResPartner, self)._avatar_get_placeholder_path()
