// FancyText.cs 的逐函数移植：把对话字符串解析成可逐字显示的节点列表。
(function () {
  const D = window.CelesteDemo;

  const DEFAULT_COLOR = { r: 211, g: 211, b: 211 }; // Microsoft.Xna.Framework.Color.LightGray
  const NUMBER_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

  class NodeBase {}

  class CharNode extends NodeBase {
    constructor(code) {
      super();
      this.index = 0;
      this.code = code;
      this.position = 0;
      this.line = 0;
      this.page = 0;
      this.delay = 0;
      this.lineWidth = 0;
      this.color = DEFAULT_COLOR;
      this.scale = 1;
      this.rotation = 0;
      this.yOffset = 0;
      this.fade = 0;
      this.shake = false;
      this.wave = false;
      this.impact = false;
      this.isPunctuation = false;
    }
  }

  class NewLineNode extends NodeBase {}
  class NewPageNode extends NodeBase {}

  class WaitNode extends NodeBase {
    constructor(duration) {
      super();
      this.duration = duration;
    }
  }

  class TriggerNode extends NodeBase {
    constructor(index, silent, label) {
      super();
      this.index = index;
      this.silent = silent;
      this.label = label;
    }
  }

  class AnchorNode extends NodeBase {
    constructor(position) {
      super();
      this.position = position;
    }
  }

  class PortraitNode extends NodeBase {
    constructor() {
      super();
      this.side = 0;
      this.sprite = null;
      this.animation = null;
      this.upsideDown = false;
      this.flipped = false;
      this.pop = false;
      this.glitchy = false;
      this.info = null;
      this.event = null;
      this.expression = 1;
      this.textbox = 'default';
      // Textbox.cs 里由 "idle_" + Animation 等拼出
      this.beginAnimation = 'begin_normal';
      this.idleAnimation = 'idle_normal';
      this.talkAnimation = 'talk_normal';
    }
  }

  class Group {
    constructor(font, baseSize) {
      this.nodes = [];
      this.lines = 0;
      this.pages = 0;
      this.font = font;
      this.baseSize = baseSize;
    }

    /** 对应 FancyText.Text.Draw：把从 start 开始的当前页交给 painter 绘制。 */
    draw(painter, position, justifyX, justifyY, scaleX, scaleY, alpha, start) {
      const nodes = this.nodes;
      const total = nodes.length;

      let maxWidth = 0;
      let runScale = 0;
      let lineCount = 0;
      for (let i = start; i < total; i++) {
        const node = nodes[i];
        if (node instanceof NewLineNode) {
          if (runScale === 0) runScale = 1;
          lineCount += runScale;
          runScale = 0;
        } else if (node instanceof CharNode) {
          if (node.lineWidth > maxWidth) maxWidth = node.lineWidth;
          if (node.scale > runScale) runScale = node.scale;
        } else if (node instanceof NewPageNode) {
          break;
        }
      }
      lineCount += runScale;

      let x = position.x - justifyX * maxWidth * scaleX;
      let y = position.y - justifyY * lineCount * this.font.lineHeight * scaleY;

      runScale = 0;
      let i = start;
      while (i < total && !(nodes[i] instanceof NewPageNode)) {
        const node = nodes[i];
        if (node instanceof NewLineNode) {
          if (runScale === 0) runScale = 1;
          y += this.font.lineHeight * runScale * scaleY;
          runScale = 0;
        }
        if (node instanceof CharNode) {
          painter(node, x, y, scaleX, scaleY, alpha);
          if (node.scale > runScale) runScale = node.scale;
        }
        i++;
      }
    }
  }

  function hexToColor(text) {
    const hex = String(text || '').replace(/[^0-9a-fA-F]/g, '');
    if (hex.length !== 6) return DEFAULT_COLOR;
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16),
    };
  }

  class Builder {
    constructor(options) {
      this.text = options.text;
      this.maxLineWidth = options.maxLineWidth;
      this.linesPerPage = options.linesPerPage;
      this.startFade = options.startFade === undefined ? 1 : options.startFade;
      this.defaultColor = options.defaultColor || DEFAULT_COLOR;
      this.language = options.language;
      this.font = options.font;
      this.portraits = options.portraits || {};
      this.playerName = options.playerName || 'Madeline';

      this.group = new Group(this.font, this.font.size);

      this.currentColor = this.defaultColor;
      this.colorStack = [];
      this.currentLine = 0;
      this.currentPage = 0;
      this.currentPosition = 0;
      this.currentScale = 1;
      this.currentDelay = 0.01;
      this.currentShake = false;
      this.currentWave = false;
      this.currentImpact = false;
      this.currentMessedUp = false;
      this.currentCharIndex = 0;
      this.leftPortrait = null;
      this.rightPortrait = null;
    }

    parse() {
      const regex = new RegExp(this.language.splitRegex, 'i');
      const parts = this.text.split(regex);
      const tokens = [];
      for (const part of parts) {
        if (part !== undefined && part !== null && part !== '') tokens.push(part);
      }

      for (let i = 0; i < tokens.length; i++) {
        if (tokens[i] === '{') {
          i++;
          const command = tokens[i];
          i++;
          const args = [];
          while (i < tokens.length && tokens[i] !== '}') {
            if (tokens[i] && tokens[i].trim()) args.push(tokens[i]);
            i++;
          }
          this.applyCommand(command, args);
        } else {
          this.addWord(tokens[i]);
        }
      }

      this.calcLineWidth();
      return this.group;
    }

    applyCommand(command, args) {
      if (command === undefined) return;

      if (NUMBER_RE.test(command)) {
        this.group.nodes.push(new WaitNode(parseFloat(command)));
        return;
      }

      if (command[0] === '#') {
        let hex = '';
        if (command.length > 1) hex = command.slice(1);
        else if (args.length > 0) hex = args[0];
        if (!hex || !hex.trim()) {
          this.currentColor = this.colorStack.length > 0
            ? this.colorStack.pop()
            : this.defaultColor;
        } else {
          this.colorStack.push(this.currentColor);
          const lower = hex.trim().toLowerCase();
          if (lower === 'red') this.currentColor = { r: 255, g: 0, b: 0 };
          else if (lower === 'green') this.currentColor = { r: 0, g: 128, b: 0 };
          else if (lower === 'blue') this.currentColor = { r: 0, g: 0, b: 255 };
          else this.currentColor = hexToColor(hex);
        }
        return;
      }

      switch (command) {
        case 'break':
          this.calcLineWidth();
          this.currentPage++;
          this.group.pages++;
          this.currentLine = 0;
          this.currentPosition = 0;
          this.group.nodes.push(new NewPageNode());
          return;

        case 'n':
          this.addNewLine();
          return;

        case '>>': {
          const speed = args.length > 0 ? parseFloat(args[0]) : NaN;
          this.currentDelay = NUMBER_RE.test(String(args[0] ?? '')) && speed !== 0
            ? 0.01 / speed
            : 0.01;
          return;
        }

        case '/>>':
          this.currentDelay = 0.01;
          return;

        case 'anchor': {
          const name = (args[0] || '').toLowerCase();
          const map = { top: 'Top', middle: 'Middle', bottom: 'Bottom' };
          if (map[name]) this.group.nodes.push(new AnchorNode(map[name]));
          return;
        }

        case 'portrait':
        case 'left':
        case 'right':
          this.addPortrait(command, args);
          return;

        case 'trigger':
        case 'silent_trigger': {
          const index = parseInt(args[0], 10);
          if (!Number.isNaN(index) && index >= 0) {
            const label = args.slice(1).join(' ');
            this.group.nodes.push(new TriggerNode(index, command.startsWith('silent'), label));
          }
          return;
        }

        case '*': this.currentShake = true; return;
        case '/*': this.currentShake = false; return;
        case '~': this.currentWave = true; return;
        case '/~': this.currentWave = false; return;
        case '!': this.currentImpact = true; return;
        case '/!': this.currentImpact = false; return;
        case '%': this.currentMessedUp = true; return;
        case '/%': this.currentMessedUp = false; return;
        case 'big': this.currentScale = 1.5; return;
        case '/big': this.currentScale = 1; return;

        case 's': {
          let n = 1;
          if (args.length > 0) {
            const parsed = parseInt(args[0], 10);
            if (!Number.isNaN(parsed)) n = parsed;
          }
          this.currentPosition += 5 * n;
          return;
        }

        case 'savedata': {
          const key = (args[0] || '').toLowerCase();
          if (key === 'name') this.addWord(this.playerName);
          else if (key === 'theosistemame') this.addWord('Alex');
          else if (key === 'theosisteraltname') this.addWord('Maddy');
          return;
        }

        default:
          return;
      }
    }

    addPortrait(command, args) {
      if (command === 'portrait' && args.length > 0 && args[0].toLowerCase() === 'none') {
        this.group.nodes.push(new PortraitNode());
        return;
      }

      let portrait;
      if (command === 'left' && this.leftPortrait) portrait = this.leftPortrait;
      else if (command === 'right' && this.rightPortrait) portrait = this.rightPortrait;
      else portrait = new PortraitNode();

      for (const token of args) {
        const low = token.toLowerCase();
        if (low === 'upsidedown') portrait.upsideDown = true;
        else if (low === 'flip') portrait.flipped = true;
        else if (low === 'left') portrait.side = -1;
        else if (low === 'right') portrait.side = 1;
        else if (low === 'pop') portrait.pop = true;
        else if (portrait.sprite === null) portrait.sprite = token;
        else if (portrait.animation === null) portrait.animation = token;
      }

      const info = portrait.sprite
        ? this.portraits[portrait.sprite.toLowerCase()]
        : null;
      portrait.info = info || null;
      portrait.event = info ? info.event : null;
      portrait.textbox = info ? info.textbox : 'default';

      const animation = (portrait.animation || 'normal').toLowerCase();
      portrait.animation = animation;
      portrait.beginAnimation = `begin_${animation}`;
      portrait.idleAnimation = `idle_${animation}`;
      portrait.talkAnimation = `talk_${animation}`;
      // 对应 Textbox.cs 的 isPortraitGlitchy = next2.Glitchy
      // （Portraits.xml 上的 glitchy="true"，例如电话立绘）
      portrait.glitchy = !!(info && info.glitchy);

      if (info) {
        portrait.expression = info.expressions && info.expressions[animation] !== undefined
          ? info.expressions[animation]
          : (info.defaultExpression || 1);
      } else {
        portrait.expression = 1;
      }

      this.group.nodes.push(portrait);
      if (portrait.side > 0) this.rightPortrait = portrait;
      else this.leftPortrait = portrait;
    }

    addNewLine() {
      this.calcLineWidth();
      this.currentLine++;
      this.currentPosition = 0;
      this.group.lines++;

      if (this.currentLine > this.linesPerPage) {
        this.group.pages++;
        this.currentPage++;
        this.currentLine = 0;
        this.group.nodes.push(new NewPageNode());
        return;
      }
      this.group.nodes.push(new NewLineNode());
    }

    addWord(word) {
      const measured = this.font.measure(word) * this.currentScale;
      if (this.currentPosition + measured > this.maxLineWidth) {
        this.addNewLine();
      }

      for (let i = 0; i < word.length; i++) {
        const code = word.charCodeAt(i);
        if ((this.currentPosition !== 0 || code !== 32) && code !== 92 /* \ */) {
          const glyph = this.font.get(code);
          if (!glyph) continue;

          let punctuationDelay = 0;
          if (i === word.length - 1 && (i === 0 || word.charCodeAt(i - 1) !== 92)) {
            if (this.language.commas.indexOf(word[i]) >= 0) punctuationDelay = 0.15;
            else if (this.language.periods.indexOf(word[i]) >= 0) punctuationDelay = 0.3;
          }

          const node = new CharNode(code);
          node.index = this.currentCharIndex++;
          node.position = this.currentPosition;
          node.line = this.currentLine;
          node.page = this.currentPage;
          node.delay = this.currentImpact ? 0.0035 : (this.currentDelay + punctuationDelay);
          node.color = this.currentColor;
          node.scale = this.currentScale;
          if (this.currentMessedUp) {
            node.rotation = (Math.random() < 0.5 ? -1 : 1)
              * (Math.random() < 0.5 ? 0.17453292 : 0.34906584);
            node.yOffset = [-3, -6, 3, 6][Math.floor(Math.random() * 4)];
          }
          node.fade = this.startFade;
          node.shake = this.currentShake;
          node.impact = this.currentImpact;
          node.wave = this.currentWave;
          node.isPunctuation = this.language.commas.indexOf(word[i]) >= 0
            || this.language.periods.indexOf(word[i]) >= 0;

          this.group.nodes.push(node);

          this.currentPosition += glyph.xa * this.currentScale;
          if (i < word.length - 1) {
            this.currentPosition += this.font.kerning(code, word.charCodeAt(i + 1)) * this.currentScale;
          }
        }
      }
    }

    calcLineWidth() {
      const nodes = this.group.nodes;
      let index = nodes.length - 1;
      let last = null;

      while (index >= 0 && last === null) {
        const node = nodes[index];
        if (node instanceof CharNode) last = node;
        else if (node instanceof NewLineNode || node instanceof NewPageNode) return;
        index--;
      }
      if (!last) return;

      const glyph = this.font.get(last.code);
      if (!glyph) return;
      const lineWidth = last.position + glyph.xa * last.scale;
      last.lineWidth = lineWidth;

      while (index >= 0
        && !(nodes[index] instanceof NewLineNode)
        && !(nodes[index] instanceof NewPageNode)) {
        if (nodes[index] instanceof CharNode) nodes[index].lineWidth = lineWidth;
        index--;
      }
    }
  }

  function parse(options) {
    return new Builder(options).parse();
  }

  D.FancyText = {
    parse,
    DEFAULT_COLOR,
    CharNode,
    NewLineNode,
    NewPageNode,
    WaitNode,
    TriggerNode,
    AnchorNode,
    PortraitNode,
  };
})();
