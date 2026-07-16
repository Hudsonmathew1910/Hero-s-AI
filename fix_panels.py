import re

with open('templates/home.html', 'r', encoding='utf-8') as f:
    content = f.read()

correct_html = '''          <div class="settings-panel" id="spanel-about">
            <div class="settings-panel-title">About Hero's AI</div>
            <div class="about-logo-wrap">
              <img src="{% static 'images/Hero_ai.png' %}" alt="Hero's AI" />
            </div>
            <div class="about-title">Hero's AI</div>
            <div class="about-badge">V2.6 · Plus</div>
            <p class="about-desc">
              Hero's AI is your intelligent personal assistant — built for code,
              creativity, conversations, and everything in between. Powered by
              Baymax and the ZORVIN engine.
            </p>
            <div class="about-coming-soon">
              <i class="fa-solid fa-sparkles"></i>
              <h3>What's New in Hero's AI</h3>
              <p style="margin-bottom: 10px;">
                <strong>Zeno Extension:</strong> Meet Zeno, your mini AI assistant Chrome extension. Enjoy instant text and voice chats right from your browser, powered by our intelligent NLP routing (Plus & Eco modes).
              </p>
              <p style="margin-bottom: 10px;">
                <strong>Infinsight (AI Analyst):</strong> Deep dive into your data with our powerful data visualization and analysis tool.
              </p>
              <p>
                <strong>Advanced NLP Pipeline:</strong> Hero's AI automatically routes your prompts (Coding, Web Search, Text) to the best model—like Groq for lightning-fast answers, or Gemini for complex tasks.
              </p>
            </div>
            <div style="margin-bottom: 24px; display: flex; justify-content: center;">
              <a href="{% url 'landing' %}" class="modal-save-btn" style="text-decoration: none; max-width: 280px; width: 100%;">
                <i class="fa-solid fa-compass"></i> Discover Hero's AI
              </a>
            </div>
            <div class="about-version">
              Built with ❤️ by the Hero's AI team &nbsp;·&nbsp; huddy1910@gmail.com
            </div>
          </div>

          <div class="settings-panel" id="spanel-help">
            <div class="settings-panel-title">Help & Support</div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-regular fa-message"></i></div>
              <div class="help-text-group">
                <div class="help-title">Start a conversation</div>
                <div class="help-desc">
                  Type your message and press Enter or click send to chat with
                  Hero's AI.
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-solid fa-plus"></i></div>
              <div class="help-text-group">
                <div class="help-title">+ Menu</div>
                <div class="help-desc">
                  Click + in the input to attach files, enable Coding mode, or
                  activate Web Search.
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-solid fa-microphone"></i></div>
              <div class="help-text-group">
                <div class="help-title">Voice input</div>
                <div class="help-desc">
                  Click the mic icon to dictate, or use "Talk to Baymax" for a full
                  voice conversation.
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-solid fa-robot"></i></div>
              <div class="help-text-group">
                <div class="help-title">Switch AI model</div>
                <div class="help-desc">
                  Use the model selector to switch between Baymax, Halo, and ZORVIN. Enable the Developer Option in Settings to access the Developer mode!
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-brands fa-chrome"></i></div>
              <div class="help-text-group">
                <div class="help-title">Zeno Chrome Extension</div>
                <div class="help-desc">
                  Install the Zeno extension to chat with Hero's AI from anywhere on the web. Try Eco mode for fast text, or Plus mode for full NLP coding/search capabilities.
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-solid fa-chart-line"></i></div>
              <div class="help-text-group">
                <div class="help-title">AI Analyst (Infinsight)</div>
                <div class="help-desc">
                  Click the + menu and select AI Analyst to upload data and get intelligent insights and graphs.
                </div>
              </div>
            </div>
            
            <div class="help-item">
              <div class="help-icon"><i class="fa-regular fa-envelope"></i></div>
              <div class="help-text-group">
                <div class="help-title">Contact support</div>
                <div class="help-desc">
                  Reach us at
                  <strong style="color: var(--accent)">huddy1910@gmail.com</strong>
                </div>
              </div>
            </div>
            
          </div>\n\n          <!-- General panel -->'''

content = re.sub(r'<div class="settings-panel" id="spanel-about">.*?<!-- General panel -->', correct_html, content, flags=re.DOTALL)

with open('templates/home.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("done")
