import { proxy } from "@odoo/owl";
import { MobileRecord, toUIData } from "@mobile_web/views/record";

export const PAGE_SIZE = 40;

/**
 * 列表与看板共用的数据集合: 分页加载, 切换 domain 时重新加载
 *
 * state.records: MobileRecord[]   state.total: 符合条件的总数
 */
export class RecordCollection {
    /**
     * @param {import("@mobile_web/views/record_model").MobileRecordModel} model
     * @param {string[]} fieldNames
     */
    constructor(model, fieldNames) {
        this.model = model;
        this.fieldNames = fieldNames;
        this.domain = [];
        this.state = proxy({
            records: [],
            total: null,
            loading: false,
            error: null,
        });
        this.requestId = 0;
    }

    /**
     * 重新加载第一页
     */
    async reload(domain = this.domain) {
        this.domain = domain;
        const requestId = ++this.requestId;
        this.state.loading = true;
        this.state.error = null;
        try {
            const { records, length } = await this.model.searchRecords({
                domain,
                fieldNames: this.fieldNames,
                offset: 0,
                limit: PAGE_SIZE,
            });
            if (requestId !== this.requestId) {
                return;
            }
            this.state.records = records.map((raw) => this.toRecord(raw));
            this.state.total = length;
        } catch (error) {
            this.state.error = error;
        } finally {
            if (requestId === this.requestId) {
                this.state.loading = false;
            }
        }
    }

    /**
     * 追加下一页
     */
    async loadMore() {
        if (this.state.loading || this.state.records.length >= this.state.total) {
            return;
        }
        const requestId = this.requestId;
        this.state.loading = true;
        try {
            const { records } = await this.model.searchRecords({
                domain: this.domain,
                fieldNames: this.fieldNames,
                offset: this.state.records.length,
                limit: PAGE_SIZE,
            });
            if (requestId !== this.requestId) {
                return;
            }
            this.state.records = [...this.state.records, ...records.map((raw) => this.toRecord(raw))];
        } catch (error) {
            this.state.error = error;
        } finally {
            this.state.loading = false;
        }
    }

    toRecord(raw) {
        return new MobileRecord(this.model.fields, raw.id, toUIData(this.model.fields, raw, this.fieldNames));
    }
}
