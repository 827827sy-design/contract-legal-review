# contract-legal-review · 合同法律风险审查 Skill

供 AI agent 使用的中国境内合同审查技能。保留合同原文，通过本地 Python 脚本检索法律条文、校验引用与原文位置，生成可离线打开的单文件交互式 HTML 报告。

## 直接交给其他 agent

复制下面这段指令即可：

```text
请读取 https://raw.githubusercontent.com/827827sy-design/contract-legal-review/main/SKILL.md ，
按照这个 skill 审查我提供的合同。先下载完整仓库，并按需阅读 references/ 中的说明；
使用仓库中的 scripts/、law_index/ 和 assets/，将合同文件及审查产物保存在本地。
```

- [技能入口（网页）](https://github.com/827827sy-design/contract-legal-review/blob/main/SKILL.md)
- [技能入口（纯文本，适合 agent 读取）](https://raw.githubusercontent.com/827827sy-design/contract-legal-review/main/SKILL.md)
- [完整仓库 ZIP](https://github.com/827827sy-design/contract-legal-review/archive/refs/heads/main.zip)
- [Agent 文件索引](https://raw.githubusercontent.com/827827sy-design/contract-legal-review/main/llms.txt)

网页和纯文本入口都公开可读，无需 GitHub 登录。实际执行审查需要 agent 能读取本地文件、运行 Python，并自行形成结构化审查草稿；脚本负责解析、检索、机械校验与报告渲染。仅打开网站不会自动运行审查。

## 下载与运行

```bash
git clone https://github.com/827827sy-design/contract-legal-review.git
cd contract-legal-review
python --version
```

要求 Python 3.10+。Windows 可用 `python`，macOS/Linux 可按实际环境改为 `python3`。DOCX、TXT、MD 的解析和后续检索、校验、渲染只需要标准库。解析含文本层的 PDF 时额外安装：

```bash
python -m pip install -r requirements.txt
```

也可把完整仓库文件夹复制到你所用 agent 的技能目录，由该 agent 读取根目录的 `SKILL.md`。

```bash
# 在 skill 根目录运行；替换示例输入与任务目录
python scripts/extract_contract.py --input "/path/to/contract.docx" --task-dir "/path/to/review-task"
python scripts/search_law.py --index-dir law_index --list-topics
```

随后让 agent 按 [审查流程](SKILL.md) 和 [风险数据格式](references/risk_schema.md) 生成任务目录内的 `review_draft.json`。草稿完成后：

```bash
python scripts/validate_review.py --task-dir "/path/to/review-task" --index-dir law_index
python scripts/render_report.py --task-dir "/path/to/review-task"
```

用浏览器打开任务目录内的 `contract_review.html`。校验结果同时保存在 `verified_review.json`、`review_result.json`，各阶段日志保存在 `review_log.json`。

旧式二进制 DOC 需先转换为 DOCX；扫描 PDF 需先 OCR。解析失败时停止审查，部分解析时明确说明覆盖范围。

## 文件结构

```text
SKILL.md                    agent 的技能说明与工作流程
scripts/                    合同解析、法律检索、引用校验、报告渲染
references/                 风险 JSON 格式、核查清单、法律索引说明
law_index/                  三部法律的条文及主题索引
assets/report_template.html 单文件报告模板
requirements.txt            PDF 解析的可选依赖
llms.txt                    公开文件入口索引
```

## 审查范围与数据

随技能分发的法律索引记录《民法典》《劳动合同法（2012修正）》《公司法（2023修订）》三个版本，条数分别为 1260、98、266；具体来源、版本、采集时间与语料校验和见各 JSON 元数据和 [知识库说明](references/law_topics.md)。它们是随仓库分发的固定快照，不会自动更新。

技能在这三部法律的范围内识别法律合规风险、效力疑点、条款缺失和约定不明；其他法律法规、司法解释与外部事实作为待核实事项。引用与位置的机械校验只能证明其与本地语料及合同原文匹配，不能代替法律适用判断或人工核实。

合同及审查产物保存在本地，不上传第三方服务。请勿把真实合同、审查报告或任务目录提交到这个公开仓库；`.gitignore` 已排除常见产物目录与文件。

## License

技能说明、脚本和报告模板按 [MIT License](LICENSE) 发布。法律条文按各自来源及适用规则使用，MIT 许可不声称授予法律文本本身的权利。
