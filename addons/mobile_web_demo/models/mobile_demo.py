from odoo import api, fields, models


class MobileDemoTag(models.Model):
    _name = 'mobile.demo.tag'
    _description = "Mobile Demo Tag"

    name = fields.Char(required=True)
    color = fields.Integer()


class MobileDemoLine(models.Model):
    _name = 'mobile.demo.line'
    _description = "Mobile Demo Line"

    item_id = fields.Many2one('mobile.demo.item', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    quantity = fields.Float(default=1.0)
    date = fields.Date(string="Date", default=fields.Date.context_today)
    unit_price = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(related='item_id.currency_id')
    amount = fields.Monetary(compute='_compute_amount', store=True, currency_field='currency_id')

    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.unit_price


class MobileDemoItem(models.Model):
    _name = 'mobile.demo.item'
    _description = "Mobile Demo Item"
    _order = 'sequence, id'

    # --- basic ---
    name = fields.Char(string="Name", required=True, index=True)
    code = fields.Char(string="Code", readonly=True, copy=False, default="DEMO")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(string="Description")
    notes = fields.Html(string="Notes")

    # --- selections and status ---
    state = fields.Selection(
        [('draft', "Draft"), ('confirmed', "Confirmed"), ('done', "Done"), ('cancel', "Cancelled")],
        string="Status", default='draft', required=True)
    priority = fields.Selection([('0', "Normal"), ('1', "Important"), ('2', "Urgent")], string="Priority", default='0')
    visit_type = fields.Selection([('normal', "Normal"), ('urgent', "Urgent")], string="Visit type", default='normal')
    category = fields.Selection(
        [('a', "Category A"), ('b', "Category B"), ('c', "Category C"), ('d', "Category D")],
        string="Category")
    color = fields.Char(string="Color", default="#0f9b8e")
    is_urgent = fields.Boolean(string="Urgent")
    urgent_reason = fields.Char(string="Urgent reason")
    note_required = fields.Char(string="Required when urgent")

    # --- numbers ---
    progress = fields.Float(string="Progress", default=0.0)
    percentage = fields.Float(string="Percentage", default=0.0)
    qty = fields.Float(string="Quantity", default=1.0)
    duration = fields.Float(string="Duration (hours)", default=0.5)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Float(string="Amount")
    price = fields.Monetary(string="Price", currency_field='currency_id')
    total_amount = fields.Monetary(string="Total", compute='_compute_total', store=True, currency_field='currency_id')

    # --- dates ---
    date = fields.Date(string="Date", default=fields.Date.context_today)
    visit_datetime = fields.Datetime(string="Visit at")

    # --- relations ---
    partner_id = fields.Many2one('res.partner', string="Partner")
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    user_id = fields.Many2one('res.users', string="Responsible")
    tag_ids = fields.Many2many('mobile.demo.tag', string="Tags")
    line_ids = fields.One2many('mobile.demo.line', 'item_id', string="Lines")

    # --- contact and special text fields ---
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    website = fields.Char(string="Website")
    secret = fields.Char(string="Secret")

    # --- files and structured data ---
    image = fields.Binary(string="Image", attachment=True)
    attachment = fields.Binary(string="Attachment")
    payload = fields.Json(string="Payload")

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for item in self:
            item.total_amount = sum(item.line_ids.mapped('amount'))

    def action_demo(self):
        """Button used by the demo form: returns a notification so the mobile client has something to show."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': "Demo button", 'message': self.name, 'type': 'success'},
        }

    @api.model
    def dynamic_filter_config(self):
        """ Custom filter panel of the mobile client (see mobile_web dynamic_filter_config). """
        return [
            {
                'name': 'subordinates',
                'label': "Subordinates",
                'options': [
                    {'key': 'mine', 'label': "Only mine", 'domain': [('user_id', '=', self.env.uid)], 'radio': True},
                ],
                'cards': {'field': 'user_id', 'subfield': 'login'},
            },
            {
                'name': 'speaker',
                'label': "Speaker",
                'options': [
                    {'key': 'speaker', 'label': "Speaker", 'domain': [('is_urgent', '=', True)]},
                    {'key': 'not_speaker', 'label': "Non-speaker", 'domain': [('is_urgent', '=', False)]},
                ],
            },
        ]

