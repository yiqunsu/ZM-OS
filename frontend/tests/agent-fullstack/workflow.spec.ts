import { expect, test, type Page } from "@playwright/test";
import type { Snapshot, WorkItem } from "../../components/agent/types";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAAE0lEQVR4nGP8//8/AwwwwVnoHABvLQMDNeDq7AAAAABJRU5ErkJggg==",
  "base64",
);
type State = Omit<Snapshot, "work_items"> & {
  work_items: (WorkItem & { order_id: string | null })[];
};

async function login(page: Page, user = "owner") {
  await page.goto("/login");
  await page.getByLabel("邮箱").fill(`${user}@e2e.filmos.local`);
  await page.getByLabel("密码").fill("e2e-only-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "今天，先处理哪件事？" }),
  ).toBeVisible();
}

async function snapshot(page: Page, id: string): Promise<State> {
  const response = await page.request.get(
    `/api/agent/v2/sessions/${id}/snapshot`,
  );
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function completed(page: Page, id: string, count: number) {
  await expect
    .poll(async () => {
      const state = await snapshot(page, id);
      return !state.active_run && state.recent_run_results.length >= count;
    })
    .toBe(true);
  const state = await snapshot(page, id);
  expect(
    state.recent_run_results.every((r) => r.status === "SUCCEEDED"),
    JSON.stringify(state.recent_run_results),
  ).toBe(true);
  return state;
}

async function business(page: Page, path: string) {
  const session = await (await page.request.get("/api/auth/session")).json();
  const response = await page.request.get(`http://127.0.0.1:8131/api${path}`, {
    headers: { Authorization: `Bearer ${session.backendToken}` },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("真实登录、多图录单、刷新恢复、最新稿确认、下一张和人工排单", async ({
  page,
  browser,
}) => {
  await login(page);
  await page.getByRole("button", { name: /开始录单/ }).click();
  await expect(page.getByRole("heading", {name:"截图创建订单"})).toBeVisible();
  await page.getByRole("button",{name:"添加截图",exact:true}).click();
  const intakeId = new URL(page.url()).searchParams.get("session")!;
  await page.locator('input[type="file"]').setInputFiles([
    { name: "order-1.png", mimeType: "image/png", buffer: png },
    { name: "order-2.png", mimeType: "image/png", buffer: png },
  ]);
  const accepted = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/sessions/${intakeId}/recognize`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /识别订单/ }).click();
  await expect(page.getByLabel("消息", { exact: true })).toHaveCount(0);
  expect((await accepted).status()).toBe(202);
  await page.reload();
  let state = await completed(page, intakeId, 2);
  expect(state.work_items.map((i) => i.status)).toEqual(["ACTIVE", "PENDING"]);
  expect(state.work_items[1].recognition_status).toBe("SUCCEEDED");
  const eventPage = await (
    await page.request.get(
      `/api/agent/v2/sessions/${intakeId}/events?stream=false`,
    )
  ).json();
  expect(eventPage.events.map((event: { kind: string }) => event.kind)).toEqual(
    expect.arrayContaining([
      "recognition.completed",
      "tool.started",
      "tool.succeeded",
      "run.succeeded",
    ]),
  );
  expect(await business(page, "/orders")).toEqual([]);
  await expect(page.getByLabel("客户", { exact: true })).toHaveValue(
    "e2e-customer",
  );
  await expect(page.getByLabel("产品", { exact: true })).toHaveValue(
    "e2e-product",
  );
  await page.getByLabel("数量", { exact: true }).fill("111");
  await page.getByText("米数 · m", { exact: true }).click();
  await expect(page.getByRole("radio", { name: "米数 · m", exact: true })).toBeChecked();
  await expect(
    page.getByRole("button", { name: "确认创建订单", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "确认创建订单", exact: true }).click();
  await expect(page.getByLabel("数量", {exact:true})).toHaveValue("250");
  state = await snapshot(page, intakeId);
  expect(state.work_items.map((i) => i.status)).toEqual(["CREATED", "ACTIVE"]);
  const orders = await business(page, "/orders");
  expect(orders).toHaveLength(1);
  expect(orders[0]).toMatchObject({
    quantity: 111,
    unit: "m",
    status: "PENDING",
    task_id: null,
  });
  state = await completed(page, intakeId, 2);
  expect(state.work_items[1].recognition_status).toBe("SUCCEEDED");
  await expect(
    page.getByRole("button", { name: "确认创建订单", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "确认创建订单", exact: true }).click();
  await expect
    .poll(async () =>
      (await snapshot(page, intakeId)).work_items.map((i) => i.status),
    )
    .toEqual(["CREATED", "CREATED"]);
  expect(await business(page, "/orders")).toHaveLength(2);

  // A second real login cannot read the first user's session or attachment.
  const otherContext = await browser.newContext({
    baseURL: "http://127.0.0.1:3131",
  });
  const other = await otherContext.newPage();
  await login(other, "other");
  expect(
    (
      await other.request.get(`/api/agent/v2/sessions/${intakeId}/snapshot`)
    ).status(),
  ).toBe(404);
  expect(
    (
      await other.request.get(
        `/api/agent/v2/attachments/${state.work_items[0].source_attachment_id}/content`,
      )
    ).status(),
  ).toBe(404);
  await otherContext.close();

  await page.goto("/");
  await page.getByRole("button", { name: /开始排单/ }).click();
  await expect(page.getByRole("heading", { name: "智能排单", exact: true })).toBeVisible();
  const schedulingId = new URL(page.url()).searchParams.get("session")!;
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await page.getByRole("button", { name: "全选", exact: true }).click();
  await page.getByRole("button", { name: "开始排单", exact: true }).click();
  let schedule = await completed(page, schedulingId, 1);
  expect(schedule.session.active_plan_id).toBeTruthy();
  await expect(page.getByText("按米数 · 独立生产", { exact: true })).toHaveCount(0);
  const generatedPlan = await (await page.request.get(`/api/agent/v2/plans/${schedule.session.active_plan_id}`)).json();
  expect(generatedPlan.load_basis).toBe("TASK_COUNT");
  expect(generatedPlan.tasks.every((task: {order_ids:string[]}) => task.order_ids.length === 1)).toBe(true);
  await expect(
    page.getByRole("button", { name: "确认排单", exact: true }),
  ).toBeEnabled();
  const before = await business(page, "/orders");
  expect(
    before.every((o: { task_id: string | null }) => o.task_id === null),
  ).toBe(true);
  const discardedId = schedule.session.active_plan_id;
  await page.getByRole("button", { name: "放弃草稿", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "取消", exact: true }).click();
  expect((await snapshot(page, schedulingId)).session.active_plan_id).toBe(discardedId);
  await page.getByRole("button", { name: "放弃草稿", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "放弃草稿", exact: true }).click();
  await expect(page.getByText("草稿已放弃，订单仍在待排列表。", { exact: true })).toBeVisible();
  expect((await (await page.request.get(`/api/agent/v2/plans/${discardedId}`)).json()).status).toBe("CLOSED");
  expect((await snapshot(page, schedulingId)).session.active_plan_id).toBeNull();
  expect((await business(page, "/orders")).every((order: {task_id:string|null}) => order.task_id === null)).toBe(true);
  await page.reload();
  await expect(page.getByRole("button", { name: "确认排单", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "全选", exact: true }).click();
  await page.getByRole("button", { name: "开始排单", exact: true }).click();
  schedule = await completed(page, schedulingId, 2);
  expect(schedule.session.active_plan_id).not.toBe(discardedId);
  await expect(page.getByRole("button", { name: "确认排单", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "确认排单", exact: true }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "确认排单", exact: true }).click();
  await expect
    .poll(async () => {
      const result = await business(page, "/orders");
      return result.every(
        (o: { status: string; task_id: string | null }) =>
          o.status === "PRODUCING" && !!o.task_id,
      );
    })
    .toBe(true);
  await page.reload();
  expect(await business(page, "/orders")).toHaveLength(2);
  const plan = await page.request.get(
    `/api/agent/v2/plans/${schedule.session.active_plan_id}`,
  );
  expect((await plan.json()).status).toBe("APPLIED");
  const meterOrder = (await business(page, "/orders")).find((order: {id:string}) => order.id === orders[0].id);
  expect(meterOrder).toMatchObject({quantity:111, unit:"m", status:"PRODUCING"});

  await page.goto("/orders");
  const statusButton = page.getByRole("button", {name:`修改订单 ${meterOrder.order_no} 的状态`,exact:true});
  await expect(statusButton).toContainText("待生产");
  await statusButton.click();
  await page.getByRole("dialog", {name:"选择订单状态"}).getByRole("button", {name:"开始生产",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button", {name:"确认开始",exact:true}).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(statusButton).toContainText("生产中");
  await page.goto("/kanban");
  await page.getByRole("button",{name:"撤回",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"确认撤回",exact:true}).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await page.goto("/orders");
  await expect(statusButton).toContainText("待生产");
  await statusButton.click();
  await page.getByRole("dialog",{name:"选择订单状态"}).getByRole("button",{name:"开始生产",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"确认开始",exact:true}).click();
  await expect(statusButton).toContainText("生产中");
  await statusButton.click();
  await page.getByRole("dialog", {name:"选择订单状态"}).getByRole("button", {name:"已完成",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button", {name:"确认完成",exact:true}).click();
  await expect(statusButton).toContainText("已完成");
  await page.reload();
  await statusButton.click();
  await page.getByRole("dialog", {name:"选择订单状态"}).getByRole("button", {name:"恢复生产中",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button", {name:"确认恢复",exact:true}).click();
  await expect(statusButton).toContainText("生产中");
  const restored = (await business(page,"/orders")).find((order: {id:string})=>order.id===meterOrder.id);
  expect(restored.task.status).toBe("PRODUCING");
  expect(restored.task_id).toBe(meterOrder.task_id);
  expect(restored.unit).toBe("m");

  await page.goto("/");
  await page.getByRole("button", { name: /开始排单/ }).click();
  await expect(page.getByText("当前没有待排单的订单", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始排单", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "确认排单", exact: true })).toHaveCount(0);

});

test("旧历史入口和旧接口已移除", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("link", { name: /旧版历史/ })).toHaveCount(0);
  expect((await page.request.get("/agent-history")).status()).toBe(404);
  expect(
    (await page.request.get("/api/agent/v2/history/sessions")).status(),
  ).toBe(404);
  const session = await (await page.request.get("/api/auth/session")).json();
  const oldWrite = await page.request.post(
    "http://127.0.0.1:8131/api/agent/sessions",
    {
      headers: { Authorization: `Bearer ${session.backendToken}` },
      data: {},
    },
  );
  expect(oldWrite.status()).toBe(404);
});

test("一张截图两份草稿，分别确认且下一单不重复识别", async ({ page }, info) => {
  await login(page);
  const before = (await business(page, "/orders")).length;
  await page.getByRole("button", { name: /开始录单/ }).click();
  await expect(page.getByRole("heading", {name:"截图创建订单"})).toBeVisible();
  await page.getByRole("button",{name:"添加截图",exact:true}).click();
  const sid = new URL(page.url()).searchParams.get("session")!;
  const previous = await snapshot(page, sid);
  await page.locator('input[type="file"]').setInputFiles({
    name: "two-orders.png",
    mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC", "base64"),
  });
  await expect(
    page.getByAltText("待发送截图 1", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /识别订单/ }).click();
  let state = await completed(page, sid, previous.recent_run_results.length + 1);
  const newItems = state.work_items.filter(i => !previous.work_items.some(old => old.id === i.id));
  expect(newItems).toHaveLength(2);
  expect(newItems.map((i) => i.source_order_index)).toEqual([1, 2]);
  expect(newItems.map((i) => i.recognition_status)).toEqual([
    "SUCCEEDED",
    "SUCCEEDED",
  ]);
  await expect(
    page.getByRole("button", {name: new RegExp(`第 ${newItems[0].source_day_position} 张截图.*2 笔订单`)}),
  ).toBeVisible();
  await expect(page.getByLabel("数量", { exact: true })).toHaveValue("250");
  await expect(page.getByLabel("宽幅", { exact: true })).toHaveValue("425");
  await expect(page.getByLabel("厚度", { exact: true })).toHaveValue("118");
  expect(newItems[0].issues.filter((i) => i.code === "UNIT_INFERRED")).toHaveLength(2);
  await expect(page.getByRole("button", { name: /：核对单位$/ })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "确认创建订单", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "确认创建订单", exact: true }).click();
  await expect
    .poll(async () => (await business(page, "/orders")).length)
    .toBe(before + 1);
  await expect(
    page.getByRole("heading", { name: "核对订单 2", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("数量", { exact: true })).toHaveValue("600");
  await page.reload();
  await expect(page.getByLabel("数量", { exact: true })).toHaveValue("600");
  state = await snapshot(page, sid);
  expect(state.recent_run_results).toHaveLength(previous.recent_run_results.length + 1);
  expect(state.active_run).toBeNull();
  await page.getByRole("button",{name:/^已下发/}).click();
  await page.locator(".screenshot-group").filter({hasText:`第 ${newItems[0].source_day_position} 张截图`}).getByRole("button",{name:/联调客户-透明膜.*已下发/}).click();
  await expect(
    page.getByRole("link", { name: "查看正式订单", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("数量", { exact: true })).toHaveValue("250");
  await page.getByRole("button",{name:/^待处理/}).click();
  await page.getByRole("button",{name:/联调客户-透明膜.*待处理/}).click();
  await expect(page.getByLabel("数量", { exact: true })).toHaveValue("600");
  await page.screenshot({ path: info.outputPath("multi-order-workspace.png") });
  await page.getByRole("button", { name: "确认创建订单", exact: true }).click();
  await expect
    .poll(async () => (await business(page, "/orders")).length)
    .toBe(before + 2);
});

test("统一入口复用工作区，整图归档刷新保留并可恢复，正式订单不受影响", async ({page}) => {
  await login(page);
  const before = (await business(page,"/orders")).length;
  await page.getByRole("button",{name:/开始录单/}).click();
  await expect(page.getByRole("heading",{name:"截图创建订单"})).toBeVisible();
  const sid = new URL(page.url()).searchParams.get("session")!;
  await page.getByRole("button",{name:/^已下发/}).click();
  const group = page.locator(".screenshot-group").first();
  await expect(group).toBeVisible();
  const initialGroups = await page.locator(".screenshot-group").count();
  await group.getByRole("button",{name:/^归档 /}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"归档截图",exact:true}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(initialGroups - 1);
  await page.reload();
  await page.getByRole("button",{name:/已归档/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(1);
  await page.locator(".intake-item").first().click();
  await expect(page.getByRole("link",{name:"查看正式订单"})).toBeVisible();
  await expect(page.getByRole("button",{name:"确认创建订单",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:/^恢复 .*张截图/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(0);
  await page.getByRole("button",{name:/^已下发/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(initialGroups);
  expect((await business(page,"/orders")).length).toBe(before);
  await page.goto("/");
  await page.getByRole("button",{name:/开始录单/}).click();
  await expect(page).toHaveURL(new RegExp(`session=${sid}`));
});
