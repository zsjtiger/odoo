import { onMounted, onWillUnmount, proxy, signal } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";

/** 松开后触发刷新所需的下拉距离(已乘阻尼系数) */
export const PULL_THRESHOLD = 48;
/** 下拉时内容跟随手指的阻尼系数, 手感更接近原生 */
const DAMPING = 0.5;
/** 指示器最大高度, 避免下拉过长 */
const MAX_PULL = 96;

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译
export const PULL_TEXTS = {
    pull: _t("Pull to refresh"),
    release: _t("Release to refresh"),
    refreshing: _t("Refreshing…"),
};

/**
 * 下拉刷新: 页面在顶部时向下滑动, 超过阈值后松开即调用 onRefresh.
 *
 * 模板中在根元素上放 `t-ref="this.pull.container"`, 并在其中放 `PullIndicator` 的内容;
 * state.distance 为指示器高度, state.refreshing 为刷新中.
 *
 * @param {() => Promise<any>} onRefresh
 * @returns {{container: Function, state: {distance: number, refreshing: boolean}}}
 */
export function usePullToRefresh(onRefresh) {
    const container = signal.ref();
    const state = proxy({ distance: 0, refreshing: false });
    let startY = null;

    const onTouchStart = (ev) => {
        // 只有页面位于顶部时才开始下拉, 否则是普通的上滑浏览
        startY = window.scrollY <= 0 && !state.refreshing ? ev.touches[0].clientY : null;
    };
    const onTouchMove = (ev) => {
        if (startY === null) {
            return;
        }
        const dy = ev.touches[0].clientY - startY;
        state.distance = dy > 0 ? Math.min(dy * DAMPING, MAX_PULL) : 0;
    };
    const onTouchEnd = async () => {
        const pulled = state.distance >= PULL_THRESHOLD;
        startY = null;
        if (!pulled) {
            state.distance = 0;
            return;
        }
        state.refreshing = true;
        state.distance = PULL_THRESHOLD;
        try {
            await onRefresh();
        } finally {
            state.refreshing = false;
            state.distance = 0;
        }
    };

    const listeners = [
        ["touchstart", onTouchStart, { passive: true }],
        ["touchmove", onTouchMove, { passive: true }],
        ["touchend", onTouchEnd, { passive: true }],
    ];
    onMounted(() => {
        const el = container();
        for (const [type, handler, options] of listeners) {
            el.addEventListener(type, handler, options);
        }
    });
    onWillUnmount(() => {
        const el = container();
        for (const [type, handler] of listeners) {
            el?.removeEventListener(type, handler);
        }
    });

    return { container, state };
}

/**
 * 指示器的文字: 下拉中提示下拉, 超过阈值提示松开, 刷新中显示进度
 *
 * @param {{distance: number, refreshing: boolean}} state
 * @returns {string}
 */
export function pullLabel(state) {
    if (state.refreshing) {
        return PULL_TEXTS.refreshing;
    }
    return state.distance >= PULL_THRESHOLD ? PULL_TEXTS.release : PULL_TEXTS.pull;
}
