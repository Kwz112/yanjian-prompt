const $ = id => document.getElementById(id);
let depth = '标准', busy = false, records = [], current = null, toastTimer;
try { const saved = JSON.parse(localStorage.getItem('yanjian-history') || '[]'); records = Array.isArray(saved) ? saved.filter(r => r && typeof r.input === 'string' && r.result && typeof r.result.prompt === 'string' && Array.isArray(r.result.changes) && Array.isArray(r.result.questions)).slice(0, 20) : []; } catch {}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 3000); }
async function api(path, data) {
  let response;
  try { response = await fetch('/api/' + path, data ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)} : {}); }
  catch { throw new Error('无法连接本地服务，请重新运行启动脚本。'); }
  const result = await response.json(); if (!response.ok) throw new Error(result.error || '请求失败，请重试。'); return result;
}
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function count() { $('count').textContent = `${$('prompt').value.length} / 12000`; }
function setDepth(value) { depth = value; document.querySelectorAll('[data-depth]').forEach(b => {b.classList.toggle('selected', b.dataset.depth === depth); b.setAttribute('aria-pressed', b.dataset.depth === depth);}); }
function render(result) {
  current = result; $('empty').hidden = true; $('result').hidden = false; $('output').value = result.prompt;
  $('result-meta').textContent = `${result.model || '历史记录'}${result.tokens ? ' · ' + result.tokens + ' tokens' : ''}`;
  for (const field of ['changes','questions']) { $(field).replaceChildren(); for (const line of result[field]) { const li = document.createElement('li'); li.textContent = line; $(field).append(li); } }
  $('questions-box').hidden = !result.questions.length;
}
function saveHistory() { try { localStorage.setItem('yanjian-history', JSON.stringify(records)); } catch { toast('浏览器存储不可用，历史记录仅在本次页面中保留。'); } $('history-count').textContent = records.length; }
async function models() {
  $('refresh-models').disabled = true;
  try { const data = await api('models'); const previous = $('model').value; $('model').replaceChildren(); for (const model of data.models) { $('model').add(new Option(model, model)); } if (data.models.includes(previous)) $('model').value = previous; else { const preferred = ['deepseek-flash','deepseek-chat','deepseek-v4-flash'].find(m => data.models.includes(m)); if (preferred) $('model').value = preferred; } if (!data.models.length) throw new Error('账号没有可用模型。'); $('status-text').textContent = 'DeepSeek 已连接'; document.body.classList.add('connected'); error(''); }
  catch (e) { $('status-text').textContent = '连接待检查'; document.body.classList.remove('connected'); error(e.message); throw e; }
  finally { $('refresh-models').disabled = false; }
}
async function run() {
  if (busy) return; if (!$('prompt').value.trim()) { toast('先写下你想优化的需求。'); $('prompt').focus(); return; } if (!$('model').value) { error('请先在连接设置中连接 DeepSeek 并加载模型。'); return; }
  const input = {prompt:$('prompt').value, context:$('context').value, scene:$('scene').value, depth, model:$('model').value};
  busy = true; error(''); $('optimize').disabled = true; $('loading').hidden = false; $('empty').hidden = true; $('result').hidden = true;
  document.querySelectorAll('#history-toggle,#reuse,#clear,[data-example],#settings,#connection').forEach(b => b.disabled = true);
  try { const result = await api('optimize', input); render(result); records.unshift({input:input.prompt, context:input.context, scene:input.scene, depth:input.depth, result, time:new Date().toISOString()}); records = records.slice(0,20); saveHistory(); }
  catch(e) { error(e.message); if (current) { $('result').hidden = false; } else $('empty').hidden = false; }
  finally { busy = false; $('optimize').disabled = false; $('loading').hidden = true; document.querySelectorAll('#history-toggle,#reuse,#clear,[data-example],#settings,#connection').forEach(b => b.disabled = false); }
}
$('prompt').addEventListener('input', count);
document.querySelectorAll('[data-depth]').forEach(b => b.onclick = () => setDepth(b.dataset.depth));
$('optimize').onclick = run;
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !document.querySelector('dialog[open]')) { e.preventDefault(); run(); } });
$('clear').onclick = () => { $('prompt').value = ''; $('context').value = ''; count(); $('prompt').focus(); };
const examples = {
  app:['网站 / 应用','我想做一个个人记账工具，能记录每天的收入和支出，按类别查看这个月的钱花在哪里。'],
  script:['自动化脚本','我想做一个整理下载文件夹的工具，按文件类型自动分类，先预览整理结果，再确认移动，避免覆盖同名文件。'],
  feature:['现有项目改进','我已经有一个任务管理项目，想增加按关键词搜索和按完成状态筛选的功能，保持现在的界面风格。']
};
document.querySelectorAll('[data-example]').forEach(b => b.onclick = () => { const [scene,prompt] = examples[b.dataset.example]; $('scene').value = scene; $('prompt').value = prompt; count(); $('prompt').focus(); });
$('copy').onclick = async () => { try { await navigator.clipboard.writeText($('output').value); toast('已复制，粘贴给开发 Agent 即可使用。'); } catch { $('output').focus(); $('output').select(); toast('请按 Ctrl+C 复制选中的提示词。'); } };
$('download').onclick = () => { const url = URL.createObjectURL(new Blob([$ ('output').value], {type:'text/markdown;charset=utf-8'})); const a = document.createElement('a'); a.href = url; a.download = '言简-Agent开发任务.md'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); };
$('reuse').onclick = () => { if ($('output').value.length > 12000) return toast('结果超过 12000 字，请先精简后再优化。'); $('prompt').value = $('output').value; count(); $('prompt').focus(); toast('已填入左侧，可补充要求后再次优化。'); };
for (const id of ['settings','connection']) $(id).onclick = () => { $('settings-message').textContent = ''; $('settings-dialog').showModal(); };
document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $(b.dataset.close).close());
$('settings-dialog').addEventListener('close', () => { $('api-key').value = ''; });
$('settings-form').onsubmit = async e => { e.preventDefault(); const button = e.submitter; button.disabled = true; $('settings-message').textContent = '正在连接…'; try { await api('settings', {key:$('api-key').value.trim()}); $('api-key').value = ''; await models(); $('settings-dialog').close(); toast('密钥已保存，连接成功。'); } catch (e) { $('settings-message').textContent = e.message; } finally { button.disabled = false; } };
$('refresh-models').onclick = () => models().catch(() => {});
function showHistory() { $('history-list').replaceChildren(); if (!records.length) { const p = document.createElement('p'); p.textContent = '还没有优化记录，开始你的第一次优化吧。'; $('history-list').append(p); } for (const r of records) { const b = document.createElement('button'); b.className = 'history-item'; const title = document.createElement('strong'); title.textContent = r.input; const small = document.createElement('small'); small.textContent = `${new Date(r.time).toLocaleString('zh-CN')} · ${r.scene || '通用任务'}`; b.append(title, small); b.onclick = () => { $('prompt').value = r.input; $('context').value = r.context || ''; $('scene').value = Array.from($('scene').options).some(o => o.value === r.scene) ? r.scene : '自动判断'; setDepth(r.depth || '标准'); render(r.result); error(''); count(); $('history-dialog').close(); }; $('history-list').append(b); } }
$('history-toggle').onclick = () => { showHistory(); $('history-dialog').showModal(); };
$('clear-history').onclick = () => { if (!records.length || !confirm('确定删除当前浏览器中保存的全部优化历史？')) return; records = []; saveHistory(); showHistory(); };
$('workspace').onclick = () => $('prompt').focus();
$('history-count').textContent = records.length;
api('status').then(s => { if (s.configured) return models(); $('status-text').textContent = '待配置密钥'; }).catch(e => error(e.message));
