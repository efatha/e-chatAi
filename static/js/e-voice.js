const startRecordBtn = document.getElementById('start-record');
const messageInput = document.getElementById('message-input');
const composerForm = messageInput.closest('form');
const messageTrack = document.querySelector('.voice-message-track');
messageTrack.replaceChildren();
const TRACK_BARS = 36;
for (let index = 0; index < TRACK_BARS; index += 1) {
  const bar = document.createElement('span');
  bar.style.animationDelay = `${(index % 8) * 0.07}s`;
  messageTrack.appendChild(bar);
}
const trackBars = messageTrack.querySelectorAll('span');
const iconBars = startRecordBtn.querySelectorAll('.voice-live i');

iconBars.forEach((bar, index) => {
  bar.style.animationDelay = `${index * 0.1}s`;
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SpeechRecognition) {
  startRecordBtn.disabled = true;
  startRecordBtn.title = 'Voice input not supported on this browser.';
  startRecordBtn.setAttribute('aria-label', 'Voice input not supported on this browser.');
} else {
  const recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;

  let committed = '';
  let sessionFinal = '';
  let sessionInterim = '';
  let listening = false;
  let stopRequested = false;
  let delivered = false;
  let audioContext = null;
  let analyser = null;
  let sourceNode = null;
  let mediaStream = null;
  let frameId = 0;
  let levelSession = 0;
  const history = [];

  const setListening = (on) => {
    listening = on;
    startRecordBtn.classList.toggle('is-listening', on);
    composerForm.classList.toggle('is-recording', on);
    startRecordBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    startRecordBtn.title = on ? 'Stop voice input' : 'Start voice input';
    startRecordBtn.setAttribute('aria-label', startRecordBtn.title);
    if (!on) {
      startRecordBtn.classList.remove('has-levels');
      composerForm.classList.remove('has-levels');
    }
  };

  const paintHistory = () => {
    const count = history.length;
    const bars = trackBars.length;
    if (!count) return;
    if (count <= bars) {
      for (let i = 0; i < bars; i += 1) {
        trackBars[i].style.transform = `scaleY(${i < count ? history[i] : 0.16})`;
      }
      return;
    }
    for (let i = 0; i < bars; i += 1) {
      const start = Math.floor((i * count) / bars);
      const end = Math.max(start + 1, Math.floor(((i + 1) * count) / bars));
      let peak = 0.16;
      for (let j = start; j < end; j += 1) peak = Math.max(peak, history[j]);
      trackBars[i].style.transform = `scaleY(${peak})`;
    }
  };

  const ensureAudio = () => {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!audioContext) audioContext = new AudioCtx();
    if (audioContext.state === 'suspended') audioContext.resume();
    return audioContext;
  };

  const stopLevels = () => {
    levelSession += 1;
    cancelAnimationFrame(frameId);
    frameId = 0;
    if (sourceNode) {
      sourceNode.disconnect();
      sourceNode = null;
    }
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    analyser = null;
  };

  const startLevels = () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    const token = levelSession;
    const ctx = ensureAudio();
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      if (token !== levelSession || !listening || !ctx) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStream = stream;
      analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0;
      sourceNode = ctx.createMediaStreamSource(stream);
      sourceNode.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      let frame = 0;
      startRecordBtn.classList.add('has-levels');
      composerForm.classList.add('has-levels');
      const tick = () => {
        if (!analyser || token !== levelSession) return;
        analyser.getByteTimeDomainData(samples);
        let energy = 0;
        for (let i = 0; i < samples.length; i += 1) {
          const sample = (samples[i] - 128) / 128;
          energy += sample * sample;
        }
        const level = Math.min(1, Math.sqrt(energy / samples.length) * 3.4);
        history.push(Math.max(0.16, Math.min(1, 0.18 + level * 0.82)));
        if (history.length > 480) {
          const compact = [];
          for (let i = 0; i < history.length; i += 2) {
            compact.push(Math.max(history[i], history[i + 1] || 0));
          }
          history.length = 0;
          for (let i = 0; i < compact.length; i += 1) history.push(compact[i]);
        }
        paintHistory();
        frame += 1;
        iconBars.forEach((bar, index) => {
          const wobble = 0.55 + 0.45 * Math.sin(frame / 2.4 + index * 0.9);
          bar.style.transform = `scaleY(${0.26 + level * wobble})`;
        });
        frameId = requestAnimationFrame(tick);
      };
      tick();
    }).catch(() => {
      if (token !== levelSession) return;
      startRecordBtn.classList.remove('has-levels');
      composerForm.classList.remove('has-levels');
    });
  };

  const liveText = () => [committed, sessionFinal, sessionInterim]
    .map((part) => part.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(' ');

  const renderTranscript = () => {
    if (delivered || stopRequested) return;
    const next = liveText();
    if (messageInput.value === next) return;
    messageInput.value = next;
    const end = next.length;
    if (document.activeElement === messageInput) messageInput.setSelectionRange(end, end);
    messageInput.scrollTop = messageInput.scrollHeight;
  };

  const deliver = (spoken) => {
    if (delivered) return;
    stopRequested = true;
    setListening(false);
    stopLevels();
    const text = (spoken || '').trim();
    if (!text) {
      messageInput.value = '';
      return;
    }
    delivered = true;
    messageInput.value = text;
    const sendBtn = document.querySelector('.send-message');
    if (sendBtn) sendBtn.click();
    if (messageInput.value.trim() === text) messageInput.value = '';
  };

  const haltRecognition = () => {
    try {
      recognition.abort();
    } catch (error) {
      try {
        recognition.stop();
      } catch (stopError) {
        /* already idle */
      }
    }
  };

  startRecordBtn.addEventListener('click', () => {
    if (listening) {
      const spoken = liveText() || messageInput.value.trim();
      stopRequested = true;
      haltRecognition();
      deliver(spoken);
      return;
    }
    stopRequested = false;
    delivered = false;
    committed = messageInput.value.trim();
    sessionFinal = '';
    sessionInterim = '';
    history.length = 0;
    setListening(true);
    ensureAudio();
    startLevels();
    try {
      recognition.start();
    } catch (error) {
      console.error('Speech recognition could not start:', error);
    }
  });

  messageInput.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.isComposing || !listening) return;
    event.preventDefault();
    const spoken = liveText() || messageInput.value.trim();
    stopRequested = true;
    delivered = true;
    setListening(false);
    stopLevels();
    messageInput.value = spoken;
    haltRecognition();
  });

  recognition.onstart = () => {
    if (!stopRequested) return;
    haltRecognition();
  };

  recognition.onresult = (event) => {
    if (stopRequested || delivered) return;
    sessionFinal = '';
    sessionInterim = '';
    for (let i = 0; i < event.results.length; i += 1) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) sessionFinal += `${transcript} `;
      else sessionInterim += transcript;
    }
    renderTranscript();
  };

  recognition.onend = () => {
    if (stopRequested || delivered) return;
    committed = liveText();
    sessionFinal = '';
    sessionInterim = '';
    renderTranscript();
    if (!listening) return;
    try {
      recognition.start();
    } catch (error) {
      deliver(committed);
    }
  };

  recognition.onerror = (event) => {
    if (event.error === 'no-speech' || event.error === 'aborted') return;
    console.error('Speech recognition error:', event.error);
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed' || event.error === 'audio-capture') {
      stopRequested = true;
      setListening(false);
      stopLevels();
    }
  };
}
