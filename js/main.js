// 入口：加载资源 -> 解析对话 -> 驱动 Textbox/立绘/音频/渲染。
(function () {
  'use strict';

  const D = window.CelesteDemo;
  const C = D.config;
  const assets = D.assets || {};

  const overlay = document.getElementById('overlay');
  const canvas = document.getElementById('stage');
  const debugEl = document.getElementById('debug');

  const params = new URLSearchParams(window.location.search);
  const playerName = params.get('name') || C.playerName;
  const debug = params.get('debug') === '1';

  function showOverlay(html, isError) {
    overlay.innerHTML = `<div class="panel">${html}</div>`;
    overlay.classList.toggle('error', !!isError);
    overlay.classList.add('visible');
  }

  function hideOverlay() {
    overlay.classList.remove('visible');
  }

  const missing = [];
  if (!assets.manifest) missing.push('assets/celeste/manifest.js');
  if (!assets.font) missing.push('assets/celeste/fonts/chinese.js');
  if (!assets.portraits) missing.push('assets/celeste/portraits.js');
  if (!assets.dialogScenes) missing.push('assets/celeste/dialog/scenes.js');

  if (missing.length > 0) {
    showOverlay(
      '<h1>缺少提取资源</h1>'
      + '<p>下面这些文件不存在：</p>'
      + `<ul>${missing.map((m) => `<li><code>${m}</code></li>`).join('')}</ul>`
      + '<p>请在仓库根目录先运行 <code>tools\\extract_all.cmd</code>（需要本机安装 Celeste）。</p>',
      true,
    );
    return;
  }

  const scenes = (assets.dialogScenes && assets.dialogScenes.scenes) || [];
  const language = (assets.dialogScenes && assets.dialogScenes.language) || {};

  function sceneById(id) {
    return scenes.find((scene) => scene.id === id) || scenes[0];
  }

  let currentScene = sceneById(params.get('scene') || C.scene || (scenes[0] && scenes[0].id));

  let font;
  let renderer;
  let audio;
  let layout;
  let portraitBank = {};
  let noiseSprite = null;

  function portraitNamesForScene(scene) {
    const names = new Set();
    for (const use of scene.portraitUsage || []) {
      if (use.sprite && assets.portraits[use.sprite]) names.add(use.sprite);
    }
    return [...names];
  }

  (async function boot() {
    try {
      font = await D.loadPixelFont(
        C.assetRoot, assets.font, assets.manifest.files.font.texture);

      const lineHeight = font.lineHeight - 1;
      const linesPerPage = Math.floor(240 / lineHeight);
      const innerTextPadding = (C.textboxHeight - lineHeight * linesPerPage) / 2;
      const maxLineWidthNoPortrait = C.textboxWidth - innerTextPadding * 2;
      const maxLineWidth = maxLineWidthNoPortrait - C.portraitWidth - C.portraitGap;
      layout = { lineHeight, linesPerPage, innerTextPadding, maxLineWidth, maxLineWidthNoPortrait };

      audio = new D.DialogAudio(C.assetRoot);
      const allNames = new Set();
      for (const scene of scenes) {
        for (const use of scene.portraitUsage || []) {
          if (use.event) audio.registerVoice(use.event, use.expression);
          if (use.sprite) allNames.add(use.sprite);
        }
      }
      for (const name of allNames) {
        const info = assets.portraits[name];
        if (info && info.phonestatic) audio.registerLoop(`phone_static_${info.phonestatic}`);
      }
      for (const name of [
        'ui_textbox_madeline_in', 'ui_textbox_madeline_out',
        'ui_textbox_other_in', 'ui_textbox_other_out',
      ]) {
        audio.registerUI(name);
      }

      renderer = new D.Renderer(canvas);
      portraitBank = await D.loadPortraitBank([...allNames], assets.portraits, C.assetRoot);
      noiseSprite = await D.loadNoise(assets.portraits._noise, C.assetRoot);
      await renderer.load(C.assetRoot, assets.manifest);
    } catch (err) {
      console.error(err);
      showOverlay(
        '<h1>启动失败</h1>'
        + `<p>${String(err.message || err)}</p>`
        + '<p>如果资源不完整，请重新运行 <code>tools\\extract_all.cmd</code>。</p>',
        true,
      );
      return;
    }

    const input = { confirmPressed: false, cancelPressed: false };
    let textbox = null;
    let started = false;
    let last = 0;
    let pressCount = 0;
    let startCalls = 0;
    let overlayClicks = 0;
    let sceneSwitches = 0;
    let startError = null;

    function createTextbox(scene) {
      const group = D.FancyText.parse({
        text: scene.text,
        maxLineWidth: layout.maxLineWidth,
        linesPerPage: layout.linesPerPage,
        startFade: 0,
        language,
        font,
        portraits: assets.portraits,
        playerName,
      });
      return new D.Textbox({
        group,
        font,
        layout,
        audio,
        input,
        portraits: portraitBank,
        noise: noiseSprite,
        events: {},
      });
    }

    function markInput(isCancel) {
      if (!started) return;
      pressCount++;
      if (isCancel) input.cancelPressed = true;
      else input.confirmPressed = true;
      renderer.hintVisible = false;
    }

    function start() {
      if (started) return;
      started = true;
      startCalls++;
      try {
        audio.unlock();          // 必须在用户手势里同步调用
        hideOverlay();
        textbox = createTextbox(currentScene);
        last = performance.now();
        requestAnimationFrame(frame);
      } catch (err) {
        startError = String(err && err.stack ? err.stack : err);
        console.error(err);
      }
    }

    function switchScene(id) {
      const next = sceneById(id);
      if (!next) return;
      currentScene = next;
      sceneSwitches++;
      // 换场景相当于重新开一个文本框，先把上一段的声音收干净
      audio.stopTalker();
      audio.setPhonestatic('');
      input.confirmPressed = false;
      input.cancelPressed = false;
      textbox = createTextbox(next);
      renderer.hintVisible = false;
      if (!started) {
        start();
      } else {
        last = performance.now();
      }
    }

    function updateDebug() {
      debugEl.style.display = 'block';
      debugEl.textContent = [
        `scene=${currentScene.id}`,
        `page=${textbox.page}`,
        `index=${textbox.index}/${textbox.group.nodes.length}`,
        `ease=${textbox.ease.toFixed(2)}`,
        `wait=${textbox.waitingForInput}`,
        `voice=${audio.activeKey || '-'}`,
        `portrait=${textbox.portrait ? textbox.portrait.sprite : '-'}`
          + (textbox.portraitSprite && textbox.portraitSprite.currentId
            ? `/${textbox.portraitSprite.currentId}` : ''),
        `phone=${audio.phonestaticName || '-'}`,
      ].join('  ');
    }

    function frame(now) {
      let dt = (now - last) / 1000;
      last = now;
      if (!(dt > 0)) dt = 1 / 60;
      dt = Math.min(dt, 0.05);

      if (textbox.closed && (input.confirmPressed || input.cancelPressed)) {
        audio.stopTalker();
        audio.setPhonestatic('');
        textbox = createTextbox(currentScene);
        // 重播的那一次点击不应该继续被新文本框消费掉
        input.confirmPressed = false;
        input.cancelPressed = false;
      }

      textbox.update(dt);
      audio.update(dt);
      renderer.render(textbox, dt);
      if (textbox.closed) renderer.drawEndCard(renderer.ctx);

      if (debug) updateDebug();

      input.confirmPressed = false;
      input.cancelPressed = false;
      requestAnimationFrame(frame);
    }

    window.addEventListener('keydown', (event) => {
      if (event.repeat) return;

      // 数字键切换场景
      const digit = /^(Digit|Numpad)([1-9])$/.exec(event.code);
      if (digit) {
        const index = Number(digit[2]) - 1;
        if (index < scenes.length) {
          event.preventDefault();
          switchScene(scenes[index].id);
          return;
        }
      }

      if (event.code === 'Space' || event.code === 'Enter' || event.code === 'NumpadEnter') {
        event.preventDefault();
        markInput(false);
      } else if (event.code === 'Escape') {
        markInput(true);
      } else if (event.code === 'KeyR' && started) {
        audio.stopTalker();
        audio.setPhonestatic('');
        textbox = createTextbox(currentScene);
      }
    });

    canvas.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      markInput(event.button === 2);
    });
    canvas.addEventListener('contextmenu', (event) => event.preventDefault());

    window.__demo = {
      get textbox() { return textbox; },
      get input() { return input; },
      get pressCount() { return pressCount; },
      get startCalls() { return startCalls; },
      get overlayClicks() { return overlayClicks; },
      get sceneSwitches() { return sceneSwitches; },
      get startError() { return startError; },
      get started() { return started; },
      get scene() { return currentScene; },
      get portraitBank() { return portraitBank; },
      scenes,
      switchScene,
      audio,
      renderer,
      layout,
    };

    const sceneButtons = scenes.map((scene, index) => (
      `<button type="button" class="scene" data-scene="${scene.id}">`
      + `<span class="num">${index + 1}</span>`
      + `<span class="name">${scene.title}</span>`
      + `<span class="src">${scene.subtitle}</span>`
      + '</button>'
    )).join('');

    showOverlay(
      '<h1>Celeste · 对话复刻</h1>'
      + '<p class="sub">原版文本 / 字体 / 立绘 / 音效（简体中文）</p>'
      + `<div class="scenes">${sceneButtons}</div>`
      + '<p class="small">空格 / 回车 / 点击：继续　·　对话中按一次可跳至本页末尾</p>'
      + '<p class="small">键盘 <code>1</code>~<code>'
      + `${scenes.length}</code> 随时切换场景　·　<code>R</code> 重播当前场景</p>`,
      false,
    );

    overlay.addEventListener('click', (event) => {
      event.preventDefault();
      overlayClicks++;
      const button = event.target.closest ? event.target.closest('[data-scene]') : null;
      if (button) {
        switchScene(button.getAttribute('data-scene'));
      } else {
        start();
      }
    });
  })();
})();
