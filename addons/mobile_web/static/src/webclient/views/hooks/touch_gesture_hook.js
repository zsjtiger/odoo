import { onMounted, onWillUnmount } from "@odoo/owl";

// -----------------------------------------------------------------------------
// Touch Gesture Hook
// -----------------------------------------------------------------------------

/**
 * @typedef {Object} TouchGestureOptions
 * @property {() => void} [onSwipeLeft]
 * @property {() => void} [onSwipeRight]
 * @property {number} [threshold=50]
 * @property {number} [angleThreshold=45]
 * @property {import("@odoo/owl").Ref} [zoneRef]
 */

/**
 * 识别水平滑动手势的 hook
 * - 仅在 gestureZone 内触发, 默认 document.body
 * - 忽略 input/select/textarea 及可滚动元素内的水平滑动
 *
 * @param {TouchGestureOptions} options
 */
export function useTouchGesture(options = {}) {
    const {
        onSwipeLeft,
        onSwipeRight,
        threshold = 50,
        angleThreshold = 45,
        zoneRef,
    } = options;

    const startRef = { current: { x: 0, y: 0, time: 0 } };

    const attachTouchListeners = (el) => {
            if (!el) {
                return;
            }

            const isInteractive = (target) => {
                const tagName = target.tagName;
                if (["INPUT", "SELECT", "TEXTAREA"].includes(tagName)) {
                    return true;
                }
                const closest = target.closest(".o_datepicker, .o_dropdown, .o-autocomplete, select, .m_pull_refresh_zone");
                return !!closest;
            };

            const shouldIgnoreHorizontalSwipe = (target, deltaX, deltaY) => {
                const scrollable = target.closest(".o_list_table, .o_content, .o_form_view, [data-scrollable]");
                if (!scrollable) {
                    return false;
                }
                const style = window.getComputedStyle(scrollable);
                const overflowX = style.overflowX;
                if (overflowX === "auto" || overflowX === "scroll" || scrollable.scrollWidth > scrollable.clientWidth) {
                    const nearLeft = scrollable.scrollLeft <= 0 && deltaX > 0;
                    const nearRight = scrollable.scrollLeft + scrollable.clientWidth >= scrollable.scrollWidth && deltaX < 0;
                    return !(nearLeft || nearRight);
                }
                return false;
            };

            const onTouchStart = (ev) => {
                const touch = ev.touches[0];
                startRef.current = { x: touch.clientX, y: touch.clientY, time: Date.now() };
            };

            const onTouchMove = (ev) => {
                const touch = ev.touches[0];
                const { x, y } = startRef.current;
                const deltaX = touch.clientX - x;
                const deltaY = touch.clientY - y;
                if (Math.abs(deltaX) > 10 && Math.abs(deltaX) > Math.abs(deltaY)) {
                    const target = ev.target;
                    if (shouldIgnoreHorizontalSwipe(target, deltaX, deltaY)) {
                        return;
                    }
                    ev.preventDefault();
                }
            };

            const onTouchEnd = (ev) => {
                const touch = ev.changedTouches[0];
                const { x, y, time } = startRef.current;
                const deltaX = touch.clientX - x;
                const deltaY = touch.clientY - y;
                const deltaTime = Date.now() - time;

                if (deltaTime > 800 || Math.abs(deltaX) < threshold) {
                    return;
                }
                if (Math.abs(deltaY) > Math.abs(deltaX) * Math.tan((angleThreshold * Math.PI) / 180)) {
                    return;
                }
                if (isInteractive(ev.target)) {
                    return;
                }

                if (deltaX < 0 && onSwipeLeft) {
                    onSwipeLeft();
                } else if (deltaX > 0 && onSwipeRight) {
                    onSwipeRight();
                }
            };

            el.addEventListener("touchstart", onTouchStart, { passive: true });
            el.addEventListener("touchmove", onTouchMove, { passive: false });
            el.addEventListener("touchend", onTouchEnd, { passive: true });

            return () => {
                el.removeEventListener("touchstart", onTouchStart);
                el.removeEventListener("touchmove", onTouchMove);
                el.removeEventListener("touchend", onTouchEnd);
            };
    };

    const getZone = () => (typeof zoneRef === "function" ? zoneRef() : zoneRef?.el) || document.body;
    let detachTouchListeners = null;
    onMounted(() => {
        detachTouchListeners = attachTouchListeners(getZone());
    });
    onWillUnmount(() => detachTouchListeners?.());
}
