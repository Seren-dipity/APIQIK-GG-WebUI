import re

html_path = r'e:\Python_Projects\TempScripts\apiqik\static\index.html'
with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

replacements = [
    (r'rgba\(255,255,255,0\.04\)', r'var(--surface-primary)'),
    (r'rgba\(255,255,255,0\.06\)', r'var(--surface-primary)'),
    (r'rgba\(255,255,255,0\.1\)', r'var(--border)'),
    (r'var\(--muted\)', r'var(--ink-secondary)'),
    (r'var\(--text\)', r'var(--ink)'),
    (r'var\(--surface\)', r'var(--surface-primary)')
]

for pattern, repl in replacements:
    html = re.sub(pattern, repl, html)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print("index.html cleaned up")
