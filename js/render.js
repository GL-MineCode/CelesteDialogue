// 1920x1080 Canvas 渲染：文本框、逐字淡入、波浪/抖动、继续按钮。
(function () {
  const D = window.CelesteDemo;
  const C = D.config;
  const FT = D.FancyText;

  function cubeInOut(t) {
    if (t < 0.5) return 4 * t * t * t;
    t = 2 * t - 2;
    return 0.5 * t * t * t + 1;
  }

  function hash2(a, b) {
    const x = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  class Renderer {
    constructor(canvas) {
      this.canvas = canvas;
      canvas.width = C.width;
      canvas.height = C.height;
      this.ctx = canvas.getContext('2d', { alpha: false });
      this.textboxes = new Map();
      this.button = null;
      this.time = 0;
      this.hintVisible = C.showHint;
      this.hintAlpha = 1;
      this.gradient = null;
    }

    async load(assetRoot, manifest) {
      const files = (manifest && manifest.files) || {};

      for (const [key, entry] of Object.entries(files)) {
        if (!key.startsWith('textbox_')) continue;
        const name = key.slice('textbox_'.length);
        try {
          const img = await D.loadImage(`${assetRoot}/${entry.path}`);
          this.textboxes.set(name, { img, frame: entry.frame, offset: entry.offset });
        } catch (err) {
          console.warn(err.message);
        }
      }

      if (files.textboxbutton) {
        try {
          const img = await D.loadImage(`${assetRoot}/${files.textboxbutton.path}`);
          this.button = {
            img,
            frame: files.textboxbutton.frame,
            offset: files.textboxbutton.offset,
          };
        } catch (err) {
          console.warn(err.message);
        }
      }
    }

    resize() { /* canvas 固定 1920x1080，由 CSS 缩放 */ }

    render(tb, dt) {
      this.time += dt;
      const ctx = this.ctx;

      this.drawBackground(ctx);

      const ease = cubeInOut(tb.ease);
      if (ease >= 0.05) {
        const pos = this.boxPosition(tb.anchor, ease);
        this.drawTextbox(ctx, tb, pos, ease);
        if (tb.waitingForInput) this.drawContinueButton(ctx, tb, pos);
        this.drawPortrait(ctx, tb, pos, ease);
        this.drawTextboxOverlay(ctx, tb, pos, ease);
        this.drawText(ctx, tb, pos, ease);
      }

      this.drawHint(ctx, dt);
    }

    boxPosition(anchor, ease) {
      let y = C.textboxBaseY;
      if (anchor === 'Bottom') y = C.textboxBottomY;
      else if (anchor === 'Middle') y = C.textboxMiddleY;
      y += Math.trunc(136 * (1 - ease));
      return { x: C.textboxX, y };
    }

    drawBackground(ctx) {
      if (!this.gradient) {
        const gradient = ctx.createLinearGradient(0, 0, 0, C.height);
        gradient.addColorStop(0, C.background[0]);
        gradient.addColorStop(1, C.background[1]);
        this.gradient = gradient;
      }
      ctx.globalAlpha = 1;
      ctx.fillStyle = this.gradient;
      ctx.fillRect(0, 0, C.width, C.height);

      // 轻微暗角，让白色文本框更突出
      const vignette = ctx.createRadialGradient(
        C.width / 2, C.height / 2, C.height * 0.2,
        C.width / 2, C.height / 2, C.height * 0.85);
      vignette.addColorStop(0, 'rgba(0,0,0,0)');
      vignette.addColorStop(1, 'rgba(0,0,0,0.55)');
      ctx.fillStyle = vignette;
      ctx.fillRect(0, 0, C.width, C.height);
    }

    drawTextbox(ctx, tb, pos, ease) {
      const entry = this.textboxes.get(tb.textboxName) || this.textboxes.get('default');

      if (!entry) {
        // 资源缺失时的兜底，至少让文字可读
        ctx.fillStyle = 'rgba(10, 12, 20, 0.92)';
        ctx.strokeStyle = 'rgba(255,255,255,0.55)';
        ctx.lineWidth = 4;
        const h = C.textboxHeight * ease;
        ctx.beginPath();
        ctx.roundRect(pos.x, pos.y, C.textboxWidth, h, 8);
        ctx.fill();
        ctx.stroke();
        return;
      }

      const centerX = pos.x + C.textboxWidth / 2;
      const centerY = pos.y + (C.textboxHeight * ease) / 2;

      ctx.globalAlpha = 1;
      this.drawAtlas(ctx, entry, centerX, centerY, 1, ease);
    }

    /** 对应 MTexture.Draw(position, color, scale)：以 Center-DrawOffset 为原点绘制。 */
    drawAtlas(ctx, entry, centerX, centerY, scaleX, scaleY) {
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.scale(scaleX, scaleY);
      ctx.drawImage(entry.img,
        -entry.frame[0] / 2 + entry.offset[0],
        -entry.frame[1] / 2 + entry.offset[1]);
      ctx.restore();
    }

    /** 立绘（含 pop 抖动 / glitchy 噪点叠层），对应 Textbox.Render 的 portrait 分支。 */
    drawPortrait(ctx, tb, pos, ease) {
      const node = tb.portrait;
      const sprite = tb.portraitSprite;
      if (!tb.portraitExists || !node || !sprite) return;

      const image = sprite.texture;
      if (!image) return;

      const scale = tb.portraitScale;
      const side = node.side;
      const baseX = side > 0
        ? pos.x + C.textboxWidth - C.portraitWidth - C.portraitPadding
        : pos.x + C.portraitPadding;

      // portraitSprite.Position += new Vector2(120f, 272f * num * 0.5f)
      const px = baseX + 120;
      const py = pos.y + (C.textboxHeight * ease) * 0.5;

      let sx = (side > 0 ? -scale : scale) * (node.flipped ? -1 : 1);
      let sy = scale * ((C.textboxHeight * ease - 32) / C.portraitWidth)
        * (node.upsideDown ? -1 : 1);

      const wiggle = 0.9 + tb.portraitWiggle.value * 0.1;
      sx *= wiggle;
      sy *= wiggle;

      if (Math.abs(sy) <= 0.05) return;

      const originX = image.width * sprite.justify;
      const originY = image.height * sprite.justify;

      ctx.save();
      ctx.globalAlpha = ease;
      ctx.translate(px, py);
      ctx.scale(sx, sy);
      ctx.drawImage(image, -originX, -originY);
      ctx.restore();

      if (tb.isPortraitGlitchy && tb.glitchSprite && tb.glitchSprite.texture) {
        ctx.save();
        ctx.globalAlpha = 0.2 * ease;
        ctx.translate(px, py);
        ctx.scale(sx, sy);
        ctx.drawImage(tb.glitchSprite.texture, -originX, -originY);
        ctx.restore();
      }
      ctx.globalAlpha = 1;
    }

    /** 文本框叠加层（例如 oshiro 的面具），右立绘时水平镜像。 */
    drawTextboxOverlay(ctx, tb, pos, ease) {
      if (!tb.textboxOverlay) return;
      const entry = this.textboxes.get(tb.textboxOverlay);
      if (!entry) return;
      const centerX = pos.x + C.textboxWidth / 2;
      const centerY = pos.y + (C.textboxHeight * ease) / 2;
      const flip = tb.portrait && tb.portrait.side > 0 ? -1 : 1;
      ctx.globalAlpha = 1;
      this.drawAtlas(ctx, entry, centerX, centerY, flip, ease);
    }

    drawContinueButton(ctx, tb, pos) {
      const x = pos.x + ((!tb.portrait || tb.portrait.side < 0) ? 1688 : 1432) - 48;
      const bob = (tb.timer % 1) < 0.25 ? C.pageButtonBob : 0;
      const y = pos.y + C.textboxHeight - 40 + bob;

      if (this.button) {
        const frameW = this.button.frame[0];
        const frameH = this.button.frame[1];
        const fx = x - frameW / 2 + this.button.offset[0];
        const fy = y - frameH / 2 + this.button.offset[1];
        ctx.globalAlpha = 1;
        ctx.drawImage(this.button.img, fx, fy);
        return;
      }

      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.moveTo(x - 10, y - 6);
      ctx.lineTo(x + 10, y - 6);
      ctx.lineTo(x, y + 8);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    drawText(ctx, tb, pos, ease) {
      const lines = tb.linesOnPage();
      const textScale = lines >= 4 ? 0.75 : 1;

      const hasPortrait = !!tb.portrait;
      // Vector2 value = new Vector2(innerTextPadding + (portrait != null && side < 0 ? 256f : 0f), innerTextPadding)
      const valueX = tb.innerTextPadding + (hasPortrait && tb.portrait.side < 0 ? 256 : 0);
      const valueY = tb.innerTextPadding;
      const areaW = hasPortrait ? tb.maxLineWidth : tb.maxLineWidthNoPortrait;
      const areaH = tb.linesPerPage * tb.lineHeight * ease;

      const origin = {
        x: pos.x + valueX + areaW / 2,
        y: pos.y + valueY + areaH / 2,
      };

      const scaleX = textScale;
      const scaleY = ease * textScale;
      const alpha = ease;
      const time = this.time;

      tb.group.draw(
        (node, x, y, sx, sy, groupAlpha) => {
          this.drawChar(ctx, tb.font, node, x, y, sx, sy, groupAlpha, time);
        },
        origin, 0.5, 0.5, scaleX, scaleY, alpha, tb.start,
      );
    }

    drawChar(ctx, font, node, x, y, scaleX, scaleY, alpha, time) {
      const glyph = font.get(node.code);
      if (!glyph) return;

      const fade = node.fade;
      if (fade <= 0.001) return;

      const charScale = (node.impact ? 2 - fade : 1) * node.scale;
      const sx = scaleX * charScale;
      const sy = scaleY * charScale;
      if (Math.abs(sx) < 0.0001 || Math.abs(sy) < 0.0001) return;

      let offsetX = 0;
      let offsetY = 0;

      if (node.shake) {
        const seed = Math.floor(time * 20);
        offsetX += (Math.floor(hash2(seed, node.index) * 3) - 1) * 2;
        offsetY += (Math.floor(hash2(seed + 17, node.index) * 3) - 1) * 2;
      }
      if (node.wave) {
        offsetY += Math.sin(node.index * 0.25 + time * 8) * 4;
      }

      offsetX += glyph.xo;
      offsetY += glyph.yo + (-8 * (1 - fade) + node.yOffset * fade);

      const drawX = x + node.position * scaleX + offsetX * sx;
      const drawY = y + offsetY * sy;

      const image = font.tintedGlyph(node.code, node.color);
      if (!image) return;

      ctx.globalAlpha = Math.max(0, Math.min(1, fade * alpha));
      ctx.save();
      ctx.translate(drawX, drawY);
      if (node.rotation) ctx.rotate(node.rotation);
      ctx.scale(sx, sy);
      ctx.drawImage(image, 0, 0);
      ctx.restore();
      ctx.globalAlpha = 1;
    }

    drawHint(ctx, dt) {
      if (!this.hintVisible) return;
      if (this.hintAlpha <= 0) return;
      this.hintAlpha = Math.max(0, this.hintAlpha - dt * 0.35);

      ctx.globalAlpha = Math.min(1, this.hintAlpha);
      ctx.fillStyle = 'rgba(255,255,255,0.62)';
      ctx.font = '26px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('空格 / 回车 / 点击：继续　·　对话中按一次可跳至本页末尾', C.width / 2, C.height - 46);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
      ctx.globalAlpha = 1;
    }

    drawEndCard(ctx) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.fillRect(0, 0, C.width, C.height);
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      ctx.font = '44px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('对话结束', C.width / 2, C.height / 2 - 24);
      ctx.font = '28px "Microsoft YaHei", "PingFang SC", sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.65)';
      ctx.fillText('点击任意位置重新播放', C.width / 2, C.height / 2 + 44);
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
    }
  }

  D.Renderer = Renderer;
  D.cubeInOut = cubeInOut;
})();
