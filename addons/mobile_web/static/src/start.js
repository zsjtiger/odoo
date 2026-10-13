import { mountComponent } from "@web/env";
import { session } from "@web/session";
import { Component, whenReady } from "@crossnow/owl";

/**
 * 启动MobileWebClient, 与web/static/src/start.js的逻辑一致
 * 1. 初始化crossnow对象的信息
 * 2. 使用WebClient初始化env对象
 * 3. 为父类Component添加env对象，确保当前环境的所有组件都能使用env
 *
 * @param {Component} WebClient
 */
export async function startWebClient(WebClient) {
    crossnow.info = {
        db: session.db,
        server_version: session.server_version,
        server_version_info: session.server_version_info
    };

    // TODO: 手机端如果不涉及legacy，完全使用owl，是否可以去掉这个属性？
    crossnow.isReady = false;

    await whenReady();
    const app = await mountComponent(WebClient, document.body, { name: "CrossNow Mobile Web Client" });
    // env 的 属性,方法 见web/static/src/env.js
    const { env } = app;
    Component.env = env;

    // delete crossnow.debug; // FIXME: some legacy code rely on this
    crossnow.isReady = true;
}
