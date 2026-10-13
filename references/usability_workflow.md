# 首次审查、候选方案与便捷修订

宿主为WorkBuddy。固定脚本处理数据和执行，WorkBuddy模型负责合同语义及法律适用。不要重新生成编辑器代码，不增加本地服务或浏览器Word导出。

## 首次审查必须完成的生成工作

同一轮分析中识别风险、原因、既有权利、关联影响，并生成`suggestion.candidates[]`。每项风险必须有完整结构化计划，或`suggestion.no_edit_reason`明确说明为什么现在不适合修改。不能只写recommendation而遗漏计划，也不能把内部生成失败转交给用户填写。

```json
{
  "risk_id": "analysis-stable-id",
  "suggestion": {
    "candidates": [{
      "plan_id": "independent-plan-id",
      "risk_id": "analysis-stable-id",
      "label": "推荐方案",
      "reason": "该方案改变哪些表述、保留什么权利",
      "questions": [],
      "business_terms": [],
      "edits": []
    }]
  }
}
```

示意中的edits必须换成真实动作；完整动作协议见risk_schema.md。默认第一个方案为推荐方案，不超过必要数量。各候选分别生成、核验，不能只替换一个数字就沿用不适用的结论。每个候选的risk_id必须指向所属分析风险，plan_id独立且唯一。

区分信息来源：

- 事实：原合同、用户已确认资料或履约证据，逐字核对，不猜金额、税率、实际日期、主体和履行事实。
- 谈判推荐：可以提出具体期限或机制及备选，business_terms用`kind=negotiation,proposed=true,confirmed=false,source`明确推荐来源。相关condition_changes用proposal_term_id指向该推荐。通过质量检查仅表示可提交确认；应用时用户必须明确接受，组记录保留accepted_negotiation_terms。
- 必须核实的事实或关键机制：提出具体问题，注明必填与影响；未确认时提供有用草案，不把占位文本标成完成稿。非必要问题设required=false，不让其阻断已有完整方案。

运行validate_review.py，按quality_requests.json逐候选完成真实十项语义判断及绑定；只重新核验变化范围。最后使用：

```bash
python scripts/finalize_review.py --task-dir "<任务目录>"
```

它会核验建议覆盖率；遗漏计划时退出2并生成generation_requests.json，WorkBuddy应在交付之前修复。`--allow-incomplete`只适用于明确披露的旧报告迁移/失败诊断，不作为正常首次审查捷径。Python不会自动撰写法律条款或伪造模型检查。

质量请求的requests仅包含绑定过期或十项核验未完成的方案；bindings保留所有方案的原文、计划和校验绑定用于追溯，不代表必须重复调用模型。无修改且有明确理由的人工核实事项，不要求伪造修改后语义审查。

## 状态

ready是完整可确认的单处方案；editable_draft是有用的预审字段草案；needs_input缺必要事实；coordinated_review按整体展示多位置；manual_review是依据或可靠判断不足；generation_failed是生成/关联数据未完成。执行故障、结构错误、尚未核验和法律文本实质冲突分开记录，不将无法应用统称“发现明确冲突”。多位置方案另用can_apply判断是否可提交应用。

## 不往返调用模型的两种路径

1. 切换已经生成并核验的候选，不修改其内容，不需要模型再次分析。
2. 只填写预审过的事实字段。field_bindings规定id、question_id、edit_ids、kind(date/decimal/short_text)、semantic_effect=fact_only；数字有min/max，短文字有max_length。语义审查收据必须另有field_policy.approved及field_ids，并说明为什么该字段的允许取值不改变已审查的合同机制与法律范围。

模板标记为`{{field:id}}`，仅内部数据使用，网页显示可读的待填说明。用户确认事实后，字段填入受类型、范围、位置和完整组检查控制。materialization保留原模板和填写值，Python重新推导新文并核对，沿用原字段规则的语义记录，不声称做了新的法律语义审查。此途径不用于自行选择税率、报酬机制、责任划分、生效条件，或会改变适用法律期间的日期。无法证明是fact_only时不要声明field_policy可批准。

用户自由改写草案或改变实质条件时保留草稿；填写字段不能覆盖或丢弃自由改写。提交核验只处理该风险与受影响范围，必须先填完必填问题；保存草稿允许不完整并显示缺失数量。相同内容不创建新版本，也不使原来有效方案无故失效。

## 网页与文档操作

完善区嵌入所属卡片，同时只显示一个编辑区。筛选、搜索、收起卡片和Escape关闭不属于视图的区域，临时输入随修订JSON保存，重新打开恢复。关闭恢复焦点。正文人工编辑、拒绝建议和已核验计划独立，不自动认定风险解决。

局部操作保持原审核片段；同节点多处不重叠修改按倒序执行，整组预检和重放后提交。新记录execution_protocol=2；旧组记录按原合并协议校验兼容。导入时也检查实际组步骤是否等于计划，不只核验快照。

普通Word文字与正文Tab、换行可分开处理；保留实际分隔符及其XML属性，不允许普通文本编辑改变结构。段落Tab停靠点是格式声明，不是正文字符。旧解析器产生的虚拟前导Tab只在原文件、节点、未改动状态均可验证时迁移；旧计划范围受表示变化影响时必须复核。网页导入支持受控迁移，也可：

```bash
python scripts/migrate_revisions.py --task-dir "<重新解析的任务>" --revisions "<旧JSON>" --output "<新的JSON>"
```

迁移不覆盖旧文件、不接受旧Word修订、不等于法律复审。复杂字段、移动修订、分页/分栏换行和未支持的对象仍有具体限制；可在该段后插入补充条款，或交给WorkBuddy文档工具处理结构。旧独立HTML仍用原内嵌代码，需重新生成报告获得新流程。

完成编辑只显示紧凑交接，仍可继续编辑；再修改会使完成状态失效。保存区分未保存、已修改、发起下载、用户声明已保存、文件接口写入成功、失败及导入。普通下载不冒充已验证落盘。Word交接需标明原合同路径/散列、修订文件及恢复流程；只使用已确认修订生成新文件。
