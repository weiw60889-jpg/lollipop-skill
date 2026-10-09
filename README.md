# Lollipop Skill

为 Codex 等支持 `SKILL.md` 的助手提供 Lollipop 面试报告读取能力。仅依赖 Python 标准库；正常读取通过网站实际使用的接口完成，无需反复打开页面。

## 安装

将本仓库放入技能目录中名为 `lollipop` 的文件夹，例如 `~/.codex/skills/lollipop`。在新会话中使用 `$lollipop`，也可直接请求读取 `lollipop.plus/report/...` 链接。

要求 Python 3.10+。首次浏览器绑定需要已安装 [agent-browser](https://github.com/vercel-labs/agent-browser)。安装后使用 `python scripts/lollipop.py --help` 查看命令。

## 首次连接

```text
python scripts/lollipop.py login
# 在打开的浏览器中自行登录，然后：
python scripts/lollipop.py login --capture
python scripts/lollipop.py status --verify
```

也可绑定已有已登录的 agent-browser 会话：

```text
python scripts/lollipop.py bind-browser --session your-session
```

默认自动选择该会话中现有的 Lollipop 标签页。保存授权前会验证它确实有效。后续读取直接使用本机缓存；授权过期或撤销后才需要重新登录。密码不用发送给助手。

## 日常使用

```text
python scripts/lollipop.py history
python scripts/lollipop.py report https://lollipop.plus/report/REPORT_UUID --output report.json
python scripts/lollipop.py answers https://lollipop.plus/report/REPORT_UUID --output answers.md
python scripts/lollipop.py logout
```

`answers` 原样保留网站的参考答案，包含其中的占位符和示例数据。它们不是用户真实工作经历的证明。未生成、锁定或字段缺失时命令会报出缺项，不会编造内容。导出包含面试私人信息，保存位置由用户指定，请勿提交到公共仓库。

授权元数据位于本机应用数据目录，与技能分开。Windows 使用 DPAPI；macOS 使用钥匙串；Linux 使用 secret-tool，缺少系统凭证服务时可以只通过环境变量 `LOLLIPOP_TOKEN` 提供授权。令牌不会打印。`LOLLIPOP_AUTH_DIR` 可覆盖元数据路径。

## 飞书回填

本技能负责 Lollipop 读取，飞书写入沿用目标环境已有的已授权连接或浏览器。安装技能不会自动登录第三方服务，也不会获得文档权限。回填时逐题匹配原始提问、避免重复，并重新打开文档核实保存结果。

## 开发与验证

```text
python -m unittest discover -s tests -v
```

使用网站当前的内部只读接口，不是官方 SDK；接口变化可能需要更新。仓库不包含账户凭证、私人报告、浏览器状态或抓包记录。
