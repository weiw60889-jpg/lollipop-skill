---
name: lollipop
description: 直接读取 Lollipop（lollipop.plus）的面试历史、报告及每题原文参考答案，复用本机授权状态。适用于 Lollipop/lolipop 报告提取、面试复盘、补回参考答案和向文档同步记录。
---

# Lollipop 面试报告连接

使用本技能的 Python 客户端直接读取已授权账户的报告。先复用本机授权；仅授权缺失或过期时请用户在浏览器登录。脚本只读，不启动面试、不消耗生成额度、不修改账户或报告。

命令中的 `<skill-dir>` 替换为本技能目录的绝对路径。依赖 Python 3.10+；首次绑定浏览器需要 `agent-browser`。

## 连接与登录

1. 先运行 `python "<skill-dir>/scripts/lollipop.py" status --verify`。
2. 如未授权，检查现有的 Lollipop 浏览器会话。已有已登录的 agent-browser 会话时，绑定它：
   `python "<skill-dir>/scripts/lollipop.py" bind-browser --session <existing-session>`
   脚本只在 `https://lollipop.plus` 域读取 `lp_auth_token`，本地加密/保护保存，不输出令牌。
3. 如没有可绑定的已登录会话，运行 `python "<skill-dir>/scripts/lollipop.py" login` 打开专用浏览器，请用户在网页输入账号密码。完成后运行同一命令并添加 `--capture`。它会保存授权，后续读报告不再依赖该浏览器。默认会话名为 `lollipop-skill`；不要误操作别的任务的浏览器。
4. 401/403 时说明授权可能失效，停止连续重试，按以上方式重新绑定。不能承诺永不登录：服务端授权撤销、令牌过期或更换电脑均可能需要再次登录。

## 读取与原文导出

```text
python "<skill-dir>/scripts/lollipop.py" history
python "<skill-dir>/scripts/lollipop.py" report <report-url-or-uuid> --output "<work-dir>/report.json"
python "<skill-dir>/scripts/lollipop.py" answers <report-url-or-uuid> --output "<output-dir>/answers.md"
```

`history` 默认返回面试元数据和报告链接，不导出全部对话。命令参数可以是报告链接或其中的 UUID。该网站的 `/report/<UUID>` 页面及 `/api/reports/<UUID>` 接口实际使用 **session_id**；响应中的 `report_id` 是不同的内部 ID。从历史跳转时使用脚本生成的 `report_url`，不要误用响应的内部 `report_id`。

原文参考答案取自 `report_data.qa_reviews[].reference_answer`，题目、我的回答与拆解依次为 `question`、`answer`、`review_summary`。保留原始题序、文字、数字、占位符和结束语，不能把示例数字当成用户真实经历。遇到未生成、锁定、缺失字段或题数不符时报告具体缺项，不能自行生成替代答案冒充原文。内部接口非官方公开 API，结构变化时停止并重新核实。

## 同步到飞书或其他文档

先查看当前环境实际可用的目标文档技能与连接；文件夹存在不代表技能完整安装，至少需要有效的 `SKILL.md`。技能是工作说明，不等同于已授权连接。优先采用已授权 API/连接器；否则复用目标文档已有浏览器登录。

用户要求“补回每题参考答案”时，先以完整提问匹配对应题，在该题“本轮拆解”之后插入“参考答案”与原文。保留原题、用户回答及拆解。每题检查是否已存在相同答案，避免重复；同题已有不同答案时先检查来源，不能直接覆盖。最后重新读取已保存文档，核对题数、逐题文字与顺序。仅提取文件不等于已经完成文档回填。

## 授权存放

授权默认保存在用户本机应用数据目录的 `lollipop-skill/auth.json`，与技能目录和 Git 仓库分开。Windows 使用当前用户的 DPAPI 加密；macOS 使用系统钥匙串；Linux 使用系统 secret-tool，如系统密钥服务不可用可在运行时提供 `LOLLIPOP_TOKEN`，不落盘。可用 `LOLLIPOP_AUTH_DIR` 改变授权元数据目录。

不要在消息、日志、Git、技能文件、HAR 或导出报告里附带密码、令牌或浏览器状态。退出连接使用 `python "<skill-dir>/scripts/lollipop.py" logout`，只删除本地缓存授权，不退出网页账户。
