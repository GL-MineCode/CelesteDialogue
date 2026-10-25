// 全局配置。所有数值都对应 Celeste 的 1920x1080 逻辑分辨率。
window.CelesteDemo = window.CelesteDemo || {};

window.CelesteDemo.config = {
  assetRoot: 'assets/celeste',
  entry: 'CH0_GRANNY',
  playerName: 'Madeline',
  // 默认场景（留空 = 第一个场景）；也可用 ?scene=ch1_theo 指定
  scene: '',

  // 逻辑画布
  width: 1920,
  height: 1080,

  // Textbox.cs 中的常量
  textboxWidth: 1688,
  textboxHeight: 272,
  textboxX: 116,
  textboxBaseY: 58,          // new Vector2(116, 116/2)
  textboxBottomY: 1080 - 58 - 272,
  textboxMiddleY: 404,
  portraitPadding: 16,
  portraitWidth: 240,
  portraitGap: 32,
  tweenDuration: 0.4,
  idleDelay: 0.5,            // delay > 0.5 时停止说话
  stopVoiceEarly: 4,         // 页尾前 4 个字符提前停声
  pageButtonBob: 6,

  // 演示用
  showHint: true,
  background: ['#141420', '#07070c'],
};
