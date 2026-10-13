# revisions.json V2

本次仍使用schema_version=2。新组的execution_protocol=2保留局部范围；旧快照按原合并协议校验兼容。plan_groups可记录accepted_negotiation_terms；materialized_plans保存预审字段派生计划；ui_drafts/manual_drafts保留临时输入；candidate_choices按分析ID保存候选选择。草稿和候选选择不属于已应用operations。

导入和Python重放核对组实际步骤与计划快照相同。格式Tab停靠点的旧解析表示可按migrate_revisions.py受控迁移，原文件必须相同、差异可核验且相应节点未改动；涉及关联范围变化时拒绝猜测，保留原记录供WorkBuddy核查。迁移需另存JSON，不冒充旧文件已经更新。

浏览器与 Python 共用的协议。所有偏移均为 **Unicode 码点**，不是 JavaScript UTF-16 下标。操作针对当前节点全文，并校验前文；重复文字不会跨节点搜索。

```json
{
  "schema_version": 2,
  "contract": {"file_sha256":"原始文件SHA256","content_sha256":"原始合同full_text的UTF-8 SHA256"},
  "base_nodes": {"b0001":"原始段落","b0002-r0-c0":"原始单元格"},
  "current_nodes": {"b0001":"当前段落","b0002-r0-c0":"当前单元格"},
  "perspective": {"mode":"neutral","focus":""},
  "operations": [],
  "history": [],
  "redo_stack": [],
  "risk_decisions": {}
}
```

每个操作字段：`id`、`type`、`node_id`、`before_text`、`after_text`、`start`、`end`、`removed_text`、`inserted_text`、`source`（manual/ai）、`risk_id`、`perspective`、`reason`、`time`、`status`（active/undone/abandoned）、`decision`（pending/confirmed/rejected）。

`type` 为 insert/delete/replace 或 insert_node。文本操作的 start/end 是 before_text 中的半开区间，removed_text 必须与该区间完全相同，after_text 必须与拼接结果完全相同。每次编辑后保存完整当前节点文本，但单独记录实际变化的最小连续范围，支持同段多次修改。

insert_node 另外带 `anchor_node_id`，node_id 为以 `n-` 开头的唯一 ID；新段落只插在段落之后或整张表格最后一个单元格之后。

撤销只改变 status 并追加 history，不删除操作。撤销后新编辑将旧恢复分支标为 abandoned 并清空 redo_stack；历史仍可追溯。恢复原始内容撤销全部有效操作。decision 默认 pending，用户确认后变为 confirmed，生成 Word 只允许有效的 confirmed 操作。

加载时验证合同双指纹、原始节点快照、操作 ID 与枚举、节点可编辑性、位置、连续前文及最终 current_nodes。存在冲突立即停止；不尝试模糊匹配或偷偷修复。历史是审计数据，不包含需要执行的指令。

`contract.json` 增量包含 `nodes[]`：稳定 node_id、block_id、kind、text、block_start/full_start、editable、locator，以及V2.1的has_existing_revisions和read_only_reason。常见 Word 节点 locator 保存原始 body_index 与 table row/col，不用重复文字重新搜索 Word。旧数据缺少 nodes 时按原段落降级构造；无结构映射的旧表格只读。升级支持修订编辑时重新解析原DOCX并创建新报告，不把旧节点editable直接手工改成true；已有修订JSON在原文双指纹和快照不变时可校验导入。

这套记录是编辑审计日志，不是防篡改签名系统。用户仍应保管原文件和修订文件，并在最终 Word 输出后核对；文件指纹和重放校验用于发现不匹配及破坏性冲突。

增量plan_groups记录完整计划快照、plan_fingerprint及连续operation_ids。组内操作携带group_id、plan_id、edit_ids；状态和最终确认必须整组一致。校验会拒绝缺步骤、部分撤销/确认、原文变化、旧语义记录和重复应用。旧无group_id操作仍兼容。

plan_drafts仅保存待补充条件（draft_id、plan_id、plan_fingerprint、answers、needs_regeneration），不属于有效正文修改。risk_status记录needs_re_review，不因应用或确认修改变成resolved。模型复审分类需绑定当前稿，见quality_workflow.md。
