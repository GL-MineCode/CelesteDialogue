// Monocle.Sprite 的立绘移植：动画表 / goto 权重 / 逐帧原点 / 弹出抖动。
(function () {
  const D = window.CelesteDemo;

  function chooseWeighted(entries) {
    let total = 0;
    for (const entry of entries) total += entry[1];
    if (total <= 0) return entries.length ? entries[0][0] : null;
    let roll = Math.random() * total;
    for (const entry of entries) {
      roll -= entry[1];
      if (roll <= 0) return entry[0];
    }
    return entries[entries.length - 1][0];
  }

  // Monocle.Wiggler：Start() 后 value 从 0 起振，按 (1 - t/duration) 衰减。
  class Wiggler {
    constructor(duration, frequency) {
      this.duration = duration;
      this.frequency = frequency;
      this.timer = 0;
      this.active = false;
      this.value = 0;
    }

    start() {
      this.timer = 0;
      this.value = 0;
      this.active = true;
    }

    update(dt) {
      if (!this.active) return;
      this.timer += dt;
      if (this.timer >= this.duration) {
        this.timer = this.duration;
        this.active = false;
        this.value = 0;
        return;
      }
      const k = this.timer / this.duration;
      this.value = Math.sin(this.timer * this.frequency * Math.PI * 2) * (1 - k);
    }
  }

  /**
   * 一张立绘（对应 GFX.PortraitsSpriteBank 里的一个 Sprite 实例）。
   * images: { "normal/0": HTMLImageElement, ... }，与 portraits.json 的 frameFiles 同键。
   */
  class PortraitSprite {
    constructor(asset, images) {
      this.asset = asset;
      this.images = images;
      this.animations = asset.animations || {};
      // <Center/> 时 Justify=(0.5,0.5)，Sprite.SetFrame 会用“当前帧尺寸”重算原点
      this.justify = asset.center === false ? 0 : 0.5;

      this.currentId = '';
      this.current = null;
      this.timer = 0;
      this.frame = 0;
      this.animating = false;
      this.texture = null;
    }

    has(id) {
      return !!(id && this.animations[String(id).toLowerCase()]);
    }

    play(id, restart) {
      const key = String(id || '').toLowerCase();
      const anim = this.animations[key];
      if (!anim) return;
      if (this.currentId === key && !restart) return;

      this.currentId = key;
      this.current = anim;
      this.animating = anim.delay > 0;
      this.timer = 0;
      this.frame = 0;
      this.apply();
    }

    apply() {
      if (!this.current) {
        this.texture = null;
        return;
      }
      const key = `${this.current.path}/${this.current.frames[this.frame]}`;
      this.texture = this.images[key] || null;
    }

    update(dt) {
      if (!this.animating || !this.current) return;
      this.timer += dt;
      const delay = this.current.delay;
      if (Math.abs(this.timer) < delay) return;

      const sign = this.timer > 0 ? 1 : -1;
      this.frame += sign;
      this.timer -= sign * delay;

      const frames = this.current.frames;
      if (this.frame < 0 || this.frame >= frames.length) {
        const goto = this.current.goto;
        const nextId = goto && goto.length ? String(chooseWeighted(goto)).toLowerCase() : null;
        const next = nextId ? this.animations[nextId] : null;
        if (next) {
          this.current = next;
          this.currentId = nextId;
          this.frame = this.frame < 0 ? next.frames.length - 1 : 0;
          this.apply();
          return;
        }
        this.frame = this.frame < 0 ? 0 : frames.length - 1;
        this.animating = false;
        this.currentId = '';
        this.current = null;
        this.timer = 0;
        return;
      }
      this.apply();
    }
  }

  /** glitchy 立绘上叠加的 noise/ 循环（AddLoop("noise", "", 0.1f)）。 */
  class NoiseSprite {
    constructor(files, images, delay) {
      this.files = files || [];
      this.images = images || {};
      this.delay = delay || 0.1;
      this.timer = 0;
      this.frame = 0;
      this.texture = this.files.length ? this.images[this.files[0]] || null : null;
    }

    update(dt) {
      if (!this.files.length) return;
      this.timer += dt;
      while (this.timer >= this.delay) {
        this.timer -= this.delay;
        this.frame = (this.frame + 1) % this.files.length;
      }
      this.texture = this.images[this.files[this.frame]] || null;
    }
  }

  /**
   * 预加载立绘帧。返回 { spriteName: { info, images } }，
   * Textbox 每次换立绘时用 info/images 新建一个 PortraitSprite（互不共享动画状态）。
   */
  async function loadPortraitBank(names, portraits, assetRoot) {
    const bank = {};
    const jobs = [];
    for (const name of names) {
      const info = portraits[name];
      if (!info) continue;
      const images = {};
      bank[name] = { info, images };
      const dir = `${assetRoot}/portraits/${info.folder}`;
      for (const [key, file] of Object.entries(info.frameFiles || {})) {
        jobs.push(D.loadImage(`${dir}/${file}`).then((img) => {
          images[key] = img;
        }).catch((err) => {
          console.warn(err.message);
        }));
      }
    }
    await Promise.all(jobs);
    return bank;
  }

  async function loadNoise(noiseInfo, assetRoot) {
    if (!noiseInfo || !noiseInfo.frames) return null;
    const images = {};
    const dir = `${assetRoot}/portraits/noise`;
    await Promise.all(noiseInfo.frames.map(async (file) => {
      try {
        images[file] = await D.loadImage(`${dir}/${file}`);
      } catch (err) {
        console.warn(err.message);
      }
    }));
    return new NoiseSprite(noiseInfo.frames, images, noiseInfo.delay || 0.1);
  }

  D.PortraitSprite = PortraitSprite;
  D.NoiseSprite = NoiseSprite;
  D.Wiggler = Wiggler;
  D.loadPortraitBank = loadPortraitBank;
  D.loadNoise = loadNoise;
  D.chooseWeighted = chooseWeighted;
})();
