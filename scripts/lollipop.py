#!/usr/bin/env python3
"""Read-only Lollipop client; credentials stay in the user's local secret store."""

import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

ORIGIN = "https://lollipop.plus"
SECRET_NAME = "lollipop-skill"
DEFAULT_SESSION = "lollipop-skill"


class ClientError(Exception):
    pass


def auth_path():
    custom = os.environ.get("LOLLIPOP_AUTH_DIR")
    if custom:
        root = Path(custom).expanduser()
    elif os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / SECRET_NAME
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support" / SECRET_NAME
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / SECRET_NAME
    return root / "auth.json"


def valid_token(token):
    return isinstance(token, str) and 0 < len(token) < 32768 and not any(c.isspace() for c in token)


def dpapi(data, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        success = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        success = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not success:
        raise ClientError("无法使用当前 Windows 用户解密/保存授权，请重新绑定登录。")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)


def secret_command(args, input_text=None):
    try:
        p = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientError("本机系统凭证服务不可用，请使用运行时环境变量 LOLLIPOP_TOKEN。") from exc
    if p.returncode:
        raise ClientError("系统凭证操作失败，请重新绑定或使用运行时环境变量 LOLLIPOP_TOKEN。")
    return p.stdout.strip()


def save_token(token):
    if not valid_token(token):
        raise ClientError("浏览器尚未提供有效授权，请先完成登录。")
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        record = {"version": 1, "store": "dpapi", "encrypted": base64.b64encode(dpapi(token.encode())).decode()}
    elif sys.platform == "darwin":
        # Use interactive stdin so a token never appears in a process argument.
        escaped = token.replace("\\", "\\\\").replace('"', '\\"')
        command = f'add-generic-password -U -a current -s {SECRET_NAME} -w "{escaped}"\n'
        secret_command(["security", "-i"], command)
        record = {"version": 1, "store": "keychain"}
    else:
        if not shutil.which("secret-tool"):
            raise ClientError("Linux 缺少 secret-tool；请安装系统凭证服务或使用 LOLLIPOP_TOKEN，不保存明文令牌。")
        secret_command(["secret-tool", "store", "--label=Lollipop Skill", "service", SECRET_NAME, "account", "current"], token)
        record = {"version": 1, "store": "secret-service"}
    fd, temporary = tempfile.mkstemp(prefix="auth-", suffix=".tmp", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_token():
    token = os.environ.get("LOLLIPOP_TOKEN")
    if token is not None:
        if not valid_token(token):
            raise ClientError("LOLLIPOP_TOKEN 格式无效。")
        return token
    path = auth_path()
    if not path.exists():
        raise ClientError("尚未连接。请运行 login 或绑定已有会话：bind-browser --session <会话名>。")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("store") == "dpapi" and os.name == "nt":
            token = dpapi(base64.b64decode(record["encrypted"], validate=True), decrypt=True).decode()
        elif record.get("store") == "keychain" and sys.platform == "darwin":
            token = secret_command(["security", "find-generic-password", "-a", "current", "-s", SECRET_NAME, "-w"])
        elif record.get("store") == "secret-service" and sys.platform != "darwin" and os.name != "nt":
            token = secret_command(["secret-tool", "lookup", "service", SECRET_NAME, "account", "current"])
        else:
            raise ClientError("授权缓存来自其他系统或格式已失效，请重新绑定。")
    except (OSError, ValueError, KeyError, UnicodeError) as exc:
        raise ClientError("授权缓存不可读，请重新绑定。") from exc
    if not valid_token(token):
        raise ClientError("缓存中没有有效授权，请重新绑定。")
    return token


def remove_token():
    path = auth_path()
    if path.exists():
        try:
            store = json.loads(path.read_text(encoding="utf-8")).get("store")
        except (ValueError, OSError):
            store = None
        if store == "keychain" and sys.platform == "darwin":
            secret_command(["security", "delete-generic-password", "-a", "current", "-s", SECRET_NAME])
        elif store == "secret-service" and os.name != "nt":
            secret_command(["secret-tool", "clear", "service", SECRET_NAME, "account", "current"])
        path.unlink()


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError("接口返回重定向，已停止请求以避免授权发送到其他地址。")


class LollipopClient:
    def __init__(self, token):
        if not valid_token(token):
            raise ClientError("授权格式无效。")
        self.token = token
        self.opener = build_opener(NoRedirects())

    def get(self, path):
        if not re.fullmatch(r"/api/(auth/profile|history|reports/[0-9a-f-]{36})", path):
            raise ClientError("仅支持已核实的 Lollipop 只读接口。")
        req = Request(ORIGIN + path, headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"}, method="GET")
        for attempt in range(3):
            try:
                with self.opener.open(req, timeout=30) as response:
                    data = json.load(response)
                return data
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise ClientError("Lollipop 授权失效或没有读取权限，请重新登录绑定。") from exc
                if exc.code == 404:
                    raise ClientError("找不到报告，请检查链接或报告 ID。") from exc
                if exc.code in (502, 503, 504) and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise ClientError(f"Lollipop 接口返回 HTTP {exc.code}，请稍后再试。") from exc
            except (URLError, TimeoutError) as exc:
                raise ClientError("无法连接 Lollipop，请检查网络后重试。") from exc
            except (ValueError, UnicodeError) as exc:
                raise ClientError("接口返回格式已变化或服务暂不可用。") from exc


def report_id(value):
    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc != "lollipop.plus":
            raise ClientError("报告链接必须来自 https://lollipop.plus。")
        match = re.fullmatch(r"/report/([0-9a-fA-F-]{36})/?", parsed.path)
        if not match:
            raise ClientError("报告链接路径应为 /report/<UUID>。")
        value = match.group(1)
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ClientError("报告 ID 必须是有效 UUID。") from exc


def answers_markdown(report, identifier):
    if not isinstance(report, dict) or report.get("status") != "completed":
        raise ClientError("报告尚未完成生成，不能导出完整参考答案。")
    data = report.get("report_data")
    if not isinstance(data, dict) or not isinstance(data.get("qa_reviews"), list):
        raise ClientError("报告缺少 qa_reviews，可能受权限限制或接口结构已变化。")
    reviews = data["qa_reviews"]
    count = data.get("question_count")
    if not reviews or not isinstance(count, int) or isinstance(count, bool) or count != len(reviews):
        raise ClientError("题数与报告声明不一致或没有题目，请先核对报告完整性。")
    sections = ["# Lollipop 面试参考答案（原文）", "", f"来源：{ORIGIN}/report/{identifier}", ""]
    missing = []
    seen = set()
    for number, review in enumerate(reviews, 1):
        if not isinstance(review, dict):
            raise ClientError(f"第 {number} 题结构无效。")
        key = review.get("question_id")
        if not isinstance(key, str) or not key or key in seen:
            raise ClientError(f"第 {number} 题 ID 缺失或重复。")
        seen.add(key)
        question = review.get("question")
        answer = review.get("reference_answer")
        if not isinstance(question, str) or not question.strip() or not isinstance(answer, str) or not answer.strip():
            missing.append(str(number))
            continue
        sections += [f"## 第 {number} 题", "", "面试官提问：" + question, "", "**参考答案**", "", answer, ""]
    if missing:
        raise ClientError("这些题目缺少原文提问或参考答案：" + ", ".join(missing) + "。没有生成替代内容。")
    return "\n".join(sections), len(reviews)


def browser(args):
    executable = shutil.which("agent-browser")
    if not executable:
        raise ClientError("首次绑定需要 agent-browser；请先安装，或通过 LOLLIPOP_TOKEN 在运行时提供授权。")
    try:
        p = subprocess.run([executable, *args, "--json"], capture_output=True, text=True, encoding="utf-8", timeout=45)
        result = json.loads(p.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ClientError("无法连接指定浏览器会话，请检查 agent-browser 会话是否仍在运行。") from exc
    if p.returncode or not result.get("success"):
        raise ClientError("浏览器操作失败，请检查会话和当前页面。")
    return result.get("data", {})


def bind_browser(session):
    listing = browser(["--session", session, "tab", "list"])
    tabs = listing.get("tabs", [])
    suitable = [tab for tab in tabs if urlparse(tab.get("url", "")).scheme == "https" and urlparse(tab.get("url", "")).netloc == "lollipop.plus"]
    if not suitable:
        raise ClientError("该会话没有 Lollipop 页面；请先运行 login，并在网页完成登录。")
    tab = next((tab for tab in suitable if tab.get("active")), suitable[0])
    browser(["--session", session, "tab", tab["tabId"]])
    script = "(()=>{if(location.origin!=='https://lollipop.plus')return null;const raw=localStorage.getItem('lp_auth_token');try{const value=JSON.parse(raw);return typeof value==='string'?value:null}catch{return raw}})()"
    encoded = base64.b64encode(script.encode()).decode()
    token = browser(["--session", session, "eval", "-b", encoded]).get("result")
    if not valid_token(token):
        raise ClientError("网页还未登录或授权已失效，请在 Lollipop 网页登录后再次绑定。")
    LollipopClient(token).get("/api/auth/profile")
    save_token(token)


def write_output(path, text):
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="直接读取 Lollipop 面试报告；首次授权后复用本机安全缓存。")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="检查本机授权；不输出令牌")
    status.add_argument("--verify", action="store_true", help="请求服务端验证授权")
    login = commands.add_parser("login", help="首次打开登录网页；--capture 保存已登录授权")
    login.add_argument("--session", default=DEFAULT_SESSION)
    login.add_argument("--capture", action="store_true")
    bind = commands.add_parser("bind-browser", help="绑定已有已登录浏览器会话")
    bind.add_argument("--session", required=True)
    history = commands.add_parser("history", help="读取历史元数据，不导出全部对话")
    history.add_argument("--output")
    for name in ("report", "answers"):
        sub = commands.add_parser(name, help="读取报告 JSON" if name == "report" else "导出每题原文参考答案 Markdown")
        sub.add_argument("report")
        sub.add_argument("--output", required=True)
    commands.add_parser("logout", help="移除本地授权缓存，不退出网页账户")
    args = parser.parse_args(argv)
    try:
        if args.command == "logout":
            remove_token()
            print("已移除本地缓存。若设置了 LOLLIPOP_TOKEN，请另行取消环境变量。")
        elif args.command == "status":
            token = load_token()
            if args.verify:
                LollipopClient(token).get("/api/auth/profile")
            print(json.dumps({"connected": True, "verified": args.verify}, ensure_ascii=False))
        elif args.command == "bind-browser":
            bind_browser(args.session)
            print("已验证并保存本机授权；后续可直接读报告，无需浏览器。")
        elif args.command == "login":
            if args.capture:
                bind_browser(args.session)
                print("已验证并保存本机授权。")
            else:
                try:
                    LollipopClient(load_token()).get("/api/auth/profile")
                    print("已有有效授权，无需重复登录。")
                    return 0
                except ClientError:
                    pass
                browser(["--session", args.session, "--headed", "open", ORIGIN + "/auth/login"])
                print("请在打开的网页登录。完成后运行：login --capture --session " + args.session)
        elif args.command == "history":
            items = LollipopClient(load_token()).get("/api/history")
            if not isinstance(items, list):
                raise ClientError("历史记录结构已变化。")
            keys = ("session_id", "status", "job_title", "company_name", "duration_minutes", "started_at", "ended_at", "report_status")
            metadata = [{key: item.get(key) for key in keys if key in item} for item in items if isinstance(item, dict)]
            if len(metadata) != len(items):
                raise ClientError("历史记录含无效项目。")
            for item in metadata:
                if isinstance(item.get("session_id"), str):
                    item["report_url"] = ORIGIN + "/report/" + report_id(item["session_id"])
            text = json.dumps(metadata, ensure_ascii=False, indent=2)
            if args.output:
                write_output(args.output, text)
                print(f"已保存 {len(metadata)} 条面试历史元数据。")
            else:
                print(text)
        else:
            identifier = report_id(args.report)
            report = LollipopClient(load_token()).get("/api/reports/" + identifier)
            if args.command == "report":
                if not isinstance(report, dict):
                    raise ClientError("报告返回结构无效。")
                write_output(args.output, json.dumps(report, ensure_ascii=False, indent=2))
                print("已保存原始报告 JSON。")
            else:
                text, count = answers_markdown(report, identifier)
                write_output(args.output, text)
                print(f"已保存 {count} 题原文参考答案。")
        return 0
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("本地文件操作失败，请检查保存路径与权限。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
