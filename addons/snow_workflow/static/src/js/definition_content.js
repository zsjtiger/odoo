crossnow.define('snow_workflow.definition_content', function (require) {
    'use strict';
    var registry = require('web.field_registry');
    var fields = require('web.basic_fields');

    var DefinitionContent = fields.FieldText.extend({
        init: function(parent, options) {
            this._super.apply(this, arguments);
        },
        start: function() {
            if (this.mode == 'readonly') {
                var text = this.value;
                var lines = text.split('\n');
                var displayText = lines.slice(0, 5).join('\n');
                if (lines.length > 5) {
                    displayText += '\n...';
                }
                this.value = displayText;
                this._super.apply(this, arguments);
            } else {
                this._super.apply(this, arguments);
            }
        }
    });

    registry.add('definition_content', DefinitionContent);

    return DefinitionContent;
});
