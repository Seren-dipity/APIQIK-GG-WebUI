const THEME_FONTS = {
  apple: [],
  claude: [
    {
      id: 'font-cormorant',
      href: 'https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&display=swap'
    },
    {
      id: 'font-jetbrains',
      href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400&display=swap'
    }
  ],
  vercel: [
    {
      id: 'font-geist',
      href: 'https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap'
    }
  ]
};

const ThemeManager = {
  currentStyle: 'claude',
  currentMode: 'dark',

  init() {
    const style = localStorage.getItem('theme-style') || 'claude';
    const mode = localStorage.getItem('theme-mode') || 'dark';
    
    this.apply(style, mode);

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
      if (!localStorage.getItem('theme-mode')) {
        this.apply(this.currentStyle, e.matches ? 'dark' : 'light');
      }
    });
  },

  apply(style, mode) {
    this.currentStyle = style;
    this.currentMode = mode;
    
    document.documentElement.setAttribute('data-theme', `${style}-${mode}`);
    localStorage.setItem('theme-style', style);
    localStorage.setItem('theme-mode', mode);
    
    this.loadFonts(style);
    this.updateUI();
  },

  loadFonts(style) {
    const fonts = THEME_FONTS[style] || [];
    fonts.forEach(f => {
      if (!document.getElementById(f.id)) {
        const link = document.createElement('link');
        link.id = f.id;
        link.rel = 'stylesheet';
        link.href = f.href;
        document.head.appendChild(link);
      }
    });
  },

  toggleMode() {
    this.apply(this.currentStyle, this.currentMode === 'light' ? 'dark' : 'light');
  },

  setStyle(style) {
    this.apply(style, this.currentMode);
  },

  updateUI() {
    const styleSelect = document.getElementById('theme-style-select');
    if (styleSelect) styleSelect.value = this.currentStyle;
    
    const modeBtn = document.getElementById('theme-mode-toggle');
    if (modeBtn) {
      modeBtn.innerHTML = this.currentMode === 'light' ? 
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>' : 
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>';
    }
  }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => ThemeManager.init());
