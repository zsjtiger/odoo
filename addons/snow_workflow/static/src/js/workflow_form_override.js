crossnow.define('snow_workflow.form_override', function (require) {
    'use strict';

    var session = require('web.session');
    var FormRenderer = require('web.FormRenderer');
    var FormController = require('web.FormController');
    var _t = require('web.core')._t;

    FormRenderer.include({
        /**
         * 防抖函数，防止短时间双击按钮多次调用
         */
        debounce: function(func, wait) {
            let timeout;
            return function(...args) {
                const context = this;
                clearTimeout(timeout);
                timeout = setTimeout(() => func.apply(context, args), wait);
            };
        },
        /**
         * 对 web.FormRenderer 中 _renderStatusbarButtons 函数的覆盖
         * 首先调用原函数加载按钮，再通过权限判断，加载审批流按钮
         *
         * @param buttons - xml模板中定义的按钮
         * @returns 拼接后的按钮列表
         */
        _renderStatusbarButtons: function (buttons) {
            let $statusbarButtons = this._super.apply(this, arguments);
            let isApprovalEnable = session.approval_models.indexOf(this.state.model) !== -1;
            let enable_common_workflow = session.enable_common_workflow;
            if (enable_common_workflow && isApprovalEnable && this.mode == 'readonly') {
                this._rpc({
                    model: 'snow.workflow.action',
                    method: 'get_status',
                    args: [this.state.model, this.state.data.id],
                    context: this.state.context
                }).then(values => {
                    if (values.length > 0) {
                        values.forEach(value => {
                            let button = $('<button>').text(_t(value['button_name'])).attr({
                            'class': 'btn btn-primary oe_read_only'
                            }).css('margin-right', '4px').click(this.debounce(this.approval_action.bind(this, value), 300));
                            $statusbarButtons.prepend(button);
                        })
                    }
                })
            } else if (enable_common_workflow && isApprovalEnable && this.mode == 'edit') {
                this._rpc({
                    model: 'snow.workflow.action',
                    method: 'get_save_and_submit_button',
                    args: [this.state.model, this.state.data.id],
                    context: this.state.context
                }).then(value => {
                    if (value) {
                        let button = $('<button>').text(_t(value['button_name'])).attr({
                        'class': 'btn btn-primary'
                        }).css('margin-right', '4px').click(this.debounce(this.save_and_submit.bind(this, value), 300));
                        $statusbarButtons.prepend(button);
                    }
                })
            }
            return $statusbarButtons;
        },
        /**
         * 审批流通用按钮方法，绑定后端固定方法，通过传递方法名实现不同功能
         *
         * @param method - 不同按钮传递的方法
         */
        approval_action: function(value) {
            var self = this;
            let modelName = this.state.model;
            let id = this.state.data.id;
            value.model_name = modelName;
            value.record_id = id;
            this._rpc({
                model: 'snow.workflow.action',
                method: 'approval_action',
                args: [value],
            }).then(values => {
                if (values?.tag === 'submit_success') {
                    self.trigger_up('reload')
                } else if (values) {
                    this.do_action(values)
                }
            });
        },
        save_and_submit: function(value) {
            var self = this;
            var controller = this.getParent();

            // 调用控制器中的 saveRecord 方法
            controller.saveRecord(controller.handle, {
                stayInEdit: true,
                reload: true,
                saveAndNew: false,
            }).then(function () {
                let record_id = controller.model.get(controller.handle).res_id;
                // 提交自定义操作
                self._rpc({
                    model: 'snow.workflow.action',
                    method: 'submit_after_save',
                    args: [self.state.model, record_id],
                    context: self.state.context
                }).then(values => {
                    controller.update({ mode: 'readonly' });
                    controller.reload();
                    if (values) {
                        self.do_action(values)
                    }
                });
            });
        },
    })

});