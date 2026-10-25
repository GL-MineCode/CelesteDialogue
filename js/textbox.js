// Textbox.cs 的状态机移植：逐帧协程 + 跳过 + 开合动画 + 语音门控。
(function () {
  const D = window.CelesteDemo;
  const FT = D.FancyText;
  const C = D.config;

  class Coroutine {
    constructor(generator) {
      this.generator = generator;
      this.done = false;
      this.wait = 0;
    }

    update(dt) {
      if (this.done) return;
      if (this.wait > 0) {
        this.wait -= dt;
        if (this.wait > 0) return;
      }
      const result = this.generator.next();
      if (result.done) {
        this.done = true;
        return;
      }
      if (typeof result.value === 'number' && result.value > 0) {
        this.wait = result.value;
      }
      // yield null：本次 Update 结束，下一帧继续
    }
  }

  class Textbox {
    constructor(options) {
      this.group = options.group;
      this.font = options.font;
      this.layout = options.layout;
      this.audio = options.audio;
      this.input = options.input;
      this.events = options.events || {};
      this.portraits = options.portraits || {};   // 立绘资源库（info + images）
      this.noise = options.noise || null;         // glitchy 叠层（NoiseSprite）

      this.index = 0;
      this.start = 0;
      this.page = 0;

      this.ease = 0;
      this.gradientFade = 0;
      this.anchor = 'Top';
      this.portrait = null;
      this.portraitExists = false;
      this.textboxName = 'default';
      this.textboxOverlay = null;

      // 立绘相关（对应 Textbox.cs 的字段）
      this.portraitSprite = null;
      this.portraitIdling = false;
      this.portraitScale = 1.5;
      this.portraitWiggle = new D.Wiggler(0.4, 4);
      this.isPortraitGlitchy = false;
      this.glitchSprite = null;

      this.waitingForInput = false;
      this.disableInput = false;
      this.canSkip = true;
      this.easingOpen = false;
      this.easingClose = false;
      this.isInTrigger = false;
      this.autoPressContinue = false;

      this.timer = 0;
      this.lastChar = 0;
      this.opened = true;
      this.closed = false;
      this._dt = 0;

      this.runRoutine = new Coroutine(this.run());
      this.skipRoutine = new Coroutine(this.skipDialog());
    }

    get lineHeight() { return this.layout.lineHeight; }
    get linesPerPage() { return this.layout.linesPerPage; }
    get innerTextPadding() { return this.layout.innerTextPadding; }
    get maxLineWidth() { return this.layout.maxLineWidth; }
    get maxLineWidthNoPortrait() { return this.layout.maxLineWidthNoPortrait; }

    continuePressed() {
      return (this.input.confirmPressed || this.input.cancelPressed) && !this.disableInput;
    }

    isMadelinePortrait() {
      return !!(this.portrait && this.portrait.sprite
        && this.portrait.sprite.toLowerCase().indexOf('madeline') >= 0);
    }

    startTalker() {
      if (this.portrait && this.portrait.event) {
        this.audio.startTalker(this.portrait.event, this.portrait.expression);
      }
    }

    playTalkAnimation() {
      this.startTalker();
      if (this.portraitIdling && this.portraitSprite && this.portrait
        && this.portraitSprite.has(this.portrait.talkAnimation)) {
        this.portraitSprite.play(this.portrait.talkAnimation, false);
        this.portraitIdling = false;
      }
    }

    playIdleAnimation() {
      this.audio.stopTalker();
      if (!this.portraitIdling && this.portraitSprite && this.portrait
        && this.portraitSprite.has(this.portrait.idleAnimation)) {
        this.portraitSprite.play(this.portrait.idleAnimation, false);
        this.portraitIdling = true;
      }
    }

    /** 换立绘：创建 Sprite 并播放 begin_ 或 idle_ 动画（对应 Textbox.cs 的 Portrait 分支）。 */
    applyPortrait(next) {
      this.audio.setPhonestatic('');

      const prev = this.portrait;
      this.textboxName = 'default';
      this.textboxOverlay = null;
      this.portraitExists = false;
      this.isPortraitGlitchy = false;

      if (next.sprite && next.info) {
        this.portraitExists = true;
        this.isPortraitGlitchy = !!next.glitchy;
        if (this.isPortraitGlitchy && this.noise) {
          this.glitchSprite = this.noise;
        }
      }
      if (!this.portraitExists) {
        this.portrait = null;
        this.portraitSprite = null;
        return false;
      }

      const bank = this.portraits[String(next.sprite).toLowerCase()];
      if (prev == null || prev.sprite !== next.sprite) {
        if (bank) {
          this.portraitSprite = new D.PortraitSprite(bank.info, bank.images);
          this.portraitScale = C.portraitWidth / (bank.info.size || 160);
        } else {
          this.portraitSprite = null;
        }
        this.portraitIdling = false;
      }

      this.textboxName = next.info.textbox || 'default';
      this.textboxOverlay = `${this.textboxName}_overlay`;
      this.audio.setPhonestatic(next.info.phonestatic || '');

      this.portrait = next;
      if (next.pop) this.portraitWiggle.start();

      const changed = prev == null
        || prev.sprite !== next.sprite
        || prev.animation !== next.animation;
      return changed;
    }

    *easeOpen() {
      if (this.ease < 1) {
        this.easingOpen = true;
        this.audio.playUI(this.isMadelinePortrait() ? 'madeline_in' : 'other_in');
        while ((this.ease += this._dt / C.tweenDuration) < 1) {
          yield null;
        }
        this.ease = 1;
        this.gradientFade = 1;
        this.easingOpen = false;
      }
    }

    *easeClose(final) {
      this.easingClose = true;
      this.audio.playUI(this.isMadelinePortrait() ? 'madeline_out' : 'other_out');
      while ((this.ease -= this._dt / C.tweenDuration) > 0) {
        if (final) this.gradientFade = this.ease;
        yield null;
      }
      this.ease = 0;
      this.easingClose = false;
    }

    *run() {
      const nodes = this.group.nodes;
      let last = null;
      let delayBuildup = 0;

      while (this.index < nodes.length) {
        const current = nodes[this.index];
        let delay = 0;

        if (current instanceof FT.AnchorNode) {
          if (this.ease >= 1 && current.position !== this.anchor) {
            yield* this.easeClose(false);
          }
          this.anchor = current.position;
        } else if (current instanceof FT.PortraitNode) {
          if (this.ease >= 1
            && (!this.portrait
              || current.sprite !== this.portrait.sprite
              || current.side !== this.portrait.side)) {
            yield* this.easeClose(false);
          }

          this.canSkip = false;
          const changed = this.applyPortrait(current);

          if (!this.portraitExists) {
            yield* this.easeOpen();
            this.canSkip = true;
          } else {
            if (changed && this.portraitSprite) {
              if (this.portraitSprite.has(current.beginAnimation)) {
                this.portraitSprite.play(current.beginAnimation, true);
                yield* this.easeOpen();
                while (this.portraitSprite.currentId === current.beginAnimation
                  && this.portraitSprite.animating) {
                  yield null;
                }
              }
              if (this.portraitSprite.has(current.idleAnimation)) {
                this.portraitIdling = true;
                this.portraitSprite.play(current.idleAnimation, true);
              }
            }
            yield* this.easeOpen();
            this.canSkip = true;
          }
        } else if (current instanceof FT.NewPageNode) {
          this.playIdleAnimation();
          if (this.ease >= 1) {
            this.waitingForInput = true;
            yield 0.1;
            while (!this.continuePressed()) yield null;
            this.waitingForInput = false;
          }
          this.start = this.index + 1;
          this.page++;
        } else if (current instanceof FT.WaitNode) {
          this.playIdleAnimation();
          delay = current.duration;
        } else if (current instanceof FT.TriggerNode) {
          this.isInTrigger = true;
          this.playIdleAnimation();
          if (!current.silent) {
            yield* this.easeClose(false);
          }
          const handler = this.events[current.index];
          if (typeof handler === 'function') {
            yield* handler(current);
          } else if (current.label) {
            console.debug(`[trigger ${current.index}] ${current.label}`);
          }
          this.isInTrigger = false;
        } else if (current instanceof FT.CharNode) {
          this.lastChar = current.code;

          if (this.ease < 1) {
            yield* this.easeOpen();
          }

          let nearPageBreak = false;
          if (this.index - 5 > this.start) {
            const limit = Math.min(this.index + C.stopVoiceEarly, nodes.length);
            for (let i = this.index; i < limit; i++) {
              if (nodes[i] instanceof FT.NewPageNode) {
                nearPageBreak = true;
                this.playIdleAnimation();
              }
            }
          }
          if (!nearPageBreak && !current.isPunctuation) {
            this.playTalkAnimation();
          }

          if (last instanceof FT.NewPageNode) {
            this.index--;
            yield 0.2;
            this.index++;
          }

          delay = current.delay + delayBuildup;
        }

        last = current;
        this.index++;

        if (delay < 0.016) {
          delayBuildup += delay;
        } else {
          delayBuildup = 0;
          if (delay > C.idleDelay) {
            this.playIdleAnimation();
          }
          yield delay;
        }
      }

      this.playIdleAnimation();
      if (this.ease > 0) {
        this.waitingForInput = true;
        while (!this.continuePressed()) yield null;
        this.waitingForInput = false;
        this.start = nodes.length;
        yield* this.easeClose(true);
      }
      this.close();
    }

    *skipDialog() {
      for (;;) {
        if (!this.waitingForInput
          && this.canSkip
          && !this.easingOpen
          && !this.easingClose
          && this.continuePressed()) {
          this.playIdleAnimation();
          this.disableInput = true;
          let guard = 0;
          while (!this.waitingForInput
            && this.canSkip
            && !this.easingOpen
            && !this.easingClose
            && !this.isInTrigger
            && !this.runRoutine.done) {
            this.runRoutine.update(this._dt || 1 / 60);
            guard++;
            if (guard > 20000) break;
          }
        }
        yield null;
        this.disableInput = false;
      }
    }

    update(dt) {
      this._dt = dt;
      this.skipRoutine.update(dt);
      this.runRoutine.update(dt);

      if (this.portraitSprite && this.ease >= 1) {
        this.portraitSprite.update(dt);
      }
      if (this.glitchSprite && this.isPortraitGlitchy && this.ease >= 1) {
        this.glitchSprite.update(dt);
      }
      this.portraitWiggle.update(dt);

      this.timer += dt;

      const total = Math.min(this.index, this.group.nodes.length);
      for (let i = this.start; i < total; i++) {
        const node = this.group.nodes[i];
        if (node instanceof FT.CharNode && node.fade < 1) {
          node.fade = Math.min(1, node.fade + 8 * dt);
        }
      }
    }

    close() {
      this.opened = false;
      this.closed = true;
      this.audio.stopTalker();
      this.audio.setPhonestatic('');
    }

    // 统计当前页在页断前有多少个换行，用于决定 0.75 缩放
    linesOnPage() {
      const nodes = this.group.nodes;
      let lines = 1;
      for (let i = this.start; i < nodes.length; i++) {
        if (nodes[i] instanceof FT.NewLineNode) lines++;
        else if (nodes[i] instanceof FT.NewPageNode) break;
      }
      return lines;
    }
  }

  D.Textbox = Textbox;
  D.Coroutine = Coroutine;
})();
