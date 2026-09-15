import { createServer } from "node:http";
import { expect, test, type Page } from "@playwright/test";
import { screenshotGroups } from "../../components/agent/screenshotGroups";
import type { WorkItem, Snapshot } from "../../components/agent/types";
import { encode } from "next-auth/jwt";

const item = {
  id: "item-1",
  source_attachment_id: "image-1",
  queue_position: 1,
  status: "ACTIVE",
  revision: 1,
  recognition_status: "SUCCEEDED",
  issues: [],
  draft: {
    customer_id: "c1",
    product_id: "p1",
    spec_params: { 宽幅: "425mm", 厚度: "118μm" },
    quantity: "50",
    unit: "kg",
    formula_mode: "none",
    formula_id: null,
    extra_notes: "原备注",
  },
};
function initial(type = "ORDER_INTAKE") {
  return {
    session: {
      id: "session-1",
      title: "测试会话",
      agent_type: type,
      status: "ACTIVE",
      state_revision: 1,
      active_work_item_id: type === "ORDER_INTAKE" ? item.id : null,
      active_plan_id: type === "SCHEDULING" ? "plan-1" : null,
    },
    event_cursor: 10,
    messages: [],
    active_run: null,
    recent_run_results: [],
    work_items: type === "ORDER_INTAKE" ? [structuredClone(item)] : [],
    active_work_item: null,
    next_work_item: null,
  };
}
async function common(page: Page, realEvents = false, role = "OWNER") {
  let latest: Promise<Snapshot> = Promise.resolve(initial() as Snapshot);
  page.on("response", response => {
    if (response.url().includes("/snapshot") && response.ok()) latest = response.json();
  });
  await page.route("**/intake/screenshots?*", async route => {
    const snap = await latest;
    const tab = new URL(route.request().url()).searchParams.get("tab");
    const rows = snap.work_items.map(i => ({...i, session_id: i.session_id ?? snap.session.id,
      source_archived: i.source_archived ?? snap.session.status === "ARCHIVED"}));
    const counts: Record<string, number> = {};
    for (const row of rows) if(row.status !== "CLOSED") {
      const key = row.source_archived ? "ARCHIVED" : row.status;
      counts[key] = (counts[key] ?? 0) + 1;
    }
    const groups = screenshotGroups(rows).filter(g => g.items.some(i =>
      tab === "archived" ? i.source_archived : !i.source_archived && (tab === "created" ? i.status === "CREATED" : i.status !== "CREATED")));
    await route.fulfill({json:{screenshots:groups.map(g=>({
      id:g.id, source_day:g.day, source_uploaded_at:g.uploadedAt, source_day_position:g.position,
      source_archived:g.items[0].source_archived, screenshot_revision:g.items[0].screenshot_revision ?? 0,
      busy:!!snap.active_run, running_item_id:snap.active_run?.work_item_id, items:g.items,
    })), counts, next_cursor:null}});
  });

  const cookieName = "authjs.session-token";
  const token = await encode({
    secret: "filmos-e2e-secret-local-tests-only",
    salt: cookieName,
    token: {
      uid: "e2e-user",
      email: "test@example.invalid",
      role,
      backendToken: "e2e-placeholder",
    },
  });
  await page.context().addCookies([
    {
      name: cookieName,
      value: token,
      url: "http://127.0.0.1:3101",
      httpOnly: true,
    },
  ]);
  if (!realEvents)
    await page.addInitScript(() => {
      class MockEventSource extends EventTarget {
        onopen: (() => void) | null = null;
        onerror = null;
        constructor() {
          super();
          Object.assign(window, { agentTestEvents: this });
          setTimeout(() => this.onopen?.(), 10);
        }
        close() {}
      }
      Object.defineProperty(window, "EventSource", { value: MockEventSource });
    });
  await page.route("**/api/customers", (r) =>
    r.fulfill({ json: [{ id: "c1", company: "示例工厂" }] }),
  );
  await page.route("**/api/products", (r) =>
    r.fulfill({ json: [{ id: "p1", name: "透明膜" }] }),
  );
  await page.route("**/api/product-categories", (r) =>
    r.fulfill({ json: [{ id: "cat1", name: "薄膜" }] }),
  );
  await page.route("**/api/formulas", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/kanban", (r) =>
    r.fulfill({
      json: {
        pending_orders: [],
        machines: [
          {
            id: "m1",
            name: "1号机",
            is_active: true,
            tasks: [],
            categories: [],
          },
        ],
      },
    }),
  );
  await page.route("**/api/machines", (r) =>
    r.fulfill({
      json: [
        { id: "m1", name: "1号机" },
        { id: "m2", name: "2号机" },
      ],
    }),
  );
  await page.route("**/api/agent/v2/attachments/*/content", (r) =>
    r.fulfill({
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=",
        "base64",
      ),
    }),
  );
  await page.route("**/api/agent/v2/sessions", (r) =>
    r.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route("**/api/agent/v2/sessions?limit=50", (r) =>
    r.fulfill({ json: { items: [], next_cursor: null } }),
  );
}

test.beforeEach(async ({ page }, testInfo) => {
  await common(page, testInfo.title.includes("SSE"));
});

test("SSE 重复事件不重复显示，重连携带游标，刷新恢复最终消息", async ({
  page,
}) => {
  const snapshot = initial("SCHEDULING");
  snapshot.session.active_plan_id = null;
  Object.assign(snapshot, { active_run: { id: "run-1", status: "RUNNING" } });
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: snapshot }),
  );
  const received: { cursor: string | undefined; url: string }[] = [];
  // A real HTTP stream also exercises the Next.js authenticated streaming proxy.
  const server = createServer((request, response) => {
    received.push({
      cursor: request.headers["last-event-id"] as string | undefined,
      url: request.url ?? "",
    });
    if (received.length > 1) {
      response.writeHead(204);
      response.end();
      return;
    }
    const events = [
      {
        seq: 11,
        kind: "assistant.delta",
        run_id: "run-1",
        payload: { text: "临时片段" },
      },
      {
        seq: 11,
        kind: "assistant.delta",
        run_id: "run-1",
        payload: { text: "临时片段" },
      },
      { seq: 12, kind: "message.completed", run_id: "run-1", payload: {} },
      { seq: 13, kind: "run.succeeded", run_id: "run-1", payload: {} },
    ];
    Object.assign(snapshot, {
      event_cursor: 13,
      active_run: null,
      messages: [
        {
          id: "final-1",
          run_id: "run-1",
          role: "assistant",
          content: "当前没有待排订单。",
          event_seq: 12,
          attachments: [],
        },
      ],
    });
    response.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
    });
    response.write(
      events
        .map(
          (e) =>
            `id: ${e.seq}\nevent: ${e.kind}\ndata: ${JSON.stringify(e)}\n\n`,
        )
        .join(""),
    );
    setTimeout(() => response.end(), 100);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(8102, "127.0.0.1", resolve);
  });
  try {
    await page.goto("/?session=session-1");
    await expect(
      page.getByText("当前没有待排订单。", { exact: true }),
    ).toHaveCount(1);
    await expect(page.getByText("临时片段", { exact: true })).toHaveCount(0);
    await expect.poll(() => received.length, { timeout: 10000 }).toBe(2);
    expect(received[1].cursor).toBe("13");
    await page.reload();
    await expect(
      page.getByText("当前没有待排订单。", { exact: true }),
    ).toHaveCount(1);
    await expect.poll(() => received.length).toBe(3);
    expect(
      new URL(received[2].url, "http://localhost").searchParams.get("after"),
    ).toBe("13");
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("会话代理返回 JSON 身份错误并拒绝跨站写请求", async ({
  page,
  playwright,
}) => {
  const anonymous = await playwright.request.newContext({
    baseURL: "http://127.0.0.1:3101",
  });
  const unauthenticated = await anonymous.get("/api/agent/v2/sessions");
  expect(unauthenticated.status()).toBe(401);
  expect((await unauthenticated.json()).error.code).toBe("AUTH_REQUIRED");
  await anonymous.dispose();
  const crossSite = await page.request.post("/api/agent/v2/sessions", {
    headers: { Origin: "https://untrusted.example" },
    data: { agent_type: "ORDER_INTAKE" },
  });
  expect(crossSite.status()).toBe(403);
  expect((await crossSite.json()).error.code).toBe("ORIGIN_REJECTED");
});

test("两个入口创建固定类型的会话；排单会话不开放图片", async ({ page }) => {
  const snapshot = initial("SCHEDULING");
  snapshot.session.active_plan_id = null;
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: snapshot }),
  );
  let calls = 0;
  await page.route("**/api/agent/v2/scheduling/workspace", async (r) => {
    if (r.request().method() === "POST") {
      calls++;
      expect(r.request().postDataJSON()).toEqual({});
      expect(r.request().headers()["idempotency-key"]).toBeTruthy();
      await r.fulfill({ status: 201, json: { session: snapshot.session } });
    } else await r.fulfill({ json: { items: [], next_cursor: null } });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "创建订单", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/agent-home.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /开始排单/ }).click();
  await expect(page.getByRole("heading", { name: "智能排单", exact: true })).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  expect(calls).toBe(1);
  await page.goto("/kanban");
  await expect(page.getByRole("link", { name: "新建订单", exact: true })).toHaveCount(0);
  const scheduling = page.getByRole("button", { name: "智能排单", exact: true });
  await expect(scheduling).toHaveCount(1);
  await expect(scheduling).toBeInViewport();
  await page.screenshot({path:"test-results/kanban-scheduling-entry.png"});
  await scheduling.click();
  await expect(page.getByRole("heading", { name: "智能排单", exact: true })).toBeVisible();
  expect(calls).toBe(2);
});

test("草稿发生冲突时保留本地编辑，禁止直接创建", async ({ page }) => {
  const snapshot = initial();
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: snapshot }),
  );
  await page.route("**/items/item-1/draft", async (r) => {
    expect(r.request().postDataJSON().expected_revision).toBe(1);
    snapshot.work_items[0].revision = 2;
    snapshot.work_items[0].draft.extra_notes = "后台新版本";
    snapshot.event_cursor++;
    await r.fulfill({
      status: 409,
      json: {
        error: {
          code: "DRAFT_REVISION_CONFLICT",
          message: "草稿已更新，请刷新",
        },
      },
    });
  });
  await page.goto("/?session=session-1");
  await page
    .getByRole("textbox", { name: "备注", exact: true })
    .fill("本地未保存备注");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(
    page.getByRole("region", { name: "订单核对工作区" }).getByRole("alert"),
  ).toContainText("草稿已更新");
  await expect(
    page.getByRole("textbox", { name: "备注", exact: true }),
  ).toHaveValue("本地未保存备注");
  await expect(
    page.getByRole("button", { name: "加载最新草稿" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "确认创建订单" })).toBeDisabled();
  await page.screenshot({
    path: "test-results/order-draft.png",
    fullPage: true,
  });
});

test("确认创建后自动显示下一笔，不需要再次点击继续", async ({ page }) => {
  const snap = initial();
  const second = { ...structuredClone(item), id:"item-2", source_order_index:2, status:"PENDING", draft:{...item.draft, quantity:"600"} };
  snap.work_items.push(second);
  await page.route("**/sessions/session-1/snapshot", r => r.fulfill({json:snap}));
  await page.route("**/items/item-1/confirm", r => {
    expect(r.request().postDataJSON()).toEqual({expected_revision:1, advance:true});
    snap.work_items[0].status="CREATED"; second.status="ACTIVE";
    snap.session.active_work_item_id=second.id; snap.event_cursor++;
    return r.fulfill({json:{order:{order_no:"TEST-001"}}});
  });
  await page.goto("/?session=session-1");
  await page.getByRole("button", {name:"确认创建订单",exact:true}).click();
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("600");
  await expect(page.getByRole("status").filter({hasText:"订单 TEST-001 创建成功"})).toBeVisible();
  await expect(page.getByRole("button",{name:"处理下一单",exact:true})).toHaveCount(0);
});

test("手机切换原图与表单保留编辑，保存失败阻止离开", async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.route("**/sessions/session-1/snapshot", r => r.fulfill({json:initial()}));
  await page.route("**/items/item-1/draft", r => r.fulfill({status:503,json:{error:{message:"暂时无法保存"}}}));
  await page.goto("/?session=session-1");
  await page.getByLabel("数量",{exact:true}).fill("123");
  await page.getByRole("button",{name:"原始截图",exact:true}).click();
  await page.getByRole("button",{name:"订单表单",exact:true}).click();
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("123");
  await page.getByRole("button",{name:"返回助手首页",exact:true}).click();
  await expect(page.getByRole("alert").filter({hasText:"暂时无法保存"})).toBeVisible();
  await expect(page).toHaveURL(/session=session-1/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:"test-results/agent-mobile-workspace.png"});
});

test("首页仅保留服务入口，打开失败可重试且不加载会话列表", async ({ page }) => {
  let listCalls = 0;
  let attempts = 0;
  const snapshot = initial("SCHEDULING");
  snapshot.session.active_plan_id = null;
  await page.route("**/api/agent/v2/sessions", (route) => {
    listCalls++;
    return route.fulfill({ status: 503, json: {} });
  });
  await page.route("**/sessions/session-1/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/agent/v2/scheduling/workspace", (route) => {
    attempts++;
    return attempts === 1
      ? route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "排单服务暂不可用" } },
        })
      : route.fulfill({ json: { session: snapshot.session } });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: /开始录单/ })).toBeVisible();
  await expect(page.getByText("最近排单", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "加载更多会话" })).toHaveCount(0);
  const entry = page.getByRole("button", { name: /开始排单/ });
  await entry.click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("排单服务暂不可用");
  await entry.click();
  await expect(page).toHaveURL(/session=session-1/);
  await expect(page.getByRole("heading", { name: "智能排单", exact: true })).toBeVisible();
  expect(attempts).toBe(2);
  expect(listCalls).toBe(0);
});

test("待发送截图显示缩略图，支持放大与移除", async ({ page }, info) => {
  await common(page);
  await page.route("**/api/agent/v2/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: initial() }),
  );
  await page.goto("/?session=session-1");
  await page.getByRole("button", { name: "添加截图", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "订单.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  const preview = page.getByAltText("待发送截图 1", { exact: true });
  await expect(preview).toBeVisible();
  await expect
    .poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(1);
  await page
    .getByRole("button", { name: "放大待发送截图 1", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByAltText("待发送截图 1大图")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.screenshot({ path: info.outputPath("upload-preview.png") });
  await page.getByRole("button", { name: "移除截图 1" }).click();
  await expect(preview).toHaveCount(0);
});

test("同图订单列表默认展开，切换先保存，失败保留字段", async ({page}) => {
  const snap=initial();
  const second={...structuredClone(item),id:"item-2",source_order_index:2,status:"PENDING",draft:{...item.draft,quantity:"600"}};
  snap.work_items.push(second);
  let saves=0, switches=0;
  await page.route("**/sessions/session-1/snapshot", r=>r.fulfill({json:snap}));
  await page.route("**/items/item-1/draft", r=>{
    saves++; if(saves===1)return r.fulfill({status:503,json:{error:{message:"保存失败"}}});
    snap.work_items[0].draft=r.request().postDataJSON().patch; snap.work_items[0].revision++;
    return r.fulfill({json:snap.work_items[0]});
  });
  await page.route("**/items/item-2/select", r=>{
    switches++; snap.work_items[0].status="DEFERRED"; second.status="ACTIVE";
    snap.session.active_work_item_id=second.id; snap.event_cursor++;
    return r.fulfill({json:{run_id:null}});
  });
  await page.goto("/?session=session-1");
  const next=page.getByRole("region",{name:"订单列表",exact:true}).getByRole("button",{name:/第 2 笔/});
  await expect(next).toBeVisible();
  await page.getByLabel("数量",{exact:true}).fill("123");
  await next.click(); await expect(page.getByRole("alert").filter({hasText:"保存失败"})).toBeVisible();
  expect(switches).toBe(0); await expect(page.getByLabel("数量",{exact:true})).toHaveValue("123");
  await next.click(); await expect(page.getByLabel("数量",{exact:true})).toHaveValue("600");
  expect(switches).toBe(1); expect(snap.work_items[0].draft.quantity).toBe("123");
});

for (const mode of ["page", "agent"] as const) {
  test(`${mode} 复用创建订单表单，规格和单位提交一致`, async ({
    page,
  }, info) => {
    const snap = initial();
    await page.route("**/sessions/session-1/snapshot", (r) =>
      r.fulfill({ json: snap }),
    );
    const writes: Record<string, unknown>[] = [];
    await page.route("**/api/orders/from-draft", (r) => {
      writes.push(r.request().postDataJSON());
      return r.fulfill({ json: { id: "order-new", order_no: "TEST-001" } });
    });
    let saves = 0;
    await page.route("**/items/item-1/draft", (r) => {
      const body = r.request().postDataJSON();
      expect(body.expected_revision).toBe(1);
      saves++;
      if (saves === 1)
        return r.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "暂时无法保存" } },
        });
      Object.assign(snap.work_items[0].draft, body.patch);
      snap.work_items[0].revision = 2;
      return r.fulfill({ json: snap.work_items[0] });
    });
    let confirmed = false;
    await page.route("**/items/item-1/confirm", (r) => {
      expect(r.request().postDataJSON().expected_revision).toBe(2);
      confirmed = true;
      return r.fulfill({ json: {} });
    });
    await page.goto(mode === "page" ? "/orders/new" : "/?session=session-1");
    for (const name of ["基本信息", "规格参数", "配方", "额外要求"]) {
      await expect(
        page.getByRole("heading", { name, exact: true }),
      ).toBeVisible();
    }
    await expect(
      page.getByRole("button", { name: "新建客户", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "新建产品", exact: true }),
    ).toBeVisible();
    await page.getByLabel("客户", { exact: true }).selectOption("c1");
    await page.getByLabel("产品", { exact: true }).selectOption("p1");
    await page.getByLabel("宽幅", { exact: true }).fill("500");
    await page.getByLabel("厚度", { exact: true }).fill("80");
    await page.getByLabel("数量", { exact: true }).fill("125");
    await page.getByText("米数 · m", { exact: true }).click();
    await expect(page.getByRole("radio", { name: "米数 · m" })).toBeChecked();
    await expect(page.getByLabel("数量", { exact: true })).toHaveValue("125");
    await page.getByText("重量 · kg", { exact: true }).click();
    await expect(page.getByRole("radio", { name: "重量 · kg" })).toBeChecked();
    await page.getByText("其他规格（如花纹）").click();
    await page.getByRole("button", { name: "添加规格参数" }).click();
    await page.getByPlaceholder("参数名（如：厚度）").fill("花纹");
    await page.getByPlaceholder("数值（如：50μm）").fill("平纹");
    await page.getByLabel("备注", { exact: true }).fill("统一表单核对");
    if (mode === "agent") {
      await page.getByRole("button", { name: "保存草稿", exact: true }).click();
      await expect(
        page.getByRole("region", { name: "订单核对工作区" }).getByRole("alert"),
      ).toContainText("暂时无法保存");
      await expect(page.getByLabel("宽幅", { exact: true })).toHaveValue("500");
      await page.getByRole("button", { name: "保存草稿", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "确认创建订单", exact: true }),
      ).toBeEnabled();
      expect(snap.work_items[0].draft).toMatchObject({
        quantity: "125",
        unit: "kg",
        spec_params: { 宽幅: "500mm", 厚度: "80μm", 花纹: "平纹" },
      });
      for (const viewport of [
        { width: 1366, height: 768 },
        { width: 1440, height: 900 },
      ]) {
        await page.setViewportSize(viewport);
        await expect(
          page.getByRole("heading", { name: "基本信息" }),
        ).toBeInViewport({ ratio: 1 });
        await expect(
          page.getByRole("button", { name: "确认创建订单", exact: true }),
        ).toBeInViewport({ ratio: 1 });
        const workspace = page.getByRole("complementary", {
          name: "工作区",
          exact: true,
        });
        await expect
          .poll(() =>
            workspace.evaluate((el) => el.scrollHeight - el.clientHeight),
          )
          .toBeLessThanOrEqual(1);
        await page.screenshot({
          path: info.outputPath(`compact-order-${viewport.width}.png`),
        });
      }
    }
    await page.getByRole("button", { name: mode === "page" ? "创建订单" : "确认创建订单", exact: true }).click();
    if (mode === "page") {
      await expect.poll(() => writes.length).toBe(1);
      expect(writes[0]).toMatchObject({
        customer_id: "c1",
        product_id: "p1",
        quantity: "125",
        unit: "kg",
        spec_params: { 宽幅: "500mm", 厚度: "80μm", 花纹: "平纹" },
      });
    } else {
      await expect.poll(() => confirmed).toBe(true);
      expect(writes).toHaveLength(0);
    }
  });
}

test("共享表单加载失败可以重试，未识别数量单位必须由用户选择", async ({
  page,
}) => {
  const snap = initial();
  const draft = { ...snap.work_items[0].draft, unit: null };
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({
      json: { ...snap, work_items: [{ ...snap.work_items[0], draft }] },
    }),
  );
  let attempts = 0;
  await page.route("**/api/product-categories", (r) =>
    ++attempts === 1
      ? r.fulfill({ status: 503, json: { detail: "加载失败" } })
      : r.fulfill({ json: [] }),
  );
  await page.goto("/?session=session-1");
  await expect(
    page.getByRole("button", { name: "确认创建订单", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "重试加载", exact: true }).click();
  await expect(page.getByLabel("数量", { exact: true })).toBeEnabled();
  await expect(
    page.getByRole("radio", { name: "重量 · kg" }),
  ).not.toBeChecked();
  await expect(page.getByRole("radio", { name: "米数 · m" })).not.toBeChecked();
});

test("共享表单手工维护客户产品，失败保留输入，配方选择不覆盖截图规格", async ({
  page,
}) => {
  const snap = initial();
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: snap }),
  );
  let customerAttempts = 0;
  await page.route("**/api/customers", (r) => {
    if (r.request().method() === "GET")
      return r.fulfill({ json: [{ id: "c1", company: "示例工厂" }] });
    customerAttempts++;
    expect(r.request().postDataJSON()).toEqual({
      company: "新工厂",
      contact: "张三",
    });
    if (customerAttempts === 1)
      return r.fulfill({ status: 503, json: { detail: "暂时无法创建" } });
    return r.fulfill({
      json: { id: "c2", company: "新工厂", contact: "张三" },
    });
  });
  await page.route("**/api/products", (r) =>
    r.request().method() === "GET"
      ? r.fulfill({
          json: [
            {
              id: "p1",
              name: "透明膜",
              category_id: "cat1",
              category: { id: "cat1", name: "薄膜" },
            },
          ],
        })
      : r.fulfill({
          json: {
            id: "p2",
            name: "新薄膜",
            category_id: "cat1",
            category: { id: "cat1", name: "薄膜" },
          },
        }),
  );
  await page.route("**/api/formulas", (r) =>
    r.fulfill({
      json: [
        {
          id: "f2",
          name: "配方二",
          product_id: "p2",
          spec_params: { 宽幅: "900mm", 厚度: "30μm" },
          materials: "材料说明",
        },
      ],
    }),
  );
  await page.goto("/?session=session-1");
  await page.getByRole("button", { name: "新建客户", exact: true }).click();
  await page.getByPlaceholder("如：华兴包装").fill("新工厂");
  await page.getByPlaceholder("如：张三").fill("张三");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "创建", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("暂时无法创建");
  await expect(page.getByPlaceholder("如：华兴包装")).toHaveValue("新工厂");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "创建", exact: true })
    .click();
  await expect(page.getByLabel("客户", { exact: true })).toHaveValue("c2");
  await page.getByRole("button", { name: "新建产品", exact: true }).click();
  await page.getByPlaceholder("如：透明 PE 拉伸膜").fill("新薄膜");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "创建", exact: true })
    .click();
  await expect(page.getByLabel("产品", { exact: true })).toHaveValue("p2");
  await page.getByRole("radio", { name: "选择已有配方", exact: true }).check();
  await page.getByLabel("配方", { exact: true }).selectOption("f2");
  await expect(page.getByLabel("宽幅", { exact: true })).toHaveValue("425");
  await expect(page.getByLabel("厚度", { exact: true })).toHaveValue("118");
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(
    page.getByRole("button", { name: "确认创建订单", exact: true }),
  ).toBeInViewport({ ratio: 1 });
  await expect
    .poll(() =>
      page
        .getByRole("complementary", { name: "工作区", exact: true })
        .evaluate((el) => el.scrollHeight - el.clientHeight),
    )
    .toBeLessThanOrEqual(1);

  await expect(
    page.getByRole("radio", { name: "新建配方", exact: true }),
  ).toHaveCount(0);
});

test("OPERATOR 在两个表单入口均不显示基础数据新增按钮", async ({ page }) => {
  await common(page, false, "OPERATOR");
  await page.route("**/sessions/session-1/snapshot", (r) =>
    r.fulfill({ json: initial() }),
  );
  for (const url of ["/orders/new", "/?session=session-1"]) {
    await page.goto(url);
    await expect(page.getByLabel("客户", { exact: true })).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "新建客户", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "新建产品", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("radio", { name: "新建配方", exact: true }),
    ).toHaveCount(0);
  }
});

test("多图上传中断后保留已上传附件，并使用原上传标识重试", async ({ page }) => {
  await page.route("**/sessions/session-1/snapshot", (r) => r.fulfill({ json: initial() }));
  const uploadIds: string[] = [];
  let sent = false;
  await page.route("**/sessions/session-1/attachments", async (route) => {
    const body = route.request().postDataBuffer()!.toString();
    const id = body.match(/name="client_upload_id"\r\n\r\n([^\r\n]+)/)![1];
    uploadIds.push(id);
    if (uploadIds.length === 2) await route.abort("failed");
    else await route.fulfill({ json: { id: uploadIds.length === 1 ? "a1" : "a2" } });
  });
  await page.route("**/sessions/session-1/recognize", async (route) => {
    expect(route.request().postDataJSON().attachment_ids).toEqual(["a1", "a2"]);
    sent = true;
    await route.fulfill({ status: 202, json: { run_id: "upload-run" } });
  });
  await page.goto("/?session=session-1");
  await page.getByRole("button", { name: "添加截图", exact: true }).click();
  const buffer = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII=",
    "base64",
  );
  await page.locator('input[type="file"]').setInputFiles([
    { name: "订单1.png", mimeType: "image/png", buffer },
    { name: "订单2.png", mimeType: "image/png", buffer },
  ]);
  await page.getByRole("button", { name: /识别订单/ }).click();
  await expect(page.getByRole("button", { name: "重试识别" })).toBeVisible();
  await expect(page.getByRole("button", { name: "移除截图 1" })).toBeDisabled();
  await page.getByRole("button", { name: "重试识别" }).click();
  await expect.poll(() => sent).toBe(true);
  expect(uploadIds).toHaveLength(3);
  expect(uploadIds[2]).toBe(uploadIds[1]);
  expect(uploadIds[0]).not.toBe(uploadIds[1]);
  await expect(page.getByAltText("待发送截图 1", { exact: true })).toHaveCount(0);
});

test("统一截图工作台桌面布局，无录入记录层且截图放大不离开页面", async ({ page }) => {
  const snap = initial();
  Object.assign(snap.work_items[0], {
    customer_name: "瑞豪包装", product_name: "透明膜", created_at: "2026-09-13T08:00:00+08:00", source_order_index: 1,
  });
  snap.work_items[0].draft.quantity = "7500";
  snap.work_items[0].draft.unit = "m";
  snap.work_items[0].draft.extra_notes = "加急，数量包含损耗，不要多做";
  snap.work_items.push({...structuredClone(snap.work_items[0]),id:"item-2",status:"PENDING",source_order_index:2,draft:{...snap.work_items[0].draft,quantity:"10000"}} as typeof item);
  snap.work_items.push({...structuredClone(snap.work_items[0]),id:"item-3",status:"PENDING",source_attachment_id:"image-2",queue_position:2} as typeof item);
  await page.route("**/api/customers", r => r.fulfill({json:[{id:"c1",company:"瑞豪包装"}]}));
  await page.route("**/sessions/session-1/snapshot", r => r.fulfill({json:snap}));
  await page.route("**/sessions?agent_type=ORDER_INTAKE&limit=30", r => r.fulfill({json:{items:[{...snap.session,created_at:"2026-09-13T08:00:00+08:00",image_count:2,order_count:3}],next_cursor:null}}));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="340" height="610" viewBox="0 0 340 610">
    <rect width="340" height="610" fill="#ededed"/><rect width="340" height="65" fill="#f5f5f5"/>
    <g font-family="PingFang SC,Arial,sans-serif" fill="#252525"><text x="18" y="25" font-size="13">14:59</text><text x="290" y="25" font-size="12">▰</text><text x="170" y="52" text-anchor="middle" font-size="17">瑞豪订单群</text>
    <text x="125" y="98" font-size="12" fill="#999">今天 14:59</text>
    <rect x="14" y="125" width="36" height="36" rx="6" fill="#d7c2a8"/><text x="22" y="150" font-size="17" fill="#68503a">瑞</text><text x="65" y="122" fill="#888" font-size="12">瑞豪 · 跟单</text>
    <rect x="62" y="133" width="253" height="155" rx="7" fill="white"/>
    <text x="75" y="161" font-size="17"><tspan x="75">透明膜 42.5cm × 11.8丝</tspan><tspan x="75" dy="29">7500 米，不要多做</tspan><tspan x="75" dy="29">数量包含损耗</tspan><tspan x="75" dy="29">单号：RH-0913-01</tspan><tspan x="75" dy="29">单价 9.8</tspan></text>
    <rect x="14" y="305" width="36" height="36" rx="6" fill="#d7c2a8"/><text x="22" y="330" font-size="17" fill="#68503a">瑞</text>
    <rect x="62" y="305" width="253" height="126" rx="7" fill="white"/>
    <text x="75" y="332" font-size="17"><tspan x="75">透明膜 60.5cm × 11.8丝</tspan><tspan x="75" dy="29">10000 米，包含损耗</tspan><tspan x="75" dy="29">单号：RH-0913-02</tspan><tspan x="75" dy="29">单价 9.8</tspan></text>
    <rect x="62" y="450" width="137" height="45" rx="7" fill="white"/><text x="76" y="479" font-size="17">两笔都加急</text>
    <rect x="203" y="520" width="107" height="43" rx="7" fill="#a9e77d"/><text x="220" y="548" font-size="17">好的，收到</text>
    <text x="170" y="593" text-anchor="middle" font-size="11" fill="#999">演示截图 · 非真实客户订单</text></g></svg>`;
  await page.route("**/attachments/*/content",r=>r.fulfill({contentType:"image/svg+xml",body:svg}));
  await page.goto("/?session=session-1");
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("7500");
  await expect(page.getByText("我的会话",{exact:true})).toHaveCount(0);
  await expect(page.getByLabel("消息",{exact:true})).toHaveCount(0);
  await page.addStyleTag({content:"nextjs-portal { display: none; }"});
  for (const [width,height] of [[1440,900],[1366,768]]) {
    await page.setViewportSize({width,height});
    const form=page.getByRole("complementary",{name:"工作区",exact:true});
    expect(await form.evaluate(e => e.scrollHeight <= e.clientHeight + 2)).toBe(true);
    await expect(page.getByRole("button",{name:"确认创建订单",exact:true})).toBeInViewport();
    await page.screenshot({path:`../.data/previews/order-workbench-${width}.png`});
  }
  await page.getByRole("button",{name:"放大原始截图",exact:true}).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page).toHaveURL(/session=session-1/);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button",{name:"录入记录",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:/已归档/})).toBeInViewport();
  await expect(page.getByRole("button",{name:/归档 .*第 1 张截图/})).toBeInViewport();
  await page.screenshot({path:"../.data/previews/order-unified-screenshots.png"});
});

test("基本信息核对浮层越过卡片裁剪，手机和只读记录仍可查看", async ({ page }) => {
  const snap = initial();
  Object.assign(snap.work_items[0], {issues: [
    {field:"customer_id",code:"ENTITY_INFERRED",severity:"warning",message:"已根据发送者匹配为瑞豪，请核对下单客户。"},
    {field:"product_id",code:"ENTITY_REQUIRED",severity:"blocking",message:"请选择与截图材料和颜色相符的产品。"},
  ]});
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snap}));
  await page.goto("/?session=session-1");
  for (const width of [1366,390]) {
    await page.setViewportSize({width,height:800});
    for (const label of ["客户","产品"]) {
      const trigger = page.getByRole("button",{name:`${label}：需要核对`,exact:true});
      await trigger.click();
      const popup=page.getByRole("dialog",{name:`${label}核对说明`,exact:true});
      await expect(popup).toBeInViewport();
      await expect.poll(()=>popup.evaluate(e=>{
        const r=e.getBoundingClientRect();
        return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
      })).toBe(true);
      await page.keyboard.press("Escape");
      await expect(popup).toHaveCount(0);
      await expect(trigger).toBeFocused();
    }
  }
  snap.session.status="ARCHIVED";
  await page.route("**/items/item-1",r=>r.fulfill({json:{...snap.work_items[0],source_archived:true}}));
  await page.reload();
  await page.getByRole("button",{name:"订单列表",exact:true}).click();
  await page.getByRole("button",{name:/已归档/}).click();
  await page.locator(".intake-item").click();
  await page.getByRole("button",{name:"客户：需要核对",exact:true}).click();
  await expect(page.getByRole("dialog",{name:"客户核对说明",exact:true})).toBeInViewport();
  await page.screenshot({path:"../.data/previews/order-field-hint-mobile.png"});
});

test("放弃同图订单取消不写入，失败保留原图，全部放弃后刷新不再显示截图", async ({ page }) => {
  const snap=initial();
  snap.work_items.push({...structuredClone(item),id:"item-2",status:"PENDING"});
  Object.assign(snap.work_items[1],{source_order_index:2});
  let calls=0, fail=true;
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snap}));
  await page.route("**/items/*/close",async r=>{
    calls++;
    if(fail) return r.fulfill({status:503,json:{error:{message:"暂时无法放弃，请重试"}}});
    const closing=snap.work_items.find(i=>r.request().url().includes(`/items/${i.id}/`))!;
    expect(r.request().postDataJSON()).toMatchObject({confirmed:true,advance:true});
    closing.status="CLOSED";
    const next=snap.work_items.find(i=>i.status!=="CLOSED");
    if(next) next.status="ACTIVE";
    snap.session.active_work_item_id=next?.id??null;
    await r.fulfill({json:{}});
  });
  await page.goto("/?session=session-1");
  await page.getByRole("button",{name:"放弃",exact:true}).click();
  const dialog=page.getByRole("alertdialog",{name:"放弃这笔订单？"});
  await expect(dialog).toBeInViewport();
  await expect(dialog.getByRole("button",{name:"继续核对"})).toBeFocused();
  await page.screenshot({path:"../.data/previews/confirm-abandon-order.png"});
  await dialog.getByRole("button",{name:"继续核对"}).click();
  expect(calls).toBe(0);
  await page.getByRole("button",{name:"放弃",exact:true}).click();
  await dialog.getByRole("button",{name:"确认放弃",exact:true}).click();
  await expect(page.getByRole("alert").filter({hasText:"暂时无法放弃"})).toBeVisible();
  await expect(page.getByRole("button",{name:"放大原始截图",exact:true})).toBeVisible();
  fail=false;
  for(const index of [1,2]) {
    await page.getByRole("button",{name:"放弃",exact:true}).click();
    await dialog.getByRole("button",{name:"确认放弃",exact:true}).click();
    if(index===1) {
      await expect(page.getByRole("heading",{name:"核对订单 2",exact:true})).toBeVisible();
      await expect(page.getByRole("button",{name:"放大原始截图",exact:true})).toBeVisible();
    }
  }
  await expect(page.getByRole("heading",{name:"把订单截图放进来"})).toBeVisible();
  await expect(page.getByRole("button",{name:"放大原始截图",exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading",{name:"把订单截图放进来"})).toBeVisible();
  await expect(page.locator('.source-panel img, .screenshot-group')).toHaveCount(0);
});

test("截图归档确认适配手机，取消和失败保留，归档只读且可以恢复",async({page})=>{
  await page.setViewportSize({width:390,height:844});
  const snap=initial();
  Object.assign(snap.work_items[0],{created_at:"2026-09-13T01:00:00Z",source_archived:false,screenshot_revision:0});
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snap}));
  await page.route("**/items/item-1",r=>r.fulfill({json:snap.work_items[0]}));
  let calls=0, fail=true;
  await page.route("**/intake/screenshots/image-1/*",r=>{
    calls++;
    if(fail)return r.fulfill({status:409,json:{error:{message:"截图正在处理，请稍后重试"}}});
    const archived=r.request().url().endsWith("/archive");
    Object.assign(snap.work_items[0],{source_archived:archived,screenshot_revision:archived?1:2,status:"DEFERRED"});
    snap.session.active_work_item_id=null;
    snap.event_cursor++;
    return r.fulfill({json:{}});
  });
  await page.goto("/?session=session-1");
  await page.getByRole("button",{name:"订单列表",exact:true}).click();
  const archive=page.getByRole("button",{name:/归档 .*第 1 张截图/});
  await archive.click();
  const dialog=page.getByRole("alertdialog",{name:"归档这张截图？"});
  await expect(dialog).toBeInViewport();
  expect(await dialog.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await page.keyboard.press("Escape");
  expect(calls).toBe(0);
  await archive.click();
  await dialog.getByRole("button",{name:"归档截图",exact:true}).click();
  await expect(page.getByRole("alert").filter({hasText:"截图正在处理"})).toBeVisible();
  await expect(archive).toBeVisible();
  fail=false;
  await archive.click();
  await dialog.getByRole("button",{name:"归档截图",exact:true}).click();
  await expect(archive).toHaveCount(0);
  await page.getByRole("button",{name:/已归档/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(1);
  await page.locator(".intake-item").click();
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("50");
  await expect(page.getByRole("button",{name:"确认创建订单",exact:true})).toHaveCount(0);
  await page.getByRole("button",{name:"订单列表",exact:true}).click();
  await page.screenshot({path:"../.data/previews/screenshot-archive-mobile.png"});
  await page.getByRole("button",{name:/恢复 .*第 1 张截图/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(0);
  await page.getByRole("button",{name:/待处理/}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(1);
  await page.reload();
  await page.getByRole("button",{name:"订单列表",exact:true}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(1);
});

test("客户删除统一弹窗取消不请求，处理中禁止重复提交，失败可重试",async({page})=>{
  let exists=true, calls=0;
  let release:()=>void=()=>{};
  await page.route("**/api/customers",r=>r.fulfill({json:exists?[{id:"c1",company:"示例工厂",contact:"王先生",notes:null}]:[]}));
  await page.route("**/api/customers/c1",async r=>{
    calls++;
    if(calls===1){await new Promise<void>(done=>{release=done;});return r.fulfill({status:409,json:{detail:"客户存在关联订单，无法删除"}});}
    exists=false;
    await r.fulfill({status:204});
  });
  await page.goto("/settings");
  await page.getByRole("button",{name:"删除客户 示例工厂"}).click();
  const dialog=page.getByRole("alertdialog",{name:"删除客户？"});
  await dialog.getByRole("button",{name:"取消",exact:true}).click();
  expect(calls).toBe(0);
  await page.getByRole("button",{name:"删除客户 示例工厂"}).click();
  await dialog.getByRole("button",{name:"确认删除",exact:true}).click();
  await expect.poll(()=>calls).toBe(1);
  await expect(dialog.getByRole("button",{name:"正在处理…"})).toBeDisabled();
  await expect(dialog.getByRole("button",{name:"取消",exact:true})).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog.getByRole("alert")).toContainText("客户存在关联订单");
  await dialog.getByRole("button",{name:"确认删除",exact:true}).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button",{name:"删除客户 示例工厂"})).toHaveCount(0);
  expect(calls).toBe(2);
});

test("批量删除部分失败保留弹窗，只重试未删除的产品",async({page})=>{
  const category={id:"cat1",name:"薄膜",desc:null};
  let products=[{id:"p1",name:"透明膜",category_id:category.id,category},{id:"p2",name:"磨砂膜",category_id:category.id,category}];
  const calls:string[]=[];
  await page.route("**/api/products",r=>r.fulfill({json:products}));
  await page.route("**/api/product-categories",r=>r.fulfill({json:[category]}));
  await page.route("**/api/products/*",async r=>{
    const id=r.request().url().split('/').pop()!;
    calls.push(id);
    if(id==='p2'&&calls.filter(i=>i==='p2').length===1) return r.fulfill({status:409,json:{detail:"产品存在关联订单"}});
    products=products.filter(p=>p.id!==id);
    await r.fulfill({status:204});
  });
  await page.goto('/settings');
  await page.getByRole('button',{name:'产品',exact:true}).click();
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button',{name:'删除所选 (2)'}).click();
  const dialog=page.getByRole('alertdialog',{name:'删除所选产品？'});
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await expect(dialog.getByRole('alert')).toContainText('磨砂膜：产品存在关联订单');
  await expect(dialog).toContainText('选中的 1 个产品');
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await expect(dialog).toBeHidden();
  expect(calls).toEqual(['p1','p2','p2']);
});

test("截图按上传日分组和时间排序，放弃后所有位置编号同步更新",async({page})=>{
  const snap=initial();
  const old={...structuredClone(item),id:"old",source_attachment_id:"old-image",queue_position:1,status:"CLOSED",source_day:"2026-09-12",source_uploaded_at:"2026-09-12T01:00:00Z",source_day_position:1};
  const first={...structuredClone(item),id:"first",source_attachment_id:"first-image",queue_position:4,status:"ACTIVE",source_day:"2026-09-13",source_uploaded_at:"2026-09-13T01:10:00Z",source_day_position:1};
  const second={...structuredClone(item),id:"second",source_attachment_id:"second-image",queue_position:3,status:"PENDING",source_day:"2026-09-13",source_uploaded_at:"2026-09-13T02:20:00Z",source_day_position:2};
  const yesterday={...structuredClone(item),id:"yesterday",source_attachment_id:"yesterday-image",queue_position:2,status:"PENDING",source_day:"2026-09-12",source_uploaded_at:"2026-09-12T03:30:00Z",source_day_position:1};
  snap.work_items=[old,second,yesterday,first];
  snap.session.active_work_item_id=first.id;
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snap}));
  await page.route("**/items/first/close",r=>{
    first.status="CLOSED";
    second.status="ACTIVE";
    second.source_day_position=1;
    snap.session.active_work_item_id=second.id;
    snap.event_cursor++;
    return r.fulfill({json:{}});
  });
  await page.goto('/?session=session-1');
  const today=page.getByRole('region',{name:'2026-09-13上传的截图'});
  await expect(today).toBeVisible();
  await expect(today.locator('.screenshot-heading')).toHaveText([/第 1 张截图.*09:10 上传.*1 笔订单/,/第 2 张截图.*10:20 上传.*1 笔订单/]);
  await expect(page.locator('.screenshot-day h3')).toHaveText([/2026-09-13/,/2026-09-12/]);
  await expect(page.locator('.source-panel header')).toContainText('2026-09-13 · 第 1 张截图');
  await page.getByRole('button',{name:'放弃',exact:true}).click();
  await expect(page.getByRole('alertdialog')).toContainText('2026-09-13 · 第 1 张截图');
  await page.getByRole('alertdialog').getByRole('button',{name:'确认放弃',exact:true}).click();
  await expect(today.locator('.screenshot-heading')).toHaveText([/第 1 张截图.*10:20 上传/]);
  await expect(page.locator('.source-panel header')).toContainText('2026-09-13 · 第 1 张截图');
  await page.screenshot({path:'../.data/previews/screenshot-daily-groups.png'});
  await page.reload();
  await expect(today.locator('.screenshot-heading')).toHaveText([/第 1 张截图.*10:20 上传/]);
  // Moving an order to the created tab does not renumber its source screenshot.
  second.status="CREATED";
  snap.session.active_work_item_id=null;
  snap.event_cursor++;
  await page.reload();
  await page.getByRole('button',{name:/已下发 1/}).click();
  await expect(today.locator('.screenshot-heading')).toHaveText([/第 1 张截图.*10:20 上传/]);
});

test("新截图忽略已放弃历史序号，未识别不显示零笔订单",async({page})=>{
  const snap=initial();
  Object.assign(snap.work_items[0],{queue_position:4,source_day:'2026-09-13',source_day_position:1,source_uploaded_at:'2026-09-13T04:30:00Z',recognition_status:'NOT_STARTED'});
  Object.assign(snap,{active_run:{id:'r1',status:'RUNNING',work_item_id:'item-1'}});
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snap}));
  await page.goto('/?session=session-1');
  await expect(page.locator('.screenshot-heading')).toContainText('第 1 张截图');
  await expect(page.locator('.screenshot-heading')).toContainText('正在识别');
  await expect(page.locator('.screenshot-heading')).not.toContainText('0 笔订单');
  await expect(page.locator('.workbench-progress')).toContainText('2026-09-13 · 第 1 张截图');
  await expect(page.locator('.source-panel header')).toContainText('2026-09-13 · 第 1 张截图');
});

test("跨旧录入截图统一分页，切换先保存且失败不离开草稿",async({page})=>{
  const first=initial(), second=initial();
  second.session.id="session-2";
  second.session.active_work_item_id=null;
  Object.assign(first.work_items[0],{session_id:"session-1",source_day:"2026-09-13",source_day_position:1});
  Object.assign(second.work_items[0],{id:"item-other",session_id:"session-2",source_attachment_id:"image-other",status:"PENDING",source_day:"2026-09-13",source_day_position:2});
  second.work_items[0].draft.quantity="90";
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:first}));
  await page.route("**/sessions/session-2/snapshot",r=>r.fulfill({json:second}));
  let saved=0, fail=true;
  await page.route("**/items/item-1/draft",r=>{
    saved++;
    first.work_items[0].draft.quantity=r.request().postDataJSON().patch.quantity;
    first.work_items[0].revision++;
    first.event_cursor++;
    return r.fulfill({json:first.work_items[0]});
  });
  await page.route("**/items/item-other/select",r=>{
    expect(saved).toBeGreaterThan(0);
    if(fail)return r.fulfill({status:409,json:{error:{message:"目标订单已更新，请重试"}}});
    second.session.active_work_item_id="item-other";
    second.work_items[0].status="ACTIVE";
    return r.fulfill({json:{}});
  });
  await page.route("**/intake/screenshots?*",r=>{
    const next=new URL(r.request().url()).searchParams.has("cursor");
    const state=next?second:first;
    const row=state.work_items[0] as WorkItem;
    return r.fulfill({json:{screenshots:[{
      id:row.source_attachment_id,source_day:"2026-09-13",source_day_position:next?2:1,
      source_uploaded_at:next?"2026-09-13T02:00:00Z":"2026-09-13T01:00:00Z",
      source_archived:false,screenshot_revision:0,busy:false,running_item_id:null,items:[row],
    }],counts:{ACTIVE:1,PENDING:1},next_cursor:next?null:"second-page"}});
  });
  await page.goto("/?session=session-1");
  await page.getByRole("button",{name:"加载更多截图",exact:true}).click();
  await expect(page.locator(".screenshot-group")).toHaveCount(2);
  await page.getByLabel("数量",{exact:true}).fill("60");
  await page.locator(".intake-item").nth(1).click();
  await expect(page.getByRole("alert").filter({hasText:"目标订单已更新"})).toBeVisible();
  await expect(page).toHaveURL(/session=session-1/);
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("60");
  await expect(page.locator(".screenshot-group")).toHaveCount(2);
  fail=false;
  await page.locator(".intake-item").nth(1).click();
  await expect(page).toHaveURL(/session=session-2/);
  await expect(page.getByLabel("数量",{exact:true})).toHaveValue("90");
});

function scheduleBoard() {
  const order = (id: string) => ({ id, order_no: `ORD-${id}`, customer: { id:"c1", company:"瑞豪" },
    product: { id:"p1", name:"透明膜", category:{id:"cat1",name:"薄膜"} }, spec_params:{宽幅:"425mm",厚度:"118μm"}, quantity:750, unit:"kg", status:"PENDING" });
  return { pending_orders:[order("o1"),order("o2")], machines:["m1","m2"].map((id,index)=>({id,name:`${index+1}号机`,min_width:100,max_width:1200,is_active:true,notes:null,categories:[],tasks:[]})) };
}
function schedulePlan() {
  return {id:"plan-1",revision:1,status:"DRAFT",input_order_ids:["o1"],created_by_run_id:"run-1",stale:false,stale_reasons:[],unassigned:[],
    tasks:[{draft_task_id:"t1",machine_id:"m1",machine_name:"1号机",order_ids:["o1"],order_nos:["ORD-o1"],total_width:425,reason:"规格相符，按配方合单"}]};
}
async function scheduleFixtures(page: Page, draft = true) {
  const snapshot = initial("SCHEDULING");
  if (!draft) snapshot.session.active_plan_id = null;
  const board = scheduleBoard();
  const plan = schedulePlan();
  await page.route("**/api/kanban", r=>r.fulfill({json:board}));
  await page.route("**/sessions/session-1/snapshot",r=>r.fulfill({json:snapshot}));
  await page.route("**/plans/plan-1",r=>r.fulfill({json:plan}));
  return {snapshot,board,plan};
}

test("排单只发送选中订单，不确定请求复用标识，运行期间锁定选择",async({page})=>{
  const {snapshot}=await scheduleFixtures(page,false);
  let attempts=0; let key="";
  await page.route("**/sessions/session-1/schedule",async r=>{
    attempts++; expect(r.request().postDataJSON()).toEqual({expected_state_revision:1,order_ids:["o2"]});
    if(attempts===1) {key=r.request().headers()["idempotency-key"];await r.abort();return;}
    expect(r.request().headers()["idempotency-key"]).toBe(key);
    Object.assign(snapshot,{active_run:{id:"run-1",status:"QUEUED"},event_cursor:11});
    await r.fulfill({status:202,json:{run_id:"run-1"}});
  });
  await page.goto("/?session=session-1");
  await expect(page.getByRole("button",{name:"开始排单",exact:true})).toBeDisabled();
  await page.getByRole("checkbox",{name:"选择订单 ORD-o2"}).check();
  await page.getByRole("button",{name:"开始排单",exact:true}).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await page.getByRole("button",{name:"刷新看板"}).click();
  await page.getByRole("button",{name:"开始排单",exact:true}).click();
  await expect(page.getByRole("checkbox",{name:"选择订单 ORD-o1"})).toBeDisabled();
  await expect(page.getByText("正在核对订单和设备，生成本次排单建议…")).toBeVisible();
  await expect(page.getByRole("textbox",{name:"消息",exact:true})).toHaveCount(0);
});

test("草稿换机自动保存最新版本，取消确认不下发，正式队列保持只读",async({page})=>{
  const {board,plan,snapshot}=await scheduleFixtures(page);
  Object.assign(board.machines[0],{tasks:[{id:"formal-task",machine_id:"m1",position:0,status:"WAITING",notes:null,orders:[{...board.pending_orders[1],id:"formal-order",order_no:"ORD-formal"}]}]});
  let saves=0,applies=0;
  await page.route("**/plans/plan-1/draft",async r=>{
    saves++;const body=r.request().postDataJSON();expect(body.expected_revision).toBe(1);expect(body.tasks[0].machine_id).toBe("m2");
    plan.tasks[0].machine_id="m2";plan.tasks[0].machine_name="2号机";plan.revision=2;snapshot.event_cursor++;
    await r.fulfill({json:plan});
  });
  await page.route("**/plans/plan-1/apply",async r=>{applies++;expect(r.request().postDataJSON().expected_revision).toBe(2);snapshot.session.active_plan_id=null;
    Object.assign(snapshot,{messages:[{id:"applied-message",role:"assistant",content:"排产成功：创建2个生产任务，安排2张订单。",run_id:null,event_seq:12,attachments:[]}]});
    await r.fulfill({json:{}});});
  await page.goto("/?session=session-1");
  await expect(page.getByTitle("添加订单（合并生产）")).toHaveCount(0);
  await expect(page.getByRole("button",{name:"待生产",exact:true})).toBeDisabled();
  await page.getByLabel("草稿任务 1 的机器",{exact:true}).selectOption("m2");
  await expect(page.getByLabel("草稿任务 1 的机器",{exact:true})).toHaveValue("m2");expect(saves).toBe(1);
  await page.reload();await expect(page.getByLabel("草稿任务 1 的机器",{exact:true})).toHaveValue("m2");
  await page.getByRole("button",{name:"确认排单",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"取消",exact:true}).click();expect(applies).toBe(0);
  await page.getByRole("button",{name:"确认排单",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"确认排单",exact:true}).click();
  await expect(page.getByText(/排单成功，已下发/)).toBeVisible();expect(applies).toBe(1);
  await page.reload();
  await expect(page.getByRole("button",{name:"开始排单",exact:true})).toBeVisible();
  await expect(page.getByText(/排单成功|排产成功/)).toHaveCount(0);
  await expect(page.getByRole("button",{name:"待生产",exact:true})).toBeDisabled();
});

test("无效换机保留原草稿；过期草稿禁止确认但可重新生成",async({page})=>{
  const {plan}=await scheduleFixtures(page);
  await page.route("**/plans/plan-1/draft",r=>r.fulfill({status:422,json:{error:{code:"INPUT_INVALID",message:"宽幅超过机器能力"}}}));
  await page.goto("/?session=session-1");
  await page.getByLabel("草稿任务 1 的机器",{exact:true}).selectOption("m2");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("宽幅超过机器能力");
  await expect(page.getByLabel("草稿任务 1 的机器",{exact:true})).toHaveValue("m1");
  plan.stale=true;await page.reload();
  await expect(page.getByRole("button",{name:"确认排单",exact:true})).toBeDisabled();
  await expect(page.getByRole("button",{name:"重新生成",exact:true})).toBeEnabled();
});

test("草稿拆单返回未安排，放弃需确认且失败保留草稿",async({page})=>{
  const {plan}=await scheduleFixtures(page);
  let closed=0;
  await page.route("**/plans/plan-1/draft",async r=>{
    expect(r.request().postDataJSON().tasks).toEqual([]);plan.tasks=[];plan.revision++;
    Object.assign(plan,{unassigned:[{order_id:"o1",order_no:"ORD-o1",reason:"尚未安排到草案任务"}]});await r.fulfill({json:plan});
  });
  await page.route("**/plans/plan-1/close",r=>{closed++;expect(r.request().postDataJSON()).toEqual({expected_revision:2,confirmed:true});return r.fulfill({status:503,json:{error:{code:"UNAVAILABLE",message:"稍后重试"}}});});
  await page.goto("/?session=session-1");
  await page.getByLabel("安排订单 o1",{exact:true}).selectOption("unassigned");
  await expect(page.getByText("尚未安排到草案任务")).toBeVisible();
  await expect(page.getByRole("button",{name:"确认排单",exact:true})).toBeDisabled();
  await page.getByRole("button",{name:"放弃草稿",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"取消",exact:true}).click();expect(closed).toBe(0);
  await page.getByRole("button",{name:"放弃草稿",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"放弃草稿",exact:true}).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("稍后重试");await expect(page.getByText("尚未安排到草案任务")).toBeVisible();
});

test("排单看板桌面与手机主操作可见，卡片横向查看",async({page})=>{
  await scheduleFixtures(page);
  await page.goto("/?session=session-1");
  await expect(page.getByRole("article",{name:"草稿任务 1",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"返回助手首页",exact:true})).toBeInViewport();
  await page.screenshot({path:"test-results/scheduling-desktop.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole("button",{name:"确认排单",exact:true})).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole("button",{name:"返回助手首页",exact:true})).toBeInViewport();
  await page.screenshot({path:"test-results/scheduling-mobile.png",fullPage:true});
  await page.getByRole("button",{name:"返回助手首页",exact:true}).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("button",{name:/开始排单/})).toBeVisible();
});

test("米数草稿保留原单位，同米数可合并且不混合重量",async({page})=>{
  const {board,plan} = await scheduleFixtures(page);
  board.pending_orders[0].quantity=7500;
  board.pending_orders[0].unit="m";
  Object.assign(plan,{load_basis:"TASK_COUNT",input_order_ids:["o1","o2"]});
  plan.tasks[0].reason="按规格合并，不折算重量";
  plan.tasks.push({...plan.tasks[0],draft_task_id:"t2",order_ids:["o2"],order_nos:["ORD-o2"],reason:"配方相同"});
  await page.goto("/?session=session-1");
  await expect(page.getByText("按米数 · 独立生产",{exact:true})).toHaveCount(0);
  await expect(page.getByText(/同等条件下按任务数粗略比较负载/)).toBeVisible();
  const meter = page.getByRole("article",{name:"草稿任务 1",exact:true});
  await expect(meter).toContainText("7500m");
  await expect(page.getByLabel("安排订单 o1",{exact:true}).locator('option[value^="task:"]')).toHaveCount(0);
  await expect(page.getByLabel("安排订单 o2",{exact:true}).locator('option[value^="task:"]')).toHaveCount(0);
  await expect(page.getByRole("button",{name:"确认排单",exact:true})).toBeEnabled();
  board.pending_orders[1].unit="m";
  await page.reload();
  await expect(page.getByLabel("安排订单 o1",{exact:true}).locator('option[value="task:1"]')).toHaveCount(1);
  await expect(page.getByLabel("安排订单 o2",{exact:true}).locator('option[value="task:0"]')).toHaveCount(1);
  await page.route("**/plans/plan-1/draft", async r=>{
    expect(r.request().postDataJSON().tasks).toEqual([{draft_task_id:"t2",machine_id:"m1",order_ids:["o2","o1"]}]);
    plan.tasks=[{...plan.tasks[1],order_ids:["o2","o1"],order_nos:["ORD-o2","ORD-o1"],total_width:850}];
    plan.revision=2;
    await r.fulfill({json:plan});
  });
  await page.getByLabel("安排订单 o1",{exact:true}).selectOption("task:1");
  await expect(page.getByText("草稿任务 · 2 笔",{exact:true})).toBeVisible();
  await page.screenshot({path:"test-results/scheduling-meters.png",fullPage:true});
});


test("看板生产完成需确认，取消不写入、失败保留状态与弹窗", async ({page}) => {
  const board = scheduleBoard();
  const task = {id:"task-status", machine_id:"m1", position:1, status:"PRODUCING", updated_at:"2026-09-15T01:00:00Z", orders:board.pending_orders};
  Object.assign(board.machines[0], {tasks:[task]});
  board.pending_orders=[];
  await page.route("**/api/kanban", r=>r.fulfill({json:board}));
  let calls=0, fail=true;
  await page.route("**/api/production-tasks/task-status", async r=>{
    calls++;
    expect(r.request().postDataJSON()).toEqual({status:"DONE",expected_status:"PRODUCING",expected_updated_at:task.updated_at,expected_order_ids:["o1","o2"]});
    if(fail) return r.fulfill({status:409,json:{detail:"任务状态已变化，请刷新"}});
    Object.assign(board.machines[0], {tasks:[]});
    return r.fulfill({json:{...task,status:"DONE"}});
  });
  await page.goto("/kanban");
  await page.getByRole("button",{name:"生产中",exact:true}).click();
  const dialog=page.getByRole("alertdialog",{name:"确认完成生产？"});
  await expect(dialog).toContainText("2 笔订单");
  expect(calls).toBe(0);
  await dialog.getByRole("button",{name:"取消",exact:true}).click();
  expect(calls).toBe(0);
  await page.getByRole("button",{name:"生产中",exact:true}).click();
  await dialog.getByRole("button",{name:"确认完成",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("任务状态已变化");
  await expect(page.getByRole("button",{name:"生产中",exact:true,includeHidden:true})).toBeVisible();
  fail=false;
  await dialog.getByRole("button",{name:"确认完成",exact:true}).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button",{name:"生产中",exact:true})).toHaveCount(0);
  expect(calls).toBe(2);
});

for (const width of [1366,390]) test(`订单状态选择与完成恢复同步合单，待排只读 ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:844});
  const task={id:"task-status",status:"PRODUCING",updated_at:"2026-09-15T01:00:00Z"};
  const orders=scheduleBoard().pending_orders.map(o=>({...o,status:"PRODUCING",task,created_at:"2026-09-15T01:00:00Z",formula:null}));
  const pending={...orders[0],id:"pending",order_no:"ORD-pending",status:"PENDING",task:null};
  await page.route("**/api/orders",r=>r.fulfill({json:[...orders,pending]}));
  let calls=0, fail=true;
  await page.route("**/api/production-tasks/task-status",async r=>{
    calls++;
    const body=r.request().postDataJSON();
    expect(body.expected_order_ids).toEqual(["o1","o2"]);
    expect(body.expected_status).toBe(task.status);
    expect(body.expected_updated_at).toBe(task.updated_at);
    if(fail)return r.fulfill({status:409,json:{detail:"机器已有其他任务在生产"}});
    task.status=body.status;
    task.updated_at=body.status==="DONE"?"2026-09-15T02:00:00Z":"2026-09-15T03:00:00Z";
    orders.forEach(o=>o.status=body.status === "DONE" ? "DONE" : "PRODUCING");
    return r.fulfill({json:{...task,machine_id:"m1",position:1,orders}});
  });
  await page.goto("/orders");
  await expect(page.getByRole("button",{name:"修改订单 ORD-pending 的状态"})).toHaveCount(0);
  const trigger=page.getByRole("button",{name:"修改订单 ORD-o1 的状态",exact:true});
  await trigger.click();
  const popup=page.getByRole("dialog",{name:"选择订单状态"});
  await expect(popup.getByRole("button",{name:/待排单/})).toBeDisabled();
  await popup.getByRole("button",{name:"已完成",exact:true}).click();
  const dialog=page.getByRole("alertdialog");
  await expect(dialog).toContainText("2 笔订单");
  await expect(dialog).toContainText("ORD-o2");
  expect(calls).toBe(0);
  await dialog.getByRole("button",{name:"取消",exact:true}).click();
  await expect(trigger).toContainText("生产中");
  await trigger.click();
  await popup.getByRole("button",{name:"已完成",exact:true}).click();
  await dialog.getByRole("button",{name:"确认完成",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("机器已有其他任务");
  await expect(page.locator('button[aria-label="修改订单 ORD-o1 的状态"]').filter({visible:true})).toContainText("生产中");
  fail=false;
  await dialog.getByRole("button",{name:"确认完成",exact:true}).click();
  await expect(trigger).toContainText("已完成");
  await expect(page.getByRole("button",{name:"修改订单 ORD-o2 的状态",exact:true})).toContainText("已完成");
  await trigger.click();
  await popup.getByRole("button",{name:"恢复生产中",exact:true}).click();
  await expect(dialog).toBeInViewport();
  await page.screenshot({path:`test-results/order-status-confirm-${width}.png`,fullPage:true});
  await dialog.getByRole("button",{name:"确认恢复",exact:true}).click();
  await expect(trigger).toContainText("生产中");
  await page.reload();
  await expect(page.getByRole("button",{name:"修改订单 ORD-o2 的状态",exact:true})).toContainText("生产中");
  expect(calls).toBe(3);
  await trigger.click();
  await popup.getByRole("button",{name:"撤回到待生产",exact:true}).click();
  await expect(dialog).toContainText("保留原机器与排队位置");
  await dialog.getByRole("button",{name:"确认撤回",exact:true}).click();
  await expect(trigger).toContainText("待生产");
  await expect(page.getByRole("button",{name:"修改订单 ORD-o2 的状态",exact:true})).toContainText("待生产");
  await page.reload();
  await expect(trigger).toContainText("待生产");
  expect(calls).toBe(4);
});

for (const width of [1366,390]) test(`订单按任务显示四种状态，待生产筛选和开始后计数同步 ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:844});
  const base=scheduleBoard().pending_orders[0];
  const orders=[
    {...base,id:"pending",order_no:"ORD-pending",status:"PENDING",task:null},
    {...base,id:"waiting",order_no:"ORD-waiting",status:"PRODUCING",task:{id:"tw",status:"WAITING",updated_at:"2026-09-15T01:00:00Z"}},
    {...base,id:"producing",order_no:"ORD-producing",status:"PRODUCING",task:{id:"tp",status:"PRODUCING",updated_at:"2026-09-15T01:00:00Z"}},
    {...base,id:"done",order_no:"ORD-done",status:"DONE",task:{id:"td",status:"DONE",updated_at:"2026-09-15T01:00:00Z"}},
  ].map(order=>({...order,created_at:"2026-09-15T01:00:00Z",formula:null}));
  await page.route("**/api/orders",r=>r.fulfill({json:orders}));
  await page.route("**/api/orders/waiting",r=>r.fulfill({json:orders[1]}));
  await page.route("**/api/production-tasks/tw",r=>{
    expect(r.request().postDataJSON().status).toBe("PRODUCING");
    Object.assign(orders[1].task!,{status:"PRODUCING",updated_at:"2026-09-15T02:00:00Z"});
    return r.fulfill({json:{...orders[1].task,machine_id:"m1",position:1,orders:[orders[1]]}});
  });
  await page.goto("/orders");
  for(const label of ["待排单","待生产","生产中","已完成"]) {
    await expect(page.getByRole("button",{name:new RegExp(`^${label}\\s*1$`)})).toBeVisible();
  }
  const waiting=page.getByRole("button",{name:"修改订单 ORD-waiting 的状态",exact:true});
  await expect(waiting).toHaveText("待生产");
  // The detail dialog uses the same task-derived status as the list.
  await page.getByText("waiting",{exact:true}).filter({visible:true}).click();
  const detail=page.getByRole("dialog");
  await expect(detail.getByText("待生产",{exact:true})).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button",{name:/^待生产\s*1$/}).click();
  await expect(waiting).toBeVisible();
  await expect(page.getByRole("button",{name:"修改订单 ORD-producing 的状态",exact:true})).toHaveCount(0);
  await page.screenshot({path:`test-results/order-waiting-${width}.png`,fullPage:true});
  await waiting.click();
  const popup=page.getByRole("dialog",{name:"选择订单状态"});
  await expect(popup.getByRole("button",{name:"已完成",exact:true})).toBeDisabled();
  await popup.getByRole("button",{name:"开始生产",exact:true}).click();
  await page.getByRole("alertdialog").getByRole("button",{name:"确认开始",exact:true}).click();
  await expect(page.getByText("暂无「待生产」订单",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:/^生产中\s*2$/}).click();
  await expect(waiting).toHaveText("生产中");
  await page.reload();
  await expect(waiting).toHaveText("生产中");
});


test("看板撤回生产确认，取消零写入，失败保留，成功回待生产",async({page})=>{
  const board=scheduleBoard();
  const task={id:"withdraw-task",machine_id:"m1",position:1,status:"PRODUCING",updated_at:"2026-09-16T00:00:00Z",orders:board.pending_orders};
  Object.assign(board.machines[0],{tasks:[task]});board.pending_orders=[];
  await page.route("**/api/kanban",r=>r.fulfill({json:board}));
  let calls=0,fail=true;
  await page.route("**/api/production-tasks/withdraw-task",r=>{
    calls++;
    expect(r.request().postDataJSON()).toEqual({status:"WAITING",expected_status:"PRODUCING",expected_updated_at:task.updated_at,expected_order_ids:["o1","o2"]});
    if(fail)return r.fulfill({status:409,json:{detail:"任务已变化，请刷新后重新确认"}});
    task.status="WAITING";return r.fulfill({json:task});
  });
  await page.goto("/kanban");
  await page.getByRole("button",{name:"撤回",exact:true}).click();
  const dialog=page.getByRole("alertdialog",{name:"确认撤回到待生产？"});
  await expect(dialog).toContainText("2 笔订单");
  await expect(dialog).toContainText("保留原机器与排队位置");
  await page.screenshot({path:"test-results/withdraw-production-confirm.png"});
  await dialog.getByRole("button",{name:"取消",exact:true}).click();expect(calls).toBe(0);
  await page.getByRole("button",{name:"撤回",exact:true}).click();
  await dialog.getByRole("button",{name:"确认撤回",exact:true}).click();
  await expect(dialog.getByRole("alert")).toContainText("任务已变化");
  fail=false;
  await dialog.getByRole("button",{name:"确认撤回",exact:true}).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button",{name:"待生产",exact:true})).toBeVisible();
  await expect(page.getByRole("button",{name:"撤回",exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button",{name:"待生产",exact:true})).toBeVisible();
  expect(calls).toBe(2);
});
