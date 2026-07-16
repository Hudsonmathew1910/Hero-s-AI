import codecs

def fix_file(filepath):
    with codecs.open(filepath, 'r', 'utf-8') as f:
        content = f.read()
    
    # We will use unicode escape sequences to be completely safe from PowerShell string interpolation issues.
    # 'â€¦' is \u00e2\u2026
    # But since it's already mangled in UTF-8, it might be literally those characters in the file if the file was saved wrong.
    # If the file was saved as UTF-8, the mangled characters are:
    replacements = {
        'â€¦': '…',
        'â€”': '—',
        'â€“': '–',
        'Â·': '·',
        'â ¤ï¸ ': '❤️'
    }
    for k, v in replacements.items():
        content = content.replace(k, v)
        
    with codecs.open(filepath, 'w', 'utf-8') as f:
        f.write(content)

fix_file('templates/home.html')
print('Done!')
