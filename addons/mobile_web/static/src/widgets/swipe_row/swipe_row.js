import { Component, onMounted, onWillUnmount, proxy, signal, t, useProps, xml } from "@odoo/owl";
import { SvgIcon } from "@mobile_web/widgets/svg_icon/svg_icon";

/** 删除按钮的宽度, 左滑超过一半时保持展开 */
export const DELETE_WIDTH = 72;
/** 超过这个距离才视为滑动, 小于它的手指抖动仍然是点击 */
const SLIDE_SLOP = 6;

/**
 * 左滑显示删除按钮的行容器.
 *
 * 内容放在默认插槽中; 左滑露出删除按钮, 点击按钮时调用 onDelete(resId).
 * 没有删除权限时 disabled 为真, 按钮仍然露出但不可点击.
 */
export class SwipeRow extends Component {
    static components = { SvgIcon };
    static template = xml`
        <t t-name="mobile_web.SwipeRow">
            <div class="m_swipe_row" t-ref="this.root">
                <button type="button" class="m_swipe_delete" t-att-disabled="this.props.disabled or null"
                        t-att-aria-label="this.props.label" t-att-title="this.props.label" t-on-click="this.onDeleteClick">
                    <SvgIcon iconHref="'#crossnow-icon-Delete'" className="'m_swipe_delete_icon'"/>
                </button>
                <div class="m_swipe_content" t-att-style="'transform: translateX(' + this.state.offset + 'px)'">
                    <t t-slot="default"/>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        resId: t.number(),
        disabled: t.boolean().optional(false),
        label: t.string().optional(""),
        onDelete: t.function(),
    });
    root = signal.ref();
    state = proxy({ offset: 0 });

    // 拖动过程中的临时状态, 不需要参与渲染
    startX = 0;
    startY = 0;
    baseOffset = 0;
    moved = false;
    horizontal = false;
    suppressClick = false;

    setup() {
        const listeners = [
            ["touchstart", this.onTouchStart, { passive: true }],
            ["touchmove", this.onTouchMove, { passive: true }],
            ["touchend", this.onTouchEnd, { passive: true }],
            ["click", this.onClickCapture, true],
        ];
        onMounted(() => {
            const el = this.root();
            for (const [type, handler, options] of listeners) {
                el.addEventListener(type, handler, options);
            }
        });
        onWillUnmount(() => {
            const el = this.root();
            for (const [type, handler, options] of listeners) {
                el?.removeEventListener(type, handler, options);
            }
        });
    }

    // 作为监听器传递, 使用箭头函数保持 this
    onTouchStart = (ev) => {
        const touch = ev.touches[0];
        this.startX = touch.clientX;
        this.startY = touch.clientY;
        this.baseOffset = this.state.offset;
        this.moved = false;
        this.horizontal = false;
    };

    onTouchMove = (ev) => {
        const touch = ev.touches[0];
        const dx = touch.clientX - this.startX;
        const dy = touch.clientY - this.startY;
        if (!this.moved) {
            if (Math.abs(dx) < SLIDE_SLOP && Math.abs(dy) < SLIDE_SLOP) {
                return;
            }
            // 竖直方向的滑动交给页面滚动, 不展开删除按钮
            this.horizontal = Math.abs(dx) > Math.abs(dy);
            this.moved = true;
        }
        if (this.horizontal) {
            this.state.offset = Math.min(0, Math.max(-DELETE_WIDTH, this.baseOffset + dx));
        }
    };

    onTouchEnd = () => {
        if (!this.moved) {
            return;
        }
        if (this.horizontal) {
            this.state.offset = this.state.offset < -DELETE_WIDTH / 2 ? -DELETE_WIDTH : 0;
            this.suppressClick = true;
        }
        this.moved = false;
    };

    /** 展开时点击行的其它部分只收起, 不打开记录; 滑动结束后的那次点击也忽略 */
    onClickCapture = (ev) => {
        if (ev.target.closest(".m_swipe_delete")) {
            return;
        }
        if (this.suppressClick || this.state.offset !== 0) {
            ev.preventDefault();
            ev.stopPropagation();
            this.suppressClick = false;
            this.state.offset = 0;
        }
    };

    onDeleteClick = () => {
        if (this.props.disabled) {
            return;
        }
        this.state.offset = 0;
        this.props.onDelete(this.props.resId);
    };
}
