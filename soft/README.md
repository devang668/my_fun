
# 这里有我喜欢的

逝去的秋天

潇湘子-王志文对话-李老师

潇湘子-王志文独白


```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>GitHub 音频播放器 - 一键加载</title>
  <style>
    body { font-family: Arial, sans-serif; padding: 20px; background: #f9f9f9; max-width: 800px; margin: 0 auto; }
    h2 { color: #333; text-align: center; }
    input { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; }
    button { padding: 10px 20px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1565c0; }
    .error { color: red; margin-top: 10px; }
    .track {
      padding: 10px;
      margin: 6px 0;
      background: white;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.2s;
    }
    .track:hover { background: #e3f2fd; }
    .track.playing { background: #bbdefb; font-weight: bold; }
    #playlist { margin-top: 20px; }
    audio { width: 100%; margin-top: 20px; }
  </style>
</head>
<body>
  <h2>GitHub 音频播放器</h2>
  <p>粘贴 GitHub 文件夹链接（必须是 <code>/tree/</code> 开头的路径）</p>
  
  <input type="text" id="githubUrl" placeholder="例如：https://github.com/devang668/my_fun/tree/main/soft" value="" />
  <button onclick="loadFromUrl()">加载音频</button>
  
  <div id="error" class="error"></div>
  <div id="playlist"></div>
  <audio id="player" controls></audio>

  <script>
    const audioExts = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma'];

    function isAudioFile(name) {
      const lower = name.toLowerCase();
      return audioExts.some(ext => lower.endsWith(ext));
    }

    function parseGithubUrl(url) {
      // 支持 https://github.com/user/repo/tree/branch/path
      const match = url.match(/^https:\/\/github\.com\/([^\/]+)\/([^\/]+)\/tree\/([^\/]+)(\/.*)?$/);
      if (!match) return null;
      return {
        owner: match[1],
        repo: match[2],
        branch: match[3],
        path: (match[4] || '').replace(/^\/+/, '') // 去掉开头的斜杠
      };
    }

    async function loadFromUrl() {
      const urlInput = document.getElementById('githubUrl').value.trim();
      const errorDiv = document.getElementById('error');
      const playlistDiv = document.getElementById('playlist');
      errorDiv.textContent = '';
      playlistDiv.innerHTML = '';

      const parsed = parseGithubUrl(urlInput);
      if (!parsed) {
        errorDiv.textContent = '❌ 请提供有效的 GitHub 文件夹链接（格式：https://github.com/用户名/仓库名/tree/分支/路径）';
        return;
      }

      const { owner, repo, branch, path } = parsed;
      playlistDiv.innerHTML = '<p>正在加载音频文件列表...</p>';

      try {
        // GitHub API 获取目录内容
        const apiUrl = `https://api.github.com/repos/${owner}/${repo}/contents/${path}?ref=${branch}`;
        const res = await fetch(apiUrl);
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
        }
        const data = await res.json();

        if (!Array.isArray(data)) {
          errorDiv.textContent = '⚠️ 该路径不是有效目录（可能指向单个文件）';
          playlistDiv.innerHTML = '';
          return;
        }

        const audioFiles = data
          .filter(item => item.type === 'file' && isAudioFile(item.name))
          .map(item => ({ name: item.name, url: item.download_url }));

        if (audioFiles.length === 0) {
          playlistDiv.innerHTML = '<p>📁 未找到支持的音频文件（支持格式：mp3, wav, ogg, m4a, flac 等）</p>';
          return;
        }

        playlistDiv.innerHTML = `<p>✅ 找到 ${audioFiles.length} 个音频文件：</p>`;
        const player = document.getElementById('player');

        audioFiles.forEach(file => {
          const div = document.createElement('div');
          div.className = 'track';
          div.textContent = file.name;
          div.onclick = () => {
            document.querySelectorAll('.track').forEach(t => t.classList.remove('playing'));
            div.classList.add('playing');
            player.src = file.url;
            player.play().catch(e => console.warn('播放失败:', e));
          };
          playlistDiv.appendChild(div);
        });

      } catch (err) {
        console.error(err);
        errorDiv.textContent = `❌ 加载失败：${err.message || err}`;
        playlistDiv.innerHTML = '';
      }
    }

    // 回车触发
    document.getElementById('githubUrl').addEventListener('keypress', (e) => {
      if (e.key === 'Enter') loadFromUrl();
    });
  </script>
</body>
</html>
```
