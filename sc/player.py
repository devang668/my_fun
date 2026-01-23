import os
import sys
import json
import webbrowser
from flask import Flask, send_file, jsonify, request

# ======================
# 🔧 配置区 —— 直接在这里修改你的本地音乐路径
# ======================
LOCAL_AUDIO_DIR = r"D:\Download\music-\music"  # 👈 你的本地音频文件夹（支持中文、空格、特殊符号）
CACHE_FILE = "last_github_url.txt"

# 自动创建目录（如果不存在）
os.makedirs(LOCAL_AUDIO_DIR, exist_ok=True)

# 内嵌 HTML 前端
HTML_CONTENT = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>智能 GitHub 音频播放器</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; background: #f5f5f5; max-width: 900px; margin: 0 auto; }
    h2 { text-align: center; color: #1a237e; }
    input { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }
    button { padding: 10px 16px; margin: 5px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1565c0; }
    .controls { display: flex; gap: 8px; flex-wrap: wrap; margin: 15px 0; }
    .error { color: #d32f2f; margin: 10px 0; }
    .track {
      padding: 12px; margin: 6px 0; background: white; border-radius: 6px; cursor: pointer;
      display: flex; justify-content: space-between;
    }
    .track:hover { background: #e8f5e9; }
    .track.playing { background: #c8e6c9; font-weight: bold; }
    .source-tag { font-size: 0.8em; color: #666; }
    audio { width: 100%; margin: 20px 0; }
    .mode-btn.active { background: #388e3c; }
  </style>
</head>
<body>
  <h2>🎧 智能 GitHub 音频播放器</h2>
  <input type="text" id="githubUrl" placeholder="粘贴 GitHub 文件夹链接，如 https://github.com/.../tree/main/audio" />
  <div class="controls">
    <button onclick="loadFromUrl()">加载音频</button>
    <button class="mode-btn" data-mode="stop" onclick="setPlayMode('stop')">播完停止</button>
    <button class="mode-btn" data-mode="single" onclick="setPlayMode('single')">单曲循环</button>
    <button class="mode-btn" data-mode="list" onclick="setPlayMode('list')">列表循环</button>
  </div>
  <div id="error" class="error"></div>
  <div id="playlist"></div>
  <audio id="player" controls></audio>

  <script>
    let currentPlayMode = 'stop';
    let trackList = [];
    let currentIndex = -1;

    window.addEventListener('DOMContentLoaded', async () => {
      try {
        const res = await fetch('/api/cache-url');
        const data = await res.json();
        if (data.url) {
          document.getElementById('githubUrl').value = data.url;
        }
      } catch (e) { console.warn('缓存加载失败'); }
      updateModeButtons();
    });

    function updateModeButtons() {
      document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === currentPlayMode);
      });
    }

    function setPlayMode(mode) {
      currentPlayMode = mode;
      updateModeButtons();
    }

    function isAudioFile(name) {
      const exts = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'];
      const lower = name.toLowerCase();
      return exts.some(ext => lower.endsWith(ext));
    }

    function parseGithubUrl(url) {
      const match = url.match(/^https:\\/\\/github\\.com\\/([^\\/]+)\\/([^\\/]+)\\/tree\\/([^\\/]+)(\\/.*?)?$/);
      if (!match) return null;
      return {
        owner: match[1],
        repo: match[2],
        branch: match[3],
        path: (match[4] || '').replace(/^\\/+/g, '')
      };
    }

    async function saveUrlToCache(url) {
      await fetch('/api/cache-url', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url})
      });
    }

    async function playTrack(index) {
      if (index < 0 || index >= trackList.length) return;
      const track = trackList[index];
      currentIndex = index;

      const localUrl = `/api/local-file/${encodeURIComponent(track.name)}`;
      const remoteUrl = track.download_url;

      const player = document.getElementById('player');
      player.src = localUrl;
      player.load();

      player.onerror = () => {
        console.log(`本地文件 ${track.name} 未找到，使用远程`);
        player.src = remoteUrl;
        player.play();
      };

      document.querySelectorAll('.track').forEach(t => t.classList.remove('playing'));
      document.querySelectorAll('.track')[index]?.classList.add('playing');

      try { player.play(); } catch (e) { console.warn('自动播放被阻止'); }
    }

    document.getElementById('player').addEventListener('ended', () => {
      if (currentPlayMode === 'single') {
        document.getElementById('player').currentTime = 0;
        document.getElementById('player').play();
      } else if (currentPlayMode === 'list' && trackList.length > 1) {
        const nextIndex = (currentIndex + 1) % trackList.length;
        playTrack(nextIndex);
      }
    });

    async function loadFromUrl() {
      const url = document.getElementById('githubUrl').value.trim();
      const errorDiv = document.getElementById('error');
      const playlistDiv = document.getElementById('playlist');
      errorDiv.textContent = '';
      playlistDiv.innerHTML = '';

      const parsed = parseGithubUrl(url);
      if (!parsed) {
        errorDiv.textContent = '❌ 无效的 GitHub 链接';
        return;
      }

      await saveUrlToCache(url);

      try {
        const apiUrl = `https://api.github.com/repos/${parsed.owner}/${parsed.repo}/contents/${parsed.path}?ref=${parsed.branch}`;
        const res = await fetch(apiUrl);
        if (!res.ok) throw new Error(`GitHub API: ${res.status}`);
        const files = await res.json();

        if (!Array.isArray(files)) {
          errorDiv.textContent = '⚠️ 路径不是目录';
          return;
        }

        trackList = files
          .filter(f => f.type === 'file' && isAudioFile(f.name))
          .map(f => ({ name: f.name, download_url: f.download_url }));

        if (trackList.length === 0) {
          playlistDiv.innerHTML = '<p>未找到音频文件</p>';
          return;
        }

        playlistDiv.innerHTML = `<p>共 ${trackList.length} 首 | 点击播放</p>`;
        trackList.forEach((track, i) => {
          const div = document.createElement('div');
          div.className = 'track';
          div.innerHTML = `<span>${track.name}</span><span class="source-tag">本地优先</span>`;
          div.onclick = () => playTrack(i);
          playlistDiv.appendChild(div);
        });

      } catch (err) {
        errorDiv.textContent = `❌ 加载失败: ${err.message}`;
      }
    }

    document.getElementById('githubUrl').addEventListener('keypress', e => {
      if (e.key === 'Enter') loadFromUrl();
    });
  </script>
</body>
</html>
'''

def create_app():
    app = Flask(__name__)

    @app.route('/')
    def index():
        return HTML_CONTENT

    @app.route('/api/local-file/<path:filename>')
    def serve_local_file(filename):
        safe_name = os.path.basename(filename)
        local_path = os.path.join(LOCAL_AUDIO_DIR, safe_name)
        if os.path.isfile(local_path):
            return send_file(local_path)
        else:
            return jsonify({"error": "Local file not found"}), 404

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

    return app

def main():
    print(f"📁 本地音频目录: {LOCAL_AUDIO_DIR}")
    print(f"💾 缓存文件: {os.path.abspath(CACHE_FILE)}")

    app = create_app()

    host = '127.0.0.1'
    port = 5000

    # 自动打开浏览器（可注释掉 if 不需要）
    try:
        webbrowser.open(f'http://{host}:{port}')
    except:
        pass  # 忽略浏览器打开失败

    print(f"\n🚀 启动成功！请访问: http://{host}:{port}")
    print("按 Ctrl+C 停止服务\n")

    app.run(host=host, port=port, debug=False)

if __name__ == '__main__':
    main()