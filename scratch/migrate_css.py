import re
import os

css_path = r'e:\Python_Projects\TempScripts\apiqik\static\index.html'
with open(css_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Extract CSS from <style> to </style>
match = re.search(r'<style>(.*?)</style>', content, re.DOTALL)
if not match:
    print("CSS not found")
    exit()

css = match.group(1)

# Remove :root block
css = re.sub(r':root\s*\{.*?\}', '', css, flags=re.DOTALL)

# Replacements
replacements = [
    (r'rgba\(255,\s*255,\s*255,\s*0\.055\)', 'var(--surface-primary)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.085\)', 'var(--surface-secondary)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.12\)', 'var(--border)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.08\)', 'var(--border-subtle)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.035\)', 'var(--surface-primary)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.045\)', 'var(--surface-primary)'),
    (r'rgba\(255,\s*255,\s*255,\s*0\.06\)', 'var(--surface-primary)'),
    (r'rgba\(3,\s*7,\s*18,\s*0\.58\)', 'var(--surface-input)'),
    (r'rgba\(3,\s*7,\s*18,\s*0\.62\)', 'var(--surface-code)'),
    (r'rgba\(3,\s*7,\s*18,\s*0\.28\)', 'var(--surface-primary)'),
    (r'rgba\(3,\s*7,\s*18,\s*0\.72\)', 'var(--surface-elevated)'),
    (r'#c7d2fe', 'var(--accent)'),
    (r'#7dd3fc', 'var(--accent)'),
    (r'#cbd5e1', 'var(--ink-on-code)'),
    (r'var\(--muted\)', 'var(--ink-secondary)'),
    (r'var\(--text\)', 'var(--ink)'),
    (r'var\(--soft\)', 'var(--ink-tertiary)'),
    (r'var\(--radius\)', 'var(--radius-md)'),
    (r'var\(--shadow\)', 'var(--shadow)'),
    (r'var\(--line\)', 'var(--border)'),
    (r'var\(--line-hot\)', 'var(--border-strong)'),
    (r'var\(--teal\)', 'var(--accent)'),
    (r'var\(--blue\)', 'var(--accent)'),
    (r'var\(--bg\)', 'var(--bg)'),
    (r'font-family:\s*Inter,.*?;', 'font-family: var(--font-body);'),
    (r'backdrop-filter:\s*blur\(18px\);', 'backdrop-filter: var(--backdrop-blur);'),
    (r'rgba\(20,\s*184,\s*166,\s*0\.45\)', 'var(--accent-subtle)'),
    (r'rgba\(20,\s*184,\s*166,\s*0\.28\)', 'var(--accent-glow)'),
    (r'linear-gradient\(135deg,\s*#14b8a6,\s*#2563eb\)', 'var(--accent)'),
    (r'#14b8a6', 'var(--accent)'),
    (r'#2563eb', 'var(--accent-hover)'),
    (r'rgba\(0,\s*0,\s*0,\s*0\.82\)', 'var(--overlay)'),
    # Body background special case
    (r'background:\s*linear-gradient\(140deg,.*?\s*var\(--bg\);', 'background: var(--bg);'),
]

for pattern, repl in replacements:
    css = re.sub(pattern, repl, css, flags=re.DOTALL)

# Button active transform
css = re.sub(r'(\.btn:hover\s*\{.*?transform:\s*translateY\(-1px\);)', r'\1\n    }\n    .btn:active {\n      transform: var(--btn-active-transform);', css, flags=re.DOTALL)

# Output base.css
with open(r'e:\Python_Projects\TempScripts\apiqik\static\css\base.css', 'w', encoding='utf-8') as f:
    f.write(css.strip())

print("base.css created")
