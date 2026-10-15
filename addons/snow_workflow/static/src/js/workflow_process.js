crossnow.define('web.workflow_process', function (require) {
'use strict';

var core = require('web.core');
var utils = require('web.utils');
var Dialog = require('web.Dialog');
var relational_fields = require('web.relational_fields');
var AbstractField = require('web.AbstractField');
var registry = require('web.field_registry');
var time = require('web.time');
var field_utils = require('web.field_utils');
var _lt = core._lt;
var qweb = core.qweb;

var CommonApprovalProcess = AbstractField.extend({
    actionList:{
        submit: {
            name: _lt('submit for approval'),
            color: '#03A09C',
            icon: 'fa fa-arrow-circle-o-up',
        },
        ready: {
            name: _lt('under approval'),
            color: '#F99902',
            icon: 'fa fa-clock-o',
        },
        suspend: {
            name: _lt('suspend'),
            color: '#F99902',
            icon: 'fa fa-play-circle-o',
        },
        unsuspend: {
            name: _lt('suspended recovery'),
            color: '#03A09C',
            icon: 'fa fa-pause-circle-o',
        },
        reject: {
            name: _lt('reject'),
            color: '#ff0000',
            icon: 'fa fa-times-circle-o',
        },
        pass: {
            name: _lt('pass'),
            color: '#03A09C',
            icon: 'fa fa-check-circle-o',
        },
        withdraw: {
            name: _lt('withdrawn'),
            color: '#ff0000',
            icon: 'fa fa-minus-circle',
        },
        wait: {
            name: _lt('wait'),
            color: '#ccc',
            icon: 'fa fa-dot-circle-o',
        },
        finished: {
            name: '',
            color: '#03A09C',
            icon: 'fa fa-dot-circle-o',
        },  // 其他人通过或拒绝，被动结束
    },
    template: 'snow_workflow.workflow_process',
    specialData: "_fetchSpecialRelation",
    steps: [],
    supportedFieldTypes: ['one2many'],
    start: function()
        {
            var self = this;
            const data = this.record.data;
            if (data.hasOwnProperty('id') && data.id !== undefined)
            {
                self._rpc({
                    model: 'snow.workflow.action',
                    method: 'get_process_json',
                    args: [this.model, this.res_id],
                    context: this.record.context
                }).then(function(result) {
                    if (Object.keys(result).length === 0) {
                        return;
                    }
                    let target_json = JSON.parse(result);
                    self.steps = Object.values(target_json);
                    let datetime_format_str=time.getLangDatetimeFormat();
                    var format_datetime = function(d_str) {
                        if (d_str === '') {
                            return ''
                        }
                        let moment_utc = moment.utc(d_str);
                        let moment_local = moment_utc.local();
                        return moment_local.format(datetime_format_str);
                    };
                    if (self.steps)
                    {
                        self.steps.forEach(function(item)
                        {
                            item['create_date'] = format_datetime(item['create_date']);
                            let roadmap = item['approve_roadmap'];
                            if (roadmap){
                                roadmap.forEach(function(step){
                                    let members = step['members'];
                                    members.forEach(function(member){
                                        member['create_date'] = format_datetime(member['create_date']);
                                    });
                                });
                                item['approve_roadmap'] = roadmap;
                            }
                        });
                    }
                    self._render();
                });
            }
        },
    switchButton:function(obj,args)
    {
        let $header=$(obj.target).parentsUntil(".snow-steps-content").last();
        let $brother=$header.next();
        $header.toggleClass("snow_hide");
        $brother.toggleClass("snow_hide");
    },
    _render: function(){
        this.$el.html(qweb.render(this.template, {widget:this}));
        this.$el.find(".right-icon").click(this.switchButton);
    }
});

registry.add('workflow_process', CommonApprovalProcess);

return CommonApprovalProcess;

});
