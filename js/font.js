// 把 chinese.fnt 解析出的 JSON 包装成与 Monocle.PixelFontSize 等价的度量器。
(function () {
  const D = window.CelesteDemo;

  class PixelFont {
    constructor(data, image) {
      this.data = data;
      this.image = image;
      this.face = data.face;
      this.size = data.size;           // 64
      this.lineHeight = data.lineHeight; // 64
      this.base = data.base;           // 51

      this.chars = new Map();
      for (const key of Object.keys(data.chars)) {
        const v = data.chars[key];
        this.chars.set(Number(key), {
          x: v[0], y: v[1], w: v[2], h: v[3],
          xo: v[4], yo: v[5], xa: v[6],
        });
      }

      this.kernings = new Map();
      for (const [first, second, amount] of data.kernings || []) {
        let map = this.kernings.get(first);
        if (!map) {
          map = new Map();
          this.kernings.set(first, map);
        }
        map.set(second, amount);
      }

      this.tintCache = new Map();
    }

    get(cp) {
      return this.chars.get(cp) || null;
    }

    kerning(first, second) {
      const map = this.kernings.get(first);
      return (map && map.get(second)) || 0;
    }

    // 对应 PixelFontSize.Measure(string)：返回单行宽度
    measure(text) {
      let width = 0;
      let maxWidth = 0;
      for (let i = 0; i < text.length; i++) {
        const cp = text.charCodeAt(i);
        if (cp === 10) {
          maxWidth = Math.max(maxWidth, width);
          width = 0;
          continue;
        }
        const glyph = this.chars.get(cp);
        if (!glyph) continue;
        width += glyph.xa;
        if (i < text.length - 1) width += this.kerning(cp, text.charCodeAt(i + 1));
      }
      return Math.max(maxWidth, width);
    }

    // 按颜色缓存染色后的字形（字体页是白色 + alpha）
    tintedGlyph(cp, color) {
      const glyph = this.chars.get(cp);
      if (!glyph || glyph.w <= 0 || glyph.h <= 0) return null;

      const key = `${cp}|${color.r},${color.g},${color.b}`;
      let canvas = this.tintCache.get(key);
      if (canvas) return canvas;

      canvas = document.createElement('canvas');
      canvas.width = glyph.w;
      canvas.height = glyph.h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(this.image, glyph.x, glyph.y, glyph.w, glyph.h, 0, 0, glyph.w, glyph.h);
      ctx.globalCompositeOperation = 'source-in';
      ctx.fillStyle = `rgb(${color.r},${color.g},${color.b})`;
      ctx.fillRect(0, 0, glyph.w, glyph.h);

      this.tintCache.set(key, canvas);
      return canvas;
    }
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`图片加载失败：${src}`));
      img.src = src;
    });
  }

  async function loadPixelFont(baseUrl, data, texturePath) {
    if (!data) throw new Error('缺少字体数据（assets/celeste/fonts/chinese.js）');
    const image = await loadImage(`${baseUrl}/${texturePath}`);
    return new PixelFont(data, image);
  }

  D.PixelFont = PixelFont;
  D.loadPixelFont = loadPixelFont;
  D.loadImage = loadImage;
})();
