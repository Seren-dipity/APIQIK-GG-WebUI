import re

css_path = r'e:\Python_Projects\TempScripts\apiqik\static\css\base.css'
with open(css_path, 'r', encoding='utf-8') as f:
    css = f.read()

replacements = [
    # brand h1 gradient removal
    (r'\.brand h1 \{\s*margin: 0;\s*font-size: clamp\(28px, 4vw, 52px\);\s*line-height: 1;\s*letter-spacing: 0;\s*background: linear-gradient\(120deg, #f8fafc, var\(--accent\) 38%, #c4b5fd 72%, #fbbf24\);\s*-webkit-background-clip: text;\s*-webkit-text-fill-color: transparent;\s*\}',
     r'.brand h1 {\n      margin: 0;\n      font-size: clamp(28px, 4vw, 52px);\n      line-height: 1;\n      letter-spacing: 0;\n      color: var(--ink);\n    }'),

    # Leftover #111827 (dark background for select options)
    (r'background: #111827;', r'background: var(--surface-code);'),
    
    # Leftover #fff (white border)
    (r'border-color: #fff;', r'border-color: var(--bg);'),
    
    # Leftover #fbbf24 (warning yellow)
    (r'color: #fbbf24;', r'color: var(--warning);'),
    
    # Progress bar gradient and glow
    (r'linear-gradient\(90deg, var\(--accent\), #38bdf8 78%, rgba\(248, 250, 252, 0\.92\)\)', r'var(--accent)'),
    (r'box-shadow: 0 0 8px rgba\(56, 189, 248, 0\.28\);', r'box-shadow: 0 0 8px var(--accent-glow);'),
    (r'linear-gradient\(90deg, rgba\(248, 250, 252, 0\), rgba\(248, 250, 252, 0\.92\) 46%, rgba\(125, 211, 252, 0\.58\)\)', r'var(--accent-glow)'),
    (r'0 0 5px rgba\(248, 250, 252, 0\.62\),\s*0 0 10px rgba\(56, 189, 248, 0\.42\)', r'0 0 10px var(--accent-glow)'),

    # Notice warning text
    (r'color: #fde68a;', r'color: var(--warning);'),

    # Leftovers in history tabs / actions
    (r'color: #ffffff;', r'color: var(--ink-on-accent);'),
    (r'background: #e4f5a3;', r'background: var(--success);'),
    (r'color: #e4f5a3;', r'color: var(--success);'),

    # rgba borders and backgrounds
    (r'rgba\(255, 255, 255, 0\.13\)', r'var(--border)'),
    (r'rgba\(125, 211, 252, 0\.2\)', r'var(--border)'),
    (r'rgba\(9, 14, 24, 0\.96\)', r'var(--surface-elevated)'),
    (r'rgba\(0, 0, 0, 0\.38\)', r'var(--shadow)'),
    (r'rgba\(125, 211, 252, 0\.12\)', r'var(--surface-primary)'),
    (r'rgba\(255, 255, 255, 0\.04\)', r'var(--surface-primary)'),
    (r'rgba\(255, 255, 255, 0\.25\)', r'var(--border-strong)'),
    (r'rgba\(20, 184, 166, 0\.15\)', r'var(--accent-subtle)'),
    (r'rgba\(20, 184, 166, 0\.1\)', r'var(--accent-subtle)'),
    (r'rgba\(255, 255, 255, 0\.14\)', r'var(--border)'),
    (r'rgba\(255, 255, 255, 0\.07\)', r'var(--surface-secondary)'),
    (r'rgba\(255, 255, 255, 0\.28\)', r'var(--border-strong)'),
    (r'rgba\(56, 189, 248, 0\.45\)', r'var(--border-strong)'),
    (r'rgba\(56, 189, 248, 0\.15\)', r'var(--accent-subtle)'),
    (r'rgba\(56, 189, 248, 0\.25\)', r'var(--accent-glow)'),
    (r'rgba\(245, 158, 11, 0\.38\)', r'var(--warning)'),
    (r'rgba\(125, 211, 252, 0\.45\)', r'var(--border-strong)'),
    (r'rgba\(56, 189, 248, 0\.055\)', r'var(--surface-primary)'),
    (r'rgba\(20, 184, 166, 0\.12\)', r'var(--accent-subtle)'),
    (r'rgba\(0, 0, 0, 0\.28\)', r'var(--overlay)'),
    (r'rgba\(34, 197, 94, 0\.75\)', r'var(--success)'),
    (r'rgba\(245, 158, 11, 0\.75\)', r'var(--warning)'),
    (r'rgba\(251, 113, 133, 0\.75\)', r'var(--error)'),
    (r'rgba\(148, 163, 184, 0\.16\)', r'var(--surface-primary)'),
    (r'rgba\(0, 0, 0, 0\.22\)', r'var(--shadow)'),
    (r'rgba\(255, 255, 255, 0\.1\)', r'var(--border)'),
    (r'rgba\(20, 184, 166, 0\.55\)', r'var(--accent)'),
    (r'rgba\(255, 255, 255, 0\.22\)', r'var(--border-strong)'),
    (r'rgba\(255, 255, 255, 0\.15\)', r'var(--surface-secondary)'),
    (r'rgba\(30, 30, 30, 0\.96\)', r'var(--surface-elevated)'),
    (r'rgba\(0, 0, 0, 0\.6\)', r'var(--shadow-heavy)'),
    (r'rgba\(255, 255, 255, 0\.05\)', r'var(--border)'),
    (r'rgba\(255, 255, 255, 0\.45\)', r'var(--ink-secondary)'),
    (r'rgba\(255, 255, 255, 0\.3\)', r'var(--ink-tertiary)'),
    (r'rgba\(255, 255, 255, 0\.03\)', r'var(--border-subtle)'),
    (r'rgba\(245, 158, 11, 0\.35\)', r'var(--warning)'),
    (r'rgba\(245, 158, 11, 0\.1\)', r'var(--surface-primary)'),
    (r'rgba\(0, 0, 0, 0\.55\)', r'var(--shadow-heavy)'),
    (r'rgba\(255, 255, 255, 0\.08\)', r'var(--surface-primary)')
]

for pattern, repl in replacements:
    css = re.sub(pattern, repl, css, flags=re.DOTALL)

with open(css_path, 'w', encoding='utf-8') as f:
    f.write(css)

print("base.css cleaned up")
