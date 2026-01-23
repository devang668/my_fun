import os
import json
from flask import Flask, send_file, jsonify, request

# ======================
# 🔧 配置区
# ======================
LOCAL_AUDIO_DIR = r"D:\Download\music-\music"  # 👈 修改为你的真实路径
CACHE_FILE = "last_github_url.txt"

os.makedirs(LOCAL_AUDIO_DIR, exist_ok=True)

# 支持的音频扩展名
AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}

def is_audio_file(filename):
    return os.path.splitext(filename)[1].lower() in AUDIO_EXTS

# ======================
# 本地文件树构建
# ======================
def build_local_tree(root_dir):
    tree = {}
    for dirpath, _, filenames in os.walk(root_dir):
        rel_path = os.path.relpath(dirpath, root_dir)
        if rel_path == '.':
            rel_path = ''
        node = tree
        if rel_path:
            for part in rel_path.split(os.sep):
                node = node.setdefault('dirs', {}).setdefault(part, {})
        node.setdefault('files', []).extend(
            f for f in filenames if is_audio_file(f)
        )
    return tree

# ======================
# GitHub 文件树构建（递归）
# ======================
import requests
def build_github_tree(owner, repo, branch, path="", current_depth=0, max_depth=5):
    if current_depth > max_depth:
        return {}
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            return {}
        items = resp.json()
        if not isinstance(items, list):
            return {}
        tree = {'dirs': {}, 'files': []}
        for item in items:
            name = item['name']
            if item['type'] == 'file' and is_audio_file(name):
                tree['files'].append(name)
            elif item['type'] == 'dir':
                subtree = build_github_tree(owner, repo, branch, item['path'], current_depth + 1, max_depth)
                if subtree:
                    tree['dirs'][name] = subtree
        return tree
    except Exception:
        return {}

# ======================
# 树转扁平路径集（用于快速比对）
# ======================
def flatten_tree(tree, prefix=""):
    paths = set()
    for f in tree.get('files', []):
        paths.add(os.path.join(prefix, f).replace('\\', '/'))
    for dirname, subtree in tree.get('dirs', {}).items():
        paths.update(flatten_tree(subtree, os.path.join(prefix, dirname)))
    return paths

# ======================
# 树转 HTML（递归）
# ======================
def tree_to_html(tree, base_path="", is_local=False):
    html = ""
    # 文件
    for f in sorted(tree.get('files', [])):
        full_path = os.path.join(base_path, f).replace('\\', '/')
        display_name = f + (" ↑" if not is_local and full_path in local_audio_paths else "")
        color = "green" if "↑" in display_name else "black"
        html += f'<div style="margin-left:20px;color:{color}">{display_name}</div>\n'
    # 目录
    for dirname in sorted(tree.get('dirs', {})):
        sub_base = os.path.join(base_path, dirname).replace('\\', '/')
        sub_html = tree_to_html(tree['dirs'][dirname], sub_base, is_local)
        if sub_html.strip():
            html += f'''
            <details>
              <summary>{dirname}/</summary>
              {sub_html}
            </details>
            '''
    return html

# ======================
# Flask App
# ======================
app = Flask(__name__)

@app.route('/')
def index():
    return HTML_CONTENT

@app.route('/api/local-file/<path:filename>')
def serve_local_file(filename):
    safe_name = os.path.basename(filename)
    # 注意：这里简化处理，实际应支持子目录
    local_path = os.path.join(LOCAL_AUDIO_DIR, filename)
    if os.path.isfile(local_path):
        return send_file(local_path)
    return jsonify({"error": "Not found"}), 404

@app.route('/api/cache-url', methods=['GET', 'POST'])
def handle_cache():
    if request.method == 'POST':
        data = request.get_json()
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            f.write(data.get('url', ''))
        return jsonify({"status": "saved"})
    else:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return jsonify({"url": f.read().strip()})
        return jsonify({"url": ""})

@app.route('/api/load-github-tree', methods=['POST'])
def load_github_tree():
    data = request.get_json()
    url = data.get('url', '')
    import re
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(/.*)?', url)
    if not match:
        return jsonify({"error": "Invalid URL"}), 400
    
    owner, repo, branch, path = match.groups()
    path = (path or '').lstrip('/')
    
    # 构建远程树
    github_tree = build_github_tree(owner, repo, branch, path)
    # 构建本地树（全局缓存用于标记）
    global local_audio_paths
    local_tree = build_local_tree(LOCAL_AUDIO_DIR)
    local_audio_paths = flatten_tree(local_tree)
    
    # 转 HTML
    github_html = tree_to_html(github_tree, path)
    local_html = tree_to_html(local_tree, "", is_local=True)
    
    return jsonify({
        "github_html": github_html or "<p>无音频文件</p>",
        "local_html": local_html or "<p>无音频文件</p>"
    })

# ======================
# HTML 前端（内嵌）
# ======================
HTML_CONTENT = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>GitHub + 本地 音频播放器</title>
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; }
    input { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; }
    button { padding: 10px 15px; margin: 5px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer; }
    .tree-container { margin-top: 20px; }
    .tree-title { font-weight: bold; margin-top: 20px; color: #1a237e; }
    details > summary { cursor: pointer; user-select: none; }
    audio { width: 100%; margin: 20px 0; }
    .error { color: red; }
  </style>
</head>
<body>
  <h2>🎧 GitHub + 本地 音频播放器</h2>
  <input type="text" id="githubUrl" placeholder="粘贴 GitHub 文件夹链接" />
  <button onclick="loadTrees()">加载音频树</button>
  <div id="error" class="error"></div>

  <div class="tree-container">
    <div class="tree-title">📁 GitHub 远程文件</div>
    <div id="github-tree"></div>
    
    <div class="tree-title">📁 本地音频文件</div>
    <div id="local-tree"></div>
  </div>

  <audio id="player" controls></audio>

  <script>
    let currentPlayMode = 'stop';
    let allFiles = {}; // { "relative/path.mp3": { local: true, remote_url: "..." } }

    // 初始化：加载缓存 URL
    window.addEventListener('DOMContentLoaded', async () => {
      try {
        const res = await fetch('/api/cache-url');
        const data = await res.json();
        if (data.url) document.getElementById('githubUrl').value = data.url;
      } catch (e) { console.warn(e); }
    });

    async function loadTrees() {
      const url = document.getElementById('githubUrl').value.trim();
      const errorDiv = document.getElementById('error');
      errorDiv.textContent = '';

      if (!url) {
        errorDiv.textContent = '请输入 GitHub 链接';
        return;
      }

      // 保存缓存
      await fetch('/api/cache-url', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url})
      });

      try {
        const res = await fetch('/api/load-github-tree', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({url})
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        document.getElementById('github-tree').innerHTML = data.github_html;
        document.getElementById('local-tree').innerHTML = data.local_html;

        // 绑定点击事件（委托）
        document.querySelectorAll('#github-tree div, #local-tree div')
          .forEach(el => {
            if (el.textContent.trim().endsWith('.mp3') || 
                el.textContent.trim().endsWith('.wav') ||
                el.textContent.trim().endsWith('.ogg') ||
                el.textContent.trim().endsWith('.m4a') ||
                el.textContent.trim().endsWith('.flac')) {
              const fullPath = el.textContent.replace(' ↑', '').trim();
              el.style.cursor = 'pointer';
              el.onclick = () => playFile(fullPath);
            }
          });

      } catch (err) {
        errorDiv.textContent = '❌ ' + err.message;
      }
    }

    function playFile(relativePath) {
      const player = document.getElementById('player');
      const localUrl = `/api/local-file/${encodeURIComponent(relativePath)}`;
      
      player.src = localUrl;
      player.load();
      player.onerror = () => {
        console.log('本地未找到，尝试远程...');
        // 这里简化：实际应从后端获取 remote_url，但为简化，假设用户只播本地或已知远程
        // 完整版可扩展
      };
      player.play().catch(e => console.warn('播放失败:', e));
    }
  </script>
</body>
</html>
'''

if __name__ == '__main__':
    print(f"📁 本地音频目录: {LOCAL_AUDIO_DIR}")
    app.run(host='127.0.0.1', port=5001, debug=False)