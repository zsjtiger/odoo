crossnow.define("board.BoardView", function (require) {
  "use strict";

  var Context = require("web.Context");
  var config = require("web.config");
  var core = require("web.core");
  var dataManager = require("web.data_manager");
  var Dialog = require("web.Dialog");
  var Domain = require("web.Domain");
  var FormController = require("web.FormController");
  var FormRenderer = require("web.FormRenderer");
  var FormView = require("web.FormView");
  var pyUtils = require("web.py_utils");
  var session = require("web.session");
  var viewRegistry = require("web.view_registry");
  const { loadLegacyViews } = require("@web/legacy/legacy_views");

  var _t = core._t;
  var _lt = core._lt;
  var QWeb = core.qweb;

  var BoardController = FormController.extend({
    /**
     * @override
     */
    init: function (parent, model, renderer, params) {
      this._super.apply(this, arguments);
      this.customViewID = params.customViewID;
    },

    async willStart() {
      const _super = this._super.bind(this, ...arguments);
      await loadLegacyViews({ rpc: this._rpc.bind(this) });
      return _super();
    },

    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /**
     * @override
     */
    getTitle: function () {
      // return _t("My Dashboard");
      return this._title || _t("My Dashboard");
    },
  });

  var BoardRenderer = FormRenderer.extend({
    /**
     * @override
     */
    init: function (parent, state, params) {
      this._super.apply(this, arguments);
      this.noContentHelp = params.noContentHelp;
      this.actionsDescr = {};
      this._boardSubcontrollers = []; // for board: controllers of subviews
      this._boardFormViewIDs = {}; // for board: mapping subview controller to form view id
    },
    /**
     * @override
     * @return {Promise<void>}
     */
    async start() {
      await this._super.apply(this, arguments);
    },
    /**
     * Call `on_attach_callback` for each subview
     *
     * @override
     */
    on_attach_callback: function () {
      _.each(this._boardSubcontrollers, function (controller) {
        if ("on_attach_callback" in controller) {
          controller.on_attach_callback();
        }
      });
    },
    /**
     * Call `on_detach_callback` for each subview
     *
     * @override
     */
    on_detach_callback: function () {
      _.each(this._boardSubcontrollers, function (controller) {
        if ("on_detach_callback" in controller) {
          controller.on_detach_callback();
        }
      });
    },

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * @private
     * @param {Object} params
     * @param {jQueryElement} params.$node
     * @param {integer} params.actionID
     * @param {Object} params.context
     * @param {any[]} params.domain
     * @param {string} params.viewType
     * @returns {Promise}
     */
    _createController: function (params) {
      var self = this;
      return this._rpc({
        route: "/web/action/load",
        params: { action_id: params.actionID },
      }).then(function (action) {
        if (!action) {
          // the action does not exist anymore
          return Promise.resolve();
        }
        var evalContext = new Context(
          session.user_context,
          params.context,
        ).eval();
        if (evalContext.group_by && evalContext.group_by.length === 0) {
          delete evalContext.group_by;
        }
        // tz and lang are saved in the custom view
        // override the language to take the current one
        var rawContext = new Context(action.context, evalContext, {
          lang: session.user_context.lang,
        });
        var context = pyUtils.eval("context", rawContext, evalContext);
        var domain =
          params.domain ||
          pyUtils.eval("domain", action.domain || "[]", action.context);

        action.context = context;
        action.domain = domain;

        // When creating a view, `action.views` is expected to be an array of dicts, while
        // '/web/action/load' returns an array of arrays.
        action._views = action.views;
        action.views = $.map(action.views, function (view) {
          return { viewID: view[0], type: view[1] };
        });

        var viewType = params.viewType || action._views[0][1];
        var view = _.find(action._views, function (descr) {
          return descr[1] === viewType;
        }) || [false, viewType];
        return self
          .loadViews(action.res_model, context, [view])
          .then(function (viewsInfo) {
            var viewInfo = viewsInfo[viewType];
            var xml = new DOMParser().parseFromString(
              viewInfo.arch,
              "text/xml",
            );
            var key = xml.documentElement.getAttribute("js_class");
            var View = viewRegistry.get(key || viewType);

            const searchQuery = {
              context: context,
              domain: domain,
              groupBy:
                typeof context.group_by === "string" && context.group_by
                  ? [context.group_by]
                  : context.group_by || [],
              orderedBy: context.orderedBy || [],
            };

            if (View.prototype.searchMenuTypes.includes("comparison")) {
              searchQuery.timeRanges = context.comparison || {};
            }

            var view = new View(viewInfo, {
              action: action,
              hasSelectors: false,
              modelName: action.res_model,
              searchQuery,
              withControlPanel: false,
              withSearchPanel: false,
            });
            return view.getController(self).then(function (controller) {
              self._boardFormViewIDs[controller.handle] = _.first(
                _.find(action._views, function (descr) {
                  return descr[1] === "form";
                }),
              );
              self._boardSubcontrollers.push(controller);
              return controller.appendTo(params.$node);
            });
          });
      });
    },
    /**
     * @private
     * @param {Object} node
     * @returns {jQueryElement}
     */
    _renderTagBoard: function (node) {
      var self = this;
      // we add the o_dashboard class to the renderer's $el. This means that
      // this function has a side effect.  This is ok because we assume that
      // once we have a '<board>' tag, we are in a special dashboard mode.
      this.$el.addClass("o_dashboard");

      var hasAction = _.detect(node.children, function (element) {
        return element.tag === "action" ? element : false;
      });
      if (!hasAction) {
        return $(QWeb.render("DashBoard.NoContent"));
      }

      // We should start with three columns available
      node = $.extend(true, {}, node);

      // register actions, alongside a generated unique ID
      _.each(node.children, function (action, action_index) {
        action.attrs.id = "action_" + action_index;
        self.actionsDescr[action.attrs.id] = action.attrs;
      });

      var $html = $("<div>").append(
        $(
          QWeb.render("DashBoard", {
            node: node,
            isMobile: config.device.isMobile,
          }),
        ),
      );

      // 初始化grid布局
      let gridWidth = 4;
      let gridHeight = 4;
      const boardLayout = node.attrs?.layout;
      if (boardLayout) {
        // action_mamager 减去form_view的上下padding
        const gridUnitHeight = (($('.o_action_manager').height() - 48) - (gridHeight - 1) * 8) / gridHeight;
        const [layoutRow, layoutColumn] = boardLayout.split("-").map(Number);
        if (layoutRow & layoutColumn) {
          gridWidth = layoutColumn;
          gridHeight = layoutRow;
          $html.find(".oe_dashboard_layout_grid").css({
            'height': `${gridUnitHeight * gridHeight}px`,
            'grid-template-rows': `repeat(${gridHeight}, 1fr)`,
            'grid-template-columns': `repeat(${gridWidth}, 1fr)`,
          })
        }
      }

      this._boardSubcontrollers = []; // dashboard controllers are reset on re-render

      // render each view
      _.each(this.actionsDescr, function (action) {
        self.defs.push(
          self._createController({
            $node: $html.find(
              ".oe_action[data-id=" + action.id + "] .oe_content",
            ),
            actionID: _.str.toNumber(action.name),
            context: action.context,
            domain: Domain.prototype.stringToArray(action.domain, {}),
            viewType: action.view_mode,
          }),
        );
      });

      // 设置grid布局
      const gridMap = Array.from({ length: gridHeight }, () =>
        Array(gridWidth).fill(false)
      );
      const canPlace = (row, col, w, h) => {
        if (col + w > gridWidth || row + h > gridHeight) return false;

        for (let r = row; r < row + h; r++) {
          for (let c = col; c < col + w; c++) {
            if (gridMap[r][c]) return false;
          }
        }

        return true;
      };
      const markOccupied = (row, col, w, h) => {
        for (let r = row; r < row + h; r++) {
          for (let c = col; c < col + w; c++) {
            gridMap[r][c] = true;
          }
        }
      };
      const findNextPosition = (w, h) => {
        for (let row = 0; row < gridHeight; row++) {
          for (let col = 0; col < gridWidth; col++) {
            if (canPlace(row, col, w, h)) {
              markOccupied(row, col, w, h);
              return { row, col };
            }
          }
        }
        return null;
      };

      _.each(this.actionsDescr, function (action) {
        const currentEl = $html.find(".oe_action[data-id=" + action.id + "]")[0]
        const [h, w] = action.layout.split("-").map(Number);
        const pos = findNextPosition(w, h);
        
        if (!pos) {
          throw new Error(`No space left for action id: ${action.id}, layout: ${action.layout}, \n current space: \n ${gridMap.map(row => row.join('\t')).join('\n')}`);
        }

        currentEl.style.gridColumn = `${pos.col + 1} / span ${w}`;
        currentEl.style.gridRow = `${pos.row + 1} / span ${h}`;
      });

      return $html;
    },
  });

  var BoardView = FormView.extend({
    config: _.extend({}, FormView.prototype.config, {
      Controller: BoardController,
      Renderer: BoardRenderer,
    }),
    display_name: _lt("Board"),

    /**
     * @override
     */
    init: function (viewInfo) {
      this._super.apply(this, arguments);
      this.controllerParams.customViewID = viewInfo.custom_view_id;
    },
    /**
     * @override
     */
    _extractParamsFromAction(action) {
      action.target = "inline";
      action.flags = action.flags || {};
      Object.assign(action.flags, {
        hasActionMenus: false,
        hasSearchView: false,
        headless: true,
      });
      return this._super.apply(this, arguments);
    },
  });

  return BoardView;
});

crossnow.define("board.viewRegistry", function (require) {
  "use strict";

  var BoardView = require("board.BoardView");

  var viewRegistry = require("web.view_registry");

  viewRegistry.add("board", BoardView);
});
