import os
import json
from flask import Flask, send_file, jsonify, request
import requests

# ======================
# 🔧 配置区
# ======================
LOCAL_AUDIO_DIR = r"D:\Download\music-\music"
CACHE_FILE = "last_github_url.txt"
AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}

os.makedirs(LOCAL_AUDIO_DIR, exist_ok=True)

def is_audio_file(filename):
    return os.path.splitext(filename)[1].lower() in AUDIO_EXTS

# ======================
# 构建本地文件映射：basename -> 相对路径
# ======================
def build_local_basename_map(root_dir):
    basename_map = {}
    tree = {}
    for dirpath, _, filenames in os.walk(root_dir):
        rel_path = os.path.relpath(dirpath, root_dir)
        if rel_path == '.':
            rel_path = ''
        node = tree
        if rel_path:
            for part in rel_path.split(os.sep):
                node = node.setdefault('dirs', {}).setdefault(part, {})
        audio_files = [f for f in filenames if is_audio_file(f)]
        node.setdefault('files', []).extend(audio_files)
        for f in audio_files:
            if f not in basename_map:
                basename_map[f] = os.path.join(rel_path, f).replace('\\', '/')
    return tree, basename_map

# ======================
# GitHub 树（不变）
# ======================
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
# 树转 HTML（支持缩写、tooltip、图标）
# ======================
def truncate_name(name, max_len=5):
    if len(name) <= max_len:
        return name
    return name[:max_len] + '...'

def tree_to_html(tree, base_path="", basename_map=None, is_local=False):
    html = ""
    for f in sorted(tree.get('files', [])):
        display_name = truncate_name(f)
        full_rel_path = os.path.join(base_path, f).replace('\\', '/')
        
        if is_local:
            # 本地文件
            data_attr = f'data-path="{full_rel_path}"'
            icon = "📁"  # 或用 emoji
        else:
            # 远程文件
            if basename_map and f in basename_map:
                local_full_path = basename_map[f]
                data_attr = f'data-path="{local_full_path}" style="color:green"'
                display_name += " ↑"
                icon = "🎵"  # 绿色音符表示本地有缓存
            else:
                data_attr = f'data-path="" style="color:gray; cursor:not-allowed"'
                display_name += " (无本地)"
                icon = "🌍"  # 表示纯远程
        
        html += f'<div class="audio-item" {data_attr} title="{f}">{icon} {display_name}</div>\n'
    
    for dirname in sorted(tree.get('dirs', {})):
        sub_base = os.path.join(base_path, dirname).replace('\\', '/')
        sub_html = tree_to_html(tree['dirs'][dirname], sub_base, basename_map, is_local)
        if sub_html.strip():
            html += f'''
            <details>
              <summary>📁 {dirname}/</summary>
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
    
    local_tree, basename_map = build_local_basename_map(LOCAL_AUDIO_DIR)
    github_tree = build_github_tree(owner, repo, branch, path)
    
    github_html = tree_to_html(github_tree, path, basename_map, is_local=False)
    local_html = tree_to_html(local_tree, "", None, is_local=True)
    
    return jsonify({
        "github_html": github_html or "<p>无音频文件</p>",
        "local_html": local_html or "<p>无音频文件</p>"
    })

# ======================
# HTML 前端（酷狗风格布局）
# ======================
HTML_CONTENT = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>GitHub + 本地 音频播放器</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      margin: 0;
      padding: 0;
      background: #f5f5f5;
      color: #333;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .header {
      padding: 15px 20px;
      background: white;
      border-bottom: 1px solid #ddd;
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .header input {
      flex: 1;
      padding: 8px 12px;
      border: 1px solid #ccc;
      border-radius: 4px;
      font-size: 14px;
    }
    .header button {
      padding: 8px 16px;
      background: #1976d2;
      color: white;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    }
    .header button:hover {
      background: #1565c0;
    }
    .main-content {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
    }
    .panel {
      flex: 1;
      min-width: 300px;
      max-width: 50%;
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
      padding: 15px;
      overflow-y: auto;
    }
    .panel-title {
      font-weight: bold;
      color: #1a237e;
      margin-top: 0;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .panel-title::before {
      content: "📁";
      font-size: 18px;
    }
    .audio-item {
      padding: 8px 12px;
      margin: 4px 0;
      border-radius: 4px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      transition: background 0.2s;
    }
    .audio-item:hover {
      background: #e3f2fd;
    }
    .audio-item[style*="cursor:not-allowed"] {
      opacity: 0.7;
      cursor: not-allowed;
    }
    .audio-item[style*="color:green"] {
      color: green;
    }
    .audio-item[style*="color:green"]::before {
      content: "🎵";
      color: green;
    }
    .audio-item[style*="color:gray"]::before {
      content: "🌍";
      color: gray;
    }
    .audio-item::before {
      content: "📁";
      font-size: 16px;
    }
    .footer {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: white;
      border-top: 1px solid #ddd;
      padding: 10px 20px;
      display: flex;
      align-items: center;
      gap: 10px;
      z-index: 1000;
      box-shadow: 0 -2px 4px rgba(0,0,0,0.1);
    }
    .footer audio {
      flex: 1;
    }
    .error {
      color: red;
      margin: 10px 0;
      padding: 8px;
      background: #ffebee;
      border-radius: 4px;
    }
  </style>
</head>
<body>
  <div class="header">
    <input type="text" id="githubUrl" placeholder="粘贴 GitHub 文件夹链接，如 https://github.com/devang668/my_fun/tree/main/soft" />
    <button onclick="loadTrees()">加载音频树</button>
  </div>

  <div id="error" class="error" style="display:none"></div>

  <div class="main-content">
    <div class="panel">
      <h3 class="panel-title">GitHub 远程文件</h3>
      <div id="github-tree"></div>
    </div>
    <div class="panel">
      <h3 class="panel-title">本地音频文件</h3>
      <div id="local-tree"></div>
    </div>
  </div>

  <div class="footer">
    <audio id="player" controls></audio>
  </div>

  <script>
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
      errorDiv.style.display = 'none';
      errorDiv.textContent = '';

      if (!url) {
        errorDiv.textContent = '请输入 GitHub 链接';
        errorDiv.style.display = 'block';
        return;
      }

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

        // 绑定点击事件
        document.querySelectorAll('.audio-item').forEach(el => {
          const path = el.getAttribute('data-path');
          if (path && path !== "") {
            el.onclick = () => {
              const player = document.getElementById('player');
              player.src = `/api/local-file/${encodeURIComponent(path)}`;
              player.play().catch(e => {
                console.warn('播放失败:', e);
                alert('播放失败，请检查文件是否存在或权限。');
              });
            };
          }
        });

      } catch (err) {
        errorDiv.textContent = '❌ ' + err.message;
        errorDiv.style.display = 'block';
      }
    }
  </script>
</body>
</html>
'''

if __name__ == '__main__':
    print(f"📁 本地音频目录: {LOCAL_AUDIO_DIR}")
    app.run(host='127.0.0.1', port=5001, debug=False)