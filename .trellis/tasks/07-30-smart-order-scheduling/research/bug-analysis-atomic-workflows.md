## Bug Analysis: Agent 录单与生产看板跨层状态失真

### 1. Root Cause Category

- **Category**: B - Cross-Layer Contract（主因），同时包含 D - Test Coverage Gap 与 E - Implicit Assumption
- **Specific Cause**: 页面把“确认下发订单”“移动生产任务”等一个业务动作拆成多次 API 写入，并在浏览器维护另一份推测状态。后端没有提供完整的原子命令和权威快照契约，因此任一中间请求失败、刷新或重试都可能产生半完成、重复或页面残留。

调查初始假设与证据更新：

| Hypothesis | Prior | Evidence | Posterior |
| --- | ---: | --- | ---: |
| H1 数据库未连接或数据未持久化 | 30% | API 与数据库记录可正常读写，问题集中在跨请求时序 | 5% |
| H2 图片展示组件本身有单点缺陷 | 30% | 图片刷新消失、输入框残留和订单重复涉及不同组件与写路径 | 15% |
| H3 跨层事务和状态所有权不清 | 40% | 前端存在多次写入、乐观局部更新，后端缺少原子命令；重构后一组回归均通过 | 80% |

结论置信度高于 90%：直接证据来自代码路径、数据库回滚测试、完整测试套件和浏览器操作验证。

### 2. Why Fixes Failed

1. **Surface Fix**: 只修图片预览或清空输入框，无法解决刷新后的持久化与消息生命周期。
2. **Incomplete Scope**: 只调整前端请求地址或响应字段，没有统一后端事务边界，仍会留下部分成功。
3. **Mental Model**: 把错误看成单个组件问题，忽略了 UI、SSE、API、Service、数据库共同组成的一条业务链。
4. **Test Coverage Gap**: 原测试偏向单接口成功路径，缺少重复确认、事务回滚、陈旧快照、跨机器移动和移动端无拖拽入口。

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | 一个用户意图只调用一个后端命令；行锁、校验和一次提交由 Service 统一完成 | DONE |
| P0 | Runtime contract | 看板命令返回完整 `KanbanOut`；页面以服务端快照替换本地状态 | DONE |
| P0 | Idempotency | Agent 确认锁定并消费 pending token；重复确认不得创建第二张订单 | DONE |
| P0 | Test coverage | 覆盖成功、回滚、重复、陈旧计划、兼容性与状态机 | DONE |
| P1 | Documentation | 增加生产工作流契约及跨层原子命令检查清单 | DONE |
| P1 | Browser QA | 桌面拖拽、状态切换、移动端非拖拽排单和控制台错误验证 | DONE |
| P2 | E2E | 在已配置真实模型/OCR 后人工验证文字与图片录单全链路 | TODO |

### 4. Systematic Expansion

- **Similar Issues**: 现有订单编辑时若同时新建配方，仍需检查是否也是跨请求写入；其他复杂表单和批量操作也应按同一清单审计。
- **Design Improvement**: 页面持有临时草稿，后端持有业务事实；命令成功后用完整权威响应收敛，不在两边分别实现业务规则。
- **Process Improvement**: 新增跨三层以上的功能时，先画完整数据流并列出事务、幂等、陈旧状态和失败回滚测试，再写 UI。

### 5. Knowledge Capture

- [x] 更新 `.trellis/spec/guides/cross-layer-thinking-guide.md`
- [x] 新增 `.trellis/spec/backend/core/production-workflow-guidelines.md`
- [x] 更新 `.trellis/spec/frontend/ui/state-management.md`
- [x] 更新任务设计与实现计划
- [x] 更新 `meta/GROUND_TRUTH.md` 中的排产目标和计划失效规则
- [ ] 真实模型/OCR 环境的人工端到端验收

模板同步说明：本仓库没有 `src/templates/markdown/spec/`，且上述内容是 FilmOS 业务规范而非 Trellis 上游模板，因此没有可同步的模板副本。
