# APIQIK 多主题集成规范指南

本指南旨在说明如何基于现有的“语义化 Token 架构”，正确、快速地为 APIQIK 接入一套全新的视觉风格（如 `Minimal` 或 `Cyberpunk`）。

---

## 一、 架构原理速览

APIQIK 的 CSS 架构分为三层：
1. **基础骨架 (`base.css`)**：仅包含布局、尺寸和组件结构的定义。**严禁在这里写死任何具体的色值或像素级圆角/投影**，全部使用 `var(--xxxx)`。
2. **兜底系统 (`tokens.css`)**：定义了所有可用的语义化变量池。
3. **主题实现 (`themes/*.css`)**：通过 `[data-theme="风格-模式"]` 选择器，对 `tokens.css` 中的变量进行具体的数值覆盖。

---

## 二、 接入新风格的标准流程

假设你要新增一个名为 `cyber` 的赛博朋克风格。

### 第 1 步：解析 Style.md 并提取变量
当你拿到新的 `Style_Cyber.md` 风格描述文件后，你需要将其中的设计语言翻译成具体的 CSS 变量。

在 `static/css/themes/` 目录下创建两个文件：
*   `cyber-light.css`
*   `cyber-dark.css`

文件内容需严格遵守以下模板格式：

```css
/* cyber-light.css 示例 */
[data-theme="cyber-light"] {
  /* ================= 1. 色彩系统 ================= */
  /* 背景层级 */
  --bg: #f0f0f0;                  /* 最底层背景 */
  --surface-primary: #ffffff;      /* 卡片主背景 */
  --surface-secondary: #f8f9fa;    /* 悬浮态或次级背景 */
  --surface-elevated: #ffffff;     /* 弹窗等悬浮元素背景 */
  --surface-code: #282a36;         /* 代码/日志块背景 */
  --surface-input: #ffffff;        /* 输入框背景 */

  /* 边框系统 */
  --border: #e2e8f0;               /* 默认边框 */
  --border-strong: #cbd5e1;        /* 强调边框（Hover/Focus） */
  --border-subtle: #f1f5f9;        /* 极弱边框（分割线） */

  /* 品牌与强调色 */
  --accent: #f00b51;               /* 赛博朋克霓虹红 */
  --accent-hover: #d00945;
  --accent-subtle: rgba(240, 11, 81, 0.1); 
  --accent-glow: rgba(240, 11, 81, 0.4);   /* 发光特效 */

  /* 文本系统 */
  --ink: #1e293b;                  /* 主文本 */
  --ink-secondary: #64748b;        /* 辅助文本 */
  --ink-tertiary: #94a3b8;         /* 占位符/极弱文本 */
  --ink-on-accent: #ffffff;        /* 品牌色上的文本 */
  --ink-on-code: #f8f8f2;          /* 代码块中的文本 */

  /* 状态反馈 */
  --success: #10b981;
  --warning: #f59e0b;
  --error: #ef4444;

  /* ================= 2. 几何与视觉特效 ================= */
  --radius-sm: 0px;                /* 赛博朋克通常是直角 */
  --radius-md: 2px;
  --radius-lg: 4px;
  --shadow: 4px 4px 0px rgba(0,0,0,0.1); /* 硬阴影风格 */
  --shadow-heavy: 8px 8px 0px rgba(0,0,0,0.2);
  --backdrop-blur: blur(0px);      /* 不需要毛玻璃 */
  
  /* ================= 3. 字体 ================= */
  --font-body: 'Rajdhani', system-ui, sans-serif;
  --font-mono: 'Fira Code', monospace;
}
```
*（同理完成 `cyber-dark.css`，只需调整颜色，无需调整圆角和字体等不变属性，除非该风格在暗色下有特殊的字体权重等要求）*

### 第 2 步：向 HTML 注册新 CSS 文件
打开 `static/index.html` 和 `static/settings.html`，在 `<head>` 中引入你刚创建的 CSS：

```html
<!-- 引入新主题 -->
<link rel="stylesheet" href="/static/css/themes/cyber-light.css">
<link rel="stylesheet" href="/static/css/themes/cyber-dark.css">
```

### 第 3 步：向 UI 下拉菜单添加选项
同样在 `static/index.html` 和 `static/settings.html` 中找到风格切换器 `<select id="theme-style-select">`，添加新的 `<option>`：

```html
<select id="theme-style-select" class="btn btn-small" onchange="ThemeManager.setStyle(this.value)">
  <option value="apple">Apple Style</option>
  <option value="claude">Claude Style</option>
  <!-- 你的新风格。value必须与 data-theme 的前缀一致 -->
  <option value="cyber">Cyberpunk</option>
</select>
```

### 第 4 步：按需配置外部字体 (可选)
如果该风格（如 Cyberpunk）使用了特定的 Google Fonts（比如 `Rajdhani`），为了避免全站预加载无用的字体，请打开 `static/js/theme.js`。

在顶部的 `THEME_FONTS` 配置字典中注册：
```javascript
const THEME_FONTS = {
  // 注意：不需要包含基础域，只需要 family 参数
  claude: 'family=Cormorant+Garamond:wght@400;600;700&family=JetBrains+Mono&display=swap',
  cyber: 'family=Rajdhani:wght@400;600;700&family=Fira+Code&display=swap'
};
```
当用户切换到该风格时，`ThemeManager` 会自动动态创建 `<link>` 标签从 Google Fonts 加载字体资源。如果在内网或不可达环境加载失败，CSS 变量中 `system-ui` 的兜底声明会立刻生效，不会阻断渲染。

---

## 三、 防劣化公约（核心纪律）

新风格引入后，若发现某个界面组件在新风格下“很难看”或“显示不正确”，**绝对不要**做以下事情：
1. ❌ **不要去修改 `base.css` 强行覆盖**（这会破坏 Apple 和 Claude 的现有表现）。
2. ❌ **不要在 HTML 元素里写 `style="..."` 内联样式**。
3. ❌ **不要在 `base.css` 里出现 `#` 开头的十六进制或 `rgba` 色值**。

**正确的解决思路：**
如果在新风格中，下拉菜单的边框不够清晰，说明你在 `cyber-light.css` 中定义的 `--border` 或 `--surface-elevated` 不合理，请**去对应风格的 css 文件中调整 Token 映射值**。整个系统的所有表现差异都必须通过控制 Token 解决。
