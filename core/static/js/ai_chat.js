(function () {
  'use strict';

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
  }

  const CSRF_TOKEN = getCookie('csrftoken');

  function bubble(role, text) {
    const div = document.createElement('div');
    div.className = `ai-bubble ai-bubble-${role}`;
    const textEl = document.createElement('div');
    textEl.className = 'ai-text';
    textEl.textContent = text;
    div.appendChild(textEl);
    return div;
  }

  function typingBubble() {
    const div = document.createElement('div');
    div.className = 'ai-bubble ai-bubble-assistant ai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    return div;
  }

  async function sendMessage({ sendUrl, message, conversationId, onStart, onDone, onError }) {
    onStart();
    try {
      const resp = await fetch(sendUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN || '',
        },
        body: JSON.stringify({ message, conversation_id: conversationId || null }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        onError(data.error || 'Something went wrong. Please try again.');
        return;
      }
      onDone(data);
    } catch (err) {
      onError('Network error - please check your connection and try again.');
    }
  }

  // ==========================================================================
  // Voice: speech-to-text (ask by voice) and text-to-speech (hear replies).
  // Uses the browser's own free, built-in Web Speech API - no API key, and
  // nothing is sent to any server for the voice part itself.
  // Languages: English and Urdu have full voice support (recognition +
  // speech). Sindhi is offered as a reply/typing language (the AI will
  // reply in Sindhi script) but browsers don't yet ship reliable Sindhi
  // speech recognition/synthesis, so voice is disabled for it - this is a
  // real current limitation of browser speech engines, not a bug.
  // ==========================================================================
  const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
  const speechSupported = !!SpeechRecognitionImpl;
  const synthSupported = 'speechSynthesis' in window;
  const NO_VOICE_LANGS = ['sd'];

  const VoicePrefs = {
    get lang() { return localStorage.getItem('ums-ai-lang') || 'en-US'; },
    set lang(v) { localStorage.setItem('ums-ai-lang', v); },
    get speakEnabled() { return localStorage.getItem('ums-ai-speak') === '1'; },
    set speakEnabled(v) { localStorage.setItem('ums-ai-speak', v ? '1' : '0'); },
  };

  function speak(text, lang) {
    if (!synthSupported || !VoicePrefs.speakEnabled || NO_VOICE_LANGS.includes(lang)) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = lang;
      const voices = window.speechSynthesis.getVoices();
      const match = voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(lang.split('-')[0]));
      if (match) utter.voice = match;
      window.speechSynthesis.speak(utter);
    } catch (e) { /* speech synthesis best-effort only */ }
  }

  /** Wires a language <select>, a 🎤 mic button, and a speaker toggle button
   * that live inside `container` to a given text `input` and `onVoiceResult`
   * callback (called with the transcribed text). Returns a `getLang()` fn. */
  function setupVoiceControls(container, input, onVoiceResult) {
    const langSelect = container.querySelector('[data-lang-select]');
    const micBtn = container.querySelector('[data-mic-btn]');
    const speakerBtn = container.querySelector('[data-speaker-toggle]');

    if (langSelect) {
      langSelect.value = VoicePrefs.lang;
      langSelect.addEventListener('change', function () {
        VoicePrefs.lang = langSelect.value;
        updateMicState();
      });
    }

    function updateMicState() {
      if (!micBtn) return;
      const lang = langSelect ? langSelect.value : VoicePrefs.lang;
      const disabled = !speechSupported || NO_VOICE_LANGS.includes(lang);
      micBtn.disabled = disabled;
      micBtn.title = !speechSupported
        ? 'Voice input is not supported in this browser'
        : NO_VOICE_LANGS.includes(lang)
          ? "Voice input isn't available for Sindhi yet — please type instead"
          : 'Ask by voice';
      micBtn.style.opacity = disabled ? '0.4' : '1';
    }
    updateMicState();

    if (speakerBtn) {
      function renderSpeakerBtn() {
        const on = VoicePrefs.speakEnabled;
        speakerBtn.textContent = speakerBtn.textContent.replace(/^[🔊🔇]/, on ? '🔊' : '🔇');
        if (speakerBtn.textContent.indexOf('Voice reply') !== -1) {
          speakerBtn.textContent = (on ? '🔊 Voice reply on' : '🔇 Voice reply off');
        } else {
          speakerBtn.textContent = on ? '🔊' : '🔇';
        }
      }
      renderSpeakerBtn();
      if (!synthSupported) {
        speakerBtn.disabled = true;
        speakerBtn.title = 'Text-to-speech is not supported in this browser';
      } else {
        speakerBtn.addEventListener('click', function () {
          VoicePrefs.speakEnabled = !VoicePrefs.speakEnabled;
          renderSpeakerBtn();
          window.speechSynthesis.cancel(); // stop anything currently being read aloud
        });
      }
    }

    if (micBtn && speechSupported) {
      let recognition = null;
      let listening = false;

      function stopListening() {
        if (recognition && listening) {
          recognition.stop();
        }
      }

      micBtn.addEventListener('click', function () {
        if (listening) {
          // Tap again while listening = exit/cancel voice input.
          stopListening();
          return;
        }
        const lang = langSelect ? langSelect.value : VoicePrefs.lang;
        recognition = new SpeechRecognitionImpl();
        recognition.lang = lang;
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        listening = true;
        micBtn.classList.add('listening');
        micBtn.textContent = '⏹️';
        micBtn.title = 'Tap to stop listening';

        recognition.onresult = function (event) {
          const transcript = event.results[0][0].transcript;
          if (onVoiceResult) onVoiceResult(transcript);
        };
        recognition.onerror = function () {
          listening = false;
          micBtn.classList.remove('listening');
          micBtn.textContent = '🎤';
          updateMicState();
        };
        recognition.onend = function () {
          listening = false;
          micBtn.classList.remove('listening');
          micBtn.textContent = '🎤';
          updateMicState();
        };
        try {
          recognition.start();
        } catch (e) {
          listening = false;
          micBtn.classList.remove('listening');
          micBtn.textContent = '🎤';
        }
      });

      container._stopListening = stopListening;
    }

    container._stopSpeaking = function () {
      if (synthSupported) window.speechSynthesis.cancel();
    };

    return {
      getLang: () => (langSelect ? langSelect.value : VoicePrefs.lang),
      exitVoice: function () {
        if (container._stopListening) container._stopListening();
        if (container._stopSpeaking) container._stopSpeaking();
      },
    };
  }

  // ---------------- Floating widget ----------------
  const widget = document.getElementById('ai-widget');
  if (widget) {
    const toggleBtn = document.getElementById('ai-widget-toggle');
    const closeBtn = document.getElementById('ai-widget-close');
    const panel = document.getElementById('ai-widget-panel');
    const form = document.getElementById('ai-widget-form');
    const input = document.getElementById('ai-widget-input');
    const messages = document.getElementById('ai-widget-messages');
    const sendUrl = widget.dataset.sendUrl;
    let conversationId = null;

    // Hide the floating bubble on the full-page chat screen (it has its own UI).
    if (document.getElementById('ai-messages')) {
      widget.style.display = 'none';
    }

    function openPanel() {
      panel.hidden = false;
      toggleBtn.classList.add('open');
      input.focus();
    }
    function closePanel() {
      panel.hidden = true;
      toggleBtn.classList.remove('open');
      if (voice) voice.exitVoice();
    }

    document.addEventListener('click', function (e) {
      if (e.target.closest('#ai-widget-toggle')) {
        panel.hidden ? openPanel() : closePanel();
      }
      if (e.target.closest('#ai-widget-close')) {
        closePanel();
      }
    });

    const voice = setupVoiceControls(widget, input, function (transcript) {
      input.value = transcript;
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true }));
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      messages.appendChild(bubble('user', text));
      input.value = '';
      messages.scrollTop = messages.scrollHeight;
      const typing = typingBubble();

      sendMessage({
        sendUrl, message: text, conversationId,
        onStart: () => {
          input.disabled = true;
          messages.appendChild(typing);
          messages.scrollTop = messages.scrollHeight;
        },
        onDone: (data) => {
          typing.remove();
          conversationId = data.conversation_id;
          messages.appendChild(bubble('assistant', data.answer));
          messages.scrollTop = messages.scrollHeight;
          input.disabled = false;
          input.focus();
          speak(data.answer, voice.getLang());
        },
        onError: (msg) => {
          typing.remove();
          messages.appendChild(bubble('assistant', msg));
          messages.scrollTop = messages.scrollHeight;
          input.disabled = false;
        },
      });
    });
  }

  // ---------------- Full chat page ----------------
  const fullForm = document.getElementById('ai-form');
  if (fullForm) {
    const input = document.getElementById('ai-input');
    const messages = document.getElementById('ai-messages');
    const sendUrl = '/ai/api/send/';
    let conversationId = messages.dataset.conversationId || null;
    const voice = setupVoiceControls(document, input, function (transcript) {
      input.value = transcript;
      fullForm.requestSubmit ? fullForm.requestSubmit() : fullForm.dispatchEvent(new Event('submit', { cancelable: true }));
    });

    fullForm.addEventListener('submit', function (e) {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      const emptyState = messages.querySelector('.ai-empty');
      if (emptyState) emptyState.remove();

      messages.appendChild(bubble('user', text));
      input.value = '';
      messages.scrollTop = messages.scrollHeight;
      const typing = typingBubble();

      sendMessage({
        sendUrl, message: text, conversationId,
        onStart: () => {
          input.disabled = true;
          messages.appendChild(typing);
          messages.scrollTop = messages.scrollHeight;
        },
        onDone: (data) => {
          typing.remove();
          conversationId = data.conversation_id;
          messages.appendChild(bubble('assistant', data.answer));
          messages.scrollTop = messages.scrollHeight;
          input.disabled = false;
          input.focus();
          speak(data.answer, voice.getLang());
        },
        onError: (msg) => {
          typing.remove();
          messages.appendChild(bubble('assistant', msg));
          messages.scrollTop = messages.scrollHeight;
          input.disabled = false;
        },
      });
    });
  }
})();
