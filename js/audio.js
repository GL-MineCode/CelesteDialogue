// 语音与 UI 音效。使用 <audio>（file:// 下 fetch/decodeAudioData 会被 CORS 拦截）。
(function () {
  const D = window.CelesteDemo;

  function voiceKey(event, expression) {
    return `${event}|${expression}`;
  }

  function voiceFile(event, expression) {
    const name = event.split('/').pop();
    return `vo_${name}_${expression}`;
  }

  // file:// 下 <audio src="*.wav"> 会被浏览器拦载，优先用提取脚本生成的 base64。
  function resolveAudio(root, name) {
    const assets = D.assets || {};
    if (assets.audio && assets.audio[name]) return assets.audio[name];
    return `${root}/audio/${name}.wav`;
  }

  class DialogAudio {
    constructor(assetRoot) {
      this.root = assetRoot;
      this.voices = new Map();   // key -> { el, target }
      this.ui = new Map();       // name -> el
      this.loops = new Map();    // 'phone_static_ex' -> el
      this.activeKey = null;
      this.unlocked = false;
      this.voiceVolume = 1;
      this.uiVolume = 0.9;
      this.loopVolume = 0.85;

      this.phonestaticName = '';
      this.phonestaticTarget = 0;
    }

    registerVoice(event, expression) {
      const key = voiceKey(event, expression);
      if (this.voices.has(key)) return key;

      const el = new Audio(resolveAudio(this.root, voiceFile(event, expression)));
      el.preload = 'auto';
      el.loop = true;
      el.volume = 0;
      el.addEventListener('error', () => {
        console.warn(`[audio] 语音缺失：${el.src}`);
      });
      this.voices.set(key, { el, target: 0 });
      return key;
    }

    registerUI(name) {
      if (this.ui.has(name)) return;
      const el = new Audio(resolveAudio(this.root, name));
      el.preload = 'auto';
      el.volume = 0;
      el.addEventListener('error', () => {
        console.warn(`[audio] 音效缺失：${el.src}`);
      });
      this.ui.set(name, el);
    }

    /** 电话杂音这类循环层（提取脚本输出 loop_<name>.wav） */
    registerLoop(name) {
      if (this.loops.has(name)) return;
      const el = new Audio(resolveAudio(this.root, `loop_${name}`));
      el.preload = 'auto';
      el.loop = true;
      el.volume = 0;
      el.addEventListener('error', () => {
        console.warn(`[audio] 循环音缺失：${el.src}`);
      });
      this.loops.set(name, el);
    }

    /** 对应 Textbox.cs 的 phonestatic.Play / Stop(true)；name 取 Portraits.xml 的 phonestatic（ex/mom） */
    setPhonestatic(name) {
      const key = name ? `phone_static_${name}` : '';
      const el = key ? this.loops.get(key) : null;
      this.phonestaticName = key;
      if (el) {
        if (el.paused) {
          el.currentTime = 0;
          const promise = el.play();
          if (promise && promise.catch) promise.catch(() => {});
        }
        this.phonestaticTarget = this.loopVolume;
      } else {
        this.phonestaticTarget = 0;
      }
    }

    // 浏览器要求首次播放必须发生在用户手势里。
    // 这里让语音循环以 0 音量一直跑，之后只调节音量，门控更平滑、也没有重启接缝。
    unlock() {
      if (this.unlocked) return;
      this.unlocked = true;
      const all = [...this.voices.values()].map((v) => v.el)
        .concat([...this.ui.values()])
        .concat([...this.loops.values()]);
      for (const el of all) {
        el.volume = 0;
        const promise = el.play();
        if (promise && promise.catch) promise.catch(() => {});
      }
    }

    startTalker(event, expression) {
      const key = this.registerVoice(event, expression);
      if (this.activeKey === key) {
        this.setTarget(key, this.voiceVolume);
        return;
      }
      if (this.activeKey) this.setTarget(this.activeKey, 0);
      this.activeKey = key;

      const voice = this.voices.get(key);
      if (!voice) return;
      if (voice.el.paused) {
        voice.el.currentTime = 0;
        const promise = voice.el.play();
        if (promise && promise.catch) promise.catch(() => {});
      }
      this.setTarget(key, this.voiceVolume);
    }

    stopTalker() {
      if (this.activeKey) this.setTarget(this.activeKey, 0);
    }

    setTarget(key, target) {
      const voice = this.voices.get(key);
      if (voice) voice.target = target;
    }

    playUI(name) {
      const el = this.ui.get(name);
      if (!el) return;
      el.currentTime = 0;
      el.volume = this.uiVolume;
      const promise = el.play();
      if (promise && promise.catch) promise.catch(() => {});
    }

    update(dt) {
      const step = dt * 14; // 约 70ms 完成 0→1
      for (const voice of this.voices.values()) {
        const el = voice.el;
        const target = voice.target;
        if (Math.abs(el.volume - target) <= step) {
          el.volume = target;
        } else {
          el.volume += Math.sign(target - el.volume) * step;
        }
      }

      // 电话杂音：淡入/淡出，避免 Stop 时的爆音
      for (const [name, el] of this.loops) {
        const target = (name === this.phonestaticName) ? this.phonestaticTarget : 0;
        const loopStep = dt * 10;
        if (Math.abs(el.volume - target) <= loopStep) {
          el.volume = target;
        } else {
          el.volume += Math.sign(target - el.volume) * loopStep;
        }
      }
    }
  }

  D.DialogAudio = DialogAudio;
  D.voiceKey = voiceKey;
})();
