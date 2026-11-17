import { onMounted, onWillUnmount, signal } from "@odoo/owl";

/**
 * 是否还有未加载的记录
 */
export function hasMoreRecords(collection) {
    const { records, total } = collection.state;
    return total !== null && records.length < total;
}

/**
 * 滚动到底部自动加载下一页(列表和看板共用)
 *
 * 模板中在末尾放 `<div t-ref="this.infinite.sentinel"/>`: 哨兵进入视口时加载下一页。
 * 每次加载完成后重新观察哨兵, 如果内容还不足一屏, 哨兵仍在视口内, 会继续加载。
 *
 * @param {import("@mobile_web/views/record_list").RecordCollection} collection
 * @returns {{sentinel: Function, recheck: () => void}} sentinel() 返回哨兵元素
 */
export function useInfiniteScroll(collection) {
    const sentinel = signal.ref();
    let observer = null;

    const recheck = () => {
        const el = sentinel();
        if (observer && el) {
            observer.unobserve(el);
            observer.observe(el);
        }
    };

    const loadNext = async () => {
        // 只在确实有下一页且没有正在加载时请求; 否则不重新观察, 避免死循环
        if (collection.state.loading || !hasMoreRecords(collection)) {
            return;
        }
        await collection.loadMore();
        recheck();
    };

    onMounted(() => {
        observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    loadNext();
                }
            },
            { rootMargin: "240px 0px" }
        );
        observer.observe(sentinel());
    });
    onWillUnmount(() => observer?.disconnect());

    return { sentinel, recheck };
}
