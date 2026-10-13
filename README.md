# 合同风险审查 Skill V2 / WorkBuddy

在 V1 的本地合同解析、三部法律索引、证据定位与机械核验上增量增加长期偏好、审查视角和固定离线编辑器。保留默认中立审查，合同正文不上传第三方。

将整个文件夹放在 WorkBuddy 的 skills 目录，保留 `SKILL.md`、scripts、references、assets、law_index。使用当前 WorkBuddy 可用的 Python 3.10+；只有 PDF 解析额外需要 requirements.txt 中的 pypdf。HTML 的 CSS、JS 与数据全部内嵌，无需 Node 或联网。

入口为 [SKILL.md](SKILL.md)，完整流程为 [V2 WorkBuddy 指南](references/v2_workflow.md)，协议为 [修订格式](references/revisions_schema.md)。用户可请求：

> 用 contract-legal-review 审查这份合同。首次确认长期偏好；默认中立。输出可离线编辑的审查报告，修改记录独立保存，原文件保留。

打开 HTML 后可编辑常见段落/单元格、应用建议、插入条款、撤销恢复、查看修订或清洁稿。必须主动保存并妥善保管 revisions.json；下载发起不等于保存成功。再次打开用导入恢复，或临时恢复后重新保存。

V2.1 支持继续编辑含普通 Word 插入/删除修订的段落，生成新 Word 时保留旧历史并追加原生修订，无需先接受旧修订。图片、字段、移动修订、段落合并等未支持结构显示具体限制原因。既有格式修订保留，网页只修改文字；修订模式展示本轮修改，完整旧修订仍在 Word 中。

通用建议质量整改保留现有版本号。WorkBuddy生成正式修改计划及语义关联分析，Python验证位置、原文、条件、冲突、占位、金额和审查记录绑定。缺业务条件或依据时不能应用。多处计划统一预览、确认、执行、撤销和保存；修改成功仍标记待复审。完整流程见 [通用质量工作流](references/quality_workflow.md)。旧建议继续展示，需重新生成计划才能获得新应用保护。

完整可用性整改仍保留2.1：首次审查统一生成多个候选并检查是否遗漏模型核验；已核验候选可本地切换，预审事实字段可受控填写。完善区在所属卡片内，筛选/收起/Escape保留草稿并同步关闭。真实正文Tab/换行可编辑普通文字；格式Tab停靠点不会算进正文。流程及迁移见 [首次生成与便捷修订](references/usability_workflow.md)，法律版本扩展见 [专业知识资源](references/knowledge_extensions.md)。

视角切换与修改后复审需要返回 WorkBuddy 真实重新分析；HTML 提供请求指令。最终 DOCX 由 WorkBuddy 读取原始合同与已确认修订生成新文件；浏览器没有 Word 导出或打印功能。

## 公开访问与其他 agent

- [SKILL.md 纯文本入口](https://raw.githubusercontent.com/827827sy-design/contract-legal-review/main/SKILL.md)
- [完整仓库下载](https://github.com/827827sy-design/contract-legal-review/archive/refs/heads/main.zip)
- [WorkBuddy 完整流程](https://github.com/827827sy-design/contract-legal-review/blob/main/references/v2_workflow.md)
- [Agent 文件索引](https://raw.githubusercontent.com/827827sy-design/contract-legal-review/main/llms.txt)

这些文件公开可读，无需登录。其他 agent 可读取 SKILL.md 并下载完整目录；运行仍需本地文件和 Python 能力。将上述技能入口交给 agent，并要求保留原始合同、单独保存修订记录。V2 的完成编辑和 AI 复审交接以 WorkBuddy 为目标宿主。

## 验证

开发测试使用 Python 标准库；浏览器测试额外需要本机 Playwright 与 Edge/Chromium，均不是 skill 的运行依赖。每轮测试使用独立虚构合同和偏好目录。

Windows PowerShell 示例：

```powershell
$env:CONTRACT_REVIEW_TEST_DIR = Join-Path $env:TEMP 'contract-review-v2-tests'
python -B -X utf8 tests/test_v2.py
python -B -X utf8 tests/test_tracked.py
python -B -X utf8 tests/test_plan_quality.py
python -B -X utf8 tests/test_unseen_quality.py
python -B -X utf8 tests/test_usability_core.py
python -B -X utf8 tests/test_usability_holdout.py
python -B -X utf8 tests/build_quality_fixtures.py
python -B -X utf8 tests/build_usability_fixtures.py
# 在已安装 Playwright 的开发环境执行，不需要 @playwright/test
node tests/browser_v2.cjs
node tests/browser_usability.cjs
```

浏览器测试默认使用 msedge；底层原有测试仍输出FIXTURES和latest-fixtures.txt。通用质量样本、结果与浏览器记录分别在CONTRACT_REVIEW_TEST_DIR的quality-browser、quality-fixture-results.json、quality-browser-results下。语义审查收据是明确的合成测试数据，不代表独立模型或律师评测。

原V2交付细节见 [V2_DELIVERY_REPORT.md](V2_DELIVERY_REPORT.md)；本次通用整改及实际测试边界见 [QUALITY_FIX_NOTES.md](QUALITY_FIX_NOTES.md)。MIT 许可覆盖说明、代码与模板；法律文本的来源及适用规则独立于代码许可。
