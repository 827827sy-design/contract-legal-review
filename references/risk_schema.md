# risk_schema.md — review_draft.json 结构定义

模型在第六步产出的草稿文件。validate_review.py 读取它并输出 verified_review.json。

## 顶层结构

```json
{
  "contract_type": "劳动合同",
  "scope_limitation": "本次审查仅依据《民法典》《劳动合同法(2012修正)》《公司法(2023修订)》三部法律；其他法律法规、司法解释及商业合理性不在审查范围内。文件解析状态：ok（全文覆盖）。本报告为AI辅助风险提示，不构成法律意见。",
  "contract_dates": {"signed": "", "performance_start": "", "performance_end": "", "note": "合同未载明签订日期"},
  "risks": [ ... ]
}
```

- `contract_dates` 仅用于记录与提示时间效力问题，**不得臆造**；缺失就留空并在 note 说明。

## 单条风险对象（risks 数组元素）

新版首次审查以`references/usability_workflow.md`的`suggestion.candidates`为主入口。每个候选遵循下述edit_plan动作结构；不能只写风险解释。无修改时必须给no_edit_reason；旧proposed_clause/edit仅用于可验证迁移，不能从第一条证据猜测范围。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| risk_id | string | 是 | 草稿阶段稳定编号如 D01；validate 后会重排为 R001 并保留映射 |
| title | string | 是 | 一句话风险标题，≤30字，客观中立 |
| category | enum | 是 | `法律合规风险` / `合同效力风险` / `条款缺失` / `条款约定不明确` / `待核实事项` |
| severity | enum | 是 | `high` / `medium` / `low` / `review_required`。**不允许百分比置信度** |
| conclusion | string | 是 | 风险判断。非强制性问题的表述禁用"违法"；效力问题只说"存在效力风险，需人工确认" |
| explanation | string | 是 | 具体原因：条款怎么写的、法律怎么要求的、差距在哪 |
| evidence | array | 是 | 原文证据，见下。至少 1 条；缺失条款用 no_text 形式 |
| legal_basis | array | 否 | 法律依据，见下。可为空数组（纯完整性建议时） |
| recommendation | string | 是 | 中立、可操作的修改/补充建议 |
| proposed_clause | string | 否 | 旧版展示字段，仅兼容既有示例或草稿，不作为应用来源。新建议使用 edit_plan；关键条件未知时列 questions，正式 replacement_text=null、draft_pending=true。不得编造或把占位文本当作完成条款 |
| manual_checks | array[string] | 否 | 需人工核实的事项（主体资格、审批手续、时间效力、超范围法律问题等） |
| scope_note | string | 否 | 范围说明，如"涉及个人信息保护，超出三部法律范围，仅作待核实提示" |
| risk_source | enum | 否 | V2：legal / company_policy / negotiation / experience；旧数据默认 legal。偏好不等于法律 |
| preference_id | string | 否 | 对应用户确认的长期偏好编号 |
| objective_legal_conclusion | string | 否 | 客观法律判断，切换立场时保持同一事实下的一致性 |
| edit | object | 否 | 旧版位置数据，仅兼容解析；新修改使用 edit_plan.edits，旧定位通过也不满足应用质量条件 |

顶层 V2 可带 `perspective`（mode=neutral/party_a/party_b/custom，focus 与已确认主体）；缺失时读取 review_context 或默认中立。可带 `risk_resolution[]`，复审分类由 WorkBuddy 真实语义分析生成，不能仅凭风险编号未出现认定解决。

旧结构例：`"edit":{"node_id":"b0004","kind":"partial","start":0,"end":10,"expected_text":"合同节点内逐字原文"}`。数值必须从实际节点计算，不能照抄。该结构现在仅兼容展示；新应用必须使用完整edit_plan，解释文字不能自动写入合同。

原有五种 category 保留；企业偏好或谈判建议按具体问题归类（无对应结构缺失/约定不明时用待核实事项），并以 risk_source 清楚区分，禁止把不符合偏好直接标为法律合规风险。HTML 采纳决定以 review_id + risk_id 区分，复审中的新风险编号不会继承旧风险的采纳决定。

## 通用修改计划（增量字段，不改变旧schema_version）

新增风险字段edit_plan：plan_id、risk_id（可保持草稿稳定编号，展示编号仍由父风险重排）、reason、questions、business_terms、edits、required_edit_node_ids、postconditions、amount_records、related_risk_ids、source_revision_basis、condition_changes、semantic_review。来源及上下文由验证器绑定risk_context与source_file_sha256。

新增字段：suggestion.candidates、no_edit_reason、field_bindings、semantic_review.field_policy。compiled的risk_identity记录analysis_id/display_id/source_plan_risk_id/plan_id，review_meta.risk_identity_map提供双向映射，重复或错关联阻断。六种readiness由结果推导，缺/过期核验用review_phase=awaiting_model_review区别于真实人工复核；正式语义状态还需十项检查及声明范围覆盖完整。新候选risk_id必须等于所属风险分析ID，旧嵌套计划通过父记录归属迁移并保留原别名。

每个edits动作包含edit_id、target_node_id、operation（partial/replace/insert_clause/delete_clause）、expected_node_text（完整节点逐字原文）、expected_original（局部动作的原文片段，其他动作的完整节点原文）、replacement_text、dependencies。partial还需Unicode码点start/end。delete_clause的replacement_text为空；insert_clause锚点须为完整段落或表格最后节点。缺条件时draft_pending=true且replacement_text=null，不放占位示例假装正式文本。

questions含id、question、required，可含options、impact；已确认回答包含answer、confirmed及来源说明。business_terms含id、value、confirmed、source；不要自填用户确认。未确认的关键条件需提问。

condition_changes可记录新增/变更条件的node_id、before_quote、after_quote、effect、reason、source和confirmed。合同来源附source_node_id/source_quote；legal_requirement需law_id/article_no并能对应已核验依据。模型应逐一分析实质新增条件，程序不能用关键词替模型判断clarification是否真实。

postconditions是可机械核对的明确文字约束：type=present/absent、node_ids、text。它不能代替语义结论。amount_records在原check_amounts格式上增加node_id、after_quote（修改后完整节点中的逐字片段），只对明确金额及税率作算术，不编造税率。

顶层contract_analysis记录经模型分析的语义edges与obligations，详见quality_workflow.md。semantic_review的十项checks是模型判断，每项有result和reason；必须绑定程序请求的plan_fingerprint、scope_node_hashes，记录reviewer、reviewed_at、checked_node_ids。不要先写pass后找理由。

验证器产出readiness、can_apply、validation、checks、quality_result、blockers、preview_nodes、scope_node_texts、compiled_digest。它们由程序推导，草稿不能自行指定有效状态。整组执行后risk_status_after_apply固定needs_re_review。

### evidence 元素

```json
{
  "block_id": "b0012",
  "quote": "试用期为六个月，试用期内甲方可随时解除合同且无需支付任何补偿。",
  "occurrence": 1
}
```

- `quote`：从合同原文**逐字连续复制**（允许截取片段，不允许省略号拼接、改标点、增减空格）。校验脚本按"忽略空白"规则比对，因此换行/空格差异可容忍，文字差异零容忍。
- `block_id`：quote 所在块（contract.json blocks 里的 block_id）。给对了可块内定位；给错了脚本会全文定位并标注。
- `occurrence`：同一文字在合同中重复出现时，指明第几次（从 1 开始）。不填默认 1。**引用重复文字时必须确认 occurrence 正确，否则会定位到错误位置**。
- 跨段落证据：拆成多个 evidence 元素，各自 quote 各自 block_id。
- 缺失条款（无直接原文）：

```json
{"no_text": true, "suggested_block_id": "b0030"}
```

`suggested_block_id` 指向建议插入位置附近的现有块；或加 `"locate_at_end": true` 定位到合同末尾。报告将显示"该问题无直接原文（缺失条款）"。

### legal_basis 元素

```json
{
  "law_id": "laodonghetongfa",
  "article_no": "第十九条",
  "text": "劳动合同期限三个月以上不满一年的，试用期不得超过一个月；……（从 search_law.py 结果逐字复制全文）"
}
```

- `law_id` ∈ {`minfadian`, `laodonghetongfa`, `gongsifa`}。
- `article_no` 用中文条号，与知识库一致（如"第五百八十五条"，不是"585条"）。
- `text` 必须逐字来自检索结果。validate 会做规范化全文比对：条号不存在 → not_found；文本不符 → mismatch。两者都会在报告中标红并提示"不得作为审查依据"。
- 引用条号超出三部法律 → **不要写进 legal_basis**，改写进 scope_note + manual_checks，category 用"待核实事项"。

## 分类判定速查

| 情形 | category | severity 倾向 |
|---|---|---|
| 条款违反法律强制性规定（如试用期超长、违约金违法设定、必备条款缺失于劳动合同） | 法律合规风险 | high/medium |
| 条款可能影响合同或条款效力（无权代理、显失公平、恶意串通迹象、需批准未批准） | 合同效力风险 | high 或 review_required |
| 法律未强制但常见应有事项缺失（争议解决、通知送达、验收标准） | 条款缺失 | medium/low |
| 有条款但含义模糊、无法执行（"合理期限""视情况而定"无标准） | 条款约定不明确 | medium/low |
| 需要外部事实/超出知识库范围才能判断 | 待核实事项 | review_required |

## 正例（劳动合同试用期违法）

```json
{
  "risk_id": "D01",
  "title": "试用期约定超过法定上限",
  "category": "法律合规风险",
  "severity": "high",
  "conclusion": "合同期限为一年，约定试用期六个月，超过《劳动合同法》第十九条规定的一年以上不满三年合同试用期不得超过二个月的上限。",
  "explanation": "第三条约定劳动合同期限自2026年1月1日至2026年12月31日（一年）；第五条约定试用期六个月。一年期合同法定试用期上限为二个月，超出部分无效风险由用人单位承担，且超期履行可能产生赔偿。",
  "evidence": [
    {"block_id": "b0009", "quote": "合同期限自2026年1月1日起至2026年12月31日止"},
    {"block_id": "b0015", "quote": "试用期为六个月"}
  ],
  "legal_basis": [
    {"law_id": "laodonghetongfa", "article_no": "第十九条", "text": "（从检索结果逐字复制）"}
  ],
  "recommendation": "将试用期调整为不超过二个月，或延长合同期限至三年以上后再约定相应试用期。",
  "proposed_clause": "试用期为二个月，自2026年1月1日起至2026年2月28日止。",
  "manual_checks": ["核实实际用工开始日期，判断是否已超期履行试用期"]
}
```

## 反例（禁止出现的写法）

- ❌ `"conclusion": "本合同无效"` —— 不得认定整体无效。
- ❌ `"legal_basis": [{"law_id": "gerenxinxibaohufa", ...}]` —— 知识库外法律。
- ❌ `"text": "第八十七条 ……（凭记忆复述）"` —— 未从检索结果复制。
- ❌ `"quote": "试用期六个月……无需补偿"` —— 省略号拼接非连续原文。
- ❌ `"confidence": "85%"` —— 禁止百分比置信度。
- ❌ `"conclusion": "该条款违法"`（针对法律未强制的事项，如缺少通知条款）—— 应为条款缺失/约定不明。
