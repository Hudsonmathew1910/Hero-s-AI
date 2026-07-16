import re

with open('templates/home.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. API Keys
api_match = re.search(r'<div class="modal-overlay" id="apiKeysModal">.*?<div class="modal-body">(.*?)</div>\s*<div class="modal-footer">(.*?)</div>\s*</div>\s*</div>', content, re.DOTALL)
api_content = api_match.group(1) if api_match else ''
api_footer = api_match.group(2) if api_match else ''
api_panel = f'''
          <div class="settings-panel" id="spanel-apikeys">
            <div class="settings-panel-title">API Keys</div>
            {api_content}
            <div style="margin-top: 20px;">
              {api_footer}
            </div>
          </div>
'''

# 2. About
about_match = re.search(r'<div class="modal-overlay" id="aboutHerosModal">.*?<div class="about-logo-wrap">(.*?)</div>\s*</div>', content, re.DOTALL)
about_content = '<div class="about-logo-wrap">' + about_match.group(1) if about_match else ''
about_panel = f'''
          <div class="settings-panel" id="spanel-about">
            <div class="settings-panel-title">About Hero's AI</div>
            {about_content}
          </div>
'''

# 3. Help
help_match = re.search(r'<div class="modal-overlay" id="helpModal">.*?<div class="help-item">(.*?)</div>\s*</div>', content, re.DOTALL)
help_content = '<div class="help-item">' + help_match.group(1) if help_match else ''
help_panel = f'''
          <div class="settings-panel" id="spanel-help">
            <div class="settings-panel-title">Help & Support</div>
            {help_content}
          </div>
'''

print(f'API Content Length: {len(api_content)}')
print(f'About Content Length: {len(about_content)}')
print(f'Help Content Length: {len(help_content)}')

if api_content and about_content and help_content:
    # Insert new panels into settings-content
    new_panels = api_panel + about_panel + help_panel
    # Find end of spanel-instructions
    instr_end_match = re.search(r'<div class="settings-panel" id="spanel-instructions">.*?</div>\s*</div>\s*</div>', content, re.DOTALL)
    if instr_end_match:
        insert_pos = instr_end_match.end() - 12  # roughly inside settings-content
    
    content = content.replace('<!-- Right content -->\n        <div class="settings-content">', '<!-- Right content -->\n        <div class="settings-content">\n' + new_panels)
    
    # Remove old modals
    content = re.sub(r'<!-- -.*?API KEYS MODAL.*?</div>\s*</div>', '', content, flags=re.DOTALL)
    content = re.sub(r'<!-- -.*?ABOUT HERO\'S MODAL.*?</div>\s*</div>', '', content, flags=re.DOTALL)
    content = re.sub(r'<!-- -.*?HELP MODAL.*?</div>\s*</div>', '', content, flags=re.DOTALL)
    
    # Change nav functions
    content = content.replace('onclick="openApiKeys()"', 'onclick="switchSettingsNav(\'apikeys\')" id="snav-apikeys"')
    content = content.replace('onclick="openAboutHeros()"', 'onclick="switchSettingsNav(\'about\')" id="snav-about"')
    content = content.replace('onclick="openHelp()"', 'onclick="switchSettingsNav(\'help\')" id="snav-help"')
    
    with open('templates/home.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Done refactoring home.html")
else:
    print("Failed to match")
