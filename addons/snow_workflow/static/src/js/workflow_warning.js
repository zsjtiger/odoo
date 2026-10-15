crossnow.define('snow_workflow.workflow_warning', function (require) {
    'use strict';

    var core = require('web.core');
    var AbstractField = require('web.AbstractField');
    var registry = require('web.field_registry');
    var QWeb = core.qweb;
    var Dialog = require('web.Dialog');
    var _t = core._t;

    var WorkflowWarning = AbstractField.extend({
        init: function(){
            this._super.apply(this, arguments);
        },
        events: {
            'click #cancel': '_onClickCancel',
            'click #submit': '_onClickSubmit',
        },
        start: function() {
            var self = this;
            var result = {
                warning_info: this.record.context.temporary_verify_info,
                show_check_box: this.record?.context?.show_check_box ?? true,
            };
            var $content = $(QWeb.render('snow_workflow.workflow_warning', {
                result: result
            }));
            this.$el.append($content);
        },
        reader: function(){
            QWeb.add_template('/snow_workflow/static/src/xml/workflow_warning.xml');
        },
        _onClickCancel: function(event){
            this.do_action({
                type: 'ir.actions.act_window_close',
                res_model: 'snow.workflow.execution.task.data',
                view_mode: 'form',
            });
        },
        _onClickSubmit: function(event){
            var self = this;
            var isChecked = $('#read_and_agree').is(':checked');
            if (isChecked || !this.record?.context?.show_check_box) {
                var submit_info = $("#submit_info").val();
                if(submit_info.length == 0 && this.record.context.is_submit_text){
                    var dialog = new Dialog(this, {
                        title: _t('information'),
                        size: 'medium',
                        $content: $(_t('<div>The submission description is required.</div>')),
                        buttons: [{
                            text: _t('OK'),
                            classes: 'btn-primary',
                            click: function () {
                                dialog.close();
                            }
                        }]
                    });
                    dialog.open();
                }else{
                    if(submit_info.length > 200){
                        var dialog = new Dialog(this, {
                            title: _t('information'),
                            size: 'medium',
                            $content: $(_t('<div>The submission description cannot exceed 200 characters</div>')),
                            buttons: [{
                                text: _t('OK'),
                                classes: 'btn-primary',
                                click: function () {
                                    dialog.close();
                                }
                            }]
                        });
                        dialog.open();
                    }else{
                        var context = this.record.context;
                        context['submit_info'] = submit_info;
                        this._rpc({
                            model: this.record.context.confirm.model,
                            method: this.record.context.confirm.method,
                            context: context
                        }).then(function(results) {
                            if (results) {
                                results.target = 'current';
                            }
                            self.do_action(results, {stackPosition: 'replaceCurrentAction'});
                        });
                    }
                }
            } else {
                var dialog = new Dialog(this, {
                    title: _t('information'),
                    size: 'medium',
                    $content: $(_t('<div>You must click read and agree!</div>')),
                    buttons: [{
                        text: _t('OK'),
                        classes: 'btn-primary',
                        click: function () {
                            dialog.close();
                        }
                    }]
                });
                dialog.open();
            }
        }
    });

    registry.add('workflow_warning', WorkflowWarning);
    return {
        WorkflowWarning: WorkflowWarning
    };
});