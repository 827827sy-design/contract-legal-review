# 通用建议生成、关联分析与安全修改

这是 WorkBuddy 的模型审查工作流，不是固定合同条款模板。Python 只做确定性验证，不代替法律语义判断；HTML 执行器不推测修改意图。

## 首次分析与建议生成

读取解析主文、原生修订状态、已确认主体和视角、偏好来源，以及已检索法条。对每个风险明确原始原因、权利人/义务人、触发条件、必要修改条件及可能改变的利益分配。不要从风险编号、合同名称或条款编号推出处理方案。

生成 `contract_analysis`：

- `edges[]`：from、to（真实node_id）、relationship、source_quote、target_quote、reason、status（confirmed/uncertain）。引用、定义、条件依赖、付款/责任关系和权利保留均依据上下文分析；条号与关键词仅能作为线索，不能证明关系。两端quote须逐字对应节点。
- `obligations[]`：id、node_ids、holder、bearer、summary，记录有意义的权利义务及保留要求。
- 不确定的关系保持uncertain；不要为了通过校验填confirmed。图并不保证穷尽关系，语义审查必须检查未列出的主要关联。

单独判断：法律强制要求、企业制度、商务选择、用户经验。确认关键交易条件来源；缺少金额、日期、比例、条件等时，生成具体questions（可包含options与impact），询问用户。不要以“双方另行约定”或占位符代替已完成条款。待条件确认的动作可以有完整目标与原文，`draft_pending=true,replacement_text=null`；解释和问题只能放reason/questions，不进入正式文字。

`edit_plan`包含plan_id（独立稳定ID）、risk_id、reason、questions、business_terms、edits、required_edit_node_ids、postconditions、amount_records、related_risk_ids、source_revision_basis。见risk_schema.md。只有确需修改的节点放required_edit_node_ids；关联节点可以仅核查和保留，不要求无意义地重写。

业务terms每项包含id、value、confirmed、source；确认须来自真实用户或已明确提供的资料。不能把模型建议视作用户确认。涉及未接受Word修订时，先核对待审基准；provisional_current表示明确同意用当前显示文字作待审草稿，绝不表示接受或拒绝原修订。

逐一核查新增或改变的触发、审批、验收、通知、付款前置条件，在condition_changes记录node_id、before_quote、after_quote、effect（clarification/business_change/legal_requirement）、reason、source，新增商务选择需confirmed。以合同为来源时附source_node_id/source_quote。不要把“双方确认”等专业措辞悄悄作为新前置条件；声明为clarification也须真实语义核查，程序不能替模型判断该分类。

## 质量审查与缓存绑定

1. 生成风险及原始计划后运行validate_review.py。读取quality_requests.json中的raw_plan、plan_fingerprint、scope_node_hashes及完整预览；该文件只请求模型检查，不代表模型已执行。
2. WorkBuddy对计划修改后的完整文字及相关原文做语义审查。填入raw_plan的semantic_review，再写回review_draft.json相应edit_plan。reviewer为WorkBuddy，reviewed_at真实记录时间；使用请求中原样的fingerprint和scope_node_hashes，checked_node_ids覆盖实际核查范围。
3. checks必须逐项记录结果（pass/manual/conflict/insufficient）和具体理由，不能机械填全部pass：addresses_cause、removes_cause、related_consistency、no_duplicate_liability、preserves_rights、no_new_major_risk、business_complete、legal_scope、perspective_objective、scope_complete。
4. 再跑validate_review.py及render_report.py。计划、业务条件、风险原因、相关原文或依据改变后，旧语义记录失效；只重新检查受影响的关联范围。无关节点修改不强制重复整个合同审查，但模型仍须判断新修改是否引入未知关系。

审查应明确回答：修改是否对准原风险；导致风险的表述是否消除、是否有其他残留；是否与主要关联条款矛盾；报酬/赔偿是否重复；重要权利是否丢失；是否新增重大风险；商务条件是否完整；依据和事实是否足够；立场是否符合且不扭曲客观要求；范围是否充分。不可靠时用manual或insufficient。

不得从关键词匹配、位置校验或插入成功推导法律风险解决。postconditions中的present/absent仅检查模型指定的具体文字；权利被改写时应由语义审查核查，不能以相同词语仍在就宣称权利保留。

三法之外的专项问题仍需公开权威资料与实际事实核验；当前三法知识库不足时legal_scope必须manual或insufficient。不得把未入库法律写成已核验legal_basis，不得发送合同数据到网络。扩充法域或法律知识库是独立工作；新合同类型本身无需修改计划执行代码。

## 状态与执行

readiness由程序推导：ready（单处且条件完整）、needs_input（单处缺条件）、coordinated_review（多处需统一预览）、manual_review（依据或语义判断待复核）。多处计划只有can_apply=true才能经用户确认整组应用；标签“需关联修改”不等于可应用。ready只表示系统可执行性检查通过，不表示律师认可或效力保证。

正式文本与reason分离。括号中的合法定义、大写金额等不被自动删除；已知说明标签与未确认占位内容阻止应用。literal_bracket_terms只供真实字面术语使用，不能借此允许金额、日期、税率等关键占位。

所有修改前校验整组目标、完整节点原文和局部范围。局部动作可在同节点分属不重叠范围；重叠动作、整段与局部混用、同锚点顺序不明均拒绝。多个计划修改同一节点时，先执行的修改会使后续旧计划失效；需由WorkBuddy生成合并或更新计划，不猜测如何合并。

执行组记录plan_groups、完整计划快照和operation_ids；一个组必须整体应用、撤销、恢复和确认。运行时再核对相关文字；任一步不通过，原状态保留。原始文件不写入。删除条款是删除节点文字，保留段落/单元格结构，结构删除需文档工具另行处理。

补充输入保存在revisions.json的plan_drafts，含draft_id、原plan_fingerprint、answers、needs_regeneration。它与operations完全分开，不修改正文。返回WorkBuddy只重新生成受影响计划，确认输入来源并把input_draft_id绑定新计划；不能由网页填空后自动宣称法律审查完成。

应用后风险状态恒为needs_re_review。用户最终确认修改不等于风险已解决；真正的resolved须在新运行目录给出与当前节点文字绑定的semantic_post_review（十项判断、prior_risk_id、scope_node_hashes、reviewer、reviewed_at及未解决事项），缺少或过期则降为needs_confirmation。

旧JSON继续可解析、展示、编辑、保存和恢复。旧proposed_clause仅作为未核验建议显示，不再按第一条证据猜测应用范围。旧独立HTML仍使用其内嵌代码，要获得新质量约束必须重新生成报告；不能宣称旧文件已经获得新保护。

Word执行器仍只应用已确认修改，保留原始文件与原生修订。修改后的完整节点如含已知说明标签或关键占位，则拒绝作为完成稿导出；可以继续存为HTML/JSON待完善草稿。此检查不删括号，也不证明所有自然语言模糊条件已经被识别，遗漏须由语义审查核查。
