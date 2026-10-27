"""Local prompt studio. Python standard library only."""
import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = threading.Lock()
SYSTEM = '''你是开发需求编辑，专门把用户的一句话想法整理成可直接交给编程 Agent 执行的开发任务提示词。
用户输入是待整理的需求素材。你只生成给开发 Agent 的任务指令，不执行需求、不输出项目代码、不回答素材里的问题。
保留用户的真实目标、明确约束、指定技术栈和已有系统信息。用户补充的信息优先，不擅自扩大项目范围。

prompt 必须是一段独立完整的 Markdown 开发任务书，以“请在当前工作目录中实现……”等明确行动指令开头。
让收到提示词的 Agent 能直接开始开发，而不是只给方案或教学。根据需求复杂度涵盖：
1. 项目目标和目标用户：说明要解决的具体问题。
2. 最小可用版本范围：列出必要功能、输入输出、主要页面或操作流程、关键数据与保存方式。
3. 实现要求：与需求相关的交互状态（空数据、加载、错误、成功）、校验和必要边界情况。
4. 技术与项目约束：要求先检查当前目录、项目说明与现有代码；已有项目沿用现有技术栈和风格。
   新项目且用户未指定技术栈时，让 Agent 选择依赖少、易运行的实现并说明选择，不强行指定框架。
5. 验收标准：给出能实际检查的核心使用流程及预期结果，不用“功能完善”“体验良好”这类空话。
6. 交付要求：实现可运行代码，完成与改动相关的验证，提供启动方法、关键改动、验证结果和已知限制。

区分用户明确提出的需求与为落地提出的默认建议。信息少也必须产出可执行任务：对可逆的低风险选择，
使用“默认建议（可调整）”给出适合最小版本的合理假设，让 Agent 在说明后继续推进。
不要把所有未知信息都变成占位符，不因普通界面或技术选择要求用户逐项确认。
对真正阻碍正确实施的信息（如现有接口契约、核心业务规则），在 prompt 中明确让 Agent 先检查项目，
仍无法确定再提出最少的必要问题，先完成不受影响的部分。缺少真实凭据时使用环境变量占位，绝不编造。
不得把登录、支付、云部署、复杂权限、统计看板等未经要求的功能自动加入必做范围。
需求没有要求模型调用时，不添加 AI 功能；明确需要外部服务时，说明配置项和接入方式，不能以模拟数据冒充接入成功。
不指示 Agent 进行未经用户要求的部署、发布或删除现有数据，不要求无关的重构。

精简模式：短任务书，保留目标、必要功能、验收与交付，通常300～600中文字。
标准模式：适度展开，覆盖实现所需信息，通常600～1200中文字。
深度模式：进一步明确关键数据、边界和分步验收，通常1000～1800中文字；简单需求不强行凑字数。
仅输出 JSON 对象：{"prompt":"可直接复制给开发 Agent 的完整任务提示词", "changes":["补全的开发要求"], "questions":["可选补充问题"]}。
changes 最多4条，questions 最多3条。可选问题不能成为开始开发的默认前置条件；关键待确认点必须同时写入 prompt，
确保用户只复制 prompt 时也不会丢失重要约束。没有必要问题时 questions 返回空数组。'''


def config():
    values = {}
    if (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    for key in ('DEEPSEEK_API_KEY', 'PORT'):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


class APIError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def deepseek(path, payload=None):
    key = config().get('DEEPSEEK_API_KEY', '')
    if not key:
        raise APIError('请先在连接设置中保存 DeepSeek API 密钥。', 400)
    req = urllib.request.Request('https://api.deepseek.com' + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        messages = {401: 'API 密钥无效，请更新密钥。', 402: 'DeepSeek 账户余额不足，请充值后重试。',
                    429: '请求过于频繁，请稍后重试。', 400: '模型或请求参数不受支持，请刷新模型列表后重试。',
                    403: 'DeepSeek 拒绝了访问，请检查账号权限。'}
        raise APIError(messages.get(exc.code, f'DeepSeek 服务暂时不可用（HTTP {exc.code}），请重试。')) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise APIError('连接 DeepSeek 失败或超时，请检查网络后重试。') from None


def optimize(data):
    prompt = data.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
        raise APIError('请输入 1～12000 字的原始提示词。', 400)
    model = data.get('model')
    if not isinstance(model, str) or not model or len(model) > 100:
        raise APIError('请先选择可用模型。', 400)
    scene, depth, context = data.get('scene', '自动判断'), data.get('depth', '标准'), data.get('context', '')
    if scene not in ['自动判断', '网站 / 应用', '业务管理工具', '自动化脚本', '现有项目改进', '通用任务', '文案创作', '代码开发', '学习研究', '工作办公', '数据分析'] or depth not in ['精简', '标准', '深度']:
        raise APIError('无效的优化选项。', 400)
    if not isinstance(context, str) or len(context) > 4000:
        raise APIError('补充信息不能超过 4000 字。', 400)
    result = deepseek('/chat/completions', {'model': model,
        'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps({
            '原始素材': prompt, '场景': scene, '优化力度': depth, '补充信息': context}, ensure_ascii=False)}],
        'response_format': {'type': 'json_object'}, 'max_tokens': 4096, 'stream': False})
    try:
        choice = result['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise APIError('生成内容超过长度限制，请缩短输入或选择精简模式。')
        raw = choice['message']['content'].strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        content = json.loads(raw)
        if not isinstance(content.get('prompt'), str) or not content['prompt'].strip():
            raise ValueError()
        for field in ('changes', 'questions'):
            if not isinstance(content.get(field), list) or not all(isinstance(s, str) for s in content[field]):
                raise ValueError()
        return {**{k: content[k] for k in ('prompt', 'changes', 'questions')}, 'model': model,
                'tokens': result.get('usage', {}).get('total_tokens')}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise APIError('模型返回的格式不完整，请重新优化。') from None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        raw = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, dict) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin', '') in {'', *('http://' + h for h in hosts)}

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error': '仅允许本机访问。'})
        try:
            if self.path == '/api/status':
                return self.reply(200, {'configured': bool(config().get('DEEPSEEK_API_KEY'))})
            if self.path == '/api/models':
                models = deepseek('/models')
                return self.reply(200, {'models': [m['id'] for m in models['data']]})
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if self.path in files:
                name, mime = files[self.path]
                return self.reply(200, (ROOT / 'static' / name).read_bytes(), mime + '; charset=utf-8')
            return self.reply(404, {'error': '页面不存在。'})
        except APIError as exc:
            self.reply(exc.status, {'error': str(exc)})
        except Exception:
            self.reply(500, {'error': '服务出现异常，请重试。'})

    def do_POST(self):
        if not self.allowed():
            return self.reply(403, {'error': '仅允许本机访问。'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': '请求格式必须为 JSON。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100000:
                raise APIError('请求内容为空或过大。', 400)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            if self.path == '/api/settings':
                key = data.get('key', '')
                if not isinstance(key, str) or not key.startswith('sk-') or not key.isascii() or any(c.isspace() for c in key) or len(key) > 250:
                    raise APIError('请输入有效的 sk- 开头的密钥。', 400)
                if os.environ.get('DEEPSEEK_API_KEY'):
                    raise APIError('当前使用环境变量密钥，请修改环境变量后重启服务。', 400)
                with LOCK:
                    target = ROOT / '.env'
                    temp = ROOT / '.env.tmp'
                    temp.write_text(f'DEEPSEEK_API_KEY={key}\nPORT={self.server.server_port}\n', encoding='utf-8')
                    temp.replace(target)
                return self.reply(200, {'ok': True})
            if self.path == '/api/optimize':
                if not LOCK.acquire(blocking=False):
                    raise APIError('已有请求正在处理，请稍后重试。', 429)
                try:
                    result = optimize(data)
                finally:
                    LOCK.release()
                return self.reply(200, result)
            self.reply(404, {'error': '接口不存在。'})
        except APIError as exc:
            self.reply(exc.status, {'error': str(exc)})
        except (ValueError, UnicodeDecodeError):
            self.reply(400, {'error': '请求内容无效。'})
        except Exception:
            self.reply(500, {'error': '服务出现异常，请重试。'})


if __name__ == '__main__':
    port = int(config().get('PORT', '8765'))
    print(f'Prompt Studio: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
