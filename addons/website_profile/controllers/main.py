# Part of Odoo. See LICENSE file for full copyright and licensing details.

from urllib.parse import urlsplit
import werkzeug.exceptions

from odoo import _, http, tools
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)


class WebsiteProfile(http.Controller):
    _users_per_page = 30
    _pager_max_pages = 5

    # Profile
    # ---------------------------------------------------

    def _check_avatar_access(self, user_id, **post):
        """ Base condition to see user avatar independently form access rights
        is to see published users. """
        try:
            user = request.env['res.users'].sudo().browse(user_id).exists()
        except:
            return False
        if user:
            return user.website_published
        return False

    def _check_user_profile_access(self, user_id):
        """ Takes a user_id and returns:
            - (user record, False) when the user is granted access
            - (False, str) when the user is denied access
            Raises a Not Found Exception when the profile does not exist
        """
        user_sudo = request.env['res.users'].sudo().browse(user_id)
        # User can access - no matter what - his own profile
        if user_sudo.id == request.env.user.id:
            return user_sudo, False

        if not user_sudo.website_published:
            return False, _('This profile is private!')
        elif not user_sudo.exists():
            raise request.not_found()
        return user_sudo, False

    def _prepare_user_values(self, **kwargs):
        kwargs.pop('edit_translations', None) # avoid nuking edit_translations
        values = {
            'user': request.env.user,
            'is_public_user': self.env.website.is_public_user(),
        }
        return values

    def _prepare_user_profile_parameters(self, **post):
        return post

    def _prepare_user_profile_values(self, user, **post):
        return {
            'uid': request.env.user.id,
            'user': user,
            'main_object': user,
            'is_profile_page': True,
            'can_edit_country': user.partner_id and user.partner_id._can_edit_country(),
        }

    @http.route([
        '/profile/avatar/<int:user_id>',
    ], type='http', auth="public", website=True, sitemap=False, readonly=True)
    def get_user_profile_avatar(self, user_id, field='avatar_256', width=0, height=0, crop=False, **post):
        if field not in ('image_128', 'image_256', 'avatar_128', 'avatar_256'):
            return werkzeug.exceptions.Forbidden()

        if (int(width), int(height)) == (0, 0):
            width, height = tools.image.image_guess_size_from_field_name(field)

        can_sudo = self._check_avatar_access(int(user_id), **post)
        return request.env['ir.binary']._get_image_stream_from(
            request.env['res.users'].sudo(can_sudo).browse(int(user_id)),
            field_name=field, width=int(width), height=int(height), crop=crop
        ).get_response()

    def _prepare_url_from_info(self):
        url_from = request.httprequest.headers.get('Referer')
        url_current = request.httprequest.url
        void_from_url = {'url_from_label': None, 'url_from': None}
        if url_from and ((url_from_parsed := urlsplit(url_from)).netloc == urlsplit(url_current).netloc):
            path = url_from_parsed.path
            return next(
                (
                    {'url_from_label': label, 'url_from': url_from}
                    for prefix, label in (('forum', _('Forum')), ('slides', _('All Courses')))
                    if path == f'/{prefix}' or path.startswith(f'/{prefix}/')
                ), void_from_url)
        return void_from_url

    @http.route('/profile/user/<int:user_id>', type='http', auth='public', website=True, readonly=True)
    def view_user_profile(self, user_id, **post):
        user_sudo, denial_reason = self._check_user_profile_access(user_id)
        if denial_reason:
            return request.render('website_profile.profile_access_denied', {'denial_reason': denial_reason})
        params = self._prepare_user_profile_parameters(**post)
        values = {
            **self._prepare_user_values(**post),
            **self._prepare_user_profile_values(user_sudo, **params),
            **self._prepare_url_from_info(),
        }
        return request.render("website_profile.user_profile_main", values)

    # Edit Profile
    # ---------------------------------------------------
    @http.route('/profile/user/save', type='jsonrpc', auth='user', methods=['POST'], website=True)
    def save_edited_profile(self, **kwargs):
        user_id = int(kwargs.get('user_id', 0))
        user = request.env['res.users'].browse(user_id or request.env.uid)
        qcontext = {
            'name': kwargs.get('name'),
            'website': kwargs.get('website'),
            'email': kwargs.get('email'),
            'city': kwargs.get('city'),
            'country_id': kwargs.get('country_id'),
            'website_description': kwargs.get('website_description'),
        }

        if 'image_1920' in kwargs:
            qcontext['image_1920'] = kwargs.get('image_1920')

        if request.env.uid == user.id:  # the controller allows to edit only its own privacy settings; use partner management for other cases
            qcontext['website_published'] = kwargs.get('website_published')

        if not user.partner_id._can_edit_country() and qcontext.get('country_id') != user.partner_id.country_id.id:
            raise UserError(_("Changing the country is not allowed once document(s) have been issued for your account. Please contact us directly for this operation."))
        if not user.has_access('write'):
            # no write access, grant it if we can edit the partner
            if user.partner_id._can_be_edited_by_current_customer(**kwargs):
                user = user.sudo()
            else:
                raise UserError(_("You are not allowed to edit this user"))
        user.write(qcontext)
